"""A business's time zone (Phase 14 WS1 1.10, functional spec §8).

Schedules, reports and an agent's "today" use the company's IANA time zone
instead of a hard-coded India time. With ``TENANCY_MODE=single`` it is
``companies.timezone``; with ``split`` it is the company's tenant directory
row (``tenant_directory.timezone``, WS2), and ``companies.timezone`` only for a
company that has no row yet. A change is written to both.
"""
from __future__ import annotations

import time
from typing import Any, Dict, Optional, Tuple
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

DEFAULT_TIMEZONE = "Asia/Kolkata"
CACHE_SECONDS = 60

_cache: Dict[str, Tuple[str, float]] = {}


def is_valid_timezone(name: Any) -> bool:
    if not isinstance(name, str) or not name or name != name.strip():
        return False
    if name in ("UTC", "Etc/UTC"):
        return True
    return name in _zone_names()


_ZONE_NAMES: Optional[frozenset] = None


def _zone_names() -> frozenset:
    global _ZONE_NAMES
    if _ZONE_NAMES is None:
        _ZONE_NAMES = frozenset(available_timezones())
    return _ZONE_NAMES


def zone(name: Optional[str]) -> ZoneInfo:
    """The zone, or the default for a name that is empty or unknown."""
    try:
        return ZoneInfo(name) if name and is_valid_timezone(name) else ZoneInfo(DEFAULT_TIMEZONE)
    except ZoneInfoNotFoundError:
        return ZoneInfo(DEFAULT_TIMEZONE)


async def company_timezone_name(company_id: Any, db: Any = None) -> str:
    """The company's time zone name; cached for a minute per process."""
    if not company_id:
        return DEFAULT_TIMEZONE
    key = str(company_id)
    hit = _cache.get(key)
    if hit and hit[1] > time.monotonic():
        return hit[0]
    from sqlalchemy import select

    from src.auth.models import Company

    async def read(session: Any) -> Optional[str]:
        return (await session.execute(select(Company.timezone).where(Company.id == company_id))).scalar()

    from src.common.tenancy.session import control_session, is_split

    location = None
    if is_split():
        from src.common.tenancy.directory import directory

        location = await directory.find(company_id)
    if location is not None:
        name = location.timezone
    elif db is not None:
        name = await read(db)
    else:
        async with control_session() as session:
            name = await read(session)
    name = name if is_valid_timezone(name) else DEFAULT_TIMEZONE
    _cache[key] = (name, time.monotonic() + CACHE_SECONDS)
    return name


async def company_timezone(company_id: Any, db: Any = None) -> ZoneInfo:
    return zone(await company_timezone_name(company_id, db))


def forget_company_timezone(company_id: Any = None) -> None:
    """Drop the cached zone (after an update in this process; tests)."""
    if company_id is None:
        _cache.clear()
    else:
        _cache.pop(str(company_id), None)
