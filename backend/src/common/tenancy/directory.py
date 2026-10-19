"""Where each tenant's data lives (Phase 14 WS2 2.1, tech spec §5.3, §6.1).

``TenantDirectory.get(company_id)`` reads the company's row of the control
table ``tenant_directory`` (with its server's host) as a ``TenantLocation``.
Rows are cached in-process for ``CACHE_SECONDS``; a process that changes a
row calls ``publish_change`` and every process listening on the channel
(``listen_for_changes``, started by the API and the workers in split mode)
drops it at once.

The **tenant key** names every per-tenant resource (database ``t_<key>``,
namespace ``t-<key>``, Blob container, Key Vault key). A new key is ten
characters of lower-case Crockford base32 (no ``i``, ``l``, ``o``, ``u``) and
never changes.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import secrets
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional
from uuid import UUID

from src.common.tenancy.models import DATABASE_READY_STATUSES

logger = logging.getLogger(__name__)

CACHE_SECONDS = 60
# Rows (and "no row" answers) kept per process; the oldest go first. A public
# route can ask about any company id, so the cache must not grow without bound.
CACHE_MAX_ENTRIES = 10_000
CHANGES_CHANNEL = "hb:tenancy:directory"
_LISTEN_RETRY_SECONDS = 5

TENANT_KEY_ALPHABET = "0123456789abcdefghjkmnpqrstvwxyz"
TENANT_KEY_LENGTH = 10
# Hand-picked keys (dev tenants) may be shorter; nothing else may appear in a
# database, namespace or container name.
_TENANT_KEY_RE = re.compile(r"[0-9a-hjkmnp-tv-z]{3,10}")


def new_tenant_key() -> str:
    return "".join(secrets.choice(TENANT_KEY_ALPHABET) for _ in range(TENANT_KEY_LENGTH))


def is_valid_tenant_key(key: Any) -> bool:
    return isinstance(key, str) and _TENANT_KEY_RE.fullmatch(key) is not None


def tenant_db_name(key: str) -> str:
    """The tenant's database name, ``t_<key>``."""
    if not is_valid_tenant_key(key):
        raise ValueError(f"not a tenant key: {key!r}")
    return f"t_{key}"


class TenantNotFound(LookupError):
    """The company has no row in the tenant directory (no database of its own)."""


class TenantNotReady(RuntimeError):
    """The tenant's database is not usable in its current status."""


@dataclass(frozen=True)
class TenantLocation:
    company_id: UUID
    key: str
    server_host: str
    db_name: str
    status: str
    schema_version: Optional[str]
    automation_state: str
    timezone: str

    @property
    def database_ready(self) -> bool:
        """Whether a tenant session may open: the database has its tables and is not retired."""
        return self.status in DATABASE_READY_STATUSES


def _uuid(company_id: Any) -> UUID:
    return company_id if isinstance(company_id, UUID) else UUID(str(company_id))


class TenantDirectory:
    """Company → ``TenantLocation``, cached per process."""

    def __init__(self, ttl_seconds: float = CACHE_SECONDS,
                 clock: Callable[[], float] = time.monotonic,
                 max_entries: int = CACHE_MAX_ENTRIES) -> None:
        self._ttl = ttl_seconds
        self._clock = clock
        self._max_entries = max(1, max_entries)
        self._cache: dict[UUID, tuple[Optional[TenantLocation], float]] = {}

    async def find(self, company_id: Any) -> Optional[TenantLocation]:
        """The company's location, or ``None`` when it has no directory row."""
        cid = _uuid(company_id)
        hit = self._cache.get(cid)
        if hit is not None and hit[1] > self._clock():
            return hit[0]
        location = await self._read(cid)
        self._cache.pop(cid, None)
        self._cache[cid] = (location, self._clock() + self._ttl)
        while len(self._cache) > self._max_entries:
            self._cache.pop(next(iter(self._cache)))
        return location

    async def get(self, company_id: Any) -> TenantLocation:
        location = await self.find(company_id)
        if location is None:
            raise TenantNotFound(f"company {company_id} has no tenant database (no tenant_directory row)")
        return location

    def cached(self, company_id: Any) -> Optional[TenantLocation]:
        """The company's location if this process has read it (expired or not), without any I/O.
        For decisions that may not await (a new file's storage namespace)."""
        try:
            hit = self._cache.get(_uuid(company_id))
        except (TypeError, ValueError):
            return None
        return hit[0] if hit else None

    def invalidate(self, company_id: Any = None) -> None:
        """Forget one company's row, or every row."""
        if company_id is None:
            self._cache.clear()
        else:
            self._cache.pop(_uuid(company_id), None)

    async def ready_company_ids(self) -> list[UUID]:
        """Every company whose database a session may open, in a stable order (uncached)."""
        from sqlalchemy import select

        from src.common.tenancy.models import TenantDirectoryEntry
        from src.common.tenancy.session import control_session

        async with control_session() as db:
            rows = (await db.execute(
                select(TenantDirectoryEntry.company_id)
                .where(TenantDirectoryEntry.status.in_(sorted(DATABASE_READY_STATUSES)))
                .order_by(TenantDirectoryEntry.tenant_key)
            )).scalars().all()
        return list(rows)

    async def _read(self, company_id: UUID) -> Optional[TenantLocation]:
        from sqlalchemy import select

        from src.common.tenancy.models import TenantDbServer, TenantDirectoryEntry
        from src.common.tenancy.session import control_session

        async with control_session() as db:
            row = (await db.execute(
                select(TenantDirectoryEntry, TenantDbServer.host)
                .join(TenantDbServer, TenantDbServer.id == TenantDirectoryEntry.server_id)
                .where(TenantDirectoryEntry.company_id == company_id)
            )).first()
        if row is None:
            return None
        entry, host = row
        return TenantLocation(
            company_id=entry.company_id, key=entry.tenant_key, server_host=host,
            db_name=entry.db_name, status=entry.status,
            schema_version=entry.platform_schema_version,
            automation_state=entry.automation_state, timezone=entry.timezone,
        )


directory = TenantDirectory()


async def publish_change(redis: Any, company_id: Any = None) -> None:
    """Tell every process a directory row changed (``None``: any row). Best-effort:
    a process that misses it reads the row again within ``CACHE_SECONDS``."""
    directory.invalidate(company_id)
    try:
        await redis.publish(CHANGES_CHANNEL, json.dumps(
            {"company_id": str(company_id) if company_id is not None else None}))
    except Exception as exc:                                              # noqa: BLE001
        logger.warning("Tenant directory change not published (%s)", exc)


def _apply_change(data: Any) -> None:
    try:
        company_id = json.loads(data or "{}").get("company_id")
        directory.invalidate(UUID(company_id) if company_id else None)
    except (TypeError, ValueError, AttributeError):
        directory.invalidate()  # unreadable: drop everything


async def listen_for_changes(redis_url: str) -> None:
    """Drop a directory row from this process's cache when any process announces
    it changed. Runs for the life of the process; after losing the channel it
    drops the whole cache, for what it may have missed."""
    import redis.asyncio as redis_lib

    while True:
        client = redis_lib.from_url(redis_url)  # type: ignore[no-untyped-call]
        pubsub = client.pubsub()
        try:
            await pubsub.subscribe(CHANGES_CHANNEL)
            directory.invalidate()
            while True:
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if message and message.get("type") == "message":
                    _apply_change(message.get("data"))
        except asyncio.CancelledError:
            raise
        except Exception as exc:                                          # noqa: BLE001
            logger.warning("Tenant directory channel lost (%s); retrying in %ss", exc, _LISTEN_RETRY_SECONDS)
            await asyncio.sleep(_LISTEN_RETRY_SECONDS)
        finally:
            try:
                await pubsub.aclose()
                await client.aclose()
            except Exception:                                             # noqa: BLE001
                pass
