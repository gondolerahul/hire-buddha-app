"""
Interface 3: Unified Internal Event Endpoint.

Single endpoint: POST /internal/event

Strictly for internal microservices (agents, cron jobs, vector DB, etc.).
Authentication: X-Internal-Token shared secret (enforced by middleware).

Event types (examples):
  doc_indexed   — vector DB finished indexing a document
  timer.*       — cron-triggered events (daily summary, weekly report)
  agent.signal  — one agent sending a signal/result to another
  build.done    — CI/CD or code pipeline completed
  custom.*      — any custom internal event
"""
from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from pydantic import BaseModel, Field

from src.gateway.auth_middleware import require_internal, TenantContext
from src.gateway.event_bus import EventEnvelope, get_event_bus

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Internal Events"])


# ===========================================================================
# Request schema
# ===========================================================================

class InternalEvent(BaseModel):
    """Typed schema for internal event payloads."""

    event_type: str = Field(
        ...,
        description=(
            "Dot-namespaced event type. "
            "Examples: 'doc_indexed', 'timer.daily_summary', 'agent.signal'"
        ),
        examples=["doc_indexed", "timer.daily_summary", "agent.signal"],
    )
    client_id: str = Field(
        ...,
        description="Company / tenant UUID for routing to the correct AI agent",
    )
    source: str = Field(
        ...,
        description="Originating system. Examples: 'vector_db', 'cron', 'agent:<uuid>'",
        examples=["vector_db", "cron", "agent:abc123"],
    )
    payload: Dict[str, Any] = Field(
        default_factory=dict,
        description="Event payload data (arbitrary JSON)",
    )
    priority: int = Field(
        default=5,
        ge=1,
        le=10,
        description="Priority 1 (highest) to 10 (lowest). Default: 5",
    )
    correlation_id: Optional[str] = Field(
        default=None,
        description="Optional correlation ID for tracing (auto-generated if omitted)",
    )


class InternalEventResponse(BaseModel):
    status: str
    correlation_id: str
    event_type: str
    queued: bool


# ===========================================================================
# Endpoint
# ===========================================================================

@router.post(
    "/internal/event",
    response_model=InternalEventResponse,
    status_code=202,
    summary="Internal Event Endpoint — Interface 3",
    description=(
        "Accepts events from internal microservices. "
        "Requires X-Internal-Token authentication header. "
        "Returns 202 immediately; processing is async."
    ),
)
async def unified_internal_event(
    event: InternalEvent,
    background_tasks: BackgroundTasks,
    tenant: TenantContext = Depends(require_internal),
):
    """
    Unified Internal Event Receiver — Interface 3.

    Receives typed events from internal systems (DB, cron, agents).
    Authentication enforced via X-Internal-Token (checked by middleware).
    """
    correlation_id = event.correlation_id or str(uuid.uuid4())

    logger.info(
        f"[InternalEvent] Received {event.event_type} from {event.source} "
        f"for client={event.client_id} priority={event.priority} "
        f"correlation={correlation_id}"
    )

    envelope = EventEnvelope(
        channel="internal",
        source=event.source,
        client_id=event.client_id,
        event_type=event.event_type,
        raw_data=event.payload,
        metadata={
            "priority": event.priority,
            "correlation_id": correlation_id,
        },
        id=correlation_id,
    )

    queued = True
    try:
        background_tasks.add_task(_publish_event, envelope)
    except Exception as exc:
        logger.error(f"[InternalEvent] Failed to queue event {correlation_id}: {exc}")
        queued = False

    return InternalEventResponse(
        status="accepted",
        correlation_id=correlation_id,
        event_type=event.event_type,
        queued=queued,
    )


# ===========================================================================
# Well-known Internal Event types — helpers used by other platform services
# ===========================================================================

class WellKnownEvents:
    """Constants for well-known internal event types."""

    DOC_INDEXED = "doc_indexed"
    TIMER_DAILY = "timer.daily_summary"
    TIMER_WEEKLY = "timer.weekly_report"
    AGENT_SIGNAL = "agent.signal"
    CAMPAIGN_DONE = "campaign.done"
    BUILD_DONE = "build.done"


async def emit_internal_event(
    event_type: str,
    client_id: str,
    source: str,
    payload: Dict[str, Any],
    priority: int = 5,
) -> str:
    """
    Helper for other platform services to emit internal events without
    going through the HTTP endpoint (direct in-process publish).

    Returns the correlation_id.
    """
    correlation_id = str(uuid.uuid4())
    envelope = EventEnvelope(
        channel="internal",
        source=source,
        client_id=client_id,
        event_type=event_type,
        raw_data=payload,
        metadata={"priority": priority, "correlation_id": correlation_id},
        id=correlation_id,
    )
    bus = get_event_bus()
    await bus.publish(envelope)
    return correlation_id


async def _publish_event(envelope: EventEnvelope) -> None:
    """Background task: publish to event bus."""
    try:
        bus = get_event_bus()
        await bus.publish(envelope)
        logger.info(f"[InternalEvent] Published {envelope.event_type} ({envelope.id})")
    except Exception as exc:
        logger.error(f"[InternalEvent] Publish failed: {exc}")
