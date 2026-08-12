"""
Central AI Dispatcher.

The brain of the Unified Gateway. Receives normalized EventEnvelope objects
from any of the 5 interfaces and routes them to the correct AI agent.

Routing logic:
  1. Extract company_id from the envelope
  2. Look up which agent to invoke (from DB or Redis cache)
  3. Construct a standard execution envelope
  4. For async channels (webhook, internal): enqueue via arq job queue
  5. For streaming channels (audio, video): signal is used directly by
     the WebSocket handler (dispatcher provides agent context only)

The class is intentionally lightweight — it delegates all business logic
to the existing ExecutionEngine, SessionManager, and AgentContextLoader.
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional
from uuid import UUID

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# DispatchResult — returned by dispatch()
# ---------------------------------------------------------------------------

@dataclass
class DispatchResult:
    accepted: bool
    mode: str                     # "async_job" | "streaming" | "rejected"
    job_id: Optional[str] = None  # arq job ID for async_job mode
    session_id: Optional[str] = None
    agent_id: Optional[str] = None
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# CentralDispatcher
# ---------------------------------------------------------------------------

class CentralDispatcher:
    """
    Routes normalized EventEnvelope objects to the appropriate AI agent.

    Lifecycle:
        dispatcher = CentralDispatcher()
        await dispatcher.start()          # call once on app startup
        result = await dispatcher.dispatch(envelope)
        await dispatcher.stop()           # call on app shutdown
    """

    def __init__(self) -> None:
        self._redis = None
        self._running = False
        self._consumer_task: Optional[asyncio.Task] = None

    # -------------------------------------------------------------------------
    # Lifecycle
    # -------------------------------------------------------------------------

    async def start(self) -> None:
        """Initialize Redis connection and start the event bus consumer."""
        from src.gateway.gateway_config import settings
        from src.gateway.event_bus import get_event_bus

        try:
            import redis.asyncio as aioredis
            self._redis = await aioredis.from_url(
                settings.REDIS_URL, encoding="utf-8", decode_responses=True
            )
            logger.info("[Dispatcher] Redis connection established")
        except Exception as e:
            logger.warning(f"[Dispatcher] Redis unavailable, session cache disabled: {e}")

        self._running = True
        bus = get_event_bus()
        self._consumer_task = asyncio.create_task(
            self._consume_event_bus(bus), name="dispatcher-event-consumer"
        )
        logger.info("[Dispatcher] Central AI Dispatcher started")

    async def stop(self) -> None:
        """Graceful shutdown."""
        self._running = False
        if self._consumer_task:
            self._consumer_task.cancel()
            try:
                await self._consumer_task
            except asyncio.CancelledError:
                pass
        if self._redis:
            await self._redis.aclose()
        logger.info("[Dispatcher] Central AI Dispatcher stopped")

    # -------------------------------------------------------------------------
    # Event bus consumer loop
    # -------------------------------------------------------------------------

    async def _consume_event_bus(self, bus) -> None:
        """Background task: drains event bus and dispatches each envelope."""
        async with bus.subscribe() as subscription:
            async for envelope in subscription:
                if not self._running:
                    break
                try:
                    await self.dispatch(envelope)
                except Exception as exc:
                    logger.error(
                        f"[Dispatcher] Error dispatching event {envelope.id}: {exc}",
                        exc_info=True,
                    )

    # -------------------------------------------------------------------------
    # Dispatch
    # -------------------------------------------------------------------------

    async def dispatch(self, envelope) -> DispatchResult:
        """
        Route a normalized EventEnvelope to the correct AI agent.

        For webhook / internal events: creates an ExecutionRun via arq.
        For audio / video: agent context is resolved but the WebSocket handler
        manages the live session directly.
        """
        from src.gateway.event_bus import EventEnvelope

        channel = envelope.channel
        client_id = envelope.client_id

        if not client_id:
            logger.warning(f"[Dispatcher] Envelope {envelope.id} has no client_id — dropping")
            return DispatchResult(accepted=False, mode="rejected", error="no_client_id")

        logger.info(
            f"[Dispatcher] Dispatching {envelope.event_type} "
            f"from {envelope.source} for client {client_id} (channel={channel})"
        )

        if channel in ("webhook", "internal"):
            return await self._dispatch_async(envelope)
        elif channel in ("audio", "video"):
            # These are handled directly by the WebSocket handlers;
            # dispatcher only validates and optionally caches context.
            return DispatchResult(accepted=True, mode="streaming")
        else:
            # REST is passthrough — should not normally be dispatched here
            return DispatchResult(accepted=True, mode="async_job")

    # -------------------------------------------------------------------------
    # Async dispatch (webhook / internal events)
    # -------------------------------------------------------------------------

    async def _dispatch_async(self, envelope) -> DispatchResult:
        """
        Enqueue an ExecutionRun for webhook / internal events.

        Falls back to direct in-process execution if arq is not available.
        """
        try:
            from src.gateway.gateway_config import settings
            import redis.asyncio as aioredis
            from arq.connections import RedisSettings, create_pool

            redis_settings = RedisSettings.from_dsn(settings.REDIS_URL)
            arq_pool = await create_pool(redis_settings)

            job = await arq_pool.enqueue_job(
                "process_gateway_event",
                envelope.to_dict(),
            )
            await arq_pool.aclose()

            job_id = job.job_id if job else "queued"
            logger.info(f"[Dispatcher] Enqueued gateway event job {job_id}")
            return DispatchResult(accepted=True, mode="async_job", job_id=job_id)

        except Exception as exc:
            logger.warning(
                f"[Dispatcher] arq enqueue failed ({exc}); falling back to in-process dispatch"
            )
            # Fire-and-forget in-process fallback
            asyncio.create_task(self._execute_in_process(envelope))
            return DispatchResult(accepted=True, mode="async_job", job_id="in_process")

    async def _execute_in_process(self, envelope) -> None:
        """
        In-process fallback execution when arq is unavailable.

        For 'lead.created' events from CRM webhooks, routes directly
        to the persistent lead_queue instead of generic execution.
        For all other events, creates an ExecutionRun as before.
        """
        try:
            from src.common.database import AsyncSessionLocal
            from src.ai.models import HierarchicalEntity, ExecutionRun, RunStatus
            from sqlalchemy import select

            async with AsyncSessionLocal() as db:
                company_id = UUID(envelope.client_id)

                # --- Lead Queue path (CRM lead.created events) ---
                if envelope.event_type in ("lead.created", "lead_created"):
                    await self._enqueue_lead(db, envelope, company_id)
                    return

                # --- Standard execution path (all other events) ---
                # Check for entity_id targeting a specific agent
                raw_data = envelope.raw_data or {}
                entity_id = raw_data.get("entity_id", "")

                if entity_id:
                    try:
                        result = await db.execute(
                            select(HierarchicalEntity).where(
                                HierarchicalEntity.id == UUID(entity_id),
                                HierarchicalEntity.company_id == company_id,
                                HierarchicalEntity.status != 'ARCHIVED',
                            )
                        )
                        agent = result.scalar_one_or_none()
                    except Exception:
                        agent = None
                else:
                    agent = None

                # Fallback: find first active agent for this company
                if not agent:
                    result = await db.execute(
                        select(HierarchicalEntity).where(
                            HierarchicalEntity.company_id == company_id,
                            HierarchicalEntity.status != 'ARCHIVED',
                        ).limit(1)
                    )
                    agent = result.scalar_one_or_none()

                if not agent:
                    logger.warning(
                        f"[Dispatcher] No active agent for company {envelope.client_id}"
                    )
                    return

                run = ExecutionRun(
                    company_id=company_id,
                    entity_id=agent.id,
                    input_data={
                        "input": json.dumps(envelope.raw_data),
                        "channel": envelope.channel,
                        "source": envelope.source,
                        "event_type": envelope.event_type,
                        "correlation_id": envelope.id,
                    },
                    status=RunStatus.PENDING,
                )
                db.add(run)
                await db.commit()
                await db.refresh(run)

                # Execute synchronously in this task via the AgentLoop (the sole
                # run engine; C4 retired the legacy execute_run path).
                from src.gateway.gateway_config import settings
                import redis.asyncio as aioredis
                redis_client = await aioredis.from_url(settings.REDIS_URL)

                from src.ai.core.agent_loop import AgentLoop
                loop = AgentLoop(db, redis_client, company_id=company_id)
                await loop.run(run.id)
                await redis_client.aclose()

        except Exception as exc:
            logger.error(
                f"[Dispatcher] In-process execution failed for event {envelope.id}: {exc}",
                exc_info=True,
            )

    async def _enqueue_lead(self, db, envelope, company_id: UUID) -> None:
        """
        Route a CRM lead.created event to the persistent lead queue.

        Extracts lead data from the envelope and inserts into lead_queue
        with deduplication. The LeadQueueWorker will later pick up the
        entry and place the outbound call.
        """
        from src.ai.lead_queue_service import LeadQueueService
        from src.ai.models import HierarchicalEntity
        from sqlalchemy import select

        raw_data = envelope.raw_data or {}
        properties = raw_data.get("properties", {})
        phone = raw_data.get("phone", "") or properties.get("phone", "")
        lead_id = raw_data.get("lead_id", "") or raw_data.get("object_id", "")

        if not phone:
            logger.warning(
                f"[Dispatcher] lead.created event missing phone number — "
                f"skipping lead {lead_id}"
            )
            return

        # Resolve target agent
        entity_id = raw_data.get("entity_id", "")
        if entity_id:
            try:
                result = await db.execute(
                    select(HierarchicalEntity).where(
                        HierarchicalEntity.id == UUID(entity_id),
                        HierarchicalEntity.company_id == company_id,
                        HierarchicalEntity.status != 'ARCHIVED',
                    )
                )
                agent = result.scalar_one_or_none()
            except Exception:
                agent = None
        else:
            agent = None

        if not agent:
            result = await db.execute(
                select(HierarchicalEntity).where(
                    HierarchicalEntity.company_id == company_id,
                    HierarchicalEntity.status != 'ARCHIVED',
                ).limit(1)
            )
            agent = result.scalar_one_or_none()

        if not agent:
            logger.warning(f"[Dispatcher] No agent for company {company_id} — cannot enqueue lead")
            return

        queue_svc = LeadQueueService(db)
        await queue_svc.enqueue_lead(
            company_id=company_id,
            agent_id=agent.id,
            lead_id=lead_id or str(envelope.id),
            phone=phone,
            lead_data=raw_data.get("raw", raw_data),
            ad_source=raw_data.get("ad_source", "") or properties.get("ad_source", ""),
            project_id=raw_data.get("project_id", "") or properties.get("project_id", ""),
            correlation_id=envelope.id,
        )
        logger.info(
            f"[Dispatcher] Lead {lead_id} enqueued for company {company_id} "
            f"(agent={agent.id})"
        )

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
