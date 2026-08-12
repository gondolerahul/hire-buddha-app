"""
ai.core.events — Telemetry event emitter.

Provides the structured envelope every Phase 11 component emits through,
backed by a Python logger at INFO level by default. Optional sinks:

  * Redis pubsub on ``agent.events`` for SSE relay to the SPA.
  * Async ``capture_test_events()`` buffer for unit tests.
  * OpenTelemetry exporter when ``set_otel_exporter(...)`` is called.

Public surface:

    set_redis(client)              — wire in a Redis client (optional)
    set_otel_exporter(fn)          — wire in an OTel-compatible exporter
    capture_test_events()          — context manager: yields a fresh
                                     list of records emitted inside the
                                     block. Nested contexts do NOT bleed.
    event(name, **kwargs)          — fire-and-forget emit (sync)
    aevent(name, **kwargs)         — async variant that also pushes to Redis
    emit(event, severity=, ...)    — explicit form returning a TelemetryEvent

Naming convention:
    ``agent.<layer>.<verb>[_<qualifier>]`` — see the agent kernel EVENTS reference.

Structured kwargs accepted by every emit:
    company_id, user_id, run_id, entity_id, iteration, severity.
Everything else is folded into ``payload``.
"""
from __future__ import annotations

import json
import logging
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Iterator, Literal, Optional
from uuid import UUID

logger = logging.getLogger("agent.events")

Severity = Literal["debug", "info", "warn", "error"]

_RESERVED_KEYS = {
    "company_id", "user_id", "run_id", "entity_id",
    "iteration", "severity",
}

# Module-level state
_REDIS: Any = None
_OTEL_EXPORTER: Optional[Callable[["TelemetryEvent"], None]] = None
_CAPTURE_STACK: list[list["EventRecord"]] = []
_REDIS_CHANNEL = "agent.events"

__all__ = [
    "EventRecord",
    "TelemetryEvent",
    "set_redis",
    "set_otel_exporter",
    "capture_test_events",
    "event",
    "aevent",
    "emit",
]


@dataclass
class TelemetryEvent:
    """Structured envelope shared by every Phase 11 event."""

    event: str
    ts: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    company_id: Optional[UUID] = None
    user_id: Optional[UUID] = None
    run_id: Optional[UUID] = None
    entity_id: Optional[UUID] = None
    iteration: Optional[int] = None
    payload: dict[str, Any] = field(default_factory=dict)
    severity: Severity = "info"

    def to_dict(self) -> dict[str, Any]:
        return {
            "event": self.event,
            "ts": self.ts.isoformat() if self.ts else None,
            "company_id": str(self.company_id) if self.company_id else None,
            "user_id": str(self.user_id) if self.user_id else None,
            "run_id": str(self.run_id) if self.run_id else None,
            "entity_id": str(self.entity_id) if self.entity_id else None,
            "iteration": self.iteration,
            "severity": self.severity,
            "payload": self.payload,
        }


@dataclass
class EventRecord:
    """Lightweight legacy record kept for callers that don't need the
    full envelope (mostly ``capture_test_events()`` consumers)."""

    name: str
    payload: dict[str, Any] = field(default_factory=dict)
    ts: float = field(default_factory=time.time)
    severity: Severity = "info"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name, "payload": self.payload,
            "ts": self.ts, "severity": self.severity,
        }


def set_redis(client: Any) -> None:
    """Wire in a Redis client. Pass None to disable pubsub."""
    global _REDIS
    _REDIS = client


def set_otel_exporter(fn: Optional[Callable[[TelemetryEvent], None]]) -> None:
    """Register an OTel-compatible exporter. Pass None to disable."""
    global _OTEL_EXPORTER
    _OTEL_EXPORTER = fn


@contextmanager
def capture_test_events() -> Iterator[list[Any]]:
    """Capture events emitted inside the ``with`` block.

    Each invocation pushes its own buffer onto the capture stack;
    nested captures do NOT see each other's events (the innermost
    capture wins for each emit). After the block exits, the yielded
    list keeps its captured contents so the caller can assert.
    """
    captured: list[EventRecord] = []
    _CAPTURE_STACK.append(captured)
    try:
        yield captured
    finally:
        # Pop our buffer regardless of exceptions.
        if _CAPTURE_STACK and _CAPTURE_STACK[-1] is captured:
            _CAPTURE_STACK.pop()


_SEV_LOG_LEVEL: dict[str, int] = {
    "debug": logging.DEBUG,
    "info":  logging.INFO,
    "warn":  logging.WARNING,
    "error": logging.ERROR,
}


def _build_envelope(name: str, kwargs: dict[str, Any]) -> TelemetryEvent:
    """Split structured keys out of kwargs and fold the rest into payload."""
    structured = {k: kwargs.pop(k) for k in list(kwargs) if k in _RESERVED_KEYS}
    payload = _sanitize(kwargs)
    severity = str(structured.get("severity", "info")).lower()
    if severity not in _SEV_LOG_LEVEL:
        severity = "info"
    return TelemetryEvent(
        event=name,
        company_id=_as_uuid(structured.get("company_id")),
        user_id=_as_uuid(structured.get("user_id")),
        run_id=_as_uuid(structured.get("run_id")),
        entity_id=_as_uuid(structured.get("entity_id")),
        iteration=structured.get("iteration"),
        severity=severity,            # type: ignore[arg-type]
        payload=payload,
    )


def _as_uuid(val: Any) -> Optional[UUID]:
    if val is None or isinstance(val, UUID):
        return val
    try:
        return UUID(str(val))
    except (TypeError, ValueError):
        return None


def emit(
    name: str,
    *,
    severity: Severity = "info",
    company_id: Any = None,
    user_id: Any = None,
    run_id: Any = None,
    entity_id: Any = None,
    iteration: Optional[int] = None,
    payload: Optional[dict[str, Any]] = None,
) -> TelemetryEvent:
    """Explicit emit returning the full ``TelemetryEvent`` envelope.

    Preferred for new code; ``event()`` and ``aevent()`` are kept for
    backwards compatibility with existing call sites.
    """
    ev = TelemetryEvent(
        event=name,
        severity=severity,
        company_id=_as_uuid(company_id),
        user_id=_as_uuid(user_id),
        run_id=_as_uuid(run_id),
        entity_id=_as_uuid(entity_id),
        iteration=iteration,
        payload=_sanitize(payload or {}),
    )
    _publish_local(ev)
    return ev


def _record_payload(ev: TelemetryEvent, raw_kwargs: dict[str, Any]) -> dict[str, Any]:
    """Back-compat: include structured envelope fields in EventRecord.payload
    so legacy assertions like ``rec.payload["run_id"]`` still pass.

    The TelemetryEvent envelope remains the structured source of truth
    for OTel / Redis fan-out.
    """
    out = dict(ev.payload)
    for k in _RESERVED_KEYS - {"severity"}:
        if k in raw_kwargs and raw_kwargs[k] is not None:
            out[k] = str(raw_kwargs[k]) if not isinstance(raw_kwargs[k], int) else raw_kwargs[k]
    return out


def event(name: str, **kwargs: Any) -> EventRecord:
    """Fire-and-forget emit. Backwards-compatible interface.

    Structured keys (``company_id``, ``run_id``, ``severity``, etc.) are
    split into the ``TelemetryEvent`` envelope; everything else is
    sanitised into ``payload``.
    """
    raw = dict(kwargs)
    ev = _build_envelope(name, dict(kwargs))
    _publish_local(ev)
    rec = EventRecord(
        name=ev.event, payload=_record_payload(ev, raw), severity=ev.severity,
    )
    if _CAPTURE_STACK:
        _CAPTURE_STACK[-1].append(rec)
    return rec


async def aevent(name: str, **kwargs: Any) -> EventRecord:
    """Async emit that also publishes to Redis pubsub when registered."""
    raw = dict(kwargs)
    ev = _build_envelope(name, dict(kwargs))
    _publish_local(ev)
    rec = EventRecord(
        name=ev.event, payload=_record_payload(ev, raw), severity=ev.severity,
    )
    if _CAPTURE_STACK:
        _CAPTURE_STACK[-1].append(rec)
    if _REDIS is not None:
        try:
            await _REDIS.publish(
                _REDIS_CHANNEL,
                json.dumps(ev.to_dict(), default=str),
            )
        except Exception as exc:                                              # pragma: no cover
            logger.warning("event publish to Redis failed: %s", exc)
    return rec


def _publish_local(ev: TelemetryEvent) -> None:
    """Log + dispatch to OTel exporter (if registered)."""
    level = _SEV_LOG_LEVEL.get(ev.severity, logging.INFO)
    logger.log(
        level, "EVT %s %s", ev.event,
        json.dumps(ev.payload, default=str),
    )
    if _OTEL_EXPORTER is not None:
        try:
            _OTEL_EXPORTER(ev)
        except Exception as exc:                                              # pragma: no cover
            logger.warning("OTel exporter failed: %s", exc)


def _sanitize(payload: dict[str, Any]) -> dict[str, Any]:
    """Best-effort JSON-friendliness so the logger doesn't choke."""
    safe: dict[str, Any] = {}
    for k, v in payload.items():
        if hasattr(v, "to_dict") and callable(v.to_dict):
            try:
                safe[k] = v.to_dict()
                continue
            except Exception:
                pass
        if isinstance(v, (str, int, float, bool, type(None))):
            safe[k] = v
        elif isinstance(v, (list, tuple)):
            safe[k] = [str(x) for x in v]
        elif isinstance(v, dict):
            safe[k] = {
                str(kk): vv if isinstance(vv, (str, int, float, bool, type(None))) else str(vv)
                for kk, vv in v.items()
            }
        else:
            safe[k] = str(v)
    return safe
