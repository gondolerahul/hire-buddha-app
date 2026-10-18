"""WS3 agent tools on Postgres (tech spec §7.10; functional spec §3.3): an agent
schedules work for itself, its process or the agents the owner listed; cancels
and lists only what it may; sends custom signals one step deeper in its chain
— each within the business's limits, none unless set (D47).

Committed rows, one company per test, purged afterwards, on a per-test engine
(as ``test_automation_runtime.py``). Nudges are recorded, not sent.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import select

from src.automation import agent_actions, router, store, triggers
from src.automation import limits as limits_mod
from src.automation.models import Event, TimeIndexEntry, Trigger

pytestmark = pytest.mark.needs_db


@pytest_asyncio.fixture
async def biz(monkeypatch):
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    import src.common.orm_models  # noqa: F401
    from src.ai.orm import ExecutionRun, HierarchicalEntity
    from src.auth.models import Company
    from src.billing.billing_models import CreditWallet
    from src.common import database
    from src.common.config import settings
    from tests.harness.purge import purge_companies

    engine = create_async_engine(settings.CONTROL_DATABASE_URL, poolclass=NullPool,
                                 json_serializer=database.json_serializer)
    monkeypatch.setattr(database, "AsyncSessionLocal", async_sessionmaker(engine, expire_on_commit=False))
    nudged = []

    async def _nudge(company_id, event_id, *, attempt=""):
        nudged.append(event_id)

    async def _enqueue(*args, **kwargs):
        return None

    monkeypatch.setattr(store, "nudge", _nudge)
    monkeypatch.setattr("src.ai.service.enqueue_job", _enqueue)

    async with database.AsyncSessionLocal() as db:
        company = Company(name=f"ws3-tools-{uuid.uuid4().hex[:6]}", type="TENANT", status="active")
        db.add(company)
        await db.flush()
        later = datetime.utcnow() + timedelta(days=1)
        db.add(CreditWallet(company_id=company.id, daily_credits=Decimal("0"), daily_expires_at=later,
                            wallet_balance=Decimal("100"), wallet_expires_at=later))

        def entity(name, kind="AGENT", parent=None, status="ACTIVE", automation=None):
            row = HierarchicalEntity(company_id=company.id, type=kind, status=status, name=name,
                                     parent_id=parent.id if parent else None,
                                     capabilities={"automation": automation} if automation else None)
            db.add(row)
            return row

        process = entity("Sales process", kind="PROCESS")
        await db.flush()
        caller = entity("Sales Assistant", parent=process)
        sibling = entity("Report Writer", parent=process)
        outsider = entity("Invoice Agent")
        listed = entity("Community Manager")
        draft = entity("Draft Agent", status="DRAFT")
        await db.flush()
        caller.capabilities = {"automation": {"can_schedule": [str(listed.id), str(draft.id)]}}
        source_event = uuid.uuid4()
        run = ExecutionRun(company_id=company.id, entity_id=caller.id, status="RUNNING", input_data={},
                           event_id=None, correlation_id=source_event, chain_depth=2)
        db.add(run)
        await db.commit()
        ids = SimpleNamespace(company=company.id, process=process.id, caller=caller.id, sibling=sibling.id,
                              outsider=outsider.id, listed=listed.id, draft=draft.id, run=run.id,
                              correlation=source_event, nudged=nudged)
    limits_mod.forget()
    limits_mod.forget_state()
    try:
        yield ids
    finally:
        limits_mod.forget()
        limits_mod.forget_state()
        async with engine.begin() as conn:
            await purge_companies(conn, [ids.company])
        await engine.dispose()


def _session():
    from src.common import database

    return database.AsyncSessionLocal()


def _ctx(biz, entity=None, run=None):
    return {"company_id": str(biz.company), "run_id": str(run or biz.run), "entity_id": str(entity or biz.caller)}


async def _call(tool_name, biz, args, **ctx):
    import src.ai.tools  # noqa: F401
    from src.ai.tools.base import ToolRegistry

    return await ToolRegistry.get_tool(tool_name).invoke(args, _ctx(biz, **ctx))


async def _limits(biz, values):
    async with _session() as db:
        await limits_mod.save(db, biz.company, values, None)


async def test_an_agent_schedules_a_follow_up_for_itself_and_nothing_runs_now(biz):
    out = await _call("schedule_agent", biz, {"after": "3d", "name": "Follow up with Priya",
                                              "input": "Ask Priya about {{ the visit }}"})
    assert out.success, out.error
    async with _session() as db:
        trigger = await db.get(Trigger, uuid.UUID(out.output["schedule_id"]))
        row = await db.get(TimeIndexEntry, (biz.company, "trigger", trigger.id))
    assert (trigger.kind, trigger.entity_id, trigger.created_by_kind) == ("timer", biz.caller, "agent")
    assert (trigger.created_by_id, trigger.created_by_run_id) == (biz.caller, biz.run)
    assert abs(trigger.run_at - (datetime.utcnow() + timedelta(days=3))) < timedelta(minutes=1)
    assert row.due_at == trigger.next_fire_at
    # The agent's text is the input as written, braces and all.
    from src.automation import templates
    assert templates.render(trigger.input_template, {}) == {"input": "Ask Priya about {{ the visit }}"}
    assert biz.nudged == []


async def test_who_an_agent_may_schedule(biz):
    sibling = await _call("schedule_agent", biz, {"cron": "0 9 * * 1-5", "agent": "Report Writer"})
    listed = await _call("schedule_agent", biz, {"at": "2027-01-01T09:00", "agent": str(biz.listed)})
    outsider = await _call("schedule_agent", biz, {"after": "1h", "agent": "invoice agent"})
    draft = await _call("schedule_agent", biz, {"after": "1h", "agent": "Draft Agent"})
    assert sibling.success and listed.success, (sibling.error, listed.error)
    assert sibling.output["timezone"] == "Asia/Kolkata"
    assert listed.output["run_at"] == "2027-01-01T03:30:00Z"  # 09:00 in the business's zone
    assert not outsider.success and "Automation tab" in outsider.error
    assert not draft.success and "DRAFT" in draft.error
    both = await _call("schedule_agent", biz, {"after": "1h", "cron": "* * * * *"})
    assert not both.success and "exactly one" in both.error


async def test_the_businesss_limits_on_agent_schedules_apply_only_when_set(biz):
    for _ in range(3):
        assert (await _call("schedule_agent", biz, {"cron": "*/5 * * * *"})).success
    await _limits(biz, {"agent_schedules_per_run": 3, "agent_min_repeat_minutes": 60})
    over = await _call("schedule_agent", biz, {"after": "1d"})
    assert not over.success and "at most 3 schedules" in over.error
    fresh_run = await _new_run(biz)
    too_often = await _call("schedule_agent", biz, {"cron": "*/5 * * * *"}, run=fresh_run)
    assert not too_often.success and "every 60 minutes" in too_often.error
    await _limits(biz, {"agent_max_schedules": 3})
    full = await _call("schedule_agent", biz, {"after": "1d"}, run=fresh_run)
    assert not full.success and "already has 3 schedules" in full.error


async def _new_run(biz):
    from src.ai.orm import ExecutionRun

    async with _session() as db:
        run = ExecutionRun(company_id=biz.company, entity_id=biz.caller, status="RUNNING", input_data={})
        db.add(run)
        await db.commit()
        return run.id


async def test_an_agent_cancels_only_what_it_or_its_process_made(biz):
    mine = (await _call("schedule_agent", biz, {"after": "2d"})).output["schedule_id"]
    by_sibling = (await _call("schedule_agent", biz, {"after": "2d"}, entity=biz.sibling)).output["schedule_id"]
    async with _session() as db, _session() as cdb:
        by_owner = await triggers.create(db, cdb, biz.company, {"name": "owner's", "kind": "manual",
                                                                "entity_id": biz.caller},
                                         triggers.Actor("user", None))
        await db.commit()
        await cdb.commit()

    cancelled = await _call("cancel_schedule", biz, {"schedule_id": mine})
    assert cancelled.success and cancelled.output["enabled"] is False
    assert "cancelled by agent Sales Assistant" in cancelled.output["status_note"]
    assert (await _call("cancel_schedule", biz, {"schedule_id": by_sibling})).success  # same process
    refused = await _call("cancel_schedule", biz, {"schedule_id": str(by_owner.id)})
    assert not refused.success and "only schedules you or your process made" in refused.error
    async with _session() as db:
        assert await db.get(TimeIndexEntry, (biz.company, "trigger", uuid.UUID(mine))) is None


async def test_an_agent_lists_its_own_its_processs_and_what_runs_it(biz):
    await _call("schedule_agent", biz, {"after": "1d", "name": "mine"})
    await _call("schedule_agent", biz, {"after": "1d", "name": "sibling's", "agent": "Sales Assistant"},
                entity=biz.sibling)
    names = lambda out: sorted(s["name"] for s in out.output["schedules"])  # noqa: E731
    assert names(await _call("list_schedules", biz, {})) == ["mine"]
    assert names(await _call("list_schedules", biz, {"scope": "process"})) == ["mine", "sibling's"]
    assert names(await _call("list_schedules", biz, {"scope": "runs_me"})) == ["mine", "sibling's"]
    assert names(await _call("list_schedules", biz, {"scope": "mine"}, entity=biz.outsider)) == []


async def test_a_signal_is_one_step_deeper_and_wakes_the_listening_trigger(biz):
    refused = await _call("emit_event", biz, {"type": "record.order.created", "data": {}})
    assert not refused.success and "custom." in refused.error

    async with _session() as db, _session() as cdb:
        listener = await triggers.create(db, cdb, biz.company, {
            "name": "on qualified lead", "kind": "event", "event_type": "custom.lead.*",
            "entity_id": biz.listed, "input_template": {"input": "Call {{ event.data.lead }}"}},
            triggers.Actor("user", None))
        await db.commit()
        await cdb.commit()

    out = await _call("emit_event", biz, {"type": "custom.lead.qualified", "data": {"lead": "Priya"},
                                          "subject": "lead:42"})
    assert out.success, out.error
    event_id = uuid.UUID(out.output["event_id"])
    assert biz.nudged == [event_id]
    async with _session() as db:
        event = await db.get(Event, event_id)
        assert (event.chain_depth, event.correlation_id, event.source) == (3, biz.correlation, f"run:{biz.run}")
        decided = await router.route(db, biz.company, event_id)
    [decision] = decided["decisions"]
    assert decision["trigger"] == str(listener.id) and decision["outcome"] == "started"

    await _limits(biz, {"agent_events_per_run": 1})
    again = await _call("emit_event", biz, {"type": "custom.lead.qualified", "data": {"lead": "Ravi"}})
    assert not again.success and "at most 1 events" in again.error


async def test_the_tools_need_a_run_of_the_business(biz):
    import src.ai.tools  # noqa: F401
    from src.ai.tools.base import ToolRegistry

    tool = ToolRegistry.get_tool("schedule_agent")
    assert (await tool.invoke({"after": "1d"}, {})).error_code == "no_context"
    assert (await tool.invoke({"after": "1d"}, {"company_id": str(biz.company)})).error_code == "no_run"


async def test_a_fired_timer_can_still_be_turned_off(biz):
    now = datetime.utcnow()
    async with _session() as db, _session() as cdb:
        timer = await triggers.create(db, cdb, biz.company, {"name": "t", "kind": "timer", "entity_id": biz.caller,
                                                             "run_at": now + timedelta(minutes=1)},
                                      triggers.Actor("user", None), now=now)
        timer.firings, timer.next_fire_at = 1, None
        await db.commit()
        await triggers.update(db, cdb, biz.company, timer, {"enabled": False}, now=now + timedelta(hours=1))
        await db.commit()
        await cdb.commit()
        assert timer.enabled is False


async def test_editing_an_agent_elsewhere_keeps_its_automation_settings(biz):
    from src.ai.schemas.entity import HierarchicalEntityUpdate
    from src.ai.service import AIService

    async with _session() as db:
        await AIService(db).update_entity(biz.caller, HierarchicalEntityUpdate(capabilities={"tools": []}),
                                          biz.company)
    async with _session() as db:
        caller = await agent_actions._entity(db, biz.company, biz.caller)
    assert caller.capabilities["automation"]["can_schedule"] == [str(biz.listed), str(biz.draft)]
