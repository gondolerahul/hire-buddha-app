"""One engine per tenant database (Phase 14 WS2 2.1, tech spec §5.3).

Shared workers serve every tenant (TD-01), so a process opens the databases
of the tenants it is working for: one small pool each (``POOL_SIZE`` +
``MAX_OVERFLOW``), at most ``TENANT_ENGINE_CACHE_SIZE`` engines, the least
recently used closed first.

A tenant engine signs in the way the control engine does (``DB_AUTH``:
the URL's password, or a fresh Entra token per connection — the same
``dbauth`` provider), as the same principal, on the tenant's server at
``TENANT_DB_PORT``. Its connections search the ``platform`` schema first, so
the models' unqualified table names — and raw SQL — find the tenant's tables.
"""
from __future__ import annotations

import asyncio
import logging
from collections import OrderedDict
from typing import Any, Optional

from sqlalchemy import event
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from src.common.config import settings
from src.common.tenancy.bases import TENANT_SCHEMA
from src.common.tenancy.directory import TenantLocation

logger = logging.getLogger(__name__)

POOL_SIZE = 2
MAX_OVERFLOW = 3
SEARCH_PATH = f"{TENANT_SCHEMA}, public"  # public: the extensions (vector, pgcrypto)


def tenant_url(location: TenantLocation) -> URL:
    """The tenant database's URL: the control URL's driver and principal, the tenant's server and database."""
    base = make_url(settings.CONTROL_DATABASE_URL)
    return base.set(host=location.server_host, port=settings.TENANT_DB_PORT or base.port,
                    database=location.db_name)


def _search_platform_first(dbapi_connection: Any, connection_record: Any) -> None:
    run_async = getattr(dbapi_connection, "run_async", None)
    if run_async is None:  # not asyncpg
        return
    run_async(lambda conn: conn.execute(f"SET search_path TO {SEARCH_PATH}"))


def create_tenant_engine(url: URL, *, role: Optional[str] = None) -> AsyncEngine:
    """A tenant database's engine; ``role``: every connection acts as that role
    (``SET ROLE`` at sign-in) — the DDL role, for the provisioner's work (db_roles)."""
    from src.common.database import json_serializer
    from src.common.platform.dbauth import install as install_db_auth

    engine = create_async_engine(
        url, pool_size=POOL_SIZE, max_overflow=MAX_OVERFLOW, pool_timeout=60,
        pool_recycle=1800, pool_pre_ping=True, json_serializer=json_serializer,
        connect_args={"server_settings": {"role": role}} if role else {},
    )
    install_db_auth(engine)
    event.listen(engine.sync_engine, "connect", _search_platform_first)
    return engine


class TenantEngines:
    """Engines by (host, port, database), least recently used first out."""

    def __init__(self, capacity: Optional[int] = None) -> None:
        self._capacity = capacity
        self._engines: "OrderedDict[tuple[str, Optional[int], str], AsyncEngine]" = OrderedDict()
        self._closing: set[asyncio.Task[None]] = set()

    def __len__(self) -> int:
        return len(self._engines)

    @property
    def capacity(self) -> int:
        return max(1, self._capacity or settings.TENANT_ENGINE_CACHE_SIZE)

    def get(self, location: TenantLocation) -> AsyncEngine:
        url = tenant_url(location)
        key = (str(url.host), url.port, str(url.database))
        engine = self._engines.get(key)
        if engine is not None:
            self._engines.move_to_end(key)
            return engine
        engine = create_tenant_engine(url)
        self._engines[key] = engine
        while len(self._engines) > self.capacity:
            _, oldest = self._engines.popitem(last=False)
            self._close_later(oldest)
        return engine

    def _close_later(self, engine: AsyncEngine) -> None:
        # A session still using it keeps its connection until it returns it.
        try:
            task = asyncio.get_running_loop().create_task(engine.dispose())
        except RuntimeError:  # no running loop: nothing is using it
            return
        self._closing.add(task)
        task.add_done_callback(self._closing.discard)

    async def dispose_all(self) -> None:
        engines, self._engines = list(self._engines.values()), OrderedDict()
        for engine in engines:
            await engine.dispose()
        if self._closing:
            await asyncio.gather(*self._closing, return_exceptions=True)


engines = TenantEngines()
