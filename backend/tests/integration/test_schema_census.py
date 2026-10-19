"""A database built by the migration trees matches the ORM (DM-20, DM-I9, DM-21; Phase 14 WS2 2.7).

Builds a scratch shared database the way a fresh single-mode deploy does —
``python -m src.common.tenancy.migrate control``: the control tree, then the
tenant tree in ``public`` — and compares it with every table the ORM declares
(``src.common.orm_models``): tables, columns, column types, declared indexes and
unique constraints.
Before DM-21 the chain stopped at ``m0b1e0d1a100`` (asyncpg rejected its
multi-statement SQL), and past it the database lacked ``subscription_tiers``,
``phone_numbers`` and eleven columns that had only been created by hand.

Marked ``slow``. Nullability is not compared: four CORTEX columns differ
harmlessly (``migrations/envlib.py``); ``alembic check`` in
``test_migration_trees.py`` compares everything else, both ways.
"""
from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from tests.harness.infra import infra_unavailable

pytestmark = [pytest.mark.needs_db, pytest.mark.slow]

BACKEND = Path(__file__).resolve().parents[2]

# Tables the database may hold without an ORM model, and why.
DB_ONLY_TABLES: dict[str, str] = {
    "alembic_version": "Alembic's own bookkeeping (the control tree)",
    "alembic_version_tenant_platform": "Alembic's own bookkeeping (the tenant tree, in public in single mode)",
}
# Columns the database may hold without an ORM attribute, and why.
DB_ONLY_COLUMNS: dict[tuple[str, str], str] = {}
# Type names that are the same Postgres type.
_SAME_TYPE = {"FLOAT": "DOUBLE PRECISION"}


def _type_name(sa_type, dialect) -> str:
    name = sa_type.compile(dialect=dialect).split("(")[0].strip()
    return _SAME_TYPE.get(name, name)


def _foreign_keys(insp, table: str) -> set[tuple]:
    """``(column, referred table, ON DELETE)`` of each single-column foreign key."""
    return {(fk["constrained_columns"][0], fk["referred_table"], (fk.get("options") or {}).get("ondelete"))
            for fk in insp.get_foreign_keys(table) if len(fk["constrained_columns"]) == 1}


def _run(url: str, *args: str) -> None:
    env = {**os.environ, "CONTROL_DATABASE_URL": url, "DATABASE_URL": url, "TENANCY_MODE": "single",
           "PYTHONUTF8": "1", "OTEL_SDK_DISABLED": "true"}
    result = subprocess.run([sys.executable, "-m", *args], cwd=BACKEND, env=env,
                            capture_output=True, text=True, timeout=600)
    assert result.returncode == 0, f"{' '.join(args)} failed:\n{result.stderr[-4000:]}"


def _alembic(url: str, *args: str) -> None:
    _run(url, "alembic", *args)


@pytest.fixture(scope="module")
def fresh_database_url():
    from sqlalchemy.engine import make_url

    from src.common.config import settings

    base = make_url(settings.DATABASE_URL)
    name = f"census_{uuid.uuid4().hex[:10]}"
    admin_dsn = base.set(drivername="postgresql", database="postgres").render_as_string(hide_password=False)

    import asyncio

    import asyncpg

    async def admin(sql: str) -> None:
        conn = await asyncpg.connect(admin_dsn)
        try:
            await conn.execute(sql)
        finally:
            await conn.close()

    try:
        asyncio.run(admin(f'CREATE DATABASE "{name}"'))
    except Exception as exc:  # noqa: BLE001
        infra_unavailable(f"cannot create a scratch database: {exc}")
    url = base.set(database=name).render_as_string(hide_password=False)
    try:
        _run(url, "src.common.tenancy.migrate", "control")
        yield url
    finally:
        asyncio.run(admin(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))


@pytest.fixture(scope="module")
def census(fresh_database_url):
    """(ORM tables by name, a snapshot of the live schema)."""
    import asyncio

    from sqlalchemy import inspect
    from sqlalchemy.ext.asyncio import create_async_engine

    from src.common.orm_models import import_all_models

    orm = {t.name: t for metadata in import_all_models() for t in metadata.sorted_tables}

    def snapshot(conn):
        insp = inspect(conn)
        tables = {}
        for name in insp.get_table_names():
            indexed = {tuple(i["column_names"]) for i in insp.get_indexes(name)}
            indexed |= {tuple(u["column_names"]) for u in insp.get_unique_constraints(name)}
            unique = {tuple(u["column_names"]) for u in insp.get_unique_constraints(name)}
            unique |= {tuple(i["column_names"]) for i in insp.get_indexes(name) if i["unique"]}
            tables[name] = {
                "columns": {c["name"]: _type_name(c["type"], conn.dialect) for c in insp.get_columns(name)},
                "indexed": indexed,
                "unique": unique,
                "foreign_keys": _foreign_keys(insp, name),
            }
        return tables, conn.dialect

    async def run():
        engine = create_async_engine(fresh_database_url)
        try:
            async with engine.connect() as conn:
                return await conn.run_sync(snapshot)
        finally:
            await engine.dispose()

    live, dialect = asyncio.run(run())
    return orm, live, dialect


def test_every_orm_table_is_created_by_a_migration(census):
    orm, live, _ = census
    assert sorted(set(orm) - set(live)) == []


def test_every_database_table_has_a_model_or_a_reason(census):
    orm, live, _ = census
    assert sorted(set(live) - set(orm) - set(DB_ONLY_TABLES)) == []


def test_every_orm_column_exists_with_its_type(census):
    orm, live, dialect = census
    problems = []
    for name, table in orm.items():
        columns = live.get(name, {}).get("columns", {})
        for column in table.columns:
            if column.name not in columns:
                problems.append(f"{name}.{column.name}: missing")
            elif columns[column.name] != _type_name(column.type, dialect):
                problems.append(f"{name}.{column.name}: ORM {_type_name(column.type, dialect)}, "
                                f"database {columns[column.name]}")
    assert problems == []


def test_every_database_column_is_mapped_or_has_a_reason(census):
    orm, live, _ = census
    extra = [
        f"{name}.{column}"
        for name, table in orm.items()
        for column in live.get(name, {}).get("columns", {})
        if column not in table.columns and (name, column) not in DB_ONLY_COLUMNS
    ]
    assert extra == []


def test_every_declared_index_exists(census):
    orm, live, _ = census
    missing = [
        f"{name}: {index.name} {tuple(c.name for c in index.columns)}"
        for name, table in orm.items()
        for index in table.indexes
        if index.columns and tuple(c.name for c in index.columns) not in live.get(name, {}).get("indexed", set())
    ]
    assert missing == []


def test_every_declared_unique_constraint_exists(census):
    from sqlalchemy import UniqueConstraint

    orm, live, _ = census
    missing = [
        f"{name}: {constraint.name} {tuple(c.name for c in constraint.columns)}"
        for name, table in orm.items()
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
        and tuple(c.name for c in constraint.columns) not in live.get(name, {}).get("unique", set())
    ]
    assert missing == []


def test_the_reasons_are_not_stale(census):
    """An allow-list entry whose table or column is gone must be removed."""
    _, live, _ = census
    assert [t for t in DB_ONLY_TABLES if not t.startswith("alembic_version") and t not in live] == []
    assert [c for c in DB_ONLY_COLUMNS if c[1] not in live.get(c[0], {}).get("columns", {})] == []


def test_no_foreign_key_crosses_the_planes(census):
    """Phase 14 WS2 2.3: a key between a control and a tenant table could not
    exist once the tenant's tables are in a database of their own."""
    from src.common.tenancy.bases import plane_of

    orm, live, _ = census
    crossing = sorted(
        f"{name}.{column} -> {referred}"
        for name, table in orm.items()
        for column, referred, _ in live.get(name, {}).get("foreign_keys", set())
        if referred in orm and plane_of(orm[referred]) != plane_of(table)
    )
    assert crossing == []


# ── The old chain (``alembic -n legacy``), squashed into the trees at ``p14_run_settlement`` ──

@pytest.fixture(scope="module")
def legacy_database_url(fresh_database_url):
    """A scratch database built by the old chain (``migrations/legacy``, ~50 s)."""
    import asyncio

    import asyncpg
    from sqlalchemy.engine import make_url

    base = make_url(fresh_database_url)
    name = f"census_old_{uuid.uuid4().hex[:8]}"
    admin_dsn = base.set(drivername="postgresql", database="postgres").render_as_string(hide_password=False)

    async def admin(sql: str) -> None:
        conn = await asyncpg.connect(admin_dsn)
        try:
            await conn.execute(sql)
        finally:
            await conn.close()

    asyncio.run(admin(f'CREATE DATABASE "{name}"'))
    url = base.set(database=name).render_as_string(hide_password=False)
    try:
        _alembic(url, "-n", "legacy", "upgrade", "head")
        yield url
    finally:
        asyncio.run(admin(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))


def _catalog(url: str, schema: str = "public") -> dict:
    import asyncio

    import asyncpg
    from sqlalchemy.engine import make_url

    from src.common.tenancy.schema_catalog import catalog

    async def read():
        conn = await asyncpg.connect(make_url(url).set(drivername="postgresql").render_as_string(hide_password=False))
        try:
            return await catalog(conn, schema)
        finally:
            await conn.close()

    return asyncio.run(read())


def test_the_trees_build_what_the_old_chain_built(baseline_database_url, legacy_database_url):
    """Every column, default, constraint, index, enum type and the view, as Postgres prints them:
    the baselines (the trees as they started) equal the old chain at the cut."""
    from src.common.tenancy.schema_catalog import differences

    assert differences(_catalog(legacy_database_url), _catalog(baseline_database_url)) == []


@pytest.fixture(scope="module")
def baseline_database_url(fresh_database_url):
    """A database with both trees at their baselines only (``public``, as the shared database)."""
    import asyncio

    import asyncpg
    from sqlalchemy.engine import make_url

    base = make_url(fresh_database_url)
    name = f"census_base_{uuid.uuid4().hex[:8]}"
    admin_dsn = base.set(drivername="postgresql", database="postgres").render_as_string(hide_password=False)

    async def admin(sql: str) -> None:
        conn = await asyncpg.connect(admin_dsn)
        try:
            await conn.execute(sql)
        finally:
            await conn.close()

    asyncio.run(admin(f'CREATE DATABASE "{name}"'))
    url = base.set(database=name).render_as_string(hide_password=False)
    try:
        from src.common.tenancy.migrate import CONTROL_BASELINE, TENANT_BASELINE

        _alembic(url, "upgrade", CONTROL_BASELINE)
        _alembic(url, "-n", "tenant_platform", "-x", "schema=public", "upgrade", TENANT_BASELINE)
        yield url
    finally:
        asyncio.run(admin(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))


def test_the_cross_plane_keys_come_back_on_downgrade_and_go_again(legacy_database_url):
    """``p14_drop_cross_plane_fks`` restores each key the models now record as a
    reference (``bases.refers_to()``), with its ON DELETE action, and drops them
    again. The database ends at the old chain's head again."""
    import asyncio

    from sqlalchemy import inspect
    from sqlalchemy.ext.asyncio import create_async_engine

    from src.common.tenancy.bases import cross_plane_references

    def live_keys() -> set[tuple]:
        def read(conn):
            insp = inspect(conn)
            return {(name, *fk) for name in insp.get_table_names() for fk in _foreign_keys(insp, name)}

        async def run():
            engine = create_async_engine(legacy_database_url)
            try:
                async with engine.connect() as conn:
                    return await conn.run_sync(read)
            finally:
                await engine.dispose()

        return asyncio.run(run())

    references = {(r.table, r.column, r.referred_table, r.ondelete) for r in cross_plane_references()}
    assert len(references) == 38
    _alembic(legacy_database_url, "-n", "legacy", "downgrade", "p14_tenant_directory")
    try:
        assert references <= live_keys()
    finally:
        _alembic(legacy_database_url, "-n", "legacy", "upgrade", "head")
    assert references & live_keys() == set()


def _versions(url: str) -> tuple:
    import asyncio

    import asyncpg
    from sqlalchemy.engine import make_url

    async def read():
        conn = await asyncpg.connect(make_url(url).set(drivername="postgresql").render_as_string(hide_password=False))
        try:
            tenant = await conn.fetchval("SELECT to_regclass('alembic_version_tenant_platform')")
            return (await conn.fetchval("SELECT version_num FROM alembic_version"),
                    await conn.fetchval("SELECT version_num FROM alembic_version_tenant_platform") if tenant else None,
                    await conn.fetchval("SELECT 1 FROM pg_namespace WHERE nspname = '_hb_baseline'"))
        finally:
            await conn.close()

    return asyncio.run(read())


def _sql(url: str, statement: str) -> None:
    import asyncio

    import asyncpg
    from sqlalchemy.engine import make_url

    async def run():
        conn = await asyncpg.connect(make_url(url).set(drivername="postgresql").render_as_string(hide_password=False))
        try:
            await conn.execute(statement)
        finally:
            await conn.close()

    asyncio.run(run())


def test_an_old_chain_database_is_brought_to_the_cut_and_stamped(fresh_database_url, legacy_database_url):
    """``migrate control`` on a database two revisions short of the cut: the old chain brings it there,
    it must equal what the trees build — one changed by hand is refused, at the cut, unstamped — and
    it is stamped onto the baselines without anything else changing. Last in the module: the old
    chain's database is on the trees after it."""
    from src.common.tenancy.migrate import CONTROL_TREE, LEGACY_CUT, TENANT_TREE, tree_head
    from src.common.tenancy.schema_catalog import differences

    heads = (tree_head(CONTROL_TREE), tree_head(TENANT_TREE), None)  # stamped at the cut, then upgraded

    env = {**os.environ, "CONTROL_DATABASE_URL": legacy_database_url, "DATABASE_URL": legacy_database_url,
           "TENANCY_MODE": "single", "PYTHONUTF8": "1"}
    _alembic(legacy_database_url, "-n", "legacy", "downgrade", "-2")
    _sql(legacy_database_url, "ALTER TABLE companies ADD COLUMN kept_by_hand text")
    refused = subprocess.run([sys.executable, "-m", "src.common.tenancy.migrate", "control"], cwd=BACKEND,
                             env=env, capture_output=True, text=True, timeout=600)
    assert refused.returncode != 0 and "kept_by_hand" in refused.stderr, refused.stderr[-2000:]
    assert _versions(legacy_database_url) == (LEGACY_CUT, None, None)  # brought to the cut, not stamped

    _sql(legacy_database_url, "ALTER TABLE companies DROP COLUMN kept_by_hand")
    _alembic(legacy_database_url, "-n", "legacy", "downgrade", "-2")
    _run(legacy_database_url, "src.common.tenancy.migrate", "control")
    assert _versions(legacy_database_url) == heads
    assert differences(_catalog(legacy_database_url), _catalog(fresh_database_url)) == []
    _run(legacy_database_url, "src.common.tenancy.migrate", "control")  # on the trees: nothing more to do
    assert _versions(legacy_database_url) == heads
