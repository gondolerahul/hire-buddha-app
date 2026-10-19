"""The tenant data plane's building blocks (Phase 14 WS2 2.1, 2.2, 2.8).

Settings, table planes (tech spec Appendix A), the tenant directory's cache,
the engine cache and session routing — without a database. Routing to two
real databases is ``tests/integration/test_tenant_routing.py``.
"""
from __future__ import annotations

import dataclasses
import uuid
from types import SimpleNamespace

import pytest

from src.common.tenancy import bases, directory as directory_mod, engines as engines_mod, session as tsession
from src.common.tenancy.bases import CONTROL, TENANT
from src.common.tenancy.directory import (
    TENANT_KEY_ALPHABET, TenantDirectory, TenantLocation, TenantNotFound, TenantNotReady,
    is_valid_tenant_key, new_tenant_key, tenant_db_name,
)

CONTROL_URL = "postgresql+asyncpg://hb_runtime:pw@control.local:5433/hb_control"


# ── Settings ────────────────────────────────────────────────────────────────

def _settings(monkeypatch, **values):
    from src.common.config import Settings

    for name in ("DATABASE_URL", "CONTROL_DATABASE_URL", "TENANCY_MODE"):
        monkeypatch.delenv(name, raising=False)
    base = {"REDIS_URL": "redis://localhost:6379", "SECRET_KEY": "s" * 40,
            "ENCRYPTION_MASTER_KEY": "k" * 40}
    return Settings(_env_file=None, **{**base, **values})


def test_control_database_url_fills_its_old_name(monkeypatch):
    s = _settings(monkeypatch, CONTROL_DATABASE_URL=CONTROL_URL)
    assert s.DATABASE_URL == s.CONTROL_DATABASE_URL == CONTROL_URL


def test_the_old_name_alone_still_works(monkeypatch):
    s = _settings(monkeypatch, DATABASE_URL=CONTROL_URL)
    assert s.CONTROL_DATABASE_URL == CONTROL_URL


def test_two_different_database_urls_refuse_to_load(monkeypatch):
    with pytest.raises(ValueError, match="differ"):
        _settings(monkeypatch, CONTROL_DATABASE_URL=CONTROL_URL, DATABASE_URL=CONTROL_URL + "x")


def test_a_database_url_is_required(monkeypatch):
    with pytest.raises(ValueError, match="CONTROL_DATABASE_URL"):
        _settings(monkeypatch)


def test_tenancy_mode_is_single_unless_set(monkeypatch):
    assert _settings(monkeypatch, DATABASE_URL=CONTROL_URL).TENANCY_MODE == "single"
    assert _settings(monkeypatch, DATABASE_URL=CONTROL_URL, TENANCY_MODE=" Split ").TENANCY_MODE == "split"
    with pytest.raises(ValueError, match="single or split"):
        _settings(monkeypatch, DATABASE_URL=CONTROL_URL, TENANCY_MODE="multi")


# ── Planes (Appendix A) ─────────────────────────────────────────────────────

APPENDIX_A_CONTROL = {
    "companies", "users", "refresh_tokens", "user_devices",
    "subscription_tiers", "subscriptions", "payment_transactions", "credit_wallets", "credit_holds",
    "billing_config", "billing_events", "usage_logs",
    "integration_registry", "model_task_defaults", "feature_flags", "tool_registry_entries",
    "phone_numbers", "webhook_endpoints",
    "tenant_db_servers", "tenant_directory", "tenant_provisioning_log",
    # Automation (WS3): what is due when, and each business's settings (D47).
    "time_index", "automation_settings",
    # Notifications (WS3 3.11): one row per person told.
    "notifications",
    # Connections (WS5, tech spec §10.2): what can be connected, who owns which
    # outside account, provider deliveries nobody owns.
    "connector_catalog", "external_account_routes", "unrouted_events",
}
APPENDIX_A_TENANT = {
    "hierarchical_entities", "entity_versions", "entity_assets",
    "execution_runs", "execution_trace_events", "llm_interaction_logs", "tool_interaction_logs",
    "human_approvals", "run_subjects",
    "documents", "cortex_trees", "cortex_nodes", "cortex_edges", "artifacts",
    "campaigns", "campaign_calls", "campaign_assignees", "lead_queue", "contact_uploads",
    "call_logs", "call_content",
    "voice_sessions", "whatsapp_sessions", "conversation_history",
    "mobile_call_attempts", "mobile_call_events", "mobile_campaign_runs", "mobile_client_logs",
    # Replaced by platform.connections (WS5); tenant data until then.
    "email_connections", "social_connections",
    # Automation (WS3, tech spec §7.3).
    "events", "triggers", "trigger_firings", "waits",
    # Records (WS4, tech spec §8.4, §9.3): blueprints, changes, audit, keys.
    "schema_blueprints", "schema_changes", "audit_log", "api_keys", "records_settings",
    # Connections (WS5, tech spec §10.3): accounts, sealed secrets, grants, use, the DEK.
    "connections", "connection_secrets", "connection_grants", "connection_audit", "tenant_keys",
}

# What the foreign keys between the planes were: a tenant database cannot hold
# them, so 2.3 dropped them (migration p14_drop_cross_plane_fks) and kept the
# columns as plain UUIDs marked ``refers_to()``. The 34 the models declared,
# and four the migration chain gave cortex_trees (its package declares none).
CROSS_PLANE_REFERENCES = {
    "artifacts.company_id -> companies", "call_logs.company_id -> companies",
    "campaign_assignees.user_id -> users", "campaigns.company_id -> companies",
    "campaigns.created_by -> users", "contact_uploads.company_id -> companies",
    "contact_uploads.uploaded_by -> users", "conversation_history.company_id -> companies",
    "cortex_trees.app_id -> companies", "cortex_trees.company_id -> companies",
    "cortex_trees.partner_id -> companies", "cortex_trees.user_id -> users",
    "credit_holds.run_id -> execution_runs", "documents.company_id -> companies",
    "email_connections.company_id -> companies", "entity_versions.company_id -> companies",
    "entity_versions.created_by -> users", "entity_versions.published_by -> users",
    "execution_runs.company_id -> companies", "execution_runs.user_id -> users",
    "hierarchical_entities.company_id -> companies", "hierarchical_entities.created_by -> users",
    "human_approvals.responded_by -> users", "lead_queue.company_id -> companies",
    "mobile_call_attempts.company_id -> companies", "mobile_call_attempts.device_id -> user_devices",
    "mobile_call_attempts.user_id -> users", "mobile_campaign_runs.company_id -> companies",
    "mobile_campaign_runs.device_id -> user_devices", "mobile_campaign_runs.user_id -> users",
    "mobile_client_logs.company_id -> companies", "mobile_client_logs.user_id -> users",
    "phone_numbers.agent_id -> hierarchical_entities", "social_connections.company_id -> companies",
    "usage_logs.run_id -> execution_runs", "voice_sessions.company_id -> companies",
    "webhook_endpoints.entity_id -> hierarchical_entities", "whatsapp_sessions.company_id -> companies",
}
# The ON DELETE actions those keys had; the rest refused the delete. Whatever
# deletes the referred rows now does these itself.
CROSS_PLANE_ON_DELETE = {
    "campaign_assignees.user_id -> users": "CASCADE",
    "credit_holds.run_id -> execution_runs": "CASCADE",
    "cortex_trees.app_id -> companies": "SET NULL",
    "cortex_trees.partner_id -> companies": "SET NULL",
    "hierarchical_entities.created_by -> users": "SET NULL",
    "webhook_endpoints.entity_id -> hierarchical_entities": "SET NULL",
}


def test_every_table_is_on_exactly_one_plane():
    assert bases.unclassified_tables() == []


def test_tables_are_placed_as_appendix_a_says():
    assert {t.name for t in bases.plane_tables(CONTROL)} == APPENDIX_A_CONTROL
    assert {t.name for t in bases.plane_tables(TENANT)} == APPENDIX_A_TENANT


def test_no_model_is_declared_on_the_shared_base_directly():
    from src.common.database import Base
    from src.common.orm_models import import_all_models

    import_all_models()
    direct = [m.class_.__name__ for m in Base.registry.mappers
              if not issubclass(m.class_, (bases.ControlBase, bases.TenantBase))]
    assert direct == []


def test_no_foreign_key_crosses_the_planes():
    assert bases.cross_plane_foreign_keys() == []


def test_no_relationship_crosses_the_planes():
    from sqlalchemy.orm import configure_mappers

    from src.common.orm_models import import_all_models

    import_all_models()
    configure_mappers()  # every relationship still resolves without the keys
    assert bases.cross_plane_relationships() == []


def test_the_dropped_keys_are_recorded_as_references():
    from sqlalchemy.dialects.postgresql import UUID

    from src.common.orm_models import import_all_models

    references = bases.cross_plane_references()
    assert {str(r) for r in references} == CROSS_PLANE_REFERENCES
    assert len(references) == len(CROSS_PLANE_REFERENCES)
    assert {str(r): r.ondelete for r in references if r.ondelete} == CROSS_PLANE_ON_DELETE
    tables = {t.name: t for metadata in import_all_models() for t in metadata.tables.values()}
    for r in references:
        column, referred = tables[r.table].columns[r.column], tables[r.referred_table]
        assert isinstance(column.type, UUID) and not column.foreign_keys, r
        assert r.referred_column in referred.columns, r
        assert bases.plane_of(tables[r.table]) != bases.plane_of(referred), f"{r}: same plane, use a key"


def test_the_migration_drops_and_restores_exactly_the_references():
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "migrations" / "legacy" / "versions" / "p14_drop_cross_plane_fks.py"
    spec = importlib.util.spec_from_file_location("p14_drop_cross_plane_fks", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert set(migration.CROSS_PLANE_KEYS) == {
        (r.table, r.column, r.referred_table, r.ondelete) for r in bases.cross_plane_references()}


def test_a_tenant_database_refuses_a_key_to_a_control_table(monkeypatch):
    monkeypatch.setattr(bases, "cross_plane_foreign_keys", lambda: ["runs.company_id -> companies"])
    with pytest.raises(ValueError, match="runs.company_id"):
        bases.tenant_ddl_metadata()


def test_tenant_schema_has_only_tenant_tables_and_tenant_foreign_keys():
    metadata = bases.tenant_ddl_metadata()
    assert {t.name for t in metadata.tables.values()} == APPENDIX_A_TENANT
    assert {t.schema for t in metadata.tables.values()} == {"platform"}
    tenant_fks = set()
    for table in metadata.tables.values():
        for fk in table.foreign_keys:
            schema, referred, _ = fk.target_fullname.split(".")
            assert schema == "platform" and referred in APPENDIX_A_TENANT, (table.name, fk.target_fullname)
            tenant_fks.add(f"{table.name}.{fk.parent.name} -> {referred}")
    assert "execution_trace_events.run_id -> execution_runs" in tenant_fks
    # A run still names its company, as a plain UUID.
    assert "company_id" in metadata.tables["platform.execution_runs"].columns


def test_a_split_session_binds_each_plane_to_its_engine(monkeypatch):
    from src.ai.orm.execution import ExecutionRun
    from src.auth.models import Company
    from src.common import database
    from cortex_memory.models import CortexTree

    control_engine, tenant_engine = object(), object()
    monkeypatch.setattr(database, "engine", control_engine)
    monkeypatch.setattr(engines_mod.engines, "get", lambda location: tenant_engine)
    monkeypatch.setattr(tsession, "async_sessionmaker", lambda **kw: kw)

    kw = tsession._tenant_factory(_location())
    binds = kw["binds"]
    assert kw["bind"] is tenant_engine  # raw SQL goes to the tenant database
    assert binds[bases.TenantBase] is tenant_engine and binds[bases.cortex_base()] is tenant_engine
    assert binds[bases.ControlBase] is control_engine
    assert issubclass(ExecutionRun, bases.TenantBase) and issubclass(Company, bases.ControlBase)
    assert issubclass(CortexTree, bases.cortex_base())
    assert kw["info"]["tenant_key"] == "devacme01"


async def test_a_split_session_routes_each_class_by_its_plane():
    """The SQLAlchemy side of the binds: a session sends each mapped class to its engine."""
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

    from src.ai.orm.execution import ExecutionRun
    from src.auth.models import Company
    from src.common.tenancy.models import TenantDirectoryEntry
    from cortex_memory.models import CortexNode

    control = create_async_engine("postgresql+asyncpg://u:p@control/hb_control")
    tenant = create_async_engine("postgresql+asyncpg://u:p@pool/t_devacme01")
    session = AsyncSession(bind=tenant, binds={bases.TenantBase: tenant, bases.cortex_base(): tenant,
                                               bases.ControlBase: control})
    sync = session.sync_session
    try:
        for cls, engine in ((ExecutionRun, tenant), (CortexNode, tenant), (Company, control),
                            (TenantDirectoryEntry, control)):
            from sqlalchemy import inspect
            assert sync.get_bind(mapper=inspect(cls)) is engine.sync_engine, cls
        assert sync.get_bind() is tenant.sync_engine
    finally:
        await session.close()
        await control.dispose()
        await tenant.dispose()


# ── Tenant keys and the directory ───────────────────────────────────────────

def test_new_tenant_keys_are_ten_crockford_characters():
    keys = {new_tenant_key() for _ in range(200)}
    assert len(keys) == 200
    assert all(len(k) == 10 and set(k) <= set(TENANT_KEY_ALPHABET) and is_valid_tenant_key(k) for k in keys)


@pytest.mark.parametrize("key", ["devacme01", "devbeta001", "abc"])
def test_dev_keys_are_valid(key):
    assert is_valid_tenant_key(key) and tenant_db_name(key) == f"t_{key}"


@pytest.mark.parametrize("key", ["", "ab", "Upper12345", "a_b", "x;drop", "abcdefghjkm", "ilou", None, 7])
def test_anything_else_is_not_a_key(key):
    assert not is_valid_tenant_key(key)
    with pytest.raises(ValueError):
        tenant_db_name(key)  # type: ignore[arg-type]


def _location(status="active", key="devacme01", company_id=None, host="localhost"):
    return TenantLocation(company_id=company_id or uuid.uuid4(), key=key, server_host=host,
                          db_name=f"t_{key}", status=status, schema_version=None,
                          automation_state="running", timezone="Asia/Kolkata")


class _Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def _directory(rows):
    clock = _Clock()
    d = TenantDirectory(ttl_seconds=60, clock=clock)
    reads = []

    async def read(company_id):
        reads.append(company_id)
        return rows.get(company_id)

    d._read = read  # type: ignore[method-assign]
    return d, clock, reads


async def test_the_directory_caches_a_row_for_a_minute():
    cid = uuid.uuid4()
    d, clock, reads = _directory({cid: _location(company_id=cid)})
    assert (await d.get(cid)).key == "devacme01"
    assert (await d.get(str(cid))).key == "devacme01"
    clock.now += 59
    await d.get(cid)
    assert len(reads) == 1
    clock.now += 2
    await d.get(cid)
    assert len(reads) == 2


async def test_invalidating_reads_the_row_again():
    cid = uuid.uuid4()
    d, _, reads = _directory({cid: _location(company_id=cid)})
    await d.get(cid)
    d.invalidate(cid)
    await d.get(cid)
    d.invalidate()
    await d.get(cid)
    assert len(reads) == 3


async def test_a_company_without_a_row_is_not_found():
    d, _, _ = _directory({})
    assert await d.find(uuid.uuid4()) is None
    with pytest.raises(TenantNotFound):
        await d.get(uuid.uuid4())


def test_a_change_message_drops_one_row_or_all(monkeypatch):
    dropped = []
    monkeypatch.setattr(directory_mod.directory, "invalidate", lambda cid=None: dropped.append(cid))
    cid = uuid.uuid4()
    directory_mod._apply_change(f'{{"company_id": "{cid}"}}')
    directory_mod._apply_change('{"company_id": null}')
    directory_mod._apply_change("not json")
    assert dropped == [cid, None, None]


async def test_publishing_a_change_drops_it_here_too(monkeypatch):
    published = []

    class _Redis:
        async def publish(self, channel, data):
            published.append((channel, data))

    dropped = []
    monkeypatch.setattr(directory_mod.directory, "invalidate", lambda cid=None: dropped.append(cid))
    cid = uuid.uuid4()
    await directory_mod.publish_change(_Redis(), cid)
    assert dropped == [cid]
    assert published == [(directory_mod.CHANGES_CHANNEL, f'{{"company_id": "{cid}"}}')]


@pytest.mark.parametrize("status,ready", [
    ("requested", False), ("db_created", False), ("migrated", True), ("active", True),
    ("suspended", True), ("exporting", True), ("retired", False), ("failed", False)])
def test_a_tenant_database_is_ready_from_migrated_until_retired(status, ready):
    assert _location(status=status).database_ready is ready


# ── Engines ─────────────────────────────────────────────────────────────────

def test_a_tenant_url_is_the_control_principal_on_the_tenant_server(monkeypatch):
    from src.common.config import settings

    monkeypatch.setattr(settings, "CONTROL_DATABASE_URL", CONTROL_URL)
    monkeypatch.setattr(settings, "TENANT_DB_PORT", 0)
    url = engines_mod.tenant_url(_location(host="pool-01.private"))
    assert (url.drivername, url.username, url.password) == ("postgresql+asyncpg", "hb_runtime", "pw")
    assert (url.host, url.port, url.database) == ("pool-01.private", 5433, "t_devacme01")
    monkeypatch.setattr(settings, "TENANT_DB_PORT", 6432)
    assert engines_mod.tenant_url(_location()).port == 6432


async def test_the_engine_cache_closes_the_least_recently_used(monkeypatch):
    from src.common.config import settings

    monkeypatch.setattr(settings, "CONTROL_DATABASE_URL", CONTROL_URL)
    disposed = []

    class _Engine:
        def __init__(self, url):
            self.url = url

        async def dispose(self):
            disposed.append(self.url.database)

    monkeypatch.setattr(engines_mod, "create_tenant_engine", _Engine)
    cache = engines_mod.TenantEngines(capacity=2)
    a, b = _location(key="aaaaa"), _location(key="bbbbb")
    engine_a = cache.get(a)
    cache.get(b)
    assert cache.get(a) is engine_a          # a is now the most recently used
    cache.get(_location(key="ccccc"))        # so b goes
    assert [key[2] for key in cache._engines] == ["t_aaaaa", "t_ccccc"]
    await cache.dispose_all()                # also waits for b's close
    assert sorted(disposed) == ["t_aaaaa", "t_bbbbb", "t_ccccc"]
    assert len(cache) == 0


def test_a_tenant_engine_searches_the_platform_schema_first():
    executed = []

    class _Conn:
        def run_async(self, fn):
            class _Raw:
                async def execute(self, sql):
                    executed.append(sql)
            import asyncio
            asyncio.run(fn(_Raw()))

    engines_mod._search_platform_first(_Conn(), None)
    assert executed == ["SET search_path TO platform, public"]


# ── Sessions ────────────────────────────────────────────────────────────────

class _FakeSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


@pytest.fixture
def single(monkeypatch):
    from src.common.config import settings

    monkeypatch.setattr(settings, "TENANCY_MODE", "single")


@pytest.fixture
def split(monkeypatch):
    from src.common.config import settings

    monkeypatch.setattr(settings, "TENANCY_MODE", "split")


async def test_single_mode_opens_both_sessions_on_the_shared_factory(monkeypatch, single):
    """Looked up when the session opens: a test that moves AsyncSessionLocal moves them."""
    from src.common import database

    made = []

    def factory():
        made.append(1)
        return _FakeSession()

    monkeypatch.setattr(database, "AsyncSessionLocal", factory)
    async with tsession.tenant_session(uuid.uuid4()) as db:
        assert isinstance(db, _FakeSession)
    async with tsession.tenant_session(None) as db:
        assert isinstance(db, _FakeSession)
    async with tsession.control_session() as db:
        assert isinstance(db, _FakeSession)
    assert len(made) == 3
    assert await tsession.tenant_scopes() == [None]


async def test_split_mode_needs_the_company(split):
    with pytest.raises(tsession.TenantRequired):
        async with tsession.tenant_session(None):
            pass


async def test_split_mode_refuses_a_database_that_is_not_ready(monkeypatch, split):
    async def get(company_id):
        return _location(status="db_created", company_id=company_id)

    monkeypatch.setattr(directory_mod.directory, "get", get)
    with pytest.raises(TenantNotReady):
        async with tsession.tenant_session(uuid.uuid4()):
            pass


async def test_split_mode_opens_the_companys_database(monkeypatch, split):
    cid = uuid.uuid4()
    seen = []

    async def get(company_id):
        seen.append(company_id)
        return _location(company_id=cid)

    monkeypatch.setattr(directory_mod.directory, "get", get)
    monkeypatch.setattr(tsession, "_tenant_factory", lambda location: (lambda: _FakeSession()))
    async with tsession.tenant_session(cid) as db:
        assert isinstance(db, _FakeSession)
    assert seen == [cid]


async def test_split_mode_sweeps_every_ready_tenant(monkeypatch, split):
    ids = [uuid.uuid4(), uuid.uuid4()]

    async def ready():
        return ids

    monkeypatch.setattr(directory_mod.directory, "ready_company_ids", ready)
    assert await tsession.tenant_scopes() == ids


def _request(company_header=None):
    headers = {tsession.ACTING_COMPANY_HEADER: company_header} if company_header else {}
    return SimpleNamespace(headers=headers)


async def _first(gen):
    value = await gen.__anext__()
    await gen.aclose()
    return value


@pytest.fixture
def opened(monkeypatch):
    """The companies whose tenant sessions were opened."""
    companies = []

    async def factory_for(company_id):
        companies.append(company_id)
        return _FakeSession

    monkeypatch.setattr(tsession, "tenant_sessionmaker", factory_for)
    return companies


async def test_single_mode_dependencies_are_the_requests_session(single, opened):
    db, user = object(), SimpleNamespace(company_id=uuid.uuid4(), role="tenant_user")
    other = str(uuid.uuid4())
    assert await _first(tsession.get_tenant_db(_request(), current_user=user, db=db)) is db
    assert await _first(tsession.get_acting_tenant_db(_request(other), current_user=user, db=db)) is db
    assert await _first(tsession.get_control_db(db=db)) is db
    async with tsession.tenant_db_for(db, uuid.uuid4()) as same:
        assert same is db
    assert opened == []  # the header is not even read


async def test_split_mode_get_tenant_db_is_the_users_own_company(split, opened):
    user = SimpleNamespace(company_id=uuid.uuid4(), role="partner_admin")
    session = await _first(tsession.get_tenant_db(_request(str(uuid.uuid4())), current_user=user, db=object()))
    assert isinstance(session, _FakeSession)
    assert opened == [user.company_id]


async def test_split_mode_the_acting_company_is_a_visible_one(monkeypatch, split, opened):
    user = SimpleNamespace(company_id=uuid.uuid4(), role="partner_admin")
    tenant, stranger = uuid.uuid4(), uuid.uuid4()

    async def visible(db, u):
        return frozenset({u.company_id, tenant})

    monkeypatch.setattr(tsession, "visible_company_ids", visible)
    await _first(tsession.get_acting_tenant_db(_request(str(tenant)), current_user=user, db=object()))
    await _first(tsession.get_acting_tenant_db(_request(), current_user=user, db=object()))
    assert opened == [tenant, user.company_id]

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as refused:
        await _first(tsession.get_acting_tenant_db(_request(str(stranger)), current_user=user, db=object()))
    assert refused.value.status_code == 403
    with pytest.raises(HTTPException) as bad:
        await _first(tsession.get_acting_tenant_db(_request("not-a-uuid"), current_user=user, db=object()))
    assert bad.value.status_code == 400


async def test_split_mode_a_platform_admin_may_act_in_any_company(monkeypatch, split, opened):
    admin = SimpleNamespace(company_id=uuid.uuid4(), role="app_admin")

    async def visible(db, u):
        return None  # every company

    monkeypatch.setattr(tsession, "visible_company_ids", visible)
    anyone = uuid.uuid4()
    await _first(tsession.get_acting_tenant_db(_request(str(anyone)), current_user=admin, db=object()))
    assert opened == [anyone]


async def test_split_mode_the_company_variant_takes_the_user_from_the_pair(split, opened):
    user = SimpleNamespace(company_id=uuid.uuid4())
    await _first(tsession.get_tenant_db_with_company(_request(), current_user=(user, object()), db=object()))
    assert opened == [user.company_id]


async def test_split_mode_a_named_company_opens_its_database(split, opened):
    company = uuid.uuid4()
    async with tsession.tenant_db_for(object(), company) as session:
        assert isinstance(session, _FakeSession)
    assert opened == [company]


async def test_a_units_control_rows_get_their_own_session_only_from_a_tenant_session(monkeypatch):
    """WS2 2.6: a settlement started on a tenant session commits its control
    rows in a control session of its own; on any other session, that one."""
    from contextlib import asynccontextmanager

    controls = []

    def _control():
        @asynccontextmanager
        async def _open():
            controls.append("control")
            yield "control-db"
        return _open()

    monkeypatch.setattr(tsession, "control_session", _control)
    shared = SimpleNamespace(info={})
    async with tsession.control_db_for(shared) as session:
        assert session is shared
    tenant = SimpleNamespace(info={"company_id": uuid.uuid4(), "tenant_key": "devbeta001"})
    async with tsession.control_db_for(tenant) as session:
        assert session == "control-db"
    assert controls == ["control"]


# ── Migration runner ────────────────────────────────────────────────────────

def test_each_tree_has_one_head_and_a_tenant_s_version_is_the_tenant_tree_s():
    from src.common.tenancy import migrate

    from alembic.script import ScriptDirectory

    for tree, baseline in ((migrate.CONTROL_TREE, migrate.CONTROL_BASELINE),
                           (migrate.TENANT_TREE, migrate.TENANT_BASELINE)):
        script = ScriptDirectory.from_config(migrate.alembic_config(tree))
        assert len(script.get_heads()) == 1, tree
        assert script.get_base() == baseline                    # every revision builds on the cut's baseline
    assert migrate.tenant_schema_version() == migrate.tree_head(migrate.TENANT_TREE)


def test_the_old_chain_is_frozen_at_the_cut():
    """``migrations/legacy`` only brings a database to ``LEGACY_CUT``; a revision added there would be lost."""
    from src.common.tenancy import migrate

    assert migrate.tree_head(migrate.LEGACY_TREE) == migrate.LEGACY_CUT


def test_every_revision_id_fits_the_version_tables():
    """Alembic's version tables hold VARCHAR(32); adoption creates the tenant one itself."""
    from alembic.script import ScriptDirectory

    from src.common.tenancy import migrate

    for tree in (migrate.CONTROL_TREE, migrate.TENANT_TREE):
        script = ScriptDirectory.from_config(migrate.alembic_config(tree))
        assert [r.revision for r in script.walk_revisions() if len(r.revision) > 32] == []


def test_the_trees_have_their_own_directories_and_the_tenant_tree_its_own_version_table():
    from alembic.script import ScriptDirectory

    from migrations import envlib
    from src.common.tenancy import migrate

    control = ScriptDirectory.from_config(migrate.alembic_config(migrate.CONTROL_TREE))
    tenant = ScriptDirectory.from_config(migrate.alembic_config(migrate.TENANT_TREE))
    assert control.dir.replace("\\", "/").endswith("migrations/control")
    assert tenant.dir.replace("\\", "/").endswith("migrations/tenant_platform")
    assert envlib.TENANT_VERSION_TABLE == migrate.TENANT_VERSION_TABLE != "alembic_version"


def test_the_cortex_allow_list_names_only_what_the_tenant_baseline_creates():
    """Each object the comparison leaves alone is one the baseline makes (an entry for a gone one is stale)."""
    from pathlib import Path

    from migrations import envlib

    baseline = (Path(__file__).resolve().parents[2] / "migrations" / "tenant_platform" / "versions"
                / "tenant_platform_0001_baseline.py").read_text(encoding="utf-8")
    for name in envlib.CORTEX_DB_ONLY_INDEXES | envlib.CORTEX_DB_ONLY_FOREIGN_KEYS:
        assert f"'{name}'" in baseline, name


async def test_tenants_already_current_are_skipped_and_a_failed_batch_stops(monkeypatch):
    from src.common.tenancy import migrate

    monkeypatch.setattr(migrate, "tenant_schema_version", lambda: "tenant_platform_0002")
    locations = [_location(key=k) for k in ("aaaaa", "bbbbb", "ccccc", "ddddd", "eeeee")]
    locations[0] = dataclasses.replace(locations[0], schema_version="tenant_platform_0002")

    async def migratable(keys):
        return locations

    async def upgrade(location):
        if location.key == "ccccc":
            raise RuntimeError("boom")
        return "tenant_platform_0002"

    monkeypatch.setattr(migrate, "_migratable", migratable)
    monkeypatch.setattr(migrate, "upgrade_tenant", upgrade)
    result = await migrate.upgrade_tenants(parallel=2)
    assert result["skipped"] == ["aaaaa"]
    assert result["upgraded"] == ["bbbbb"]
    assert list(result["failed"]) == ["ccccc"]
    assert result["not_run"] == ["ddddd", "eeeee"]


# ── The business time zone moves to the directory (2.8) ─────────────────────

class _ZoneSession:
    """Answers the companies.timezone read."""

    def __init__(self, zone):
        self.zone, self.reads = zone, 0

    async def execute(self, statement):
        self.reads += 1
        return SimpleNamespace(scalar=lambda: self.zone)


async def test_split_mode_reads_the_zone_from_the_directory(monkeypatch, split):
    from src.common import timezones

    cid = uuid.uuid4()

    async def find(company_id):
        return dataclasses.replace(_location(company_id=cid), timezone="Europe/Berlin")

    monkeypatch.setattr(directory_mod.directory, "find", find)
    timezones.forget_company_timezone()
    db = _ZoneSession("Asia/Kolkata")
    assert await timezones.company_timezone_name(cid, db) == "Europe/Berlin"
    assert db.reads == 0
    timezones.forget_company_timezone()


async def test_split_mode_falls_back_to_the_company_without_a_row(monkeypatch, split):
    from src.common import timezones

    async def find(company_id):
        return None

    monkeypatch.setattr(directory_mod.directory, "find", find)
    timezones.forget_company_timezone()
    assert await timezones.company_timezone_name(uuid.uuid4(), _ZoneSession("America/Chicago")) == "America/Chicago"
    timezones.forget_company_timezone()


async def test_single_mode_never_reads_the_directory(monkeypatch, single):
    from src.common import timezones

    async def find(company_id):
        raise AssertionError("the directory is not read in single mode")

    monkeypatch.setattr(directory_mod.directory, "find", find)
    timezones.forget_company_timezone()
    assert await timezones.company_timezone_name(uuid.uuid4(), _ZoneSession("Europe/Paris")) == "Europe/Paris"
    timezones.forget_company_timezone()


# ── WS2 2.4, AI module: what the routes and services rely on ──────────────

async def test_the_directory_cache_keeps_a_bounded_number_of_rows():
    clock = _Clock()
    d = TenantDirectory(ttl_seconds=60, clock=clock, max_entries=2)

    async def read(company_id):
        return None

    d._read = read  # type: ignore[method-assign]
    ids = [uuid.uuid4() for _ in range(3)]
    for cid in ids:
        await d.find(cid)
    assert list(d._cache) == ids[1:]  # the oldest went


async def test_feature_flag_sql_names_the_control_plane():
    """So a tenant session (split mode) sends it to the control database."""
    from src.ai.core.feature_flags import FeatureFlags
    from src.ai.orm.feature_flags import FeatureFlag

    seen = []

    class _DB:
        async def execute(self, statement, params=None, **kwargs):
            seen.append(kwargs.get("bind_arguments"))
            return SimpleNamespace(first=lambda: None, rowcount=0)

    flags = FeatureFlags(_DB())
    await flags._db_lookup("some.flag", uuid.uuid4(), uuid.uuid4())
    await flags._db_lookup_value_json("some.flag", uuid.uuid4(), None)
    assert seen and all(b == {"mapper": FeatureFlag} for b in seen)


def test_a_public_file_url_names_its_company_only_in_split_mode(monkeypatch):
    from src.ai.artifact_router import public_file_url
    from src.common.config import settings

    artifact, company = uuid.uuid4(), uuid.uuid4()
    monkeypatch.setattr(settings, "TENANCY_MODE", "single")
    assert public_file_url(artifact, company) == f"/api/v1/files/{artifact}/public"
    monkeypatch.setattr(settings, "TENANCY_MODE", "split")
    assert public_file_url(artifact, company) == f"/api/v1/files/{artifact}/public?company={company}"
