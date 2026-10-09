"""GH-14: a flag's change reaches every process's cache at once, after it commits.

Each process caches resolved flags for a minute. ``set`` published an
invalidation only when given a Redis client (the admin endpoint gave none),
nothing subscribed to it, and the experimental-tool toggle wrote raw SQL —
so every other process kept the old value for up to a minute. Now ``set`` /
``delete`` publish once the caller's transaction commits, and every API and
worker process runs ``listen_for_invalidations``. Real Postgres (rolled back)
and the local Redis.
"""
from __future__ import annotations

import asyncio
import json
import uuid

import pytest

from src.ai.core import feature_flags as ff

pytestmark = pytest.mark.needs_db


@pytest.fixture
async def redis():
    import redis.asyncio as redis_lib

    from src.common.config import settings

    client = redis_lib.from_url(settings.REDIS_URL or "redis://localhost:6379")
    try:
        await client.ping()
    except Exception:
        pytest.skip("Redis is not reachable")
    yield client
    await client.aclose()


async def _until(predicate, seconds=3.0):
    for _ in range(int(seconds / 0.05)):
        if predicate():
            return True
        await asyncio.sleep(0.05)
    return predicate()


def _cached(flag: str) -> bool:
    return any(key[0] == flag for key in ff._PROCESS_CACHE)


@pytest.mark.asyncio
async def test_a_published_change_drops_the_flag_in_a_listening_process(redis):
    from src.common.config import settings

    flag = f"test.gh14.{uuid.uuid4().hex[:8]}"
    listener = asyncio.create_task(ff.listen_for_invalidations(settings.REDIS_URL))
    try:
        await asyncio.sleep(0.3)                      # subscribed (and its first clear done)
        ff._process_cache_put(flag, None, None, ff._Resolution(True, "global", flag))
        ff._process_cache_put("test.gh14.other", None, None, ff._Resolution(True, "global", "x"))
        assert _cached(flag)
        # Another process announces the change: only the raw publish, so only
        # the listener can have dropped it here.
        await redis.publish(ff._REDIS_INVALIDATION_CHANNEL, json.dumps({"flag_key": flag}))
        assert await _until(lambda: not _cached(flag)), "the listener did not drop the flag"
        assert _cached("test.gh14.other")             # one flag, not the whole cache
    finally:
        listener.cancel()
        await asyncio.gather(listener, return_exceptions=True)
        ff.invalidate_process_cache()


@pytest.mark.asyncio
async def test_set_announces_only_once_committed(db, monkeypatch):
    announced = []

    async def _publish(flag_key=None, **_kw):
        announced.append(flag_key)
        return True

    monkeypatch.setattr(ff, "publish_invalidation", _publish)
    flag = f"test.gh14.{uuid.uuid4().hex[:8]}"
    await ff.FeatureFlags(db).set(flag, enabled=True)
    await asyncio.sleep(0)
    assert announced == []                            # not before the row is visible to others
    await db.commit()
    assert await _until(lambda: announced == [flag])


@pytest.mark.asyncio
async def test_a_rolled_back_change_is_not_announced(db, monkeypatch):
    announced = []

    async def _publish(flag_key=None, **_kw):
        announced.append(flag_key)
        return True

    monkeypatch.setattr(ff, "publish_invalidation", _publish)
    await ff.FeatureFlags(db).set(f"test.gh14.{uuid.uuid4().hex[:8]}", enabled=True)
    await db.rollback()
    await asyncio.sleep(0.1)
    assert announced == []
