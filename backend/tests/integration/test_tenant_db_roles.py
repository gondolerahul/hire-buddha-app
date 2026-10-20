"""Who may do what in a tenant database (Phase 14 M2, ``tenancy/db_roles.py``).

On a real PostgreSQL server: the provisioner's server-wide roles, a secured
tenant database, a table made as the DDL role — owned by it, usable by the
runtime principals through default privileges, unreachable for anyone else —
and the tenant's own Data API sign-in. Everything here has unique names and is
dropped at the end; ``hb_runtime`` / ``hb_dataapi`` only if this test made them.
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text

from tests.harness.infra import infra_unavailable

pytestmark = [pytest.mark.needs_db]


def _engine(database: str):
    from sqlalchemy.engine import make_url
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool

    from src.common.config import settings

    url = make_url(settings.CONTROL_DATABASE_URL).set(database=database)
    return create_async_engine(url, poolclass=NullPool, isolation_level="AUTOCOMMIT")


@pytest_asyncio.fixture
async def names(monkeypatch):
    from src.common.config import settings

    sfx = uuid.uuid4().hex[:8]
    n = {"ddl": f"hbt_ddl_{sfx}", "api": f"hbt_api_{sfx}", "worker": f"hbt_wrk_{sfx}",
         "migrator": f"hbt_mig_{sfx}", "tenant": f"hbt_t_{sfx}", "other": f"hbt_other_{sfx}",
         "db": f"t_hbt{sfx}"}
    monkeypatch.setattr(settings, "TENANT_DB_DDL_ROLE", n["ddl"])
    monkeypatch.setattr(settings, "TENANT_DB_RUNTIME_PRINCIPALS", f"{n['api']}, {n['worker']}")
    monkeypatch.setattr(settings, "TENANT_DB_MIGRATOR_PRINCIPAL", n["migrator"])
    admin = _engine("postgres")
    try:
        async with admin.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        await admin.dispose()
        infra_unavailable(f"Postgres unreachable; tenant database roles skipped ({exc})")
    async with admin.connect() as conn:
        pre = set((await conn.execute(text(
            "SELECT rolname FROM pg_roles WHERE rolname IN ('hb_runtime', 'hb_dataapi')"))).scalars())
    yield n
    async with admin.connect() as conn:
        await conn.execute(text(f'DROP DATABASE IF EXISTS "{n["db"]}" WITH (FORCE)'))
        for role in [n[k] for k in ("tenant", "other", "api", "worker", "migrator", "ddl")] + \
                [r for r in ("hb_runtime", "hb_dataapi") if r not in pre]:
            if (await conn.execute(text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": role})).first():
                await conn.execute(text(f'DROP OWNED BY "{role}"'))
                await conn.execute(text(f'DROP ROLE "{role}"'))
    await admin.dispose()


async def _true(conn, sql, **params) -> bool:
    return bool((await conn.execute(text(sql), params)).scalar())


async def test_a_secured_tenant_database_belongs_to_the_ddl_role_and_serves_the_runtime(names):
    from src.common.tenancy import db_roles
    from src.common.tenancy.engines import create_tenant_engine

    admin = _engine("postgres")
    try:
        async with admin.connect() as conn:
            first = await db_roles.ensure_server_roles(conn)
            again = await db_roles.ensure_server_roles(conn)
            await conn.execute(text(f'CREATE DATABASE "{names["db"]}"'))
            await conn.execute(text(f'CREATE ROLE "{names["other"]}" LOGIN'))
    finally:
        await admin.dispose()
    assert {names["ddl"], names["api"], names["worker"], names["migrator"]} <= set(first["made"])
    assert again["made"] == []  # safe to repeat

    database = _engine(names["db"])
    try:
        async with database.connect() as conn:
            access = await db_roles.secure_database(conn, names["db"])
            grant = await db_roles.grant_tenant_principal(conn, names["db"], names["tenant"], None)
    finally:
        await database.dispose()
    assert access["owner"] == names["ddl"] and grant["made"] is True

    # DDL as the role (what the provisioner's and the migrator's connections do).
    from sqlalchemy.engine import make_url

    from src.common.config import settings
    ddl = create_tenant_engine(make_url(settings.CONTROL_DATABASE_URL).set(database=names["db"]),
                               role=names["ddl"])
    try:
        async with ddl.begin() as conn:
            assert (await conn.execute(text("SELECT current_user"))).scalar() == names["ddl"]
            await conn.execute(text("CREATE TABLE platform.widgets (id serial PRIMARY KEY, name text)"))
    finally:
        await ddl.dispose()

    database = _engine(names["db"])
    try:
        async with database.connect() as conn:
            owner = (await conn.execute(text(
                "SELECT tableowner FROM pg_tables WHERE schemaname = 'platform' AND tablename = 'widgets'"))).scalar()
            assert owner == names["ddl"]
            for runtime in (names["api"], names["worker"]):
                assert await _true(conn, "SELECT has_database_privilege(:r, :d, 'CONNECT')", r=runtime, d=names["db"])
                assert await _true(conn, "SELECT has_table_privilege(:r, 'platform.widgets', "
                                         "'SELECT, INSERT, UPDATE, DELETE')", r=runtime)
                assert await _true(conn, "SELECT has_sequence_privilege(:r, 'platform.widgets_id_seq', 'USAGE')",
                                   r=runtime)
                assert not await _true(conn, "SELECT has_table_privilege(:r, 'platform.widgets', 'TRUNCATE') "
                                             "AND has_schema_privilege(:r, 'platform', 'CREATE')", r=runtime)
            # The migrator acts as the DDL role; nobody else gets in.
            assert await _true(conn, "SELECT pg_has_role(:m, :ddl, 'MEMBER')", m=names["migrator"], ddl=names["ddl"])
            assert not await _true(conn, "SELECT has_database_privilege(:o, :d, 'CONNECT')",
                                   o=names["other"], d=names["db"])
            assert not await _true(conn, "SELECT has_table_privilege(:o, 'platform.widgets', 'SELECT')",
                                   o=names["other"])
            # The tenant's own sign-in: hb_dataapi, this database.
            assert await _true(conn, "SELECT pg_has_role(:t, 'hb_dataapi', 'MEMBER')", t=names["tenant"])
            assert await _true(conn, "SELECT has_database_privilege(:t, :d, 'CONNECT')",
                               t=names["tenant"], d=names["db"])
    finally:
        await database.dispose()


async def test_without_a_ddl_role_nothing_changes(monkeypatch):
    from src.common.config import settings
    from src.common.tenancy import db_roles

    monkeypatch.setattr(settings, "TENANT_DB_DDL_ROLE", "")
    assert "skipped" in await db_roles.ensure_server_roles(None)
    assert "skipped" in await db_roles.secure_database(None, "t_x")
