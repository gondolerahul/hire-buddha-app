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
        agent_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        The agent a live socket for ``client_id`` runs (GW-17).

        ``agent_id`` (from the handshake) names one; otherwise it is the
        company's only active agent — see ``gateway.agent_choice``. Returns the
        agent's metadata; ``{"error": code, "message": ...}`` when the choice is
        refused (an unknown agent, or several to choose from); None when the
        company has no agent or the lookup failed.
        """
        cache_key = f"gateway:agent:{client_id}:{channel}:{agent_id or '-'}"
        if self._redis:
            cached = await self._redis.get(cache_key)
            if cached:
                return json.loads(cached)

        try:
            from src.common.tenancy.session import tenant_session
            from src.gateway.agent_choice import choose_agent

            # The company's agents are in its tenant database (Phase 14 WS2).
            async with tenant_session(UUID(client_id)) as db:
                choice = await choose_agent(db, UUID(client_id), [agent_id])
            if choice.error == "no_agent":
                return None
            if choice.error:
                return {"error": choice.error, "message": choice.detail}
            agent = choice.entity
            agent_info = {
                "agent_id": str(agent.id),
                "company_id": str(agent.company_id),
                "name": agent.name,
                "channel": channel,
            }
            if self._redis:
                await self._redis.setex(cache_key, 300, json.dumps(agent_info))
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
