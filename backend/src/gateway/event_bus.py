"""
Async Event Bus — In-process implementation using asyncio.Queue.

Design:
  - Single global bus per process
  - Multiple concurrent consumers (each gets its own copy via fan-out)
  - Pluggable backend: swap memory → Kafka by changing EventBus.backend

EventEnvelope schema:
  {
      "id":          str UUID,
      "timestamp":   ISO-8601 str,
      "channel":     "webhook" | "internal" | "audio" | "video" | "rest",
      "source":      "email" | "crm" | "linkedin" | "timer" | "agent" | ...,
      "client_id":   str  (company/tenant UUID),
      "event_type":  str  (e.g. "new_email", "doc_indexed", "call_started"),
      "raw_data":    dict,
      "metadata":    dict (headers, correlation_id, etc.)
  }
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# EventEnvelope — the normalized event structure
# ---------------------------------------------------------------------------

@dataclass
class EventEnvelope:
    """Normalized event that flows through the unified gateway."""

    channel: str          # "webhook" | "internal" | "audio" | "video" | "rest"
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


# ---------------------------------------------------------------------------
# In-process fan-out event bus
# ---------------------------------------------------------------------------

class InMemoryEventBus:
    """
    In-process async event bus using asyncio.Queue fan-out pattern.

    Multiple subscribers (consumer coroutines) each receive every event.
    Designed with a Kafka-compatible interface so the backend can be swapped.
    """

    def __init__(self, maxsize: int = 1000) -> None:
        self._consumers: List[asyncio.Queue] = []
        self._maxsize = maxsize
        self._total_published = 0
        self._total_dropped = 0

    async def publish(self, envelope: EventEnvelope) -> None:
        """Fan-out event to all registered consumers."""
        self._total_published += 1
        if not self._consumers:
            logger.debug(
                f"[EventBus] No consumers registered; event '{envelope.event_type}' dropped"
            )
            self._total_dropped += 1
            return

        for q in list(self._consumers):
            try:
                q.put_nowait(envelope)
            except asyncio.QueueFull:
                logger.warning(
                    f"[EventBus] Consumer queue full; dropping event '{envelope.id}'"
                )
                self._total_dropped += 1

    def subscribe(self) -> "EventBusSubscription":
        """Return a subscription context manager for a consumer."""
        return EventBusSubscription(self)

    def _register(self, q: asyncio.Queue) -> None:
        self._consumers.append(q)
        logger.info(f"[EventBus] Consumer registered ({len(self._consumers)} total)")

    def _unregister(self, q: asyncio.Queue) -> None:
        try:
            self._consumers.remove(q)
        except ValueError:
            pass
        logger.info(f"[EventBus] Consumer unregistered ({len(self._consumers)} total)")

    @property
    def stats(self) -> dict:
        return {
            "consumer_count": len(self._consumers),
            "total_published": self._total_published,
            "total_dropped": self._total_dropped,
        }


class EventBusSubscription:
    """
    Async context manager for an event bus consumer.

    Usage:
        async with event_bus.subscribe() as sub:
            async for envelope in sub:
                await process(envelope)
    """

    def __init__(self, bus: InMemoryEventBus) -> None:
        self._bus = bus
        self._queue: Optional[asyncio.Queue] = None

    async def __aenter__(self) -> "EventBusSubscription":
        self._queue = asyncio.Queue(maxsize=self._bus._maxsize)
        self._bus._register(self._queue)
        return self

    async def __aexit__(self, *args) -> None:
        if self._queue:
            self._bus._unregister(self._queue)
            self._queue = None

    def __aiter__(self) -> "EventBusSubscription":
        return self

    async def __anext__(self) -> EventEnvelope:
        if self._queue is None:
            raise StopAsyncIteration
        return await self._queue.get()


# ---------------------------------------------------------------------------
# Global singleton — imported by all gateway components
# ---------------------------------------------------------------------------

_bus: Optional[InMemoryEventBus] = None


def get_event_bus() -> InMemoryEventBus:
    """Return (and lazily create) the global event bus instance."""
    global _bus
    if _bus is None:
        from src.gateway.gateway_config import settings
        _bus = InMemoryEventBus(maxsize=settings.EVENT_BUS_MAXSIZE)
        logger.info("[EventBus] In-memory event bus initialized")
    return _bus
