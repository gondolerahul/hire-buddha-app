"""A throwaway business with its own database, for tests of what lives there
(WS4 records: ``business.*``, ``custom.*``, the Data API).

``scratch_tenant()`` makes a company, a database ``t_<key>`` on the local
server with the extensions and the ``platform`` schema's tables (as WS2's
``scripts.dev_tenants`` does), and an active tenant-directory row; afterwards
it drops the database, the directory row and the company. Local server only.
"""
from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any, AsyncIterator

EXTENSIONS = ("vector", "pgcrypto", "pg_trgm", "uuid-ossp")
SERVER_NAME = "local-dev"


def _dsn(url: Any, database: str) -> str:
    return url.set(drivername="postgresql", database=database).render_as_string(hide_password=False)


@asynccontextmanager
async def scratch_tenant(name: str = "records") -> AsyncIterator[SimpleNamespace]:
    import asyncpg
    from sqlalchemy import delete, select
    from sqlalchemy.engine import make_url

    from src.auth.models import Company
    from src.common.config import settings
    from src.common.tenancy.directory import directory, new_tenant_key, tenant_db_name
    from src.common.tenancy.engines import engines
    from src.common.tenancy.migrate import upgrade_tenant
    from src.common.tenancy.models import TenantDbServer, TenantDirectoryEntry
    from src.common.tenancy.session import control_session

    url = make_url(settings.CONTROL_DATABASE_URL)
    if (url.host or "localhost") not in ("localhost", "127.0.0.1", "::1", "db", "postgres"):
        raise RuntimeError("scratch tenants are made on a local server only")
    key = new_tenant_key()
    db_name = tenant_db_name(key)
    admin = await asyncpg.connect(_dsn(url, "postgres"))
    try:
        await admin.execute(f'CREATE DATABASE "{db_name}"')
    finally:
        await admin.close()
    conn = await asyncpg.connect(_dsn(url, db_name))
    try:
        for extension in EXTENSIONS:
            await conn.execute(f'CREATE EXTENSION IF NOT EXISTS "{extension}"')
        await conn.execute("CREATE SCHEMA IF NOT EXISTS platform")
        await conn.execute(f'ALTER DATABASE "{db_name}" SET search_path TO platform, public')
    finally:
        await conn.close()

    company_id = uuid.uuid4()
    async with control_session() as db:
        server = (await db.execute(select(TenantDbServer).where(TenantDbServer.name == SERVER_NAME))).scalar()
        if server is None:
            server = TenantDbServer(name=SERVER_NAME, host=url.host or "localhost", kind="pool", region="local",
                                    capacity=40, status="active")
            db.add(server)
            await db.flush()
        db.add(Company(id=company_id, name=f"{name}-{key}", type="TENANT", status="active"))
        await db.flush()
        db.add(TenantDirectoryEntry(company_id=company_id, tenant_key=key, slug=f"{name}-{key}", server_id=server.id,
                                    db_name=db_name, status="active", timezone="Asia/Kolkata"))
        await db.commit()
    directory.invalidate(company_id)
    try:
        location = await directory.get(company_id)
        await upgrade_tenant(location)
        directory.invalidate(company_id)
        yield SimpleNamespace(company_id=company_id, key=key, db_name=db_name,
                              location=await directory.get(company_id))
    finally:
        directory.invalidate(company_id)
        await engines.dispose_all()
        admin = await asyncpg.connect(_dsn(url, "postgres"))
        try:
            await admin.execute(f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE)')
        finally:
            await admin.close()
        from tests.harness.purge import purge_companies

        async with control_session() as db:  # first on its own: no sweep may find a dropped database
            await db.execute(delete(TenantDirectoryEntry).where(TenantDirectoryEntry.company_id == company_id))
            await db.commit()
        async with control_session() as db:  # with whatever the test left for the company (users, wallets)
            await purge_companies(await db.connection(), [company_id])
            await db.commit()
