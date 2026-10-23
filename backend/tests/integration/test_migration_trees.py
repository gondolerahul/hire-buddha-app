"""The two migration trees (Phase 14 WS2 2.7, 2.10; tech spec §5.4).

* A tenant database built by the tenant tree (schema ``platform``) holds what
  the shared database built by both trees holds of the tenant tables (in
  ``public``), and ``alembic check`` finds nothing between the models and
  either database, for either tree.
* A tenant database built from the models before the tree existed, with a row
  in it, is adopted: afterwards it is the tree's database, the row is still
  there and its version is the head. One that only losing data could bring to
  the baseline is refused and left as it was.
* A revision added to the tenant tree reaches every tenant: each directory row
  records it, a second run skips them all, and a tenant whose migration fails
  stops the run and is migrated by the next.

Each test makes and drops its own databases on the local server.
"""
from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import text

from tests.harness.infra import infra_unavailable

pytestmark = [pytest.mark.needs_db]

BACKEND = Path(__file__).resolve().parents[2]


def _base_url():
    from sqlalchemy.engine import make_url

    from src.common.config import settings

    return make_url(settings.CONTROL_DATABASE_URL)


def _dsn(url) -> str:
    return url.set(drivername="postgresql").render_as_string(hide_password=False)


@asynccontextmanager
async def scratch_database(prefix: str = "mt"):
    """An empty database on the local server (its SQLAlchemy URL), dropped afterwards."""
    import asyncpg

    base = _base_url()
    name = f"{prefix}_{uuid.uuid4().hex[:10]}"
    admin_dsn = _dsn(base.set(database="postgres"))
    try:
        conn = await asyncpg.connect(admin_dsn)
    except Exception as exc:  # noqa: BLE001
        infra_unavailable(f"Postgres unreachable ({exc})")
    try:
        await conn.execute(f'CREATE DATABASE "{name}"')
    finally:
        await conn.close()
    try:
        yield base.set(database=name)
    finally:
        conn = await asyncpg.connect(admin_dsn)
        try:
            await conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        finally:
            await conn.close()


def _run(args: list[str], url, **env: str) -> subprocess.CompletedProcess:
    full = {**os.environ, "CONTROL_DATABASE_URL": url.render_as_string(hide_password=False),
            "DATABASE_URL": url.render_as_string(hide_password=False), "PYTHONUTF8": "1", **env}
    done = subprocess.run([sys.executable, "-m", *args], cwd=BACKEND, env=full, capture_output=True,
                          text=True, timeout=600)
    assert done.returncode == 0, f"{' '.join(args)} failed:\n{done.stderr[-4000:]}"
    return done


async def _catalog(url, schema: str, tables=None) -> dict:
    import asyncpg

    from src.common.tenancy.schema_catalog import catalog

    conn = await asyncpg.connect(_dsn(url))
    try:
        return await catalog(conn, schema, tables)
    finally:
        await conn.close()


async def _tenant_database(url) -> None:
    """What the provisioner's ``db_created`` step makes: extensions, schema ``platform``, ``search_path``."""
    import asyncpg

    from src.common.tenancy.provisioner import EXTENSIONS

    conn = await asyncpg.connect(_dsn(url))
    try:
        for extension in EXTENSIONS:
            await conn.execute(f'CREATE EXTENSION IF NOT EXISTS "{extension}"')
        await conn.execute("CREATE SCHEMA IF NOT EXISTS platform")
        await conn.execute(f'ALTER DATABASE "{url.database}" SET search_path TO platform, public')
    finally:
        await conn.close()


async def _migrate_in_a_process(url) -> str:
    from src.common.tenancy.migrate import _run_tenant_process

    return await asyncio.to_thread(_run_tenant_process, url)


async def test_a_tree_built_tenant_database_is_the_shared_databases_tenant_half_and_matches_the_models():
    from src.common.tenancy.migrate import tenant_schema_version

    async with scratch_database() as shared, scratch_database() as tenant:
        _run(["src.common.tenancy.migrate", "control"], shared, TENANCY_MODE="single")
        await _tenant_database(tenant)
        assert await _migrate_in_a_process(tenant) == tenant_schema_version()

        from src.common.tenancy.schema_catalog import differences

        in_tenant = await _catalog(tenant, "platform")
        assert "kpi_daily_rollup" in in_tenant["views"] and len(in_tenant["tables"]) >= 39
        assert differences(await _catalog(shared, "public", in_tenant["tables"]), in_tenant) == []

        for args, url in ((["alembic", "check"], shared),
                          (["alembic", "-n", "tenant_platform", "-x", "schema=public", "check"], shared),
                          (["alembic", "-n", "tenant_platform", "-x", f"database={tenant.database}", "check"],
                           shared)):
            assert "No new upgrade operations detected" in _run(args, url).stdout


async def _model_built(url) -> uuid.UUID:
    """A tenant database as ``migrate.build_platform_schema`` made them before 2.7, with one agent in it."""
    from sqlalchemy.ext.asyncio import create_async_engine

    from src.common.tenancy.bases import tenant_ddl_metadata

    await _tenant_database(url)
    metadata = tenant_ddl_metadata()
    # Only what the models held at the cut: the tenant baseline's tables (later revisions add more).
    import re

    baseline = (BACKEND / "migrations" / "tenant_platform" / "versions" / "tenant_platform_0001_baseline.py")
    at_the_cut = set(re.findall(r"op\.create_table\('([a-z_]+)'", baseline.read_text(encoding="utf-8")))
    for table in [t for t in metadata.tables.values() if t.name not in at_the_cut]:
        metadata.remove(table)
    # ... and without the columns later revisions add to those tables.
    later = [p for p in baseline.parent.glob("tenant_platform_*.py") if p != baseline]
    added = {pair for p in later for pair in re.findall(r"op\.add_column\('([a-z_]+)', sa\.Column\('([a-z_]+)'",
                                                        p.read_text(encoding="utf-8"))}
    # ... and with the types they had then: a revision that changes a column's type
    # lists it in COLUMNS (table -> [(column, type before, nullable)]), e.g. tenant_platform_0005_amounts.
    import importlib.util

    from sqlalchemy.dialects import postgresql

    retyped = []
    for path in sorted(later):
        spec = importlib.util.spec_from_file_location(path.stem, path)
        revision = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(revision)
        for table, columns in getattr(revision, "COLUMNS", {}).items():
            retyped += [(table, column, before.compile(dialect=postgresql.dialect())) for column, before, _ in columns]
    agent_id = uuid.uuid4()
    engine = create_async_engine(url)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(metadata.create_all)
            for table, column in sorted(added):
                if table in at_the_cut:
                    await conn.exec_driver_sql(f'ALTER TABLE platform."{table}" DROP COLUMN IF EXISTS "{column}"')
            for table, column, before in retyped:
                if table in at_the_cut:
                    await conn.exec_driver_sql(f'ALTER TABLE platform."{table}" ALTER COLUMN "{column}" TYPE {before}')
            await conn.execute(metadata.tables["platform.hierarchical_entities"].insert().values(
                id=agent_id, company_id=uuid.uuid4(), type="AGENT", name="kept through adoption"))
    finally:
        await engine.dispose()
    return agent_id


async def test_a_tenant_database_built_from_the_models_is_adopted():
    import asyncpg

    from src.common.tenancy.migrate import BASELINE_SCHEMA, tenant_schema_version
    from src.common.tenancy.schema_catalog import differences

    async with scratch_database() as adopted, scratch_database() as fresh:
        agent_id = await _model_built(adopted)
        before = await _catalog(adopted, "platform")
        assert "kpi_daily_rollup" not in before["views"]

        assert await _migrate_in_a_process(adopted) == tenant_schema_version()
        await _tenant_database(fresh)
        await _migrate_in_a_process(fresh)
        assert differences(await _catalog(adopted, "platform"), await _catalog(fresh, "platform")) == []

        conn = await asyncpg.connect(_dsn(adopted))
        try:
            assert await conn.fetchval("SELECT name FROM platform.hierarchical_entities WHERE id = $1",
                                       agent_id) == "kept through adoption"
            assert await conn.fetchval("SELECT version_num FROM platform.alembic_version_tenant_platform") \
                == tenant_schema_version()
            assert await conn.fetchval("SELECT 1 FROM pg_namespace WHERE nspname = $1", BASELINE_SCHEMA) is None
        finally:
            await conn.close()
        assert await _migrate_in_a_process(adopted) == tenant_schema_version()  # nothing more to do


async def test_adoption_that_would_lose_data_is_refused_and_changes_nothing():
    import asyncpg

    from src.common.tenancy.migrate import TenantMigrationFailed

    async with scratch_database() as url:
        await _model_built(url)
        conn = await asyncpg.connect(_dsn(url))
        try:
            await conn.execute("ALTER TABLE platform.events ADD COLUMN kept_by_hand text")
        finally:
            await conn.close()
        before = await _catalog(url, "platform")
        with pytest.raises(TenantMigrationFailed, match="column events.kept_by_hand"):
            await _migrate_in_a_process(url)
        from src.common.tenancy.schema_catalog import differences

        assert differences(await _catalog(url, "platform"), before) == []
        conn = await asyncpg.connect(_dsn(url))
        try:
            assert await conn.fetchval("SELECT to_regclass('platform.alembic_version_tenant_platform')") is None
            assert await conn.fetchval("SELECT 1 FROM pg_namespace WHERE nspname = '_hb_baseline'") is None
        finally:
            await conn.close()


# ── A revision reaches every tenant ─────────────────────────────────────────

ADDED_REVISION = '''"""A column for the runner's test (not part of the tree)."""
import sqlalchemy as sa
from alembic import op

revision = "tenant_platform_9999_test"
down_revision = "{head}"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("records_settings", sa.Column("x_runner_test", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("records_settings", "x_runner_test")
'''


@pytest.fixture
def tree_with_a_revision(tmp_path, monkeypatch):
    """A copy of the tenant tree with one revision more; the runner (and its child processes) use it."""
    from src.common.tenancy import migrate

    tree = tmp_path / "tenant_platform"
    shutil.copytree(BACKEND / "migrations" / "tenant_platform", tree,
                    ignore=shutil.ignore_patterns("__pycache__"))
    migrate.tree_head.cache_clear()
    head = migrate.tree_head(migrate.TENANT_TREE)  # the real tree's head, before the copy is used
    (tree / "versions" / "tenant_platform_9999_test.py").write_text(ADDED_REVISION.replace("{head}", head),
                                                                    encoding="utf-8")
    migrate.tree_head.cache_clear()  # the copy's head from here on
    ini = (BACKEND / "alembic.ini").read_text(encoding="utf-8")
    ini = ini.replace("%(here)s/migrations/tenant_platform", tree.as_posix())
    ini = ini.replace("%(here)s/migrations", (BACKEND / "migrations").as_posix())
    (tmp_path / "alembic.ini").write_text(ini, encoding="utf-8")
    migrate.tree_head.cache_clear()
    def use_the_copy() -> None:
        monkeypatch.setenv("HB_ALEMBIC_INI", str(tmp_path / "alembic.ini"))
        migrate.tree_head.cache_clear()

    yield use_the_copy
    monkeypatch.delenv("HB_ALEMBIC_INI", raising=False)
    migrate.tree_head.cache_clear()


@pytest_asyncio.fixture
async def control(monkeypatch):
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    import src.common.orm_models  # noqa: F401
    from src.common import database
    from src.common.config import settings
    from src.common.tenancy.engines import engines

    engine = create_async_engine(settings.CONTROL_DATABASE_URL, poolclass=NullPool,
                                 json_serializer=database.json_serializer)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        await engine.dispose()
        infra_unavailable(f"Postgres unreachable ({exc})")
    monkeypatch.setattr(database, "AsyncSessionLocal", async_sessionmaker(engine, expire_on_commit=False))
    monkeypatch.setattr(database, "engine", engine)
    yield engine
    await engines.dispose_all()
    await engine.dispose()


async def test_a_revision_reaches_every_tenant_and_a_failed_run_resumes(control, tree_with_a_revision):
    import asyncpg

    from src.common.tenancy import migrate
    from src.common.tenancy.directory import directory
    from tests.harness.tenant_db import scratch_tenant

    async with scratch_tenant("runner-a") as a, scratch_tenant("runner-b") as b:
        assert a.location.schema_version == b.location.schema_version == migrate.tenant_schema_version()
        dsn_b = _dsn(_base_url().set(host=b.location.server_host, database=b.db_name))
        conn = await asyncpg.connect(dsn_b)
        try:  # b's migration will fail: the column is there already
            await conn.execute("ALTER TABLE platform.records_settings ADD COLUMN x_runner_test text")
        finally:
            await conn.close()

        tree_with_a_revision()
        keys = [a.key, b.key]
        first = await migrate.upgrade_tenants(keys, parallel=1)
        assert first["version"] == "tenant_platform_9999_test"
        assert list(first["failed"]) == [b.key] and "x_runner_test" in first["failed"][b.key]
        assert set(first["upgraded"]) | set(first["not_run"]) == {a.key}

        conn = await asyncpg.connect(dsn_b)
        try:
            await conn.execute("ALTER TABLE platform.records_settings DROP COLUMN x_runner_test")
        finally:
            await conn.close()
        second = await migrate.upgrade_tenants(keys, parallel=1)
        assert second["failed"] == {} and second["not_run"] == []
        assert set(second["upgraded"]) | set(second["skipped"]) == {a.key, b.key} and b.key in second["upgraded"]

        for tenant in (a, b):
            directory.invalidate(tenant.company_id)
            assert (await directory.get(tenant.company_id)).schema_version == "tenant_platform_9999_test"
            conn = await asyncpg.connect(_dsn(_base_url().set(host=tenant.location.server_host,
                                                               database=tenant.db_name)))
            try:
                assert await conn.fetchval("SELECT to_regclass('platform.records_settings')") is not None
                assert await conn.fetchval(
                    "SELECT 1 FROM information_schema.columns WHERE table_schema = 'platform' "
                    "AND table_name = 'records_settings' AND column_name = 'x_runner_test'") == 1
            finally:
                await conn.close()

        third = await migrate.upgrade_tenants(keys, parallel=2)
        assert third["upgraded"] == [] and sorted(third["skipped"]) == sorted(keys)
