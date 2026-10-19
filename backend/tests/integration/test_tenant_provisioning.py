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


async def test_a_company_is_provisioned_to_active_and_its_database_has_its_tables(company, control, monkeypatch):
    from src.common.tenancy import provisioner
    from src.common.tenancy.directory import directory
    from src.common.tenancy.migrate import tenant_schema_version
    from src.common.tenancy.session import tenant_session

    entry = await provisioner.request_tenant(company["id"], server_name=company["server"])
    assert entry.status == "requested" and entry.slug == "provisioned-co" and entry.db_name == f"t_{entry.tenant_key}"
    assert (await provisioner.request_tenant(company["id"])).tenant_key == entry.tenant_key  # idempotent

    result = await provisioner.provision(company["id"])
    assert result["status"] == "active", result
    outcomes = {s["step"]: s["outcome"] for s in result["steps"]}
    assert outcomes == {"db_created": "succeeded", "migrated": "succeeded", "identity_ready": "skipped",
                        "keys_ready": "skipped", "namespace_ready": "skipped", "storage_ready": "succeeded",
                        "data_api_ready": "skipped", "active": "succeeded"}
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
