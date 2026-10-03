"""Cached model and key resolutions that every process drops on a change (LP-22, LP-I5).

Two problems with one cause. Every LLM call resolved its model through
``model_task_defaults`` and ``integration_registry`` — a run with thirty
iterations and four critics did that well over a hundred times for a value that
does not change mid-run (LP-I5). The one cache there was (the voice path's key
lookup, 60 s) was cleared only in the process that rotated a key, so other
workers kept serving a revoked key for up to a minute (LP-22).

Now one rule. Every write to the registry or the task defaults increments the
**integration generation**, a Redis counter. A cached resolution remembers the
generation it was made under and is used only while the counter still has that
value. The counter is re-read at most once a second, so a rotation reaches every
process within about a second. When Redis cannot be read, an entry lives
``TTL_WITHOUT_REDIS`` seconds, the old bound.

Read the generation *before* resolving and store the result under it: a write
that lands mid-resolution then makes the entry stale instead of hiding.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, Hashable, Optional, Tuple

logger = logging.getLogger(__name__)

GENERATION_KEY = "config:integration_generation"
GENERATION_REFRESH_SECONDS = 1.0
TTL_WITHOUT_REDIS = 60.0
MAX_TTL = 600.0

_monotonic = time.monotonic  # one seam for tests; asyncio's own clock is left alone
_memo: Tuple[Optional[int], float] = (None, float("-inf"))


def _client() -> Any:
    from src.common.redis_client import shared_redis
    return shared_redis()


async def current_generation() -> Optional[int]:
    """The integration generation, or ``None`` when Redis cannot be read."""
    global _memo
    value, read_at = _memo
    now = _monotonic()
    if now - read_at < GENERATION_REFRESH_SECONDS:
        return value
    try:
        raw = await _client().get(GENERATION_KEY)
        value = int(raw) if raw is not None else 0
    except Exception as exc:                                               # noqa: BLE001
        logger.debug("integration generation unavailable: %s", exc)
        value = None
    _memo = (value, now)
    return value


async def bump_generation() -> None:
    """A registry or task-default write: every process's resolutions go stale."""
    global _memo
    try:
        _memo = (int(await _client().incr(GENERATION_KEY)), _monotonic())
    except Exception as exc:                                               # noqa: BLE001
        logger.warning("could not publish the integration change (other processes keep their "
                       "resolutions up to %.0fs): %s", TTL_WITHOUT_REDIS, exc)
        _memo = (None, float("-inf"))
    for cache in _CACHES:
        cache.clear()


class ResolutionCache:
    """Values that stay valid while the integration generation does."""

    MISS = object()

    def __init__(self, maxsize: int = 1024):
        self.maxsize = maxsize
        self._entries: Dict[Hashable, Tuple[Any, Optional[int], float]] = {}
        _CACHES.append(self)

    def get(self, key: Hashable, generation: Optional[int]) -> Any:
        entry = self._entries.get(key)
        if entry is None:
            return self.MISS
        value, made_under, stored_at = entry
        age = _monotonic() - stored_at
        fresh = (age < MAX_TTL and made_under == generation) if generation is not None and made_under is not None \
            else age < TTL_WITHOUT_REDIS
        if not fresh:
            self._entries.pop(key, None)
            return self.MISS
        return value

    def put(self, key: Hashable, value: Any, generation: Optional[int]) -> None:
        if len(self._entries) >= self.maxsize:
            self._entries.pop(next(iter(self._entries)))
        self._entries[key] = (value, generation, _monotonic())

    def clear(self) -> None:
        self._entries.clear()


_CACHES: list[ResolutionCache] = []


def clear_all() -> None:
    """Drop every cached resolution in this process (tests)."""
    global _memo
    _memo = (None, float("-inf"))
    for cache in _CACHES:
        cache.clear()
