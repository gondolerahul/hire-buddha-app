"""run_quota.py — how many runs a company may start a minute (GH-03, HD17).

There was no per-tenant quota anywhere: a script, a webhook storm or a looping
integration could start runs as fast as it could call, and every one of them
held a worker and credit. Now a company may start
``settings.RUNS_STARTED_PER_MINUTE`` top-level runs in any 60 seconds (0 turns
the limit off). The count is a ``RedisRateLimiter`` window, which refuses when
Redis cannot be reached (GH-21): a quota that lifts in an outage is no quota.

Checked where a top-level run starts:

* the API — trigger, retry and refine — answers **429** with ``Retry-After``;
* the gateway job defers itself (arq ``Retry``), so a webhook's run is
  postponed, not lost; on its last try the event is refused and logged.

A run's children, and the CORTEX wake-ups the platform schedules, are not
counted: they are part of runs that were.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

__all__ = ["WINDOW_SECONDS", "RunQuotaExceeded", "require_run_slot"]

WINDOW_SECONDS = 60


class RunQuotaExceeded(Exception):
    """The company has started its quota of runs this minute."""


async def require_run_slot(company_id: Any) -> None:
    """Take one of the company's run starts this minute, or raise ``RunQuotaExceeded``."""
    from src.ai.governance.rate_limiter import RedisRateLimiter
    from src.common.config import settings
    from src.common.redis_client import shared_redis

    limit = int(settings.RUNS_STARTED_PER_MINUTE or 0)
    if limit <= 0:
        return
    allowed = await RedisRateLimiter(shared_redis()).check_and_consume(
        key=f"runs_started:{UUID(str(company_id))}", limit=limit, window_seconds=WINDOW_SECONDS)
    if not allowed:
        raise RunQuotaExceeded(
            f"This company may start {limit} runs a minute (or the limit could not be checked). "
            f"Try again in a minute.")
