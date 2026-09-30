"""
Interface 3: Unified Internal Event Endpoint.

Single endpoint: POST /internal/event

Strictly for internal microservices (agents, cron jobs, vector DB, etc.).
Authentication: X-Internal-Token shared secret (``require_internal``).

Event types (examples):
  doc_indexed   — vector DB finished indexing a document
  timer.*       — cron-triggered events (daily summary, weekly report)
  agent.signal  — one agent sending a signal/result to another
  build.done    — CI/CD or code pipeline completed
  custom.*      — any custom internal event
"""
# No ``from __future__ import annotations`` — see webhook_inbound.py.
import hmac
import logging
import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from src.common.config import settings
from src.common.rate_limit import limiter
from src.gateway.envelope import EventEnvelope, queue_event

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Internal Events"])


def require_internal(x_internal_token: str = Header(default="")) -> None:
    """Only a caller holding ``INTERNAL_TOKEN`` may post an internal event.

    With no real token configured (empty, or a placeholder such as
    ``change-me-in-production``) the endpoint is disabled: 503 for everyone,
    instead of accepting a secret that ships in the repository (SA-20).
    """
    if not settings.internal_events_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Internal events are disabled: INTERNAL_TOKEN is not set to a real secret",
        )
    if not hmac.compare_digest(x_internal_token.encode(), settings.INTERNAL_TOKEN.encode()):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing X-Internal-Token",
        )


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
        min_length=1,
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
        "Returns 202 once the event is queued for the worker; 503 if it "
        "cannot be queued. Processing is async."
    ),
    responses={503: {"description": "The event could not be queued; retry"}},
)
@limiter.exempt
async def unified_internal_event(
    event: InternalEvent,
    _: None = Depends(require_internal),
):
    """
    Unified Internal Event Receiver — Interface 3.

    Receives typed events from internal systems (DB, cron, agents).
    Authentication enforced via X-Internal-Token (``require_internal``).
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

    try:
        await queue_event(envelope)
    except Exception:
        logger.exception(f"[InternalEvent] Could not queue event {correlation_id}")
        return JSONResponse(status_code=503, content={
            "status": "unavailable",
            "correlation_id": correlation_id,
            "event_type": event.event_type,
            "queued": False,
        })

    return InternalEventResponse(
        status="accepted",
        correlation_id=correlation_id,
        event_type=event.event_type,
        queued=True,
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
    Helper for other platform services (API or worker) to emit an internal
    event without going through the HTTP endpoint: queues it straight onto
    arq, like the endpoint does. Raises if Redis cannot take it.

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
    await queue_event(envelope)
    return correlation_id
