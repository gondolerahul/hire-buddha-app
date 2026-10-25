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
from tests.harness.wallet import fund

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


async def test_credit_held_by_a_tenants_runs_is_read_across_both_databases(tenants):
    """Holds are control rows, runs tenant rows: the wallet counts the hold of
    Beta's running run, not those of its finished run or of a run that is
    gone — the same whether the service is on a control session or on Beta's."""
    from decimal import Decimal

    from sqlalchemy import delete

    from src.ai.orm.execution import ExecutionRun
    from src.billing.billing_models import CreditHold
    from src.billing.credit_service import CreditService
    from src.common.tenancy.session import control_session, tenant_session

    _, beta = tenants
    async with tenant_session(beta.company_id) as db:
        entity_id = (await _entity(db, beta.company_id, f"holds-{uuid.uuid4().hex[:8]}")).id
        running = ExecutionRun(entity_id=entity_id, company_id=beta.company_id, status="RUNNING")
        finished = ExecutionRun(entity_id=entity_id, company_id=beta.company_id, status="COMPLETED")
        db.add_all([running, finished])
        await db.commit()
        running_id, finished_id = running.id, finished.id
    gone_id = uuid.uuid4()
    holds = {running_id: Decimal("1.25"), finished_id: Decimal("4"), gone_id: Decimal("8")}
    try:
        async with control_session() as db:
            db.add_all([CreditHold(company_id=beta.company_id, run_id=run, amount=amount)
                        for run, amount in holds.items()])
            await db.commit()
        async with control_session() as db:
            assert await CreditService(db).held_by_others(beta.company_id) == Decimal("1.25")
            assert await CreditService(db).held_by_others(beta.company_id, running_id) == 0
        async with tenant_session(beta.company_id) as db:
            assert await CreditService(db).held_by_others(beta.company_id) == Decimal("1.25")
    finally:
        async with control_session() as db:
            await db.execute(delete(CreditHold).where(CreditHold.run_id.in_(list(holds))))
            await db.commit()
        async with tenant_session(beta.company_id) as db:
            await _drop_entity(db, entity_id)


async def test_a_tenants_run_is_settled_once_in_the_control_database(tenants):
    """WS2 2.6, Phase 15 T3-5: a Beta run finishes in Beta's database; its
    charge — the settlement claim on its hold, its usage rows marked settled,
    the wallet deduction, the billing event — commits in a control transaction
    of its own, and settling it again (a retried finalisation) charges nothing."""
    from decimal import Decimal

    from sqlalchemy import delete

    from src.ai.governance.governance_service import GovernanceService
    from src.ai.orm.execution import ExecutionRun
    from src.ai.orm.usage import UsageLog
    from src.billing.billing_models import BillingLine, CreditHold
    from src.common.tenancy.session import control_session, tenant_session
    from tests.harness.wallet import available, undo_entries

    _, beta = tenants
    name = f"settle-{uuid.uuid4().hex[:8]}"
    async with control_session() as db:
        await fund(db, beta.company_id, "10")
        await db.commit()
        before = await available(db, beta.company_id)
    async with tenant_session(beta.company_id) as db:
        entity_id = (await _entity(db, beta.company_id, name)).id
        run = ExecutionRun(entity_id=entity_id, company_id=beta.company_id, status="COMPLETED",
                           total_cost_usd=Decimal("0.30"), input_data={})
        db.add(run)
        await db.commit()
        run_id = run.id
    async with control_session() as db:
        db.add(UsageLog(company_id=beta.company_id, run_id=run_id, raw_quantity=Decimal(1),
                        calculated_cost=Decimal("0.30"), billed_usd=Decimal("0.30"), category="ai_models",
                        attribution="actor_step"))
        await db.commit()
    try:
        async with tenant_session(beta.company_id) as db:
            run = await db.get(ExecutionRun, run_id)
            billed = await GovernanceService(db, None).settle_billing(run, name)
            again = await GovernanceService(db, None).settle_billing(run, name)
        assert billed == Decimal("0.30") and again == 0
        async with tenant_session(beta.company_id) as db:
            assert Decimal(str((await db.get(ExecutionRun, run_id)).billed_amount)) == billed
        async with control_session() as db:
            hold = (await db.execute(select(CreditHold).where(CreditHold.run_id == run_id))).scalar_one()
            assert hold.settled_at is not None and Decimal(str(hold.billed_amount)) == billed
            [line] = (await db.execute(select(BillingLine.billed_usd).where(
                BillingLine.company_id == beta.company_id, BillingLine.grouping_id == entity_id))).scalars().all()
            assert Decimal(str(line)) == billed
            row = (await db.execute(select(UsageLog).where(UsageLog.run_id == run_id))).scalar_one()
            assert row.settlement_id is not None and Decimal(str(row.billed_ccy)) == Decimal(str(hold.billed_ccy))
            assert before - await available(db, beta.company_id) == Decimal(str(hold.billed_ccy))
    finally:
        async with control_session() as db:
            await undo_entries(db, beta.company_id, run_id=run_id)
            await undo_entries(db, beta.company_id, source_type="test")
            await db.execute(delete(UsageLog).where(UsageLog.run_id == run_id))
            await db.execute(delete(BillingLine).where(BillingLine.company_id == beta.company_id,
                                                       BillingLine.grouping_id == entity_id))
            await db.execute(delete(CreditHold).where(CreditHold.run_id == run_id))
            await db.commit()
        async with tenant_session(beta.company_id) as db:
            await _drop_entity(db, entity_id)


async def test_a_partners_tenant_views_read_each_tenants_database(tenants):
    """The partner screens' companies, users and wallets are control rows; a
    tenant's agents and runs are read in that tenant's database, and the
    analytics totals add up one database at a time."""
    import httpx
    from fastapi import FastAPI
    from sqlalchemy import func

    from src.ai.orm.entity import HierarchicalEntity
    from src.ai.orm.execution import ExecutionRun
    from src.auth import partner_router
    from src.auth.dependencies import get_current_user
    from src.common.tenancy.session import control_session, tenant_session

    acme, beta = tenants
    name = f"partner-{uuid.uuid4().hex[:8]}"
    async with tenant_session(beta.company_id) as db:
        entity_id = (await _entity(db, beta.company_id, name)).id
        db.add(ExecutionRun(entity_id=entity_id, company_id=beta.company_id, status="COMPLETED"))
        await db.commit()
    app = FastAPI()
    app.include_router(partner_router.router, prefix="/api/v1")

    async def _admin():
        return _person(acme.company_id, role="app_admin")

    app.dependency_overrides[get_current_user] = _admin
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client:
            detail = await client.get(f"/api/v1/partner/tenants/{beta.company_id}/details")
        assert detail.status_code == 200, detail.text
        body = detail.json()
        assert name in {e["name"] for e in body["entities"]}
        assert str(entity_id) in {r["entity_id"] for r in body["recent_executions"]}
        assert body["entity_count"] >= 1 and body["recent_executions_7d"] >= 1

        expected = [0, 0]
        for tenant in tenants:
            async with tenant_session(tenant.company_id) as db:
                expected[0] += (await db.execute(select(func.count(HierarchicalEntity.id)).where(
                    HierarchicalEntity.company_id == tenant.company_id))).scalar()
                expected[1] += (await db.execute(select(func.count(ExecutionRun.id)).where(
                    ExecutionRun.company_id == tenant.company_id))).scalar()
        async with control_session() as db:
            entities, runs, _, _ = await partner_router._tenant_totals(db, [acme.company_id, beta.company_id])
        assert [entities, runs] == expected and runs >= 1
    finally:
        async with tenant_session(beta.company_id) as db:
            await _drop_entity(db, entity_id)


async def test_a_webhook_endpoint_binds_only_an_agent_of_the_callers_tenant(tenants, monkeypatch):
    """The endpoint is a control row; the agent it runs is looked up in the
    caller's tenant database — Acme's agent id is unknown to a Beta admin."""
    import httpx
    from fastapi import FastAPI
    from sqlalchemy import delete

    from src.auth.dependencies import get_current_user
    from src.auth.models import User
    from src.common.config import settings
    from src.common.tenancy.session import control_session, tenant_session
    from src.gateway import webhook_endpoints_router
    from src.gateway.models import WebhookEndpoint

    monkeypatch.setattr(settings, "AUTOMATION_GATEWAY_EVENTS", False)  # no system trigger here
    acme, beta = tenants
    async with tenant_session(beta.company_id) as db:
        beta_agent = (await _entity(db, beta.company_id, f"hook-{uuid.uuid4().hex[:8]}")).id
        await db.commit()
    async with tenant_session(acme.company_id) as db:
        acme_agent = (await _entity(db, acme.company_id, f"hook-{uuid.uuid4().hex[:8]}")).id
        await db.commit()
    app = FastAPI()
    app.include_router(webhook_endpoints_router.router)
    admin = _person(beta.company_id)

    async def _admin():
        return admin

    app.dependency_overrides[get_current_user] = _admin
    try:
        async with control_session() as db:
            db.add(User(id=admin.id, email=f"ws2-hook-{admin.id.hex[:8]}@test.local", full_name="Ws2 Hook",
                        hashed_password="x", company_id=beta.company_id, role="tenant_admin", is_active=True))
            await db.commit()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client:
            ours = await client.post("/api/v1/webhook-endpoints", json={
                "source": "generic", "name": "ws2-hook", "entity_id": str(beta_agent)})
            theirs = await client.post("/api/v1/webhook-endpoints", json={
                "source": "generic", "name": "ws2-hook", "entity_id": str(acme_agent)})
        assert ours.status_code == 201, ours.text
        assert theirs.status_code == 404, theirs.text
    finally:
        async with control_session() as db:
            await db.execute(delete(WebhookEndpoint).where(WebhookEndpoint.entity_id.in_([beta_agent, acme_agent])))
            await db.execute(delete(User).where(User.id == admin.id))
            await db.commit()
        async with tenant_session(beta.company_id) as db:
            await _drop_entity(db, beta_agent)
        async with tenant_session(acme.company_id) as db:
            await _drop_entity(db, acme_agent)


async def test_a_tenants_connection_and_its_key_live_in_its_own_database(tenants, tmp_path):
    """WS5: a Beta connection, its sealed secret and its DEK are in Beta's
    database (none in Acme's or the shared one); the broker serves it from there."""
    from src.common.platform.kek import set_kek
    from src.common.platform.kek.local import LocalKeyEncryption
    from src.common.tenancy.session import control_session, tenant_session
    from src.connections import crypto, service
    from src.connections.models import Connection, ConnectionSecret, TenantKey

    acme, beta = tenants
    set_kek(LocalKeyEncryption(tmp_path))
    crypto.forget_cached()
    agent = uuid.uuid4()
    try:
        made = await service.create_from_form(beta.company_id, None, "api_key", {
            "service_name": "Courier", "api_key": "beta-key-123"})
        connection_id = uuid.UUID(made["id"])
        token = await service.issue_token(beta.company_id, connection_id, principal_kind="entity",
                                          principal_id=agent)
        assert token.access_token == "beta-key-123"
        async with tenant_session(beta.company_id) as db:
            assert (await db.get(Connection, connection_id)).company_id == beta.company_id
            assert await db.get(ConnectionSecret, connection_id) is not None
            assert (await db.execute(select(TenantKey).where(TenantKey.company_id == beta.company_id))).first()
        async with tenant_session(acme.company_id) as db:
            assert await db.get(Connection, connection_id) is None
        async with control_session() as db:  # nothing of it in the shared database
            assert (await db.execute(text("SELECT count(*) FROM public.connections WHERE id = :c"),
                                     {"c": connection_id})).scalar() == 0
    finally:
        async with tenant_session(beta.company_id) as db:
            await db.execute(text("DELETE FROM connection_audit WHERE company_id = :c"), {"c": beta.company_id})
            await db.execute(text("DELETE FROM connections WHERE company_id = :c"), {"c": beta.company_id})
            await db.execute(text("DELETE FROM tenant_keys WHERE company_id = :c"), {"c": beta.company_id})
            await db.execute(text("DELETE FROM events WHERE company_id = :c AND source = 'connections'"),
                             {"c": beta.company_id})
            await db.commit()
        set_kek(None)
        crypto.forget_cached()


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


# ── campaigns (WS2 2.4 campaigns module, 2.5, 2.12) ────────────────────────

class _Provider:
    """The provider's REST API: records what it was asked, answers 201."""

    def __init__(self):
        self.requests = []

    def __call__(self, *args, **kwargs):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, **kwargs):
        from types import SimpleNamespace

        self.requests.append((url, kwargs.get("data") or kwargs.get("json")))
        return SimpleNamespace(status_code=201, json=lambda: {"sid": f"CA{uuid.uuid4().hex}", "ref_id": "TT1"})


async def test_a_campaign_job_dials_from_the_campaigns_tenant_database(tenants, monkeypatch):
    """A Beta campaign's job carries Beta: its calls and voice session are
    written in Beta's database, the number and the credit gate are read in the
    control database, the Twilio URLs and the Tata identifier name Beta, the
    continuation job carries Beta, and Tata's status callback finds the call
    by that identifier alone. A job naming Acme finds nothing to dial."""
    import asyncio
    from types import SimpleNamespace

    import httpx
    from fastapi import FastAPI
    from sqlalchemy import delete
    from sqlalchemy.engine import make_url

    from src.ai import campaign_executor
    from src.ai.campaign_executor import CampaignExecutor
    from src.ai.campaign_models import Campaign, CampaignCall
    from src.ai.campaign_worker import execute_campaign_task
    from src.ai.services import campaign_pacing
    from src.common.config import settings
    from src.common.tenancy.session import control_session, tenant_session
    from src.voice import webhook_router
    from src.voice.agent_loader import AgentContextLoader
    from src.voice.models import VoiceSession
    from src.voice.phone_pool_models import PhoneNumber

    acme, beta = tenants
    gate_databases, continued = [], []
    provider = _Provider()

    async def _admit(db, company_id, **kwargs):
        gate_databases.append((await db.execute(text("SELECT current_database()"))).scalar())
        return None

    async def _credentials(db, company_id):
        return "AC-test", "token"

    async def _tata_credentials(db, company_id):
        return SimpleNamespace(api_key="tata-key")

    async def _continue(campaign_id, delay, company_id=None):
        continued.append((campaign_id, company_id))

    async def _no_warm(*args, **kwargs):
        return None

    real_sleep = asyncio.sleep

    async def _no_sleep(delay, *args, **kwargs):
        await real_sleep(0)

    monkeypatch.setattr(campaign_executor, "call_refusal", _admit)
    monkeypatch.setattr(campaign_executor, "httpx", SimpleNamespace(AsyncClient=provider))
    monkeypatch.setattr("src.voice.twilio_api.get_twilio_credentials", _credentials)
    monkeypatch.setattr("src.voice.tata_credentials.resolve_tata_credentials", _tata_credentials)
    monkeypatch.setattr(campaign_pacing, "schedule_continuation", _continue)
    monkeypatch.setattr(AgentContextLoader, "load_agent_for_session", _no_warm)
    monkeypatch.setattr(asyncio, "sleep", _no_sleep)

    suffix = uuid.uuid4().hex[:8]
    number = f"+1555{uuid.uuid4().int % 10_000_000:07d}"
    campaign_id, call_id = uuid.uuid4(), uuid.uuid4()
    async with tenant_session(beta.company_id) as db:
        agent_id = (await _entity(db, beta.company_id, f"dialer-{suffix}")).id
        db.add(Campaign(id=campaign_id, company_id=beta.company_id, created_by=uuid.uuid4(), agent_id=agent_id,
                        name=f"dialer-{suffix}", contact_list=[], total_contacts=1, provider="twilio",
                        status="draft"))
        await db.flush()
        db.add(CampaignCall(id=call_id, campaign_id=campaign_id, contact_data={"phone": "+15550009999"},
                            status="pending"))
        await db.commit()
    app = FastAPI()
    app.include_router(webhook_router.router)
    try:
        async with control_session() as db:
            db.add(PhoneNumber(phone_number=number, provider="twilio", country_code="+1", status="assigned",
                               is_active=True, company_id=beta.company_id, agent_id=agent_id))
            await db.commit()

        # A job naming another tenant: Acme's database has no such campaign.
        await execute_campaign_task({}, str(campaign_id), company_id=str(acme.company_id))
        assert provider.requests == []

        await execute_campaign_task({}, str(campaign_id), company_id=str(beta.company_id))
        async with tenant_session(beta.company_id) as db:
            call = await db.get(CampaignCall, call_id)
            session = await db.get(VoiceSession, call.voice_session_id)
            campaign = await db.get(Campaign, campaign_id)
        assert call.status == "calling" and call.call_sid.startswith("CA")
        assert session.company_id == beta.company_id and session.phone_number == number
        assert (campaign.status, campaign.calls_initiated) == ("running", 1)
        # Both credit gates (the campaign's and the call's) in the control database.
        assert gate_databases == [make_url(settings.CONTROL_DATABASE_URL).database] * 2
        [(url, payload)] = provider.requests
        assert payload["From"] == number
        assert f"session_id={session.id}&company={beta.company_id}" in payload["Url"]
        assert payload["StatusCallback"].endswith(f"/webhooks/voice/twilio/status?company={beta.company_id}")
        assert continued == [(campaign_id, beta.company_id)]          # the call is still in flight
        async with tenant_session(acme.company_id) as db:
            assert await db.get(Campaign, campaign_id) is None
        async with control_session() as db:  # nothing of the campaign in the shared database
            assert (await db.execute(text("SELECT count(*) FROM public.campaign_calls WHERE id = :c"),
                                     {"c": call_id})).scalar() == 0

        # Tata: the click-to-call names Beta and the session; its status
        # callback carries no number we own, only that identifier.
        async with control_session() as control:
            await CampaignExecutor._place_tata_call_static(
                db=control, to="+15550009999", from_=number, voice_session_id=session.id,
                agent_id=agent_id, company_id=beta.company_id)
        reference = provider.requests[-1][1]["custom_identifier"]
        assert reference == f"{beta.company_id}.{session.id}"
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client:
            status = await client.post("/webhooks/voice/tata/status", json={
                "custom_identifier": reference, "call_status": "answered", "duration": "30",
                "call_connected": "1"})
        assert status.json().get("session_id") == str(session.id), status.text
        async with tenant_session(beta.company_id) as db:
            assert (await db.get(VoiceSession, session.id)).status == "ended"
            assert (await db.get(CampaignCall, call_id)).status == "completed"
    finally:
        async with tenant_session(beta.company_id) as db:
            await db.execute(text("DELETE FROM campaign_calls WHERE campaign_id = :c"), {"c": campaign_id})
            await db.execute(text("DELETE FROM campaigns WHERE id = :c"), {"c": campaign_id})
            await db.execute(text("DELETE FROM voice_sessions WHERE agent_id = :a"), {"a": agent_id})
            await _drop_entity(db, agent_id)
        async with control_session() as db:
            await db.execute(delete(PhoneNumber).where(PhoneNumber.phone_number == number))
            await db.commit()
