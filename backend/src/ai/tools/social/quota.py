"""Shares of a provider's daily allowance that every business draws on (YT-E4, GADS-E6).

HireBuddha's YouTube project uploads a limited number of videos a day, and its
Google Ads developer token makes 15,000 operations a day on Basic access — for
all businesses together. Each draw is counted per day in Redis (Pacific time,
when Google resets them), for the platform and for the business: a business
may use its share, and nobody may pass the whole. Redis down: the provider's
own limit still holds, so the draw is allowed and logged.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

PACIFIC = ZoneInfo("America/Los_Angeles")
_KEEP_SECONDS = 2 * 86400


def day(now: Optional[datetime] = None) -> str:
    """Google's quota day: the date in Pacific time."""
    return (now or datetime.now(timezone.utc)).astimezone(PACIFIC).strftime("%Y%m%d")


async def draw(name: str, company_id: Any, *, amount: int = 1, total: int, share: int,
               what: str, now: Optional[datetime] = None) -> Optional[str]:
    """Count ``amount`` of ``name`` for the business; why not (nothing counted) when
    it would pass the business's share or the platform's total."""
    from src.common.redis_client import shared_redis

    stamp = day(now)
    company_key, platform_key = f"quota:{name}:{stamp}:{company_id}", f"quota:{name}:{stamp}"
    try:
        redis = shared_redis()
        mine = int(await redis.incrby(company_key, amount))
        if mine > share:
            await redis.decrby(company_key, amount)
            return (f"This business has used its share of HireBuddha's daily {what} ({share} a day); "
                    "it renews at midnight Pacific time.")
        everyone = int(await redis.incrby(platform_key, amount))
        if everyone > total:
            await redis.decrby(platform_key, amount)
            await redis.decrby(company_key, amount)
            return (f"HireBuddha's daily {what} ({total} a day, shared by all businesses) is used up; "
                    "it renews at midnight Pacific time.")
        await redis.expire(company_key, _KEEP_SECONDS)
        await redis.expire(platform_key, _KEEP_SECONDS)
    except Exception:  # noqa: BLE001 - the provider's own limit still applies
        logger.warning("daily %s not counted for %s", name, company_id, exc_info=True)
    return None


async def used(name: str, company_id: Any = None, *, now: Optional[datetime] = None) -> int:
    from src.common.redis_client import shared_redis

    key = f"quota:{name}:{day(now)}" + (f":{company_id}" if company_id else "")
    try:
        return int(await shared_redis().get(key) or 0)
    except Exception:  # noqa: BLE001
        return 0
