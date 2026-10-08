"""agent_cache_bus.py — an agent's edit reaches its next call at once (VT-16, VT-I3).

``AgentContextLoader`` caches each agent's voice context (persona, tools, API
key) for ``VOICE_AGENT_CACHE_TTL_SECONDS`` because a cold load took about five
seconds on the call-setup path, and the dispatcher caches which agent a
company's socket talks to for five minutes. Nothing dropped either when the
agent changed, so an operator fixing a bad prompt mid-campaign heard the old
one dial for up to five minutes.

Every API process holds its own context cache. An edit, a delete or a published
version calls :func:`announce_agent_changed` after its commit: it drops the
agent here, drops the company's dispatcher entries (they are in Redis, shared)
and publishes the id on ``voice:agent_changed``; every process runs
:func:`listen`, which drops it there. A process that loses the channel drops
its whole cache when it is back, for what it may have missed; a publish that
fails leaves other processes on the TTL, as before.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional
from uuid import UUID

logger = logging.getLogger(__name__)

CHANNEL = "voice:agent_changed"
_RETRY_SECONDS = 5.0


async def announce_agent_changed(agent_id: Any, company_id: Any = None) -> None:
    """Drop the agent's cached voice context in every process (best-effort)."""
    from src.common.redis_client import shared_redis
    from src.voice.agent_loader import bust_agent_cache

    agent = _agent_id(agent_id)
    if agent is None:
        return
    bust_agent_cache(agent)
    try:
        redis = shared_redis()
        if company_id is not None:
            stale = [key async for key in redis.scan_iter(match=f"gateway:agent:{company_id}:*")]
            if stale:
                await redis.delete(*stale)
        await redis.publish(CHANNEL, str(agent))
    except Exception as exc:                                                # noqa: BLE001
        logger.warning("Agent %s changed; other processes keep it until the cache TTL: %s",
                       agent_id, exc)


def _agent_id(data: Any) -> Optional[UUID]:
    if isinstance(data, UUID):
        return data
    try:
        return UUID(data.decode() if isinstance(data, bytes) else str(data))
    except (ValueError, AttributeError):
        return None


async def listen(redis_url: str) -> None:
    """Drop an agent's cached voice context when any process announces it changed.

    Runs for the life of the process (the API's lifespan starts and cancels it).
    """
    import redis.asyncio as redis_lib

    from src.voice.agent_loader import bust_agent_cache

    while True:
        client = redis_lib.from_url(redis_url)
        pubsub = client.pubsub()
        try:
            await pubsub.subscribe(CHANNEL)
            bust_agent_cache()  # whatever changed while this process was not listening
            while True:
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if message and message.get("type") == "message":
                    agent_id = _agent_id(message.get("data"))
                    if agent_id is not None:
                        bust_agent_cache(agent_id)
        except asyncio.CancelledError:
            raise
        except Exception as exc:                                            # noqa: BLE001
            logger.warning("Agent cache channel lost (%s); retrying in %ss", exc, _RETRY_SECONDS)
            await asyncio.sleep(_RETRY_SECONDS)
        finally:
            try:
                await pubsub.aclose()
                await client.aclose()
            except Exception:                                               # noqa: BLE001
                pass
