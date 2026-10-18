"""The migration runner (Phase 14 WS2 2.1 skeleton; 2.7 and 2.10 complete it).

    python -m src.common.tenancy.migrate control
    python -m src.common.tenancy.migrate tenants [--tenant KEY ...] [--parallel N]

``control`` upgrades the control database (``alembic upgrade head``; today's
one tree, until 2.7 splits it into ``migrations/control`` and
``migrations/tenant_platform``).

``tenants`` upgrades the tenant databases, ``--parallel`` at a time (default
10), and stops after the first batch with a failure; a tenant already at the
target version is skipped, so running it again resumes. Each tenant's version
is recorded in ``tenant_directory.platform_schema_version``. Until the tenant
migration tree exists, a tenant database's ``platform`` schema is built from
the models (``bases.tenant_ddl_metadata()``): missing tables are created,
existing ones are not altered, and the version is a hash of that schema
(``models-<hash>``).
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import logging
import sys
from pathlib import Path
from typing import Any, Optional, Sequence

from sqlalchemy import text

logger = logging.getLogger(__name__)

BACKEND = Path(__file__).resolve().parents[3]
DEFAULT_PARALLEL = 10


def models_schema_version() -> str:
    """The version of the tenant schema the models describe: a hash of its DDL."""
    from sqlalchemy.dialects import postgresql
    from sqlalchemy.schema import CreateIndex, CreateTable

    from src.common.tenancy.bases import tenant_ddl_metadata

    dialect = postgresql.dialect()
    digest = hashlib.sha256()
    for table in sorted(tenant_ddl_metadata().tables.values(), key=lambda t: t.name):
        # One line per column or constraint; a table's constraints are a set,
        # so their order differs between processes — sort the lines.
        ddl = str(CreateTable(table).compile(dialect=dialect))
        digest.update("\n".join(sorted(line.strip().rstrip(",") for line in ddl.splitlines())).encode())
        for index in sorted(table.indexes, key=lambda i: str(i.name)):
            digest.update(str(CreateIndex(index).compile(dialect=dialect)).encode())
    return f"models-{digest.hexdigest()[:12]}"


def upgrade_control() -> None:
    from alembic import command
    from alembic.config import Config

    command.upgrade(Config(str(BACKEND / "alembic.ini")), "head")


async def build_platform_schema(engine: Any) -> None:
    """Create the ``platform`` schema and the tenant tables it lacks (``engine``: a tenant database)."""
    from src.common.tenancy.bases import TENANT_SCHEMA, tenant_ddl_metadata

    metadata = tenant_ddl_metadata()
    async with engine.begin() as conn:
        await conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {TENANT_SCHEMA}"))
        await conn.run_sync(metadata.create_all)


async def upgrade_tenant(location: Any) -> str:
    """Bring one tenant database to the current version; returns it."""
    from sqlalchemy import update

    from src.common.tenancy.directory import directory
    from src.common.tenancy.engines import create_tenant_engine, tenant_url
    from src.common.tenancy.models import TenantDirectoryEntry
    from src.common.tenancy.session import control_session

    version = models_schema_version()
    engine = create_tenant_engine(tenant_url(location))
    try:
        await build_platform_schema(engine)
    finally:
        await engine.dispose()
    async with control_session() as db:
        await db.execute(update(TenantDirectoryEntry)
                         .where(TenantDirectoryEntry.company_id == location.company_id)
                         .values(platform_schema_version=version))
        await db.commit()
    directory.invalidate(location.company_id)
    return version


async def _migratable(keys: Optional[Sequence[str]]) -> list[Any]:
    from sqlalchemy import select

    from src.common.tenancy.directory import TenantLocation
    from src.common.tenancy.models import DATABASE_READY_STATUSES, TenantDbServer, TenantDirectoryEntry
    from src.common.tenancy.session import control_session

    statuses = sorted(DATABASE_READY_STATUSES | {"db_created"})
    query = (select(TenantDirectoryEntry, TenantDbServer.host)
             .join(TenantDbServer, TenantDbServer.id == TenantDirectoryEntry.server_id)
             .where(TenantDirectoryEntry.status.in_(statuses))
             .order_by(TenantDirectoryEntry.tenant_key))
    if keys:
        query = query.where(TenantDirectoryEntry.tenant_key.in_(list(keys)))
    async with control_session() as db:
        rows = (await db.execute(query)).all()
    return [TenantLocation(company_id=e.company_id, key=e.tenant_key, server_host=host, db_name=e.db_name,
                           status=e.status, schema_version=e.platform_schema_version,
                           automation_state=e.automation_state, timezone=e.timezone)
            for e, host in rows]


async def upgrade_tenants(keys: Optional[Sequence[str]] = None,
                          parallel: int = DEFAULT_PARALLEL) -> dict[str, Any]:
    """Upgrade tenant databases in batches; ``{"upgraded", "skipped", "failed", "not_run"}``."""
    target = models_schema_version()
    locations = await _migratable(keys)
    result: dict[str, Any] = {"version": target, "upgraded": [], "skipped": [], "failed": {}, "not_run": []}
    pending = []
    for location in locations:
        (result["skipped"] if location.schema_version == target else pending).append(location)
    result["skipped"] = [loc.key for loc in result["skipped"]]
    batch_size = max(1, parallel)
    for start in range(0, len(pending), batch_size):
        batch = pending[start:start + batch_size]
        outcomes = await asyncio.gather(*(upgrade_tenant(loc) for loc in batch), return_exceptions=True)
        for location, outcome in zip(batch, outcomes):
            if isinstance(outcome, BaseException):
                logger.error("tenant %s: migration failed: %s", location.key, outcome)
                result["failed"][location.key] = f"{type(outcome).__name__}: {outcome}"
            else:
                result["upgraded"].append(location.key)
        if result["failed"]:
            result["not_run"] = [loc.key for loc in pending[start + batch_size:]]
            break
    return result


async def _run_tenants(keys: Optional[Sequence[str]], parallel: int) -> dict[str, Any]:
    from src.common import database
    from src.common.tenancy.engines import engines

    try:
        return await upgrade_tenants(keys, parallel)
    finally:
        await engines.dispose_all()
        await database.engine.dispose()


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m src.common.tenancy.migrate",
                                     description="Upgrade the control database or the tenant databases.")
    sub = parser.add_subparsers(dest="target", required=True)
    sub.add_parser("control", help="alembic upgrade head on the control database")
    tenants = sub.add_parser("tenants", help="upgrade every tenant database (or --tenant KEY)")
    tenants.add_argument("--tenant", action="append", dest="keys", metavar="KEY",
                         help="only this tenant key (repeatable)")
    tenants.add_argument("--parallel", type=int, default=DEFAULT_PARALLEL,
                         help=f"tenants upgraded at a time (default {DEFAULT_PARALLEL})")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    if args.target == "control":
        upgrade_control()
        return 0
    result = asyncio.run(_run_tenants(args.keys, args.parallel))
    print(f"target {result['version']}: upgraded {len(result['upgraded'])}, "
          f"already current {len(result['skipped'])}, failed {len(result['failed'])}, "
          f"not run {len(result['not_run'])}")
    for key, error in result["failed"].items():
        print(f"  {key}: {error}")
    return 1 if result["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
