"""Today's inbound paths on events and triggers (WS3 3.5, 3.9; tech spec §7.13),
through the real app on Postgres and the local Redis:

* a signed webhook is stored as an event (once per delivery) before the 202,
  and the endpoint's agent runs through the endpoint's trigger, with the
  event as its input and the lead as its subject, as before;
* an event that names an agent gets a visible system trigger the first time;
* an unbound endpoint's event starts nothing and stays in the event log;
* a sheet row still becomes a one-contact voice campaign, now with a decision;
* revoking an endpoint turns its trigger off;
* migration ``p14_webhook_triggers`` gives existing endpoints the triggers that
  reproduce what ran before (the binding; the company's only agent).

Committed rows, one company per test, purged afterwards (as
``test_automation_runtime.py``). Nudges, run jobs and campaign jobs are
recorded, not sent.
"""
from __future__ import annotations

import hashlib
import hmac
import importlib.util
import json
import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select, text

from src.automation import router, store
from src.automation.models import Event, Trigger, TriggerFiring

pytestmark = pytest.mark.needs_db

BACKEND = Path(__file__).resolve().parents[2]


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
    from tests.harness.purge import purge_companies

    engine = create_async_engine(settings.CONTROL_DATABASE_URL, poolclass=NullPool,
                                 json_serializer=database.json_serializer)
    monkeypatch.setattr(database, "AsyncSessionLocal", async_sessionmaker(engine, expire_on_commit=False))
    monkeypatch.setattr(settings, "AUTOMATION_GATEWAY_EVENTS", True)
    nudged, jobs = [], []

    async def _nudge(company_id, event_id, *, attempt=""):
        nudged.append(event_id)

    async def _job(function, *args, **kwargs):
        jobs.append((function, args))
        return SimpleNamespace(job_id="test")

    monkeypatch.setattr(store, "nudge", _nudge)
    monkeypatch.setattr("src.ai.service.enqueue_job", _job)
    monkeypatch.setattr("src.common.job_queue.enqueue_job", _job)

    async with database.AsyncSessionLocal() as db:
        company = Company(name=f"ws3-gw-{uuid.uuid4().hex[:6]}", type="TENANT", status="active")
        db.add(company)
        await db.flush()
        later = datetime.utcnow() + timedelta(days=1)
        db.add(CreditWallet(company_id=company.id, daily_credits=Decimal("0"), daily_expires_at=later,
                            wallet_balance=Decimal("100"), wallet_expires_at=later))
        admin = User(email=f"ws3-{uuid.uuid4().hex[:8]}@example.com", hashed_password="x", full_name="WS3",
                     role="tenant_admin", company_id=company.id, is_active=True, is_verified=True)
        inbox = HierarchicalEntity(company_id=company.id, type="AGENT", status="ACTIVE", name="Inbox agent",
                                   created_at=datetime.utcnow() - timedelta(days=2))
        caller = HierarchicalEntity(company_id=company.id, type="AGENT", status="ACTIVE", name="Caller agent",
                                    created_at=datetime.utcnow() - timedelta(days=1))
        db.add_all([admin, inbox, caller])
        await db.commit()
        ids = SimpleNamespace(company=company.id, admin=admin, inbox=inbox.id, caller=caller.id, nudged=nudged,
                              jobs=jobs, engine=engine)
    try:
        yield ids
    finally:
        async with engine.begin() as conn:
            await purge_companies(conn, [ids.company])
        await engine.dispose()


def _session():
    from src.common import database

    return database.AsyncSessionLocal()


def _client():
    from src.main import app

    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


def _as(user):
    from src.auth import service

    return {"Authorization": f"Bearer {service.issue_access_token(user)}"}


def _signed(secret, payload):
    body = json.dumps(payload).encode()
    sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return body, {"X-HB-Signature": sig, "Content-Type": "application/json"}


async def _endpoint(client, biz, source, entity_id=None):
    r = await client.post("/api/v1/webhook-endpoints", headers=_as(biz.admin), json={
        "source": source, "name": f"{source} hook", **({"entity_id": str(entity_id)} if entity_id else {})})
    assert r.status_code == 201, r.text
    return r.json()


async def _post(client, endpoint, payload, query=""):
    body, headers = _signed(endpoint["secret"], payload)
    return await client.post(f"/webhook/inbound/{endpoint['id']}{query}", content=body, headers=headers)


async def _events(biz):
    async with _session() as db:
        return (await db.execute(select(Event).where(Event.company_id == biz.company)
                                 .order_by(Event.received_at))).scalars().all()


async def _route(biz, event_id):
    async with _session() as db:
        return await router.route(db, biz.company, event_id)


async def test_a_bound_endpoint_runs_its_agent_through_its_trigger(biz):
    async with _client() as client:
        endpoint = await _endpoint(client, biz, "crm", biz.inbox)
        payload = {"crm_event": "lead.created", "id": "L-42", "nonce": uuid.uuid4().hex,
                   "properties": {"name": "Priya", "email": "priya@example.com"}}
        first = await _post(client, endpoint, payload)
        again = await _post(client, endpoint, payload)
    assert first.status_code == 202, first.text
    assert again.status_code == 200 and again.json()["status"] == "duplicate"

    [event] = await _events(biz)
    assert (event.type, event.subject, event.trust) == ("crm.lead.created", f"webhook:{endpoint['id']}", "verified")
    assert event.source == "webhook:crm" and biz.nudged == [event.id]
    assert "entity_id" not in event.data["_gateway"]           # the binding is the trigger, not a name

    [decision] = (await _route(biz, event.id))["decisions"]
    assert decision["outcome"] == "started"
    from src.ai.orm import ExecutionRun

    async with _session() as db:
        run = await db.get(ExecutionRun, uuid.UUID(decision["run"]))
        trigger = await db.get(Trigger, uuid.UUID(decision["trigger"]))
    assert (trigger.created_by_kind, trigger.event_type, trigger.entity_id) == ("system", "*", biz.inbox)
    assert run.entity_id == biz.inbox and run.input_data["channel"] == "webhook"
    assert json.loads(run.input_data["input"])["lead_id"] == "L-42"           # the event, as before
    assert run.input_data["subjects"]["leads"] == [{"id": "L-42", "name": "Priya"}]


async def test_an_event_that_names_its_agent_gets_a_visible_trigger_once(biz):
    async with _client() as client:
        endpoint = await _endpoint(client, biz, "crm")
        for n in range(2):
            r = await _post(client, endpoint, {"crm_event": "lead.created", "id": f"L-{n}"},
                            query=f"?entity_id={biz.caller}")
            assert r.status_code == 202, r.text
    first, second = await _events(biz)
    assert [d["outcome"] for d in (await _route(biz, first.id))["decisions"]] == ["started"]
    assert [d["outcome"] for d in (await _route(biz, second.id))["decisions"]] == ["started"]
    async with _session() as db:
        made = (await db.execute(select(Trigger).where(Trigger.company_id == biz.company))).scalars().all()
    assert len(made) == 1 and made[0].entity_id == biz.caller and made[0].event_type == "crm.*"
    assert "naming Caller agent" in made[0].name


async def test_an_unbound_event_starts_nothing_and_stays_in_the_log(biz):
    async with _client() as client:
        endpoint = await _endpoint(client, biz, "generic")
        r = await _post(client, endpoint, {"type": "lead.created", "nonce": uuid.uuid4().hex})
        assert r.status_code == 202
        [event] = await _events(biz)
        assert (await _route(biz, event.id))["decisions"] == []
        log = await client.get("/api/v1/automation/events", headers=_as(biz.admin))
    assert [e["type"] for e in log.json()] == ["generic.lead.created"]
    assert log.json()[0]["status"] == "routed"


async def test_a_sheet_row_becomes_a_voice_campaign_with_a_decision(biz):
    from src.ai.campaign_models import Campaign

    async with _client() as client:
        endpoint = await _endpoint(client, biz, "generic", biz.caller)
        r = await _post(client, endpoint, {"type": "sheet.row_inserted", "sheet_name": "Leads",
                                           "data": {"Name": "Ravi", "Phone": 9876543210.0}})
        assert r.status_code == 202, r.text
        no_phone = await _post(client, endpoint, {"type": "sheet.row_inserted", "data": {"Name": "Nobody"}})
        assert no_phone.status_code == 202
    row, empty = await _events(biz)
    assert row.type == "sheet.row_inserted"
    [decision] = (await _route(biz, row.id))["decisions"]
    assert decision["outcome"] == "started" and "voice campaign" in decision["reason"]
    async with _session() as db:
        [campaign] = (await db.execute(select(Campaign).where(Campaign.company_id == biz.company))).scalars().all()
    assert campaign.agent_id == biz.caller and campaign.contact_list[0]["phone"] == "9876543210"
    assert ("execute_campaign_task", (str(campaign.id),)) in biz.jobs
    [refused] = (await _route(biz, empty.id))["decisions"]
    assert refused["outcome"] == "failed" and "no phone number" in refused["reason"]


async def test_revoking_an_endpoint_turns_its_trigger_off(biz):
    async with _client() as client:
        endpoint = await _endpoint(client, biz, "generic", biz.inbox)
        assert (await client.delete(f"/api/v1/webhook-endpoints/{endpoint['id']}",
                                    headers=_as(biz.admin))).status_code == 204
    async with _session() as db:
        [trigger] = (await db.execute(select(Trigger).where(Trigger.company_id == biz.company))).scalars().all()
    assert trigger.enabled is False and "deleted" in trigger.paused_reason


async def test_an_internal_event_is_stored_for_the_companys_triggers(biz):
    from src.gateway.internal_event import emit_internal_event

    await emit_internal_event("custom.lead.won", str(biz.company), "billing", {"lead": "L-9"})
    [event] = await _events(biz)
    assert (event.type, event.source, event.trust) == ("custom.lead.won", "internal:billing", "internal")
    assert event.data["lead"] == "L-9"


def _migration():
    spec = importlib.util.spec_from_file_location(
        "p14_webhook_triggers", BACKEND / "migrations" / "legacy" / "versions" / "p14_webhook_triggers.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def test_the_migration_keeps_what_ran_before_for_existing_endpoints(biz, monkeypatch):
    from src.gateway.models import WebhookEndpoint

    async with _session() as db:
        bound = WebhookEndpoint(company_id=biz.company, source="crm", name="bound", secret_encrypted="x",
                                entity_id=biz.inbox)
        unbound = WebhookEndpoint(company_id=biz.company, source="generic", name="unbound", secret_encrypted="x")
        db.add_all([bound, unbound])
        await db.commit()

    migration = _migration()
    statements: list[str] = []
    monkeypatch.setattr(migration, "op", SimpleNamespace(execute=statements.append))
    migration.upgrade()

    async with biz.engine.connect() as conn:
        trans = await conn.begin()
        try:
            for sql in statements:
                await conn.execute(text(sql))
            rows = (await conn.execute(text(
                "SELECT entity_id, event_type, filter FROM triggers WHERE company_id = :c ORDER BY name"),
                {"c": str(biz.company)})).all()
            # Two agents at the top level: no "only agent" trigger for the unbound endpoint.
            assert [(r.entity_id, r.event_type) for r in rows] == [(biz.inbox, "*")]
            assert rows[0].filter == {"path": "subject", "op": "eq", "value": f"webhook:{bound.id}"}

            await conn.execute(text("UPDATE hierarchical_entities SET status = 'ARCHIVED' WHERE id = :e"),
                               {"e": str(biz.caller)})
            for sql in statements:  # again: the bound one is not made twice; the only agent now is
                await conn.execute(text(sql))
            rows = (await conn.execute(text(
                "SELECT entity_id, filter FROM triggers WHERE company_id = :c ORDER BY name"),
                {"c": str(biz.company)})).all()
            assert len(rows) == 2
            only = [r for r in rows if "all" in r.filter][0]
            assert only.entity_id == biz.inbox
            assert only.filter["all"][0]["value"] == f"webhook:{unbound.id}"
        finally:
            await trans.rollback()
