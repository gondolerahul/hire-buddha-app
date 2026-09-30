"""A database built by ``alembic upgrade head`` matches the ORM (DM-20, DM-I9, DM-21).

Builds a scratch database from the migration chain alone — the way a fresh
deploy does — and compares it with every table the ORM declares
(``src.common.orm_models``): tables, columns, column types, declared indexes and
unique constraints.
Before DM-21 the chain stopped at ``m0b1e0d1a100`` (asyncpg rejected its
multi-statement SQL), and past it the database lacked ``subscription_tiers``,
``phone_numbers`` and eleven columns that had only been created by hand.

Slow (the whole chain runs, ~30 s), so it is marked ``slow``. Nullability is not
compared: six columns differ harmlessly (see ``03-data-model.md`` §17).
"""
from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

pytestmark = [pytest.mark.needs_db, pytest.mark.slow]

BACKEND = Path(__file__).resolve().parents[2]

# Tables the database may hold without an ORM model, and why.
DB_ONLY_TABLES: dict[str, str] = {
    "alembic_version": "Alembic's own bookkeeping",
    "feature_flags": "DM-03 — read with raw SQL, no model yet",
}
# Columns the database may hold without an ORM attribute, and why.
DB_ONLY_COLUMNS: dict[tuple[str, str], str] = {}
# Type names that are the same Postgres type.
_SAME_TYPE = {"FLOAT": "DOUBLE PRECISION"}


def _type_name(sa_type, dialect) -> str:
    name = sa_type.compile(dialect=dialect).split("(")[0].strip()
    return _SAME_TYPE.get(name, name)


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
        pytest.skip(f"cannot create a scratch database: {exc}")
    url = base.set(database=name).render_as_string(hide_password=False)
    try:
        env = {**os.environ, "DATABASE_URL": url, "PYTHONUTF8": "1", "OTEL_SDK_DISABLED": "true"}
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=BACKEND, env=env, capture_output=True, text=True, timeout=600,
        )
        assert result.returncode == 0, f"alembic upgrade head failed:\n{result.stderr[-4000:]}"
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
    assert [t for t in DB_ONLY_TABLES if t != "alembic_version" and t not in live] == []
    assert [c for c in DB_ONLY_COLUMNS if c[1] not in live.get(c[0], {}).get("columns", {})] == []
