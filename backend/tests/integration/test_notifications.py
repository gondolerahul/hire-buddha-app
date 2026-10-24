"""Notifications (WS3 3.11; functional spec §3.6) on Postgres: the right people
are told once, by e-mail too when the platform can send it; each reads and
clears their own; automation tells about dead events, wallet blocks, triggers
that keep failing, stopped loops and missed schedules.

Committed rows, one company per test, purged afterwards. E-mail is recorded,
not sent; nudges and run jobs are not sent.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select

from src.automation import limits as limits_mod
from src.automation import router, scheduler, store, triggers
from src.automation.events import Envelope
from src.notifications.models import Notification
from src.notifications.service import notify
from tests.harness.wallet import fund

pytestmark = pytest.mark.needs_db


@pytest_asyncio.fixture
async def biz(monkeypatch):
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    import src.common.orm_models  # noqa: F401
    from src.ai.orm import HierarchicalEntity
    from src.auth.models import Company, User
    from src.billing.billing_models import CreditWallet
    from src.common import database
    from src.common.config import settings
    from src.common.email import email_service
    from tests.harness.purge import purge_companies

    engine = create_async_engine(settings.CONTROL_DATABASE_URL, poolclass=NullPool,
                                 json_serializer=database.json_serializer)
    monkeypatch.setattr(database, "AsyncSessionLocal", async_sessionmaker(engine, expire_on_commit=False))
    mails = []

    async def _mail(to, subject, body):
        mails.append((to, subject))
        return True

    async def _quiet(*args, **kwargs):
        return None

    monkeypatch.setattr(email_service, "async_send_email", _mail)
    monkeypatch.setattr(store, "nudge", _quiet)
    monkeypatch.setattr("src.ai.service.enqueue_job", _quiet)

    async with database.AsyncSessionLocal() as db:
        company = Company(name=f"ws3-notify-{uuid.uuid4().hex[:6]}", type="TENANT", status="active")
        db.add(company)
        await db.flush()
        later = datetime.utcnow() + timedelta(days=1)
        await fund(db, company.id, "100")

        def person(role, active=True):
            row = User(email=f"ws3-{uuid.uuid4().hex[:8]}@example.com", hashed_password="x", full_name=role,
                       role=role, company_id=company.id, is_active=active, is_verified=True)
            db.add(row)
            return row

        owner, operator, gone = person("tenant_admin"), person("tenant_user"), person("tenant_admin", active=False)
        agent = HierarchicalEntity(company_id=company.id, type="AGENT", status="ACTIVE", name="Sales")
        db.add(agent)
        await db.commit()
        ids = SimpleNamespace(company=company.id, owner=owner, operator=operator, gone=gone, agent=agent.id,
                              mails=mails)
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


async def _mine(biz):
    async with _session() as db:
        rows = (await db.execute(select(Notification).where(Notification.company_id == biz.company)
                                 .order_by(Notification.created_at))).scalars().all()
    return [(r.user_id, r.kind) for r in rows]


async def test_the_right_people_are_told_once_and_emailed(biz):
    told = await notify(biz.company, kind="automation.test", title="Something happened", dedupe_key="k1",
                        audience="admins")
    assert told == 1 and await _mine(biz) == [(biz.owner.id, "automation.test")]
    assert biz.mails == [(biz.owner.email, "HireBuddha: Something happened")]
    assert await notify(biz.company, kind="automation.test", title="Again", dedupe_key="k1") == 0  # once

    await notify(biz.company, kind="automation.ops", title="Operational", dedupe_key="k2", audience="operators")
    assert {u for u, k in await _mine(biz) if k == "automation.ops"} == {biz.owner.id, biz.operator.id}
    async with _session() as db:
        emailed = (await db.execute(select(Notification.emailed_at).where(
            Notification.user_id == biz.owner.id, Notification.dedupe_key == "k1"))).scalar_one()
    assert emailed is not None


async def test_each_person_reads_and_clears_their_own(biz):
    from src.auth import service
    from src.main import app

    await notify(biz.company, kind="automation.a", title="A", dedupe_key="a", audience="operators", email=False)
    await notify(biz.company, kind="automation.b", title="B", dedupe_key="b", audience="operators", email=False)
    owner = {"Authorization": f"Bearer {service.issue_access_token(biz.owner)}"}
    operator = {"Authorization": f"Bearer {service.issue_access_token(biz.operator)}"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client:
        listed = (await client.get("/api/v1/notifications", headers=owner)).json()
        assert listed["unread"] == 2 and [n["title"] for n in listed["items"]] == ["B", "A"]
        first = listed["items"][0]["id"]
        assert (await client.post(f"/api/v1/notifications/{first}/read", headers=operator)).status_code == 404
        read = await client.post(f"/api/v1/notifications/{first}/read", headers=owner)
        assert read.status_code == 200 and read.json()["read_at"]
        assert (await client.get("/api/v1/notifications", headers=owner)).json()["unread"] == 1
        cleared = (await client.post("/api/v1/notifications/read-all", headers=owner)).json()
        assert cleared["unread"] == 0
        assert (await client.get("/api/v1/notifications", headers=operator)).json()["unread"] == 2


async def _trigger(biz, **fields):
    async with _session() as db, _session() as cdb:
        trigger = await triggers.create(db, cdb, biz.company, {"name": "Lead follow-up", "entity_id": biz.agent,
                                                               **fields}, triggers.Actor("user", biz.owner.id))
        await db.commit()
        await cdb.commit()
        return trigger.id


async def _event(biz, **kwargs):
    async with _session() as db:
        row, _ = await store.record(db, biz.company, Envelope(type="custom.lead.new", source="test",
                                                               trust="internal", dedupe_key=uuid.uuid4().hex,
                                                               **kwargs))
        await db.commit()
        return row.id


async def _route(biz, event_id):
    async with _session() as db:
        return await router.route(db, biz.company, event_id)


async def test_wallet_blocks_and_a_failing_trigger_are_told(biz, monkeypatch):
    from src.billing.credit_service import CreditService

    async def _empty(self, *args, **kwargs):
        raise HTTPException(status_code=402, detail="Insufficient credits")

    monkeypatch.setattr(CreditService, "require_credits", _empty)
    await _trigger(biz, kind="event", event_type="custom.lead.*")
    for _ in range(3):
        await _route(biz, await _event(biz))
    kinds = await _mine(biz)
    assert (biz.owner.id, "automation.blocked_budget") in kinds
    assert (biz.operator.id, "automation.blocked_budget") not in kinds        # owners and admins only
    assert {u for u, k in kinds if k == "automation.trigger_failing"} == {biz.owner.id, biz.operator.id}
    assert sum(1 for _, k in kinds if k == "automation.blocked_budget") == 1   # once a day per trigger


async def test_a_stopped_loop_and_a_dead_event_are_told(biz, monkeypatch):
    async with _session() as db:
        await limits_mod.save(db, biz.company, {"max_chain_depth": 1}, None)
    await _trigger(biz, kind="event", event_type="custom.lead.*")
    await _route(biz, await _event(biz, chain_depth=2))
    assert (biz.operator.id, "automation.loop_stopped") in await _mine(biz)

    dead = await _event(biz)

    async def _broken(*args, **kwargs):
        raise RuntimeError("database away")

    monkeypatch.setattr(router, "route", _broken)
    await router.route_event({"job_try": 5}, str(dead), str(biz.company))
    assert {u for u, k in await _mine(biz) if k == "automation.event_dead"} == {biz.owner.id, biz.operator.id}


async def test_missed_schedule_times_are_told(biz):
    now = datetime.utcnow().replace(second=0, microsecond=0) + timedelta(seconds=5)
    trigger_id = await _trigger(biz, kind="schedule", cron="* * * * *", catch_up="skip")
    async with _session() as db, _session() as cdb:
        from src.automation.models import Trigger

        trigger = await db.get(Trigger, trigger_id)
        trigger.next_fire_at = now.replace(second=0) - timedelta(hours=1)
        await db.commit()
        await triggers.sync_time_index(cdb, biz.company, trigger)
        await cdb.commit()
    due = scheduler.Due(biz.company, "trigger", trigger_id, now - timedelta(hours=1))
    assert (await scheduler.fire_trigger(due, "test", now))["skipped"]
    kinds = await _mine(biz)
    assert (biz.owner.id, "automation.missed_schedule") in kinds
    assert (biz.operator.id, "automation.missed_schedule") not in kinds
