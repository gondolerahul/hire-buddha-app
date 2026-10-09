"""An agent's edit reaches the next call at once, in every process (VT-16).

``AgentContextLoader`` cached an agent's voice context for five minutes and
nothing dropped it when the agent changed. Real Postgres (rolled back) and the
local Redis the edit is announced on.
"""
from __future__ import annotations

import asyncio
import uuid

import pytest
from cachetools import TTLCache

from tests.harness.infra import infra_unavailable

pytestmark = pytest.mark.needs_db


async def _redis_or_skip():
    from src.common.redis_client import shared_redis
    try:
        await shared_redis().ping()
    except Exception:
        infra_unavailable("Redis is not reachable")
    return shared_redis()


@pytest.fixture
def cache(monkeypatch):
    fresh = TTLCache(maxsize=16, ttl=300)
    monkeypatch.setattr("src.voice.agent_loader._AGENT_BASE_CACHE", fresh)
    return fresh


async def _until(predicate, seconds=5.0):
    for _ in range(int(seconds / 0.05)):
        if predicate():
            return True
        await asyncio.sleep(0.05)
    return predicate()


@pytest.mark.asyncio
async def test_an_edit_drops_the_cached_agent_and_is_announced(db, test_company_id, cache):
    from src.ai.orm.entity import HierarchicalEntity
    from src.ai.schemas.entity import HierarchicalEntityUpdate
    from src.ai.service import AIService
    from src.voice.agent_cache_bus import CHANNEL

    redis = await _redis_or_skip()
    agent = HierarchicalEntity(company_id=test_company_id, type="AGENT", status="ACTIVE",
                               name=f"vt16-{uuid.uuid4().hex[:6]}")
    other = uuid.uuid4()
    db.add(agent)
    await db.flush()
    cache[(agent.id, "voice")] = {"system_instruction": "the old prompt"}
    cache[(other, "voice")] = {"system_instruction": "another agent"}
    route = f"gateway:agent:{test_company_id}:voice:-"
    await redis.set(route, "{}")

    pubsub = redis.pubsub()
    await pubsub.subscribe(CHANNEL)
    try:
        await AIService(db).update_entity(
            agent.id, HierarchicalEntityUpdate(goal="the new prompt"), test_company_id)
        message = None
        for _ in range(50):
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.1)
            if message:
                break
    finally:
        await pubsub.aclose()

    assert (agent.id, "voice") not in cache          # this process
    assert (other, "voice") in cache                 # nobody else's
    assert message and message["data"].decode() == str(agent.id)   # every other process
    assert await redis.exists(route) == 0            # the dispatcher's route is looked up again


@pytest.mark.asyncio
async def test_a_listening_process_drops_an_agent_another_process_announced(cache):
    from src.voice import agent_cache_bus
    from src.common.config import settings

    redis = await _redis_or_skip()
    edited, untouched = uuid.uuid4(), uuid.uuid4()
    listener = asyncio.create_task(agent_cache_bus.listen(settings.REDIS_URL))
    try:
        async def _subscribed():
            return dict(await redis.pubsub_numsub(agent_cache_bus.CHANNEL))
        for _ in range(100):
            counts = await _subscribed()
            if counts.get(agent_cache_bus.CHANNEL.encode(), 0) >= 1:
                break
            await asyncio.sleep(0.05)
        await asyncio.sleep(0.1)                     # past its subscribe-time clear
        cache[(edited, "voice")] = {"system_instruction": "old"}
        cache[(untouched, "voice")] = {"system_instruction": "kept"}

        await redis.publish(agent_cache_bus.CHANNEL, str(edited))   # as another process would

        assert await _until(lambda: (edited, "voice") not in cache)
        assert (untouched, "voice") in cache
    finally:
        listener.cancel()
        with pytest.raises(asyncio.CancelledError):
            await listener
