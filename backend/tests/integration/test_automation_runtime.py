"""WS3 on Postgres: events are stored once, the router decides once per
trigger and event with its reason, and the scheduler fires schedules and
timers — on time, late by the catch-up rule, never twice (tech spec §7.6–§7.8,
decision D47: no limit applies unless the business sets one).

These commit, as the router and scheduler do (a refused run rolls back), so
each test has its own company and purges it afterwards, on its own engine
(the app's pool would hand a test connections of an earlier test's event
loop). Runs are created but not queued (``enqueue_job`` is replaced), and
nudges are recorded instead of sent.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import delete, func, select

from src.automation import limits as limits_mod
from src.automation import router, scheduler, store, triggers
from src.automation.events import Envelope
from src.automation.models import Event, TimeIndexEntry, Trigger, TriggerFiring
from tests.harness.wallet import fund

pytestmark = pytest.mark.needs_db


@pytest_asyncio.fixture
async def biz(monkeypatch):
    import src.common.orm_models  # noqa: F401
    from src.ai.orm import HierarchicalEntity
    from src.auth.models import Company, User
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    from src.billing.billing_models import CreditWallet
    from src.common import database
    from src.common.config import settings
    from tests.harness.purge import purge_companies

    engine = create_async_engine(settings.CONTROL_DATABASE_URL, poolclass=NullPool,
                                 json_serializer=database.json_serializer)
    # tenant_session / control_session open database.AsyncSessionLocal when called.
    monkeypatch.setattr(database, "AsyncSessionLocal", async_sessionmaker(engine, expire_on_commit=False))

    queued, nudged = [], []

    async def _enqueue(*args, **kwargs):
        queued.append(args)

    async def _nudge(company_id, event_id, *, attempt=""):
        nudged.append((company_id, event_id, attempt))

    monkeypatch.setattr("src.ai.service.enqueue_job", _enqueue)
    monkeypatch.setattr(store, "nudge", _nudge)

    async with database.AsyncSessionLocal() as db:
        company = Company(name=f"ws3-{uuid.uuid4().hex[:6]}", type="TENANT", status="active")
        db.add(company)
        await db.flush()
        later = datetime.utcnow() + timedelta(days=1)
        await fund(db, company.id, "100")
        user = User(email=f"ws3-{uuid.uuid4().hex[:8]}@example.com", hashed_password="x", full_name="WS3",
                    role="tenant_admin", company_id=company.id, is_active=True, is_verified=True)
        agent = HierarchicalEntity(company_id=company.id, type="AGENT", status="ACTIVE", name="ws3 agent")
        db.add_all([user, agent])
        await db.commit()
        ids = SimpleNamespace(company=company.id, user=user.id, agent=agent.id, queued=queued, nudged=nudged)
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


async def _trigger(biz, **fields):
    fields = {"name": "t", "entity_id": biz.agent, **fields}
    async with _session() as db, _session() as cdb:
        trigger = await triggers.create(db, cdb, biz.company, fields, triggers.Actor("user", biz.user))
        await db.commit()
        await cdb.commit()
        return trigger.id


async def _event(biz, event_type="custom.order.paid", data=None, *, dedupe=None, chain_depth=0):
    async with _session() as db:
        row, created = await store.record(db, biz.company, Envelope(
            type=event_type, source="test", trust="internal", data=data or {}, chain_depth=chain_depth,
            dedupe_key=dedupe or uuid.uuid4().hex))
        await db.commit()
        return row.id, created


async def _route(biz, event_id):
    async with _session() as db:
        return await router.route(db, biz.company, event_id)


async def _firings(biz, trigger_id):
    async with _session() as db:
        return (await db.execute(select(TriggerFiring).where(TriggerFiring.trigger_id == trigger_id)
                                 .order_by(TriggerFiring.decided_at))).scalars().all()


async def _run(run_id):
    from src.ai.orm import ExecutionRun

    async with _session() as db:
        return await db.get(ExecutionRun, run_id)


async def _set_limits(biz, values):
    async with _session() as db:
        await limits_mod.save(db, biz.company, values, biz.user)


async def _set_state(biz, state):
    from src.automation.models import AutomationLimitsRow

    async with _session() as db:
        row = (await db.execute(select(AutomationLimitsRow).where(
            AutomationLimitsRow.company_id == biz.company))).scalar_one_or_none()
        if row is None:
            row = AutomationLimitsRow(company_id=biz.company, limits={})
            db.add(row)
        row.automation_state = state
        await db.commit()
    limits_mod.forget_state(biz.company)


# ── The event store ────────────────────────────────────────────────────────

async def test_an_event_is_stored_once_per_dedupe_key(biz):
    first, created = await _event(biz, dedupe="provider:42")
    again, created_again = await _event(biz, dedupe="provider:42")
    assert created and not created_again and again == first


# ── The router ─────────────────────────────────────────────────────────────

async def test_a_matching_event_starts_one_run_with_its_rendered_input(biz):
    trigger_id = await _trigger(biz, kind="event", event_type="custom.order.*",
                                filter={"all": [{"path": "data.amount", "op": "gt", "value": 100}]},
                                input_template={"input": "Order {{ event.data.order }} paid"})
    big, _ = await _event(biz, data={"order": "A-7", "amount": 250})
    small, _ = await _event(biz, data={"order": "A-8", "amount": 20})

    decided = await _route(biz, big)
    assert [d["outcome"] for d in decided["decisions"]] == ["started"]
    assert (await _route(biz, small))["decisions"] == []  # the filter did not pass: no firing

    [firing] = await _firings(biz, trigger_id)
    run = await _run(firing.run_id)
    assert run.input_data == {"input": "Order A-7 paid"} and run.status == "PENDING"
    assert (run.trigger_id, run.event_id, run.chain_depth) == (trigger_id, big, 0)
    assert run.correlation_id == big and run.user_id == biz.user
    assert len(biz.queued) == 1  # queued for the worker as a normal run

    # Routed is routed: a second nudge, or the same event again, decides nothing.
    assert "skipped" in await _route(biz, big)
    assert len(await _firings(biz, trigger_id)) == 1


async def test_paused_automation_holds_events_and_resuming_routes_them_in_order(biz):
    trigger_id = await _trigger(biz, kind="event", event_type="custom.order.paid")
    await _set_state(biz, "paused")
    first, _ = await _event(biz)
    second, _ = await _event(biz)
    assert (await _route(biz, first))["parked"] and (await _route(biz, second))["parked"]
    assert await _firings(biz, trigger_id) == []

    await _set_state(biz, "running")
    async with _session() as db:
        assert await router.release_parked(db, biz.company) == 2
    firings = await _firings(biz, trigger_id)
    assert [f.event_id for f in firings] == [first, second]
    assert {f.outcome for f in firings} == {"started"}


async def test_no_loop_limit_unless_the_business_sets_one(biz):
    trigger_id = await _trigger(biz, kind="event", event_type="custom.order.paid")
    deep, _ = await _event(biz, chain_depth=40)
    assert (await _route(biz, deep))["decisions"][0]["outcome"] == "started"

    await _set_limits(biz, {"max_chain_depth": 3})
    deeper, _ = await _event(biz, chain_depth=4)
    [decision] = (await _route(biz, deeper))["decisions"]
    assert decision["outcome"] == "skipped_chain_depth" and "limit of 3" in decision["reason"]
    async with _session() as db:
        blocked = (await db.execute(select(Event).where(Event.company_id == biz.company,
                                                        Event.type == "automation.loop_blocked"))).scalar_one()
    assert blocked.data["trigger_id"] == str(trigger_id) and blocked.data["chain_depth"] == 4


async def test_overlap_queue_waits_its_turn_and_starts_when_there_is_room(biz):
    from src.ai.orm import ExecutionRun

    trigger_id = await _trigger(biz, kind="event", event_type="custom.order.paid", overlap="queue")
    first, _ = await _event(biz)
    second, _ = await _event(biz)
    assert (await _route(biz, first))["decisions"][0]["outcome"] == "started"
    [decision] = (await _route(biz, second))["decisions"]
    assert decision["outcome"] == "queued" and decision["run"] is None

    async with _session() as db:
        assert await router.drain_queued(db, biz.company) == 0  # the first run is still going
        started = (await db.execute(select(TriggerFiring).where(TriggerFiring.event_id == first))).scalar_one()
        run = await db.get(ExecutionRun, started.run_id)
        run.status = "RUNNING"  # runs move through their states (enums.py)
        await db.commit()
        run.status = "COMPLETED"
        await db.commit()
        assert await router.drain_queued(db, biz.company) == 1
    later = [f for f in await _firings(biz, trigger_id) if f.event_id == second][0]
    assert later.outcome == "started" and later.run_id and "waiting in the queue" in later.reason


async def test_a_run_the_wallet_refuses_is_recorded_as_blocked_budget(biz, monkeypatch):
    from src.billing.credit_service import CreditService

    async def _empty(self, *args, **kwargs):
        raise HTTPException(status_code=402, detail="Insufficient credits")

    monkeypatch.setattr(CreditService, "require_credits", _empty)
    trigger_id = await _trigger(biz, kind="event", event_type="custom.order.paid")
    event_id, _ = await _event(biz)
    [decision] = (await _route(biz, event_id))["decisions"]
    assert decision["outcome"] == "blocked_budget" and "Insufficient credits" in decision["reason"]
    [firing] = await _firings(biz, trigger_id)
    assert firing.run_id is None
    async with _session() as db:
        event = await db.get(Event, event_id)
        trigger = await db.get(Trigger, trigger_id)
    assert event.status == "routed" and trigger.last_fired_at is None


async def test_an_inactive_agent_does_not_run_automatically(biz):
    from src.ai.orm import HierarchicalEntity

    trigger_id = await _trigger(biz, kind="event", event_type="custom.order.paid")
    async with _session() as db:
        (await db.get(HierarchicalEntity, biz.agent)).status = "DRAFT"
        await db.commit()
    event_id, _ = await _event(biz)
    [decision] = (await _route(biz, event_id))["decisions"]
    assert decision["outcome"] == "blocked_policy" and "DRAFT" in decision["reason"]
    assert (await _firings(biz, trigger_id))[0].run_id is None


async def test_the_fifth_failure_makes_an_event_dead_and_says_so(biz, monkeypatch):
    from arq import Retry

    event_id, _ = await _event(biz)

    async def _broken(*args, **kwargs):
        raise RuntimeError("database away")

    monkeypatch.setattr(router, "route", _broken)
    with pytest.raises(Retry):
        await router.route_event({"job_try": 1}, str(event_id), str(biz.company))
    assert (await router.route_event({"job_try": 5}, str(event_id), str(biz.company)))["dead"]
    async with _session() as db:
        event = await db.get(Event, event_id)
        dead = (await db.execute(select(Event).where(Event.company_id == biz.company,
                                                     Event.type == "automation.event_dead"))).scalar_one()
        assert (event.status, event.attempts) == ("dead", 2) and "database away" in event.last_error
        assert dead.data["event_id"] == str(event_id)
        assert await router.replay(db, biz.company, event_id)
    assert biz.nudged[-1][1] == event_id and biz.nudged[-1][2].startswith("replay-")


# ── The scheduler ──────────────────────────────────────────────────────────

def _minute(moment: datetime) -> datetime:
    return moment.replace(second=0, microsecond=0)


async def _due(biz, trigger_id, next_fire_at, **changes):
    """Make the trigger (and its index row) due at ``next_fire_at``."""
    async with _session() as db, _session() as cdb:
        trigger = await db.get(Trigger, trigger_id)
        trigger.next_fire_at = next_fire_at
        for key, value in changes.items():
            setattr(trigger, key, value)
        await db.commit()
        await triggers.sync_time_index(cdb, biz.company, trigger)
        await cdb.commit()
    return scheduler.Due(biz.company, "trigger", trigger_id, next_fire_at)


async def _scheduled_events(biz, trigger_id):
    async with _session() as db:
        return (await db.execute(select(Event).where(
            Event.company_id == biz.company, Event.type.in_(("schedule.fired", "timer.fired")),
            Event.subject == f"trigger:{trigger_id}").order_by(Event.time))).scalars().all()


async def test_a_due_schedule_fires_once_and_moves_to_its_next_time(biz):
    now = datetime.utcnow()
    trigger_id = await _trigger(biz, kind="schedule", cron="* * * * *", timezone="Asia/Kolkata")
    due = await _due(biz, trigger_id, _minute(now))

    result = await scheduler.fire_trigger(due, "test", now)
    assert result["fired"] == 1
    [event] = await _scheduled_events(biz, trigger_id)
    assert event.data["trigger_id"] == str(trigger_id) and event.time == _minute(now)
    assert biz.nudged[-1][1] == event.id

    async with _session() as db:
        trigger = await db.get(Trigger, trigger_id)
        row = await db.get(TimeIndexEntry, (biz.company, "trigger", trigger_id))
    assert trigger.firings == 1 and trigger.next_fire_at > now
    assert row.due_at == trigger.next_fire_at and row.lease_owner is None

    # The same due row again (a second replica, a retry): nothing more fires.
    assert (await scheduler.fire_trigger(due, "test", now))["fired"] == 0
    assert len(await _scheduled_events(biz, trigger_id)) == 1

    # The router starts the trigger's agent for it.
    [decision] = (await _route(biz, event.id))["decisions"]
    assert decision["outcome"] == "started"


async def test_two_schedulers_never_claim_the_same_row(biz):
    now = datetime.utcnow()
    trigger_id = await _trigger(biz, kind="schedule", cron="* * * * *")
    await _due(biz, trigger_id, _minute(now))
    mine = [d for d in await scheduler.claim("a", now) if d.ref_id == trigger_id]
    theirs = [d for d in await scheduler.claim("b", now) if d.ref_id == trigger_id]
    assert len(mine) == 1 and theirs == []
    # A lease that lapsed (its scheduler died) is claimed again.
    assert [d for d in await scheduler.claim("b", now + timedelta(seconds=61)) if d.ref_id == trigger_id]


@pytest.mark.parametrize("rule, expected", [("skip", 0), ("once", 1), ("all", 61)])
async def test_a_late_schedule_follows_its_catch_up_rule(biz, rule, expected):
    now = _minute(datetime.utcnow()) + timedelta(seconds=5)
    trigger_id = await _trigger(biz, kind="schedule", cron="* * * * *", catch_up=rule)
    due = await _due(biz, trigger_id, now.replace(second=0) - timedelta(hours=1))

    result = await scheduler.fire_trigger(due, "test", now)
    events = await _scheduled_events(biz, trigger_id)
    assert result["fired"] == len(events) == expected
    if rule == "once":
        assert events[0].time == now.replace(second=0)  # the latest missed time
    skipped = [f for f in await _firings(biz, trigger_id) if f.outcome == "skipped_missed"]
    assert len(skipped) == (0 if rule == "all" else 1)


async def test_the_business_caps_how_many_missed_times_fire(biz):
    now = _minute(datetime.utcnow()) + timedelta(seconds=5)
    await _set_limits(biz, {"catch_up_max": 3})
    trigger_id = await _trigger(biz, kind="schedule", cron="* * * * *")  # catch-up: the business's (all)
    due = await _due(biz, trigger_id, now.replace(second=0) - timedelta(hours=1))
    assert (await scheduler.fire_trigger(due, "test", now))["fired"] == 3
    times = [e.time for e in await _scheduled_events(biz, trigger_id)]
    assert times == [now.replace(second=0) - timedelta(minutes=m) for m in (2, 1, 0)]


async def test_a_timer_fires_once_and_leaves_the_index(biz):
    now = datetime.utcnow()
    trigger_id = await _trigger(biz, kind="timer", run_at=(now + timedelta(minutes=5)).isoformat())
    due = await _due(biz, trigger_id, now - timedelta(seconds=10))
    assert (await scheduler.fire_trigger(due, "test", now))["fired"] == 1
    [event] = await _scheduled_events(biz, trigger_id)
    assert event.type == "timer.fired"
    async with _session() as db:
        assert (await db.get(Trigger, trigger_id)).next_fire_at is None
        assert await db.get(TimeIndexEntry, (biz.company, "trigger", trigger_id)) is None


async def test_nothing_fires_while_paused_and_the_row_is_looked_at_again_later(biz):
    now = datetime.utcnow()
    trigger_id = await _trigger(biz, kind="schedule", cron="* * * * *")
    due = await _due(biz, trigger_id, _minute(now))
    await _set_state(biz, "paused")
    async with _session() as db:  # leased by this scheduler, as claim() leaves it
        row = await db.get(TimeIndexEntry, (biz.company, "trigger", trigger_id))
        row.lease_owner = "test"
        await db.commit()
    assert (await scheduler.fire_trigger(due, "test", now))["paused"]
    assert await _scheduled_events(biz, trigger_id) == []
    async with _session() as db:
        row = await db.get(TimeIndexEntry, (biz.company, "trigger", trigger_id))
    assert row.lease_until >= now + timedelta(seconds=59)


async def test_a_deleted_trigger_leaves_the_index(biz):
    now = datetime.utcnow()
    trigger_id = await _trigger(biz, kind="schedule", cron="* * * * *")
    due = await _due(biz, trigger_id, _minute(now))
    async with _session() as db:
        await db.execute(delete(Trigger).where(Trigger.id == trigger_id))
        await db.commit()
    assert (await scheduler.fire_trigger(due, "test", now))["gone"]
    async with _session() as db:
        count = (await db.execute(select(func.count()).select_from(TimeIndexEntry).where(
            TimeIndexEntry.ref_id == trigger_id))).scalar()
    assert count == 0


# ── Event history kept (D47) ───────────────────────────────────────────────

async def test_event_history_is_kept_unless_the_business_sets_a_limit(biz):
    from src.automation import retention

    trigger_id = await _trigger(biz, kind="event", event_type="custom.order.paid")
    old, _ = await _event(biz)
    await _route(biz, old)                     # handled, with a decision
    failed, _ = await _event(biz)              # still needs attention
    recent, _ = await _event(biz)
    await _route(biz, recent)
    async with _session() as db:
        for event_id in (old, failed):
            (await db.get(Event, event_id)).received_at = datetime.utcnow() - timedelta(days=40)
        (await db.get(Event, failed)).status = "dead"
        await db.commit()

    assert (await retention.prune_event_history({}))["deleted"].get(str(biz.company)) is None  # no limit: kept

    await _set_limits(biz, {"event_retention_days": 30})
    assert (await retention.prune_event_history({}))["deleted"][str(biz.company)] == 1
    async with _session() as db:
        assert await db.get(Event, old) is None
        assert (await db.get(Event, failed)).status == "dead" and await db.get(Event, recent) is not None
    assert [f.event_id for f in await _firings(biz, trigger_id)] == [recent]


# ── Run finished → another agent (run.* events) ────────────────────────────

async def test_when_an_agent_finishes_the_next_one_starts_once(biz):
    from src.ai.orm import ExecutionRun, HierarchicalEntity
    from src.automation import run_events

    async with _session() as db:
        research = HierarchicalEntity(company_id=biz.company, type="AGENT", status="ACTIVE", name="Research")
        db.add(research)
        await db.flush()
        before = ExecutionRun(company_id=biz.company, entity_id=research.id, status="COMPLETED", input_data={},
                              completed_at=datetime.utcnow() - timedelta(minutes=5))
        db.add(before)
        await db.commit()
        research_id = research.id

    with pytest.raises(triggers.TriggerError, match="forever"):
        await _trigger(biz, kind="event", event_type="run.completed",
                       filter={"path": "data.entity_id", "op": "eq", "value": str(biz.agent)})
    trigger_id = await _trigger(biz, kind="event", event_type="run.completed",
                                filter={"path": "data.entity_id", "op": "eq", "value": str(research_id)},
                                input_template={"input": "Write up: {{ event.data.output.summary }}"})

    async with _session() as db:
        db.add(ExecutionRun(company_id=biz.company, entity_id=research_id, status="COMPLETED", input_data={},
                            result_data={"summary": "three findings"}, completed_at=datetime.utcnow(),
                            correlation_id=None, chain_depth=0))
        await db.commit()
        assert await run_events.relay_all(db) == 1   # the run that ended before the trigger is history
        assert await run_events.relay_all(db) == 0   # once per run
        event = (await db.execute(select(Event).where(Event.company_id == biz.company,
                                                      Event.type == "run.completed"))).scalar_one()
    assert biz.nudged[-1][1] == event.id and event.chain_depth == 1 and event.data["entity_name"] == "Research"

    [decision] = (await _route(biz, event.id))["decisions"]
    assert decision["outcome"] == "started"
    run = await _run(decision["run"] and uuid.UUID(decision["run"]))
    assert run.input_data == {"input": "Write up: three findings"} and run.chain_depth == 1
    assert [f.event_id for f in await _firings(biz, trigger_id)] == [event.id]


async def test_the_kernel_emits_a_finished_run_itself_once(biz):
    """W3-1: the event exists when the run ends, without the sweep; the sweep then adds nothing."""
    from src.ai.orm import ExecutionRun
    from src.automation import run_events

    async with _session() as db:
        run = ExecutionRun(company_id=biz.company, entity_id=biz.agent, status="COMPLETED", input_data={},
                           result_data={"summary": "done"}, completed_at=datetime.utcnow())
        db.add(run)
        await db.commit()
        assert await run_events.emit_run_finished(db, run) == []       # nobody listens: nothing stored
    other = await _other_agent(biz)
    await _trigger(biz, kind="event", event_type="run.completed", entity_id=other,
                   filter={"path": "data.entity_id", "op": "eq", "value": str(biz.agent)})
    async with _session() as db:
        run = await db.get(ExecutionRun, run.id)
        [event_id] = await run_events.emit_run_finished(db, run)
        assert await run_events.emit_run_finished(db, run) == []       # once per run and outcome
        assert await run_events.relay_all(db) == 0                     # the sweep finds it stored
        event = await db.get(Event, event_id)
    assert event.type == "run.completed" and event.data["output"] == {"summary": "done"}
    assert biz.nudged[-1][1] == event_id


async def test_cancelling_a_run_emits_run_cancelled(biz):
    from src.ai.orm import ExecutionRun
    from src.ai.service import AIService

    other = await _other_agent(biz)
    await _trigger(biz, kind="event", event_type="run.cancelled", entity_id=other)
    async with _session() as db:
        run = ExecutionRun(company_id=biz.company, entity_id=biz.agent, status="RUNNING", input_data={})
        db.add(run)
        await db.commit()
        await AIService(db).cancel_execution(run.id, biz.company, "tenant_admin")
        [event] = (await db.execute(select(Event).where(Event.company_id == biz.company,
                                                        Event.type == "run.cancelled"))).scalars().all()
    assert event.data["run_id"] == str(run.id) and event.data["status"] == "CANCELLED"


async def test_answering_an_approval_emits_approval_decided(biz):
    from src.ai.orm import ExecutionRun, HumanApproval
    from src.ai.service import AIService
    from src.automation import run_events

    await _trigger(biz, kind="event", event_type="approval.decided")
    async with _session() as db:
        run = ExecutionRun(company_id=biz.company, entity_id=biz.agent, status="PAUSED", input_data={})
        db.add(run)
        await db.flush()
        approval = HumanApproval(run_id=run.id, company_id=biz.company, checkpoint_trigger="BEFORE_STEP: Send",
                                 status="PENDING", requested_at=datetime.utcnow())
        db.add(approval)
        await db.commit()
        await AIService(db).respond_to_approval(approval.id, "APPROVED", biz.user, "fine", company_id=biz.company)
        rows = (await db.execute(select(Event).where(Event.company_id == biz.company,
                                                     Event.type == "approval.decided"))).scalars().all()
        assert await run_events.relay_all(db) == 0                     # not made twice by the sweep
    assert [(e.data["status"], e.data["notes"]) for e in rows] == [("APPROVED", "fine")]


async def _other_agent(biz):
    """A second agent to run: a trigger on its own agent's runs is refused (it would loop)."""
    from src.ai.orm import HierarchicalEntity

    async with _session() as db:
        agent = HierarchicalEntity(company_id=biz.company, type="AGENT", status="ACTIVE", name="ws3 next")
        db.add(agent)
        await db.commit()
        return agent.id


async def test_a_trigger_does_not_answer_events_from_before_it_existed(biz):
    old, _ = await _event(biz)
    async with _session() as db:
        (await db.get(Event, old)).time = datetime.utcnow() - timedelta(hours=1)
        await db.commit()
    trigger_id = await _trigger(biz, kind="event", event_type="custom.order.paid")
    assert (await _route(biz, old))["decisions"] == []
    assert await _firings(biz, trigger_id) == []


async def test_an_approval_is_an_event_when_requested_and_when_decided(biz):
    from src.ai.orm import ExecutionRun, HumanApproval
    from src.automation import run_events

    trigger_id = await _trigger(biz, kind="event", event_type="approval.requested")
    async with _session() as db:
        run = ExecutionRun(company_id=biz.company, entity_id=biz.agent, status="PAUSED", input_data={})
        db.add(run)
        await db.flush()
        approval = HumanApproval(run_id=run.id, company_id=biz.company, checkpoint_trigger="BEFORE_STEP: Send",
                                 status="PENDING", requested_at=datetime.utcnow())
        db.add(approval)
        await db.commit()
        assert await run_events.relay_all(db) == 1
        approval.status, approval.responded_at = "APPROVED", datetime.utcnow()
        await db.commit()
        assert await run_events.relay_all(db) == 1        # decided — and requested is not made twice
        assert await run_events.relay_all(db) == 0
        rows = (await db.execute(select(Event).where(Event.company_id == biz.company,
                                                     Event.type.like("approval.%"))
                                 .order_by(Event.time))).scalars().all()
    assert [(e.type, e.data["status"]) for e in rows] == [("approval.requested", "PENDING"),
                                                          ("approval.decided", "APPROVED")]
    [decision] = (await _route(biz, rows[0].id))["decisions"]
    assert decision["trigger"] == str(trigger_id) and decision["outcome"] == "started"
