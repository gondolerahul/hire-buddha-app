"""Tenant sessions open the right database (Phase 14 WS2 2.1/2.4, tech spec §5.3, §17).

Two real tenant databases on the local server — ``t_devacme01`` and
``t_devbeta001``, made by ``scripts/dev_tenants.py`` (idempotent; this module
runs it) — and ``TENANCY_MODE=split``:

* each company's session is on its own database, ``platform`` schema first;
* a row written for one tenant is in neither the other's database nor the
  control database;
* control classes read in a tenant session come from the control database,
  raw SQL goes to the tenant's;
* a company with no database is refused;
* the kernel's CORTEX wake-up cron finds a due tree in its tenant's database,
  writes the run there and queues it with the tenant's ``company_id``;
* the business time zone is read from the directory.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select, text

from tests.harness.infra import infra_unavailable

pytestmark = [pytest.mark.needs_db]


@pytest_asyncio.fixture
async def tenants(monkeypatch):
    """Split mode over the two dev tenants, on engines of this test's own."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    from src.common import database
    from src.common.config import settings
    from src.common.tenancy.directory import directory
    from src.common.tenancy.engines import engines

    control = create_async_engine(settings.CONTROL_DATABASE_URL, poolclass=NullPool,
                                  json_serializer=database.json_serializer)
    try:
        async with control.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as exc:                                                  # noqa: BLE001
        await control.dispose()
        infra_unavailable(f"Postgres unreachable; tenant routing skipped ({exc})")
    monkeypatch.setattr(database, "engine", control)
    monkeypatch.setattr(database, "AsyncSessionLocal", async_sessionmaker(control, expire_on_commit=False))

    from scripts.dev_tenants import DEV_TENANTS, ensure_dev_tenants

    await ensure_dev_tenants()
    monkeypatch.setattr(settings, "TENANCY_MODE", "split")
    directory.invalidate()
    try:
        yield DEV_TENANTS
    finally:
        await engines.dispose_all()
        directory.invalidate()
        await control.dispose()


async def _entity(db, company_id, name):
    from src.ai.orm.entity import HierarchicalEntity

    entity = HierarchicalEntity(company_id=company_id, type="AGENT", name=name)
    db.add(entity)
    await db.flush()
    return entity


async def _drop_entity(db, entity_id):
    """An entity, its runs and the version saving it made (they point at each other)."""
    params = {"e": entity_id}
    await db.execute(text("DELETE FROM execution_runs WHERE entity_id = :e"), params)
    await db.execute(text("UPDATE hierarchical_entities SET active_version_id = NULL WHERE id = :e"), params)
    await db.execute(text("DELETE FROM entity_versions WHERE entity_id = :e"), params)
    await db.execute(text("DELETE FROM hierarchical_entities WHERE id = :e"), params)
    await db.commit()


async def test_each_company_opens_its_own_database(tenants):
    from src.common.tenancy.session import tenant_session

    acme, beta = tenants
    for tenant in (acme, beta):
        async with tenant_session(tenant.company_id) as db:
            database_name, schema = (await db.execute(
                text("SELECT current_database(), current_schema()"))).one()
        assert (database_name, schema) == (tenant.db_name, "platform")


async def test_a_row_written_for_one_tenant_stays_in_its_database(tenants):
    from src.ai.orm.entity import HierarchicalEntity
    from src.common.tenancy.session import control_session, tenant_session

    acme, beta = tenants
    name = f"routing-{uuid.uuid4().hex[:8]}"
    async with tenant_session(acme.company_id) as db:
        entity_id = (await _entity(db, acme.company_id, name)).id
        await db.commit()
    try:
        async with tenant_session(acme.company_id) as db:
            assert (await db.get(HierarchicalEntity, entity_id)).name == name
        async with tenant_session(beta.company_id) as db:
            assert await db.get(HierarchicalEntity, entity_id) is None
            assert (await db.execute(select(HierarchicalEntity.id)
                                     .where(HierarchicalEntity.name == name))).first() is None
        async with control_session() as db:  # the shared (control) database's own table
            assert (await db.execute(text("SELECT count(*) FROM public.hierarchical_entities WHERE id = :id"),
                                     {"id": entity_id})).scalar() == 0
    finally:
        async with tenant_session(acme.company_id) as db:
            await _drop_entity(db, entity_id)


async def test_control_classes_come_from_the_control_database(tenants):
    from src.auth.models import Company
    from src.common.tenancy.models import TenantDirectoryEntry
    from src.common.tenancy.session import tenant_session

    acme, _ = tenants
    async with tenant_session(acme.company_id) as db:
        assert (await db.get(Company, acme.company_id)).name == acme.name
        assert (await db.get(TenantDirectoryEntry, acme.company_id)).tenant_key == acme.key
        # Raw SQL is the tenant's: its database has no control tables.
        assert (await db.execute(text("SELECT to_regclass('companies')"))).scalar() is None
        assert (await db.execute(text("SELECT to_regclass('execution_runs')"))).scalar() == "execution_runs"


async def test_a_company_without_a_database_is_refused(tenants):
    from src.common.tenancy.directory import TenantNotFound
    from src.common.tenancy.session import TenantRequired, tenant_session

    with pytest.raises(TenantNotFound):
        async with tenant_session(uuid.uuid4()):
            pass
    with pytest.raises(TenantRequired):
        async with tenant_session(None):
            pass


class _Pool:
    """The worker's arq pool: records the jobs."""

    def __init__(self):
        self.jobs = []

    async def set(self, *args, **kwargs):
        return True

    async def enqueue_job(self, function, *args, **kwargs):
        self.jobs.append((function, args, kwargs))
        return object()


async def test_the_cortex_wake_up_runs_in_the_trees_tenant_database(tenants):
    from src.ai.core.arq_jobs import cortex_resume_scheduled, sweep_stuck_runs
    from src.ai.memory.cortex_models import CortexTree, CortexTreeStatus
    from src.ai.orm.execution import ExecutionRun
    from src.common.tenancy.session import tenant_session

    acme, beta = tenants
    async with tenant_session(beta.company_id) as db:
        entity = await _entity(db, beta.company_id, f"wake-{uuid.uuid4().hex[:8]}")
        tree = CortexTree(company_id=beta.company_id, entity_id=entity.id, task_description="digest",
                          status=CortexTreeStatus.SUSPENDED,
                          next_resume_at=datetime.utcnow() - timedelta(minutes=5))
        db.add(tree)
        await db.commit()
        entity_id, tree_id = entity.id, tree.id
    pool = _Pool()
    try:
        result = await cortex_resume_scheduled({"redis": pool})
        assert result["resumed"] >= 1 and not result.get("errors")

        def runs_for_tree():
            return select(ExecutionRun).where(ExecutionRun.input_data["cortex_tree_id"].astext == str(tree_id))

        async with tenant_session(beta.company_id) as db:
            [run] = (await db.execute(runs_for_tree())).scalars().all()
            assert run.status == "PENDING" and run.company_id == beta.company_id
            assert (await db.get(CortexTree, tree_id)).next_resume_at is None
        async with tenant_session(acme.company_id) as db:
            assert (await db.execute(runs_for_tree())).first() is None
        assert ("run_execution_recursive", (str(run.id),), {"company_id": str(beta.company_id)}) in pool.jobs

        # A sweep goes over each tenant database and adds up what it did.
        swept = await sweep_stuck_runs({"redis": None})
        assert set(swept) >= {"resumed", "expired", "paused_resumed"}
    finally:
        async with tenant_session(beta.company_id) as db:
            await db.execute(text("DELETE FROM cortex_trees WHERE id = :t"), {"t": tree_id})
            await _drop_entity(db, entity_id)


async def test_the_time_zone_is_the_directorys(tenants):
    from src.common import timezones
    from src.common.tenancy.directory import directory
    from src.common.tenancy.session import control_session

    _, beta = tenants
    update = text("UPDATE tenant_directory SET timezone = :tz WHERE company_id = :c")
    async with control_session() as db:
        await db.execute(update, {"tz": "Europe/Berlin", "c": beta.company_id})
        await db.commit()
    try:
        directory.invalidate()
        timezones.forget_company_timezone()
        assert await timezones.company_timezone_name(beta.company_id) == "Europe/Berlin"
    finally:
        async with control_session() as db:
            await db.execute(update, {"tz": "Asia/Kolkata", "c": beta.company_id})
            await db.commit()
        directory.invalidate()
        timezones.forget_company_timezone()


# ── the AI routes (WS2 2.4, second module) ─────────────────────────────────

def _app(user):
    from fastapi import FastAPI

    from src.ai import router as ai_router_module
    from src.auth.dependencies import get_current_user

    app = FastAPI()
    app.include_router(ai_router_module.router, prefix="/api/v1")

    async def _user():
        return user

    app.dependency_overrides[get_current_user] = _user  # get_db stays: the control session
    return app


async def _get(user, path, *, acting=None):
    import httpx

    headers = {"X-Company-Id": str(acting)} if acting else {}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=_app(user)), base_url="http://t") as client:
        return await client.get(f"/api/v1{path}", headers=headers)


def _person(company_id, role="tenant_admin"):
    from types import SimpleNamespace

    return SimpleNamespace(id=uuid.uuid4(), company_id=company_id, role=role, email="ws2@test.local")


async def test_an_agent_route_reads_the_callers_tenant_database(tenants):
    from src.common.tenancy.session import tenant_session

    acme, beta = tenants
    async with tenant_session(acme.company_id) as db:
        entity_id = (await _entity(db, acme.company_id, f"route-{uuid.uuid4().hex[:8]}")).id
        await db.commit()
    try:
        own = await _get(_person(acme.company_id), f"/ai/entities/{entity_id}")
        assert own.status_code == 200, own.text
        assert own.json()["id"] == str(entity_id)
        listed = await _get(_person(acme.company_id), "/ai/entities")
        assert str(entity_id) in {item["id"] for item in listed.json()["items"]}

        # Another tenant's user: its database has no such agent.
        assert (await _get(_person(beta.company_id), f"/ai/entities/{entity_id}")).status_code == 404
        listed = await _get(_person(beta.company_id), "/ai/entities")
        assert str(entity_id) not in {item["id"] for item in listed.json()["items"]}

        # A platform admin acts in a tenant by naming it; a tenant user may not.
        admin = _person(beta.company_id, role="app_admin")
        assert (await _get(admin, f"/ai/entities/{entity_id}", acting=acme.company_id)).status_code == 200
        assert (await _get(admin, f"/ai/entities/{entity_id}")).status_code == 404
        refused = await _get(_person(beta.company_id), f"/ai/entities/{entity_id}", acting=acme.company_id)
        assert refused.status_code == 403
    finally:
        async with tenant_session(acme.company_id) as db:
            await _drop_entity(db, entity_id)


async def test_feature_flags_are_read_from_the_control_database_in_a_tenant_session(tenants):
    from src.ai.core.feature_flags import FeatureFlags
    from src.common.tenancy.session import control_session, tenant_session

    acme, _ = tenants
    key = f"ws2.routing_probe_{uuid.uuid4().hex[:8]}"
    async with control_session() as db:
        await FeatureFlags(db).set(key, enabled=True, company_id=acme.company_id)
        await db.commit()
    try:
        async with tenant_session(acme.company_id) as db:
            found = await FeatureFlags(db)._db_lookup(key, acme.company_id)
        assert found is not None and found.value is True and found.source == "company"
    finally:
        async with control_session() as db:
            await db.execute(text("DELETE FROM feature_flags WHERE flag_key = :k"), {"k": key})
            await db.commit()


# ── voice (WS2 2.4 voice module, 2.12) ─────────────────────────────────────

async def test_an_inbound_call_is_routed_by_its_number_to_the_tenants_database(tenants, monkeypatch):
    """Twilio dials a number assigned to Dev Beta: the session is written in
    Beta's database, the stream URL names Beta, and the status callback finds
    the session there by the same number."""
    import httpx
    from fastapi import FastAPI
    from sqlalchemy import delete

    from src.common.tenancy.session import control_session, tenant_session
    from src.voice import webhook_router
    from src.voice.models import VoiceSession
    from src.voice.phone_pool_models import PhoneNumber

    async def _admitted(*args, **kwargs):
        return None

    async def _not_mobile(*args, **kwargs):
        return None

    monkeypatch.setattr("src.voice.call_admission.call_refusal", _admitted)
    monkeypatch.setattr("src.mobile.identification.resolve_mobile_inbound", _not_mobile)

    acme, beta = tenants
    async with tenant_session(beta.company_id) as db:
        agent_id = (await _entity(db, beta.company_id, f"voice-{uuid.uuid4().hex[:8]}")).id
        await db.commit()
    number = f"+1555{uuid.uuid4().int % 10_000_000:07d}"
    app = FastAPI()
    app.include_router(webhook_router.router)
    call_sid = f"CA{uuid.uuid4().hex}"
    try:
        async with control_session() as db:
            # The number (control) names an agent that is only in Beta's database:
            # no foreign key between them since 2.3.
            db.add(PhoneNumber(phone_number=number, provider="twilio", country_code="+1", status="assigned",
                               is_active=True, company_id=beta.company_id, agent_id=agent_id,
                               customer_id=uuid.uuid4()))
            await db.commit()

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client:
            answer = await client.post("/webhooks/voice/twilio/incoming", data={
                "CallSid": call_sid, "From": "+15550000001", "To": number, "CallStatus": "ringing"})
            assert answer.status_code == 200 and "<Stream" in answer.text, answer.text

            async with tenant_session(beta.company_id) as db:
                [session] = (await db.execute(
                    select(VoiceSession).where(VoiceSession.call_sid == call_sid))).scalars().all()
            assert session.company_id == beta.company_id and session.agent_id == agent_id
            async with control_session() as db:  # nothing of the call in the shared database
                assert (await db.execute(text("SELECT count(*) FROM public.voice_sessions WHERE call_sid = :c"),
                                         {"c": call_sid})).scalar() == 0
            assert f"/stream/twilio/{beta.company_id}/{session.id}" in answer.text
            async with tenant_session(acme.company_id) as db:
                assert (await db.execute(
                    select(VoiceSession.id).where(VoiceSession.call_sid == call_sid))).first() is None

            ended = await client.post("/webhooks/voice/twilio/status", data={
                "CallSid": call_sid, "CallStatus": "completed", "CallDuration": "12",
                "From": "+15550000001", "To": number})
            assert ended.json().get("session_id") == str(session.id), ended.text
            async with tenant_session(beta.company_id) as db:
                assert (await db.get(VoiceSession, session.id)).status == "ended"

            # A number no tenant has is refused before any tenant database is read.
            unknown = await client.post("/webhooks/voice/twilio/incoming", data={
                "CallSid": f"CA{uuid.uuid4().hex}", "From": "+15550000001", "To": "+15550000002"})
            assert "not configured" in unknown.text
    finally:
        async with tenant_session(beta.company_id) as db:
            await db.execute(text("DELETE FROM conversation_history WHERE agent_id = :a"), {"a": agent_id})
            await db.execute(text("DELETE FROM voice_sessions WHERE agent_id = :a"), {"a": agent_id})
            await _drop_entity(db, agent_id)
        async with control_session() as db:
            await db.execute(delete(PhoneNumber).where(PhoneNumber.phone_number == number))
            await db.commit()


# ── mobile dialer (WS2 2.4 mobile module) ──────────────────────────────────

async def test_a_mobile_call_attempt_is_served_from_the_reps_tenant_database(tenants, monkeypatch):
    """A Beta rep's phone (a control-plane device) works a mobile campaign that
    lives in Beta's database: the run, the leased lead and the attempt are
    written there, and the AI leg the phone then places to the agent's number
    binds to that attempt by caller ID in Beta's database. Acme's database and
    the shared one hold none of it; the housekeeping cron sweeps each tenant."""
    from types import SimpleNamespace

    import httpx
    from fastapi import FastAPI
    from sqlalchemy import delete

    from src.ai.campaign_models import Campaign, CampaignCall
    from src.ai.orm.entity import HierarchicalEntity
    from src.auth.dependencies import get_current_user
    from src.auth.models import User
    from src.common.config import settings
    from src.common.tenancy.session import control_session, tenant_session
    from src.mobile import service
    from src.mobile.models import (
        ATTEMPT_AI_CONNECTED, DEVICE_VERIFIED, EXECUTION_MODE_MOBILE, IDENT_CLI,
        CampaignAssignee, MobileCallAttempt, MobileCampaignRun, UserDevice,
    )
    from src.mobile.reconciler import mobile_housekeeping_job
    from src.mobile.router import router as mobile_router
    from src.voice import webhook_router
    from src.voice.models import VoiceSession
    from src.voice.phone_pool_models import PhoneNumber

    async def _credit_ok(db, company_id):
        return None

    monkeypatch.setattr(service, "_check_credits", _credit_ok)
    monkeypatch.setattr(settings, "MOBILE_CALLING_HOURS_ENFORCED", False)

    acme, beta = tenants
    suffix = uuid.uuid4().hex[:8]
    number = f"+1555{uuid.uuid4().int % 10_000_000:07d}"
    rep_cli = f"+1556{uuid.uuid4().int % 10_000_000:07d}"
    rep_id, device_id = uuid.uuid4(), uuid.uuid4()
    agent_id, campaign_id, call_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    call_sid = f"CA{uuid.uuid4().hex}"

    app = FastAPI()
    app.include_router(mobile_router, prefix="/api/v1")
    app.include_router(webhook_router.router)
    caller = {"user": SimpleNamespace(id=rep_id, company_id=beta.company_id, role="tenant_user")}

    async def _user():
        return caller["user"]

    app.dependency_overrides[get_current_user] = _user
    try:
        async with control_session() as db:
            db.add(User(id=rep_id, email=f"ws2-rep-{suffix}@test.local", full_name="Ws2 Rep", hashed_password="x",
                        company_id=beta.company_id, role="tenant_user", is_active=True))
            await db.flush()
            db.add_all([
                UserDevice(id=device_id, install_id=f"ws2-install-{suffix}", user_id=rep_id,
                           company_id=beta.company_id, status=DEVICE_VERIFIED, verified_cli=rep_cli,
                           cli_available=True),
                PhoneNumber(phone_number=number, provider="twilio", country_code="+1", status="assigned",
                            is_active=True, company_id=beta.company_id, agent_id=agent_id),
            ])
            await db.commit()
        async with tenant_session(beta.company_id) as db:
            db.add(HierarchicalEntity(id=agent_id, company_id=beta.company_id, type="AGENT", status="ACTIVE",
                                      name=f"mobile-{suffix}"))
            await db.flush()
            db.add(Campaign(id=campaign_id, company_id=beta.company_id, created_by=rep_id, agent_id=agent_id,
                            name=f"mobile-{suffix}", contact_list=[], total_contacts=1, provider="twilio",
                            execution_mode=EXECUTION_MODE_MOBILE, status="running"))
            await db.flush()
            db.add_all([CampaignCall(id=call_id, campaign_id=campaign_id,
                                     contact_data={"name": "Lead", "phone": "+15550009999"}),
                        CampaignAssignee(campaign_id=campaign_id, user_id=rep_id)])
            await db.commit()

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client:
            listed = await client.get("/api/v1/mobile/campaigns")
            assert listed.status_code == 200, listed.text
            [view] = [c for c in listed.json()["campaigns"] if c["id"] == str(campaign_id)]
            # The agent's number and the reps' names are control rows, read apart from the campaign.
            assert view["did"] == number and view["agent_name"] == f"mobile-{suffix}"
            assert view["assignees"] == [{"user_id": str(rep_id), "name": "Ws2 Rep"}]

            run = await client.post(f"/api/v1/mobile/campaigns/{campaign_id}/runs",
                                    json={"device_id": str(device_id)})
            assert run.status_code == 201, run.text
            run_id = run.json()["run_id"]
            lease = await client.post(f"/api/v1/mobile/runs/{run_id}/next")
            assert lease.status_code == 200 and lease.json()["campaign_call_id"] == str(call_id), lease.text
            attempt = await client.post("/api/v1/mobile/call-attempts", json={
                "run_id": run_id, "campaign_call_id": str(call_id), "device_id": str(device_id)})
            assert attempt.status_code == 201, attempt.text
            assert attempt.json()["did"] == number
            attempt_id = uuid.UUID(attempt.json()["attempt_id"])

            # The phone dials the agent's number: the number names Beta, the caller ID the attempt.
            answer = await client.post("/webhooks/voice/twilio/incoming", data={
                "CallSid": call_sid, "From": rep_cli, "To": number, "CallStatus": "ringing"})
            assert f"/stream/twilio/{beta.company_id}/" in answer.text, answer.text

            # An Acme user's list is read from Acme's database.
            caller["user"] = SimpleNamespace(id=uuid.uuid4(), company_id=acme.company_id, role="tenant_admin")
            others = await client.get("/api/v1/mobile/campaigns")
            assert others.status_code == 200 and str(campaign_id) not in {c["id"] for c in others.json()["campaigns"]}

        async with tenant_session(beta.company_id) as db:
            bound = await db.get(MobileCallAttempt, attempt_id)
            assert (bound.status, bound.identification_method) == (ATTEMPT_AI_CONNECTED, IDENT_CLI)
            session = await db.get(VoiceSession, bound.voice_session_id)
            assert session.call_sid == call_sid and session.company_id == beta.company_id
            assert f"/stream/twilio/{beta.company_id}/{session.id}" in answer.text
            assert (await db.get(MobileCampaignRun, uuid.UUID(run_id))).device_id == device_id
        async with tenant_session(acme.company_id) as db:
            assert await db.get(MobileCallAttempt, attempt_id) is None
        async with control_session() as db:  # nothing of the run in the shared database
            for table in ("mobile_campaign_runs", "mobile_call_attempts"):
                assert (await db.execute(text(f"SELECT count(*) FROM public.{table} WHERE campaign_id = :c"),
                                         {"c": campaign_id})).scalar() == 0

        swept = await mobile_housekeeping_job()
        assert "errors" not in swept, swept
    finally:
        async with tenant_session(beta.company_id) as db:
            params = {"c": campaign_id}
            for table in ("mobile_call_attempts", "campaign_assignees", "campaign_calls", "mobile_campaign_runs"):
                await db.execute(text(f"DELETE FROM {table} WHERE campaign_id = :c"), params)
            await db.execute(text("DELETE FROM campaigns WHERE id = :c"), params)
            await db.execute(text("DELETE FROM voice_sessions WHERE agent_id = :a"), {"a": agent_id})
            await _drop_entity(db, agent_id)
        async with control_session() as db:
            await db.execute(delete(PhoneNumber).where(PhoneNumber.phone_number == number))
            await db.execute(delete(UserDevice).where(UserDevice.id == device_id))
            await db.execute(delete(User).where(User.id == rep_id))
            await db.commit()
