"""The agent-cache channel survives Redis trouble (VT-16).

An announce that cannot reach Redis still drops the agent here; a listener
that loses the channel reconnects and drops its whole cache, for whatever was
announced while it was away.
"""
from __future__ import annotations

import asyncio
import uuid

import pytest
from cachetools import TTLCache

from src.voice import agent_cache_bus


@pytest.fixture
def cache(monkeypatch):
    fresh = TTLCache(maxsize=16, ttl=300)
    monkeypatch.setattr("src.voice.agent_loader._AGENT_BASE_CACHE", fresh)
    return fresh


@pytest.mark.asyncio
async def test_an_announce_without_redis_still_drops_the_agent_here(cache, monkeypatch):
    agent = uuid.uuid4()
    cache[(agent, "voice")] = {}

    class _Down:
        def scan_iter(self, **_):
            raise ConnectionError("redis is down")

        async def publish(self, *_):
            raise ConnectionError("redis is down")

    monkeypatch.setattr("src.common.redis_client.shared_redis", lambda: _Down())
    await agent_cache_bus.announce_agent_changed(agent, uuid.uuid4())
    assert (agent, "voice") not in cache


@pytest.mark.asyncio
async def test_a_listener_that_loses_the_channel_reconnects_and_clears_everything(cache, monkeypatch):
    stale = uuid.uuid4()
    clients = []

    class _PubSub:
        def __init__(self, n):
            self.n = n

        async def subscribe(self, _channel):
            if self.n == 1:
                cache[(stale, "voice")] = {}     # announced while the first connection was dying

        async def get_message(self, **_):
            if self.n == 1:
                raise ConnectionError("connection reset")
            await asyncio.sleep(3600)

        async def aclose(self):
            pass

    class _Client:
        def __init__(self):
            clients.append(self)
            self.n = len(clients)

        def pubsub(self):
            return _PubSub(self.n)

        async def aclose(self):
            pass

    import redis.asyncio as redis_lib
    monkeypatch.setattr(redis_lib, "from_url", lambda _url: _Client())
    monkeypatch.setattr(agent_cache_bus, "_RETRY_SECONDS", 0.0)

    listener = asyncio.create_task(agent_cache_bus.listen("redis://unused"))
    for _ in range(100):
        if len(clients) >= 2:
            break
        await asyncio.sleep(0.01)
    await asyncio.sleep(0.01)
    listener.cancel()
    with pytest.raises(asyncio.CancelledError):
        await listener

    assert len(clients) == 2
    assert (stale, "voice") not in cache


def test_a_message_that_is_not_an_agent_id_is_ignored():
    assert agent_cache_bus._agent_id(b"not-a-uuid") is None
    agent = uuid.uuid4()
    assert agent_cache_bus._agent_id(str(agent).encode()) == agent
