"""Two dev tenants with databases of their own (Phase 14 WS2, tech spec §5.5).

    python -m scripts.dev_tenants            # create what is missing
    python -m scripts.dev_tenants --reset    # drop and recreate the two databases

On the local PostgreSQL server of ``CONTROL_DATABASE_URL`` (refused for any
other host) it makes, idempotently:

* databases ``t_devacme01`` and ``t_devbeta001``: the extensions the tables
  use, schema ``platform`` at the tenant tree's head (``migrate.upgrade_tenant``;
  a database built from the models before the tree is adopted),
  ``search_path`` = ``platform, public``;
* in the control database: companies "Dev Acme" and "Dev Beta" (fixed ids),
  the server row ``local-dev`` and an ``active`` directory row for each.

With ``TENANCY_MODE=split`` the app then opens these databases for those two
companies; with ``single`` nothing reads them.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from dataclasses import dataclass
from typing import Any, Optional, Sequence

LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "db", "postgres", "host.docker.internal"})
SERVER_NAME = "local-dev"
EXTENSIONS = ("vector", "pgcrypto", "pg_trgm", "uuid-ossp")
_NAMESPACE = uuid.UUID("5b0e6d2a-6a43-4f3e-9d1e-2f1c3a7b9e10")


@dataclass(frozen=True)
class DevTenant:
    key: str
    name: str
    slug: str

    @property
    def company_id(self) -> uuid.UUID:
        return uuid.uuid5(_NAMESPACE, self.key)

    @property
    def db_name(self) -> str:
        from src.common.tenancy.directory import tenant_db_name

        return tenant_db_name(self.key)


DEV_TENANTS = (DevTenant("devacme01", "Dev Acme", "dev-acme"),
               DevTenant("devbeta001", "Dev Beta", "dev-beta"))


def _control_url() -> Any:
    from sqlalchemy.engine import make_url

    from src.common.config import settings

    url = make_url(settings.CONTROL_DATABASE_URL)
    if (url.host or "localhost") not in LOCAL_HOSTS:
        raise SystemExit(f"dev_tenants only runs against a local server, not {url.host!r}")
    return url


def _asyncpg_dsn(url: Any, database: str) -> str:
    return url.set(drivername="postgresql", database=database).render_as_string(hide_password=False)


async def _create_databases(url: Any, reset: bool) -> None:
    import asyncpg

    admin = await asyncpg.connect(_asyncpg_dsn(url, "postgres"))
    try:
        for tenant in DEV_TENANTS:
            if reset:
                await admin.execute(f'DROP DATABASE IF EXISTS "{tenant.db_name}" WITH (FORCE)')
            exists = await admin.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", tenant.db_name)
            if not exists:
                await admin.execute(f'CREATE DATABASE "{tenant.db_name}"')
    finally:
        await admin.close()
    for tenant in DEV_TENANTS:
        conn = await asyncpg.connect(_asyncpg_dsn(url, tenant.db_name))
        try:
            for extension in EXTENSIONS:
                await conn.execute(f'CREATE EXTENSION IF NOT EXISTS "{extension}"')
            await conn.execute("CREATE SCHEMA IF NOT EXISTS platform")
            await conn.execute(f'ALTER DATABASE "{tenant.db_name}" SET search_path TO platform, public')
        finally:
            await conn.close()


async def _register(url: Any) -> uuid.UUID:
    """Companies, the server row and the directory rows, in the control database."""
    from sqlalchemy import select

    from src.auth.models import Company
    from src.common.orm_models import import_all_models
    from src.common.tenancy.models import TenantDbServer, TenantDirectoryEntry
    from src.common.tenancy.session import control_session

    import_all_models()  # every mapper, so companies → currencies resolves

    async with control_session() as db:
        server = (await db.execute(select(TenantDbServer).where(TenantDbServer.name == SERVER_NAME))).scalar()
        if server is None:
            server = TenantDbServer(name=SERVER_NAME, host=url.host or "localhost", kind="pool",
                                    region="local", capacity=40, status="active")
            db.add(server)
        server.host = url.host or "localhost"
        await db.flush()
        for tenant in DEV_TENANTS:
            company = await db.get(Company, tenant.company_id)
            if company is None:
                company = Company(id=tenant.company_id, name=tenant.name, type="TENANT", status="active")
                db.add(company)
                await db.flush()
            entry = await db.get(TenantDirectoryEntry, tenant.company_id)
            if entry is None:
                entry = TenantDirectoryEntry(company_id=tenant.company_id, tenant_key=tenant.key,
                                             slug=tenant.slug, server_id=server.id, db_name=tenant.db_name,
                                             status="active", timezone=company.timezone or "Asia/Kolkata")
                db.add(entry)
            entry.server_id, entry.db_name, entry.status = server.id, tenant.db_name, "active"
        await db.commit()
        return server.id


async def ensure_dev_tenants(reset: bool = False) -> list[Any]:
    """Make the two dev tenants (idempotent); returns their ``TenantLocation``s."""
    from src.common.tenancy.directory import directory
    from src.common.tenancy.migrate import upgrade_tenant

    url = _control_url()
    await _create_databases(url, reset)
    await _register(url)
    locations = []
    for tenant in DEV_TENANTS:
        directory.invalidate(tenant.company_id)
        location = await directory.get(tenant.company_id)
        await upgrade_tenant(location)  # the platform schema's tables
        directory.invalidate(tenant.company_id)
        locations.append(await directory.get(tenant.company_id))
    return locations


async def _main(reset: bool) -> list[Any]:
    from src.common import database
    from src.common.tenancy.engines import engines

    try:
        return await ensure_dev_tenants(reset)
    finally:
        await engines.dispose_all()
        await database.engine.dispose()


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m scripts.dev_tenants", description=__doc__.split("\n")[0])
    parser.add_argument("--reset", action="store_true", help="drop and recreate the two tenant databases")
    args = parser.parse_args(argv)
    for location in asyncio.run(_main(args.reset)):
        print(f"{location.key}: company {location.company_id}, database {location.db_name} on "
              f"{location.server_host}, {location.status}, schema {location.schema_version}")
    print("Set TENANCY_MODE=split to use them.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
