"""
Agent resolution for the audio and video WebSockets.

``resolve_agent_for_client`` picks the agent a streaming session talks to, with
a five-minute Redis cache. The API's lifespan starts the dispatcher (opens that
Redis connection) and stops it.

This used to be the "Central AI Dispatcher": it drained an in-process event bus
that the webhook and internal-event endpoints published to, enqueued
``process_gateway_event``, and — when arq was unreachable — ran a whole
AgentLoop inside the web process. The endpoints now queue their events on arq
themselves before answering (``gateway/envelope.py``, SA-09), so all of that is
gone. The class keeps its name for its callers.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional
from uuid import UUID

logger = logging.getLogger(__name__)


class CentralDispatcher:
    """Resolves the agent for a streaming client, with a Redis cache.

    Lifecycle:
        dispatcher = get_dispatcher()
        await dispatcher.start()          # on app startup: connect the cache
        agent = await dispatcher.resolve_agent_for_client(client_id, "audio")
        await dispatcher.stop()           # on app shutdown
    """

    def __init__(self) -> None:
        self._redis = None

    async def start(self) -> None:
        """Connect the agent cache. Redis is optional: without it every lookup hits the DB."""
        from src.common.config import settings

        try:
            import redis.asyncio as aioredis
            self._redis = await aioredis.from_url(
                settings.REDIS_URL, encoding="utf-8", decode_responses=True
            )
            logger.info("[Dispatcher] Redis connection established")
        except Exception as e:
            logger.warning(f"[Dispatcher] Redis unavailable, agent cache disabled: {e}")

    async def stop(self) -> None:
        """Graceful shutdown."""
        if self._redis:
            await self._redis.aclose()
        logger.info("[Dispatcher] Stopped")

    # -------------------------------------------------------------------------
    # Agent / session resolution helpers (used by WebSocket handlers)
    # -------------------------------------------------------------------------

    async def resolve_agent_for_client(
        self,
        client_id: str,
        channel: str,
        event_type: str = "",
    ) -> Optional[Dict[str, Any]]:
        """
        Look up the default AI agent for a given client (tenant).

        Returns a dict with agent metadata, or None if not found.
        Used by audio/video WebSocket handlers during their handshake phase.
        """
        # Try Redis cache first
        if self._redis:
            cache_key = f"gateway:agent:{client_id}:{channel}"
            cached = await self._redis.get(cache_key)
            if cached:
                return json.loads(cached)

        # Fall back to DB lookup
        try:
            from src.common.database import AsyncSessionLocal
            from src.ai.models import HierarchicalEntity
            from sqlalchemy import select

            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    select(HierarchicalEntity).where(
                        HierarchicalEntity.company_id == UUID(client_id),
                        HierarchicalEntity.status != 'ARCHIVED',
                    ).limit(1)
                )
                agent = result.scalar_one_or_none()
                if not agent:
                    return None

                agent_info = {
                    "agent_id": str(agent.id),
                    "company_id": str(agent.company_id),
                    "name": agent.name,
                    "channel": channel,
                }

                # Cache for 5 minutes
                if self._redis:
                    await self._redis.setex(
                        f"gateway:agent:{client_id}:{channel}",
                        300,
                        json.dumps(agent_info),
                    )

                return agent_info
        except Exception as exc:
            logger.error(f"[Dispatcher] Agent resolution failed: {exc}")
            return None


# ---------------------------------------------------------------------------
# Global singleton
# ---------------------------------------------------------------------------

_dispatcher: Optional[CentralDispatcher] = None


def get_dispatcher() -> CentralDispatcher:
    """Return (and lazily create) the global dispatcher instance."""
    global _dispatcher
    if _dispatcher is None:
        _dispatcher = CentralDispatcher()
    return _dispatcher
