"""
The normalised inbound event, and how it reaches the worker.

``POST /webhook/inbound`` and ``POST /internal/event`` build an
``EventEnvelope`` and call ``queue_event`` before they answer: the envelope
becomes a ``process_gateway_event`` arq job in Redis, and only then does the
caller get its 202 (SA-09). If Redis cannot take the job the endpoint answers
503, so the provider retries.

Before, the endpoints answered 202 and published to an in-process
``asyncio.Queue`` from a background task. A restart in between lost the event,
an event published while the dispatcher was not subscribed was counted as
"dropped", and when arq was unreachable the dispatcher ran a whole AgentLoop
inside the API process.

EventEnvelope schema:
  {
      "id":          str UUID (the correlation id),
      "timestamp":   ISO-8601 str,
      "channel":     "webhook" | "internal",
      "source":      "email" | "crm" | "linkedin" | "timer" | "agent" | ...,
      "client_id":   str  (company/tenant UUID),
      "event_type":  str  (e.g. "new_email", "doc_indexed", "sheet.row_inserted"),
      "raw_data":    dict,
      "metadata":    dict (headers, correlation_id, etc.)
  }
"""
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict

from src.common.job_queue import enqueue_job

logger = logging.getLogger(__name__)


@dataclass
class EventEnvelope:
    """Normalized event that flows from the ingress endpoints to the worker."""

    channel: str          # "webhook" | "internal"
    source: str           # "email" | "crm.hubspot" | "linkedin" | "timer" | ...
    client_id: str        # Tenant / company UUID string
    event_type: str       # e.g. "new_email", "connection_request", "doc_indexed"
    raw_data: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "timestamp": self.timestamp,
            "channel": self.channel,
            "source": self.source,
            "client_id": self.client_id,
            "event_type": self.event_type,
            "raw_data": self.raw_data,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "EventEnvelope":
        return cls(
            channel=data["channel"],
            source=data["source"],
            client_id=data["client_id"],
            event_type=data["event_type"],
            raw_data=data.get("raw_data", {}),
            metadata=data.get("metadata", {}),
            id=data.get("id", str(uuid.uuid4())),
            timestamp=data.get("timestamp", datetime.now(timezone.utc).isoformat()),
        )


async def queue_event(envelope: EventEnvelope) -> None:
    """Put the envelope on the arq queue as a ``process_gateway_event`` job.

    Raises if Redis cannot take it; the caller turns that into a 503.
    """
    job = await enqueue_job("process_gateway_event", envelope.to_dict())
    logger.info(
        f"[Ingress] Queued {envelope.channel} event {envelope.event_type} "
        f"({envelope.id}) as job {getattr(job, 'job_id', '?')}"
    )
