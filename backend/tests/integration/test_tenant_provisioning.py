"""A company gets its own database through the provisioner (Phase 14 WS2 2.8, 2.9, 2.13).

On the local PostgreSQL server, as the ``local`` platform profile: a new
company is requested (a key, a slug, the emptiest pool server with room) and
provisioned step by step — its database with the extensions and the
``platform`` schema's tables, base pack v1, its storage namespace — to
``active``, each step in ``tenant_provisioning_log``. A step that fails leaves
the tenant ``failed``; provisioning again resumes after the last good step
and does not redo the earlier ones. A finished tenant is not touched again.
The staff API adds a tenant with one call; the workspace endpoint shows the
steps; the health check reaches the database and compares its schema version.
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import delete, select, text

from tests.harness.infra import infra_unavailable

pytestmark = [pytest.mark.needs_db]


@pytest_asyncio.fixture
async def control(monkeypatch):
    """This test's own control engine (NullPool), in-memory storage, no event nudges."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    from src.automation import store
    from src.common import database
    from src.common.config import settings
    from src.common.platform.storage import set_storage
    from src.common.tenancy.directory import directory
    from src.common.tenancy.engines import engines
    from tests.harness.storage import MemoryStorage

    engine = create_async_engine(settings.CONTROL_DATABASE_URL, poolclass=NullPool,
                                 json_serializer=database.json_serializer)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as exc:                                                  # noqa: BLE001
        await engine.dispose()
        infra_unavailable(f"Postgres unreachable; provisioning skipped ({exc})")
    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(database, "AsyncSessionLocal", async_sessionmaker(engine, expire_on_commit=False))
    monkeypatch.setattr(settings, "PLATFORM_PROFILE", "local")

    async def _no_nudge(*args, **kwargs):
        return None

    monkeypatch.setattr(store, "nudge", _no_nudge)
    storage = MemoryStorage()
    set_storage(storage)
    directory.invalidate()
    try:
        yield storage
    finally:
        set_storage(None)
        await engines.dispose_all()
        directory.invalidate()
        await engine.dispose()


@pytest_asyncio.fixture
async def company(control):
    """A company and a pool server of this test's own; afterwards its database,
    directory row, log rows, server and company are gone."""
    import asyncpg
    from sqlalchemy.engine import make_url

    from src.auth.models import Company
    from src.common.config import settings
    from src.common.tenancy import provisioner
    from src.common.tenancy.models import TenantDbServer, TenantDirectoryEntry, TenantProvisioningLog
    from src.common.tenancy.session import control_session

    url = make_url(settings.CONTROL_DATABASE_URL)
    if (url.host or "localhost") not in ("localhost", "127.0.0.1", "::1", "db", "postgres"):
        pytest.skip("provisioning tests create databases on a local server only")
    company_id = uuid.uuid4()
    server_name = f"test-pool-{uuid.uuid4().hex[:6]}"
    async with control_session() as db:
        db.add(Company(id=company_id, name="Provisioned & Co", type="TENANT", status="active"))
        await provisioner.add_server(db, name=server_name, host=url.host or "localhost", capacity=5,
                                     region="test")
        await db.commit()
    try:
        yield {"id": company_id, "server": server_name}
    finally:
        async with control_session() as db:
            entry = await db.get(TenantDirectoryEntry, company_id)
            db_name = entry.db_name if entry else None
            await db.execute(delete(TenantProvisioningLog).where(TenantProvisioningLog.company_id == company_id))
            await db.execute(delete(TenantDirectoryEntry).where(TenantDirectoryEntry.company_id == company_id))
            await db.execute(delete(TenantDbServer).where(TenantDbServer.name == server_name))
            await db.commit()
        from src.common.tenancy.engines import engines

        await engines.dispose_all()
        if db_name:
            admin = await asyncpg.connect(url.set(drivername="postgresql", database="postgres")
                                          .render_as_string(hide_password=False))
            try:
                await admin.execute(f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE)')
            finally:
                await admin.close()
        from tests.harness.purge import purge_companies

        async with control_session() as db:
            await purge_companies(await db.connection(), [company_id])
            await db.commit()


async def _log(company_id):
    from src.common.tenancy.models import TenantProvisioningLog
    from src.common.tenancy.session import control_session

    async with control_session() as db:
        rows = (await db.execute(select(TenantProvisioningLog.step, TenantProvisioningLog.outcome)
                                 .where(TenantProvisioningLog.company_id == company_id)
                                 .order_by(TenantProvisioningLog.created_at, TenantProvisioningLog.id))).all()
    return [tuple(r) for r in rows]


async def test_a_company_is_provisioned_to_active_and_its_database_has_its_tables(company, control, monkeypatch,
                                                                                  tmp_path):
    from src.common.platform.kek import set_kek
    from src.common.platform.kek.local import LocalKeyEncryption
    from src.common.tenancy import provisioner
    from src.common.tenancy.directory import directory
    from src.common.tenancy.migrate import tenant_schema_version
    from src.common.tenancy.session import tenant_session
    from src.connections import crypto

    set_kek(LocalKeyEncryption(tmp_path / "keys"))
    crypto.forget_cached()
    entry = await provisioner.request_tenant(company["id"], server_name=company["server"])
    assert entry.status == "requested" and entry.slug == "provisioned-co" and entry.db_name == f"t_{entry.tenant_key}"
    assert (await provisioner.request_tenant(company["id"])).tenant_key == entry.tenant_key  # idempotent

    result = await provisioner.provision(company["id"])
    assert result["status"] == "active", result
    outcomes = {s["step"]: s["outcome"] for s in result["steps"]}
    assert outcomes == {"db_created": "succeeded", "migrated": "succeeded", "identity_ready": "skipped",
                        "keys_ready": "succeeded", "namespace_ready": "skipped", "storage_ready": "succeeded",
                        "data_api_ready": "skipped", "active": "succeeded"}
    keys = next(s for s in result["steps"] if s["step"] == "keys_ready")["detail"]
    assert keys["kek"] == f"t-{entry.tenant_key}" and keys["dek_version"] == 1   # the KEK, and its first DEK
    assert (tmp_path / "keys").is_dir()
    migrated = next(s for s in result["steps"] if s["step"] == "migrated")["detail"]
    assert migrated["platform_schema_version"] == tenant_schema_version()
    assert {"account", "contact", "activity", "consent"} <= set(migrated["objects"])
    assert f"t-{entry.tenant_key}/workspace.json" in control.objects

    location = await directory.get(company["id"])
    assert location.status == "active" and location.schema_version == tenant_schema_version()
    monkeypatch.setattr("src.common.config.settings.TENANCY_MODE", "split")
    async with tenant_session(company["id"]) as db:
        database_name, schema = (await db.execute(text("SELECT current_database(), current_schema()"))).one()
        assert (database_name, schema) == (entry.db_name, "platform")
        assert (await db.execute(text("SELECT to_regclass('execution_runs')"))).scalar() == "execution_runs"
        assert (await db.execute(text("SELECT to_regclass('business.contact')"))).scalar() is not None

    # Finished: provisioning again changes nothing.
    again = await provisioner.provision(company["id"])
    assert again["status"] == "active" and again["steps"] == []
    log = await _log(company["id"])
    assert log[0] == ("requested", "succeeded")
    assert log.count(("db_created", "started")) == 1
    set_kek(None)
    crypto.forget_cached()


async def test_a_failed_step_is_resumed_without_redoing_the_earlier_ones(company, control, monkeypatch):
    from src.common.tenancy import provisioner
    from src.common.tenancy.session import control_session

    async def _storage_down(tenant):
        raise ConnectionError("storage account unreachable")

    await provisioner.request_tenant(company["id"], server_name=company["server"])
    storage_ready = provisioner.STEP_FUNCTIONS["storage_ready"]
    monkeypatch.setitem(provisioner.STEP_FUNCTIONS, "storage_ready", _storage_down)
    failed = await provisioner.provision(company["id"])
    assert failed["status"] == "failed" and failed["failed"] == "storage_ready"
    async with control_session() as db:
        view = await provisioner.provisioning_status(db, company["id"])
    steps = {s["step"]: s for s in view["steps"]}
    assert view["status"] == "failed" and not view["ready"] and view["database_ready"] is False
    assert steps["storage_ready"]["outcome"] == "failed"
    assert "storage account unreachable" in steps["storage_ready"]["error"]
    assert steps["data_api_ready"]["outcome"] == "pending"

    monkeypatch.setitem(provisioner.STEP_FUNCTIONS, "storage_ready", storage_ready)  # the storage is back
    resumed = await provisioner.provision(company["id"])
    assert resumed["status"] == "active", resumed
    assert [s["step"] for s in resumed["steps"]] == ["storage_ready", "data_api_ready", "active"]
    log = await _log(company["id"])
    assert log.count(("db_created", "started")) == 1 and log.count(("storage_ready", "started")) == 2


async def test_two_provisioners_never_work_on_one_tenant_at_once(company, control):
    import asyncio

    from src.common.tenancy import provisioner

    await provisioner.request_tenant(company["id"], server_name=company["server"])
    first, second = await asyncio.gather(provisioner.provision(company["id"]),
                                         provisioner.provision(company["id"]))
    outcomes = sorted([first, second], key=lambda r: bool(r.get("busy")))
    assert outcomes[0]["status"] == "active" and outcomes[1] == {"company_id": str(company["id"]), "busy": True}


async def test_staff_add_a_tenant_with_one_call_and_people_see_their_workspace(company, control, monkeypatch):
    """POST /admin/tenants requests the tenant and queues its provisioning; the
    job then makes it active; GET /workspace shows the steps, GET
    /admin/tenants/{id} the health."""
    from types import SimpleNamespace

    import httpx
    from fastapi import FastAPI

    from src.auth.dependencies import get_current_user
    from src.common.tenancy import api, provisioner
    from src.common.tenancy.errors import install_tenancy_error_handlers

    queued = []

    async def _enqueue(function, *args, **kwargs):
        queued.append((function, args))
        return SimpleNamespace(job_id="test")

    monkeypatch.setattr("src.common.job_queue.enqueue_job", _enqueue)
    app = FastAPI()
    app.include_router(api.router)
    install_tenancy_error_handlers(app)
    caller = {"user": SimpleNamespace(id=uuid.uuid4(), company_id=uuid.uuid4(), role="app_admin")}

    async def _user():
        return caller["user"]

    app.dependency_overrides[get_current_user] = _user
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client:
        added = await client.post("/api/v1/admin/tenants", json={"company_id": str(company["id"]),
                                                                 "server": company["server"]})
        assert added.status_code == 202, added.text
        assert added.json()["status"] == "requested"
        assert queued == [("provision_tenant", (str(company["id"]),))]

        result = await provisioner.provision_tenant({}, str(company["id"]))  # what the worker runs
        assert result["status"] == "active"

        detail = await client.get(f"/api/v1/admin/tenants/{company['id']}")
        assert detail.status_code == 200, detail.text
        health = detail.json()["health"]
        assert health["reachable"] is True and health["schema"] == "current" and health["healthy"] is True

        listed = await client.get("/api/v1/admin/tenants", params={"health": "true"})
        mine = [t for t in listed.json()["tenants"] if t["company_id"] == str(company["id"])]
        assert mine and mine[0]["health"]["healthy"] is True and mine[0]["server"] == company["server"]
        servers = await client.get("/api/v1/admin/tenant-servers")
        assert {"name": company["server"], "tenants": 1}.items() <= next(
            s for s in servers.json() if s["name"] == company["server"]).items()

        # The person's own view: single mode is always ready; split mode shows the steps.
        caller["user"] = SimpleNamespace(id=uuid.uuid4(), company_id=company["id"], role="tenant_admin")
        single = await client.get("/api/v1/workspace")
        assert single.json()["ready"] is True and single.json()["mode"] == "single"
        monkeypatch.setattr("src.common.config.settings.TENANCY_MODE", "split")
        split = await client.get("/api/v1/workspace")
        assert split.json()["ready"] is True and split.json()["status"] == "active"
        assert {s["step"] for s in split.json()["steps"]} >= {"db_created", "active"}
        assert all(set(s) == {"step", "outcome"} for s in split.json()["steps"])  # no errors or servers

        refused = await client.get("/api/v1/admin/tenants")
        assert refused.status_code == 403


@pytest_asyncio.fixture
async def ddl_roles(company, monkeypatch):
    """The pool server's roles switched on (as on Azure), with this test's own names;
    afterwards the tenant database first (its objects belong to them), then the roles."""
    import asyncpg
    from sqlalchemy.engine import make_url

    from src.common.config import settings
    from src.common.tenancy.models import TenantDirectoryEntry
    from src.common.tenancy.session import control_session

    sfx = uuid.uuid4().hex[:8]
    names = {"ddl": f"hbt_ddl_{sfx}", "api": f"hbt_api_{sfx}", "migrator": f"hbt_mig_{sfx}"}
    for key, value in (("TENANT_DB_DDL_ROLE", names["ddl"]), ("TENANT_DB_RUNTIME_PRINCIPALS", names["api"]),
                       ("TENANT_DB_MIGRATOR_PRINCIPAL", names["migrator"])):
        monkeypatch.setattr(settings, key, value)
        monkeypatch.setenv(key, value)  # the migration runner's child process reads them too
    url = make_url(settings.CONTROL_DATABASE_URL).set(drivername="postgresql", database="postgres")
    admin = await asyncpg.connect(url.render_as_string(hide_password=False))
    pre = {r["rolname"] for r in await admin.fetch(
        "SELECT rolname FROM pg_roles WHERE rolname IN ('hb_runtime', 'hb_dataapi')")}
    try:
        yield names
    finally:
        async with control_session() as db:
            entry = await db.get(TenantDirectoryEntry, company["id"])
        if entry is not None:
            await admin.execute(f'DROP DATABASE IF EXISTS "{entry.db_name}" WITH (FORCE)')
        for role in [names["api"], names["migrator"], names["ddl"]] + \
                [r for r in ("hb_runtime", "hb_dataapi") if r not in pre]:
            if await admin.fetchval("SELECT 1 FROM pg_roles WHERE rolname = $1", role):
                await admin.execute(f'DROP OWNED BY "{role}"')
                await admin.execute(f'DROP ROLE "{role}"')
        await admin.close()


async def test_with_the_ddl_role_every_object_belongs_to_it_and_serves_the_runtime(company, control, ddl_roles,
                                                                                    tmp_path):
    """M2 (Azure): the provisioner builds the database, its migrations and the base
    pack as the DDL role (SET ROLE), so one role owns everything whoever migrates
    later, and the API and workers (hb_runtime) can use every table."""
    from src.common.platform.kek import set_kek
    from src.common.platform.kek.local import LocalKeyEncryption
    from src.common.tenancy import provisioner
    from src.connections import crypto

    set_kek(LocalKeyEncryption(tmp_path / "keys"))
    crypto.forget_cached()
    try:
        entry = await provisioner.request_tenant(company["id"], server_name=company["server"])
        result = await provisioner.provision(company["id"])
    finally:
        set_kek(None)
        crypto.forget_cached()
    assert result["status"] == "active", result
    created = next(s for s in result["steps"] if s["step"] == "db_created")["detail"]
    assert created["access"]["owner"] == ddl_roles["ddl"]
    assert {ddl_roles["api"], ddl_roles["migrator"]} <= set(created["server_roles"]["made"])

    import asyncpg
    from sqlalchemy.engine import make_url

    from src.common.config import settings
    url = make_url(settings.CONTROL_DATABASE_URL).set(drivername="postgresql", database=entry.db_name)
    conn = await asyncpg.connect(url.render_as_string(hide_password=False))
    try:
        owners = {r["tableowner"] for r in await conn.fetch(
            "SELECT DISTINCT tableowner FROM pg_tables WHERE schemaname IN ('platform', 'business')")}
        assert owners == {ddl_roles["ddl"]}
        assert await conn.fetchval("SELECT has_table_privilege($1, 'platform.execution_runs', "
                                   "'SELECT, INSERT, UPDATE, DELETE')", ddl_roles["api"])
        assert await conn.fetchval("SELECT has_table_privilege($1, 'business.contact', 'SELECT, INSERT')",
                                   ddl_roles["api"])
        assert await conn.fetchval("SELECT has_database_privilege($1, $2, 'CONNECT')", ddl_roles["api"],
                                   entry.db_name)
        assert not await conn.fetchval("SELECT has_database_privilege('public', $1, 'CONNECT')", entry.db_name)
    finally:
        await conn.close()


async def test_with_the_ddl_role_schema_changes_and_the_kpi_refresh_need_no_ddl_rights(company, control, ddl_roles,
                                                                                       tmp_path, monkeypatch):
    """M2-3: the runtime (hb_runtime, not a member of the DDL role) refreshes the KPI
    view through its owner's function, and an approved schema change is applied as
    the DDL role — here by a member, and handed to the provisioning worker when the
    caller is not one (Azure's API)."""
    import asyncpg
    from sqlalchemy.engine import make_url

    from src.common import job_queue
    from src.common.config import settings
    from src.common.platform.kek import set_kek
    from src.common.platform.kek.local import LocalKeyEncryption
    from src.common.tenancy import provisioner
    from src.common.tenancy.engines import create_tenant_engine
    from src.connections import crypto
    from src.schema_engine import engine as schema

    set_kek(LocalKeyEncryption(tmp_path / "keys"))
    crypto.forget_cached()
    try:
        entry = await provisioner.request_tenant(company["id"], server_name=company["server"])
        assert (await provisioner.provision(company["id"]))["status"] == "active"
    finally:
        set_kek(None)
        crypto.forget_cached()
    url = make_url(settings.CONTROL_DATABASE_URL).set(database=entry.db_name)

    async def owner(table):
        conn = await asyncpg.connect(url.set(drivername="postgresql").render_as_string(hide_password=False))
        try:
            return await conn.fetchval("SELECT tableowner FROM pg_tables WHERE schemaname = 'custom' "
                                       "AND tablename = $1", table)
        finally:
            await conn.close()

    # The KPI view: the runtime may not refresh it directly, only through the function.
    runtime = create_tenant_engine(url, role=ddl_roles["api"])
    try:
        async with runtime.connect() as conn:
            assert (await conn.execute(text("SELECT current_user"))).scalar() == ddl_roles["api"]
            await conn.execute(text("SELECT refresh_kpi_daily_rollup(false)"))
            await conn.commit()
            with pytest.raises(Exception, match="must be owner"):
                await conn.execute(text("REFRESH MATERIALIZED VIEW kpi_daily_rollup"))
    finally:
        await runtime.dispose()

    # A member of the DDL role (here the superuser) applies a change as the role.
    member = create_tenant_engine(url)
    try:
        change = await schema.propose(member, company["id"], [
            {"op": "add_object", "object": "shipment", "definition": {"fields": {"carrier": {"type": "text"}}}}],
            actor_kind="user", actor_id="user:owner")
    finally:
        await member.dispose()
    assert change["status"] == "applied"
    assert await owner("shipment") == ddl_roles["ddl"]

    # The runtime is not a member: with a provisioning queue the change goes to the
    # provisioning worker (played here in-process) and the caller gets its outcome.
    monkeypatch.setattr(settings, "PROVISIONING_QUEUE", "provisioning")
    monkeypatch.setattr(settings, "TENANCY_MODE", "split")
    queued = []

    class FakePool:
        pass

    class FakeJob:
        def __init__(self, args):
            self.args = args

        async def result(self, timeout=None, poll_delay=None):
            return await schema.apply_schema_change({}, *self.args)

    class _Pool:
        async def __aenter__(self):
            return FakePool()

        async def __aexit__(self, *exc):
            return False

    async def fake_enqueue(pool, function, *args, **kwargs):
        queued.append((function, kwargs.get("_queue_name")))
        return FakeJob(args)

    monkeypatch.setattr(job_queue, "arq_pool", lambda: _Pool())
    monkeypatch.setattr(job_queue, "enqueue_on", fake_enqueue)
    runtime = create_tenant_engine(url, role=ddl_roles["api"])
    try:
        change = await schema.propose(runtime, company["id"], [
            {"op": "add_object", "object": "invoice", "definition": {"fields": {"number": {"type": "text"}}}}],
            actor_kind="user", actor_id="user:owner")
    finally:
        await runtime.dispose()
    assert queued == [("apply_schema_change", "provisioning")]
    assert change["status"] == "applied"
    assert await owner("invoice") == ddl_roles["ddl"]
