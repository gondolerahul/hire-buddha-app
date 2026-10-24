"""Durable waits on Postgres (tech spec §7.9): ``wait_for_event`` writes a wait
and its deadline; a matching event answers it before any trigger; the
deadline expires it; an operator cancels it; a lost resume is re-sent; a wait
whose run ended without it is closed. The loop's park/resume side is
tests/unit/test_wait_parking.py.

Committed rows, one company per test, purged afterwards (as
``test_automation_runtime.py``). Resumes and nudges are recorded, not sent.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select

from src.automation import limits as limits_mod
from src.automation import router, scheduler, store, waits
from src.automation.events import Envelope
from src.automation.models import TimeIndexEntry, Wait
from tests.harness.wallet import fund

pytestmark = pytest.mark.needs_db


@pytest_asyncio.fixture
async def biz(monkeypatch):
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    import src.common.orm_models  # noqa: F401
    from src.ai.orm import ExecutionRun, HierarchicalEntity
    from src.auth.models import Company, User
    from src.billing.billing_models import CreditWallet
    from src.common import database
    from src.common.config import settings
    from tests.harness.purge import purge_companies

    engine = create_async_engine(settings.CONTROL_DATABASE_URL, poolclass=NullPool,
                                 json_serializer=database.json_serializer)
    monkeypatch.setattr(database, "AsyncSessionLocal", async_sessionmaker(engine, expire_on_commit=False))
    resumed, nudged = [], []

    async def _resume(company_id, run_id, wait_id):
        resumed.append((run_id, str(wait_id)))

    async def _nudge(company_id, event_id, *, attempt=""):
        nudged.append(event_id)

    monkeypatch.setattr(waits, "enqueue_resume", _resume)
    monkeypatch.setattr(store, "nudge", _nudge)

    async with database.AsyncSessionLocal() as db:
        company = Company(name=f"ws3-waits-{uuid.uuid4().hex[:6]}", type="TENANT", status="active")
        db.add(company)
        await db.flush()
        later = datetime.utcnow() + timedelta(days=1)
        await fund(db, company.id, "100")
        admin = User(email=f"ws3-{uuid.uuid4().hex[:8]}@example.com", hashed_password="x", full_name="WS3",
                     role="tenant_admin", company_id=company.id, is_active=True, is_verified=True)
        agent = HierarchicalEntity(company_id=company.id, type="AGENT", status="ACTIVE", name="Sales",
                                   capabilities={"tools": [{"tool_id": "wait_for_event"}]})
        db.add_all([admin, agent])
        await db.flush()
        run = ExecutionRun(company_id=company.id, entity_id=agent.id, status="RUNNING", input_data={})
        db.add(run)
        await db.commit()
        ids = SimpleNamespace(company=company.id, agent=agent.id, run=run.id, admin=admin, resumed=resumed,
                              nudged=nudged)
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


async def _wait(biz, **args):
    import src.ai.tools  # noqa: F401
    from src.ai.tools.base import ToolRegistry

    ctx = {"company_id": str(biz.company), "run_id": str(biz.run), "entity_id": str(biz.agent)}
    return await ToolRegistry.get_tool("wait_for_event").invoke(args, ctx)


async def _event(biz, event_type="email.received", data=None, time=None):
    async with _session() as db:
        row, _ = await store.record(db, biz.company, Envelope(
            type=event_type, source="test", trust="verified", data=data or {}, dedupe_key=uuid.uuid4().hex,
            **({"time": time} if time else {})))
        await db.commit()
        return row.id


async def _route(biz, event_id):
    async with _session() as db:
        return await router.route(db, biz.company, event_id)


async def _set_run_status(biz, status):
    from src.ai.orm import ExecutionRun

    async with _session() as db:
        run = await db.get(ExecutionRun, biz.run)
        run.status = status
        await db.commit()


async def test_a_run_waits_once_with_a_deadline(biz):
    out = await _wait(biz, type="email.received", timeout="48h",
                      match={"path": "data.from", "op": "eq", "value": "priya@example.com"})
    assert out.success, out.error
    async with _session() as db:
        wait = await db.get(Wait, uuid.UUID(out.output["wait_id"]))
        row = await db.get(TimeIndexEntry, (biz.company, "wait", wait.id))
    assert (wait.status, wait.run_id, wait.event_type) == ("waiting", biz.run, "email.received")
    assert row.due_at == wait.deadline_at
    assert abs(wait.deadline_at - (datetime.utcnow() + timedelta(hours=48))) < timedelta(minutes=1)

    again = await _wait(biz, type="email.received", timeout="1h")
    assert not again.success and "already waiting" in again.error
    bad = await _wait(biz, type="not an event", timeout="1h")
    assert not bad.success


async def test_the_business_limit_on_wait_length_applies_only_when_set(biz):
    assert (await _wait(biz, type="custom.lead.replied", timeout="400d")).success  # no limit by default
    async with _session() as db:
        await db.execute(Wait.__table__.update().values(status="cancelled"))
        await db.commit()
        await limits_mod.save(db, biz.company, {"max_wait_days": 30}, None)
    over = await _wait(biz, type="custom.lead.replied", timeout="31d")
    assert not over.success and "at most 30 days" in over.error


async def test_a_matching_event_answers_the_wait_before_any_trigger(biz):
    await _set_run_status(biz, "WAITING_ON_EVENT")
    out = await _wait(biz, type="email.*", timeout="2d", match={"path": "data.from", "op": "eq", "value": "priya"})
    wait_id = uuid.UUID(out.output["wait_id"])

    other = await _event(biz, data={"from": "ravi"})
    assert (await _route(biz, other))["resumed_waits"] == []
    earlier = await _event(biz, data={"from": "priya"}, time=datetime.utcnow() - timedelta(hours=1))
    assert (await _route(biz, earlier))["resumed_waits"] == []        # from before the wait began
    reply = await _event(biz, data={"from": "priya", "body": "Yes, Saturday works"})
    assert (await _route(biz, reply))["resumed_waits"] == [str(wait_id)]
    assert biz.resumed == [(biz.run, str(wait_id))]

    async with _session() as db:
        wait = await db.get(Wait, wait_id)
        assert (wait.status, wait.satisfied_by_event_id) == ("satisfied", reply)
        outcome = await waits.outcome_for(db, {"wait_id": str(wait_id)})
        assert outcome["status"] == "satisfied" and "Saturday works" in outcome["text"]
        assert await waits.claim_run(db, biz.run) is True
        assert await waits.claim_run(db, biz.run) is False                # one resume drives it


async def test_the_deadline_expires_the_wait_and_resumes_with_a_timeout(biz):
    await _set_run_status(biz, "WAITING_ON_EVENT")
    out = await _wait(biz, type="email.received", timeout="1h")
    wait_id = uuid.UUID(out.output["wait_id"])
    due = scheduler.Due(biz.company, "wait", wait_id, datetime.utcnow())
    assert (await scheduler.fire(due, "test", datetime.utcnow() + timedelta(hours=2)))["expired"]
    assert biz.resumed == [(biz.run, str(wait_id))]
    async with _session() as db:
        assert (await db.get(Wait, wait_id)).status == "expired"
        assert await db.get(TimeIndexEntry, (biz.company, "wait", wait_id)) is None
        outcome = await waits.outcome_for(db, {"wait_id": str(wait_id)})
    assert outcome["status"] == "expired" and "timed out" in outcome["text"]
    # A late event no longer answers it.
    assert (await _route(biz, await _event(biz)))["resumed_waits"] == []


async def test_an_operator_cancels_a_wait_from_the_control_room(biz):
    from src.auth import service
    from src.main import app

    await _set_run_status(biz, "WAITING_ON_EVENT")
    out = await _wait(biz, type="custom.lead.replied", timeout="3d")
    headers = {"Authorization": f"Bearer {service.issue_access_token(biz.admin)}"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client:
        listed = await client.get("/api/v1/automation/waits", headers=headers)
        assert listed.status_code == 200, listed.text
        [item] = listed.json()
        assert item["entity_name"] == "Sales" and item["event_type"] == "custom.lead.replied"
        cancelled = await client.post(f"/api/v1/automation/waits/{item['id']}/cancel", headers=headers)
        assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
        again = await client.post(f"/api/v1/automation/waits/{item['id']}/cancel", headers=headers)
        assert again.status_code == 409
        health = (await client.get("/api/v1/automation/health", headers=headers)).json()
    assert health["waiting_runs"] == 0
    assert biz.resumed and biz.resumed[-1][0] == biz.run
    async with _session() as db:
        outcome = await waits.outcome_for(db, {"wait_id": out.output["wait_id"]})
    assert outcome["status"] == "cancelled"


async def test_the_sweep_resends_a_lost_resume_and_closes_waits_of_ended_runs(biz):
    await _set_run_status(biz, "WAITING_ON_EVENT")
    out = await _wait(biz, type="email.received", timeout="1h")
    wait_id = uuid.UUID(out.output["wait_id"])
    reply = await _event(biz)
    await _route(biz, reply)
    biz.resumed.clear()
    async with _session() as db:
        assert await waits.sweep_lost_resumes(db) == 0                    # its resume is on its way
        assert await waits.sweep_lost_resumes(db, now=datetime.utcnow() + timedelta(minutes=5)) == 1
    assert biz.resumed[0][0] == biz.run

    # A run that ended (failed) while waiting: its wait is closed, not answered later.
    await _set_run_status(biz, "FAILED")
    async with _session() as db:
        open_wait = Wait(id=uuid.uuid4(), company_id=biz.company, run_id=biz.run, step_ref="",
                         event_type="custom.x.y", status="waiting", deadline_at=datetime.utcnow() + timedelta(days=1))
        db.add(open_wait)
        await db.commit()
        await waits.sweep_lost_resumes(db)
        assert (await db.get(Wait, open_wait.id)).status == "cancelled"
        assert (await db.get(Wait, wait_id)).status == "satisfied"
