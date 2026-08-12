"""ai.core.trace — Per-run execution trace recorder (transparency spans).

This is the linchpin of the "what happened inside each iteration" feature. A
single :class:`TraceRecorder` is bound to a ``ContextVar`` for the duration of a
run (see ``core/arq_jobs.py``), so *any* code in the call stack — including the
``@staticmethod`` tool executor and the LLM router, which receive no run context
in their signatures — can open/close spans through the ambient recorder:

    async with span("tool", tool_id, input=raw_input) as sp:
        result = await ToolExecutor.execute_tools(...)
        sp.set_output(result)

Each span does two things:

  * **Live sink** — publishes ``span_open`` / ``span_close`` to the existing
    ``execution:{run_id}`` Redis channel the SSE endpoint relays to the SPA
    (same envelope contract as ``agent_loop.event_async``).
  * **Historical sink** — persists one ``execution_trace_events`` row on close
    (full payload), on a *dedicated* short-lived ``AsyncSessionLocal`` so a
    trace write can never corrupt the run's own session. Best-effort: any
    failure is swallowed.

Parent linkage is tracked via a second ContextVar (``_CURRENT_SPAN``), which
asyncio copies per task — so concurrent DAG branches nest correctly without a
shared mutable stack.

When no recorder is bound (unit tests, non-run callers), ``span()`` is a no-op
context manager and the deep layers behave exactly as before.
"""
from __future__ import annotations

import json
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from contextvars import ContextVar
from datetime import datetime
from decimal import Decimal
from typing import Any, AsyncIterator, Optional
from uuid import UUID

logger = logging.getLogger(__name__)

__all__ = [
    "TraceRecorder",
    "SpanHandle",
    "set_recorder",
    "current_recorder",
    "span",
]

# Per-field payload safety ceiling. Full capture is the default; this only
# guards against a single pathological multi-MB blob (a scraped page, a base64
# image) exceeding sane row sizes.
TRACE_MAX_FIELD_BYTES = int(os.getenv("TRACE_MAX_FIELD_BYTES", str(1 * 1024 * 1024)))

_RECORDER: ContextVar[Optional["TraceRecorder"]] = ContextVar(
    "hb_trace_recorder", default=None
)
_CURRENT_SPAN: ContextVar[Optional[UUID]] = ContextVar(
    "hb_trace_current_span", default=None
)


def current_recorder() -> Optional["TraceRecorder"]:
    """Return the recorder bound to the current run, or ``None``."""
    return _RECORDER.get()


class set_recorder:
    """Context manager that binds a recorder for a run.

    Usage::

        with set_recorder(TraceRecorder(run_id, company_id, redis)):
            await loop.run(run_id)
    """

    def __init__(self, recorder: Optional["TraceRecorder"]):
        self._recorder = recorder
        self._token: Any = None

    def __enter__(self) -> Optional["TraceRecorder"]:
        self._token = _RECORDER.set(self._recorder)
        return self._recorder

    def __exit__(self, *exc: Any) -> None:
        if self._token is not None:
            _RECORDER.reset(self._token)


class SpanHandle:
    """Mutable handle yielded by :func:`span`; lets the body attach outputs,
    cost, tokens, child-run links, and an explicit status before close."""

    __slots__ = (
        "span_id", "parent_span_id", "kind", "name", "iteration", "seq",
        "started_at", "_start_perf", "payload", "status", "cost_usd",
        "tokens_in", "tokens_out", "child_run_id", "error_message",
    )

    def __init__(
        self,
        *,
        span_id: UUID,
        parent_span_id: Optional[UUID],
        kind: str,
        name: Optional[str],
        iteration: Optional[int],
        seq: int,
        payload: dict[str, Any],
    ):
        self.span_id = span_id
        self.parent_span_id = parent_span_id
        self.kind = kind
        self.name = name
        self.iteration = iteration
        self.seq = seq
        self.started_at = datetime.utcnow()
        self._start_perf = time.perf_counter()
        self.payload: dict[str, Any] = dict(payload or {})
        self.status: str = "running"
        self.cost_usd: Optional[Decimal] = None
        self.tokens_in: Optional[int] = None
        self.tokens_out: Optional[int] = None
        self.child_run_id: Optional[UUID] = None
        self.error_message: Optional[str] = None

    # ---- body-facing setters -------------------------------------------------

    def set_output(self, value: Any, key: str = "output") -> None:
        self.payload[key] = value

    def update(self, **fields: Any) -> None:
        self.payload.update(fields)

    def set_cost(self, cost_usd: Any) -> None:
        try:
            self.cost_usd = Decimal(str(cost_usd))
        except Exception:
            pass

    def set_tokens(self, tokens_in: Optional[int] = None,
                   tokens_out: Optional[int] = None) -> None:
        if tokens_in is not None:
            self.tokens_in = int(tokens_in)
        if tokens_out is not None:
            self.tokens_out = int(tokens_out)

    def set_child_run_id(self, run_id: Any) -> None:
        try:
            self.child_run_id = UUID(str(run_id))
        except Exception:
            pass

    def set_error(self, message: str) -> None:
        self.status = "error"
        self.error_message = str(message)[:4000]

    @property
    def duration_ms(self) -> int:
        return int((time.perf_counter() - self._start_perf) * 1000)


class TraceRecorder:
    """Records spans for one run to Redis (live) + Postgres (historical)."""

    def __init__(
        self,
        run_id: Any,
        company_id: Any = None,
        redis: Any = None,
        *,
        capture_payloads: bool = True,
    ):
        self.run_id = _coerce_uuid(run_id)
        self.company_id = _coerce_uuid(company_id)
        self.redis = redis
        # When False, span metadata is recorded but verbose payloads
        # (prompts, responses, tool I/O) are dropped. Wired to the entity's
        # ``observability.log_thoughts`` flag by the loop.
        self.capture_payloads = capture_payloads
        self.iteration: Optional[int] = None
        self._seq = 0

    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq

    # ------------------------------------------------------------------
    # Span open / close
    # ------------------------------------------------------------------

    async def open(
        self,
        kind: str,
        name: Optional[str],
        *,
        parent_span_id: Optional[UUID],
        iteration: Optional[int],
        payload: dict[str, Any],
    ) -> SpanHandle:
        handle = SpanHandle(
            span_id=uuid.uuid4(),
            parent_span_id=parent_span_id,
            kind=kind,
            name=name,
            iteration=iteration if iteration is not None else self.iteration,
            seq=self._next_seq(),
            payload=payload if self.capture_payloads else {},
        )
        await self._publish("span_open", handle)
        return handle

    async def close(self, handle: SpanHandle) -> None:
        if handle.status == "running":
            handle.status = "success"
        await self._publish("span_close", handle)
        await self._persist(handle)

    # ------------------------------------------------------------------
    # Sinks
    # ------------------------------------------------------------------

    def _envelope(self, type_: str, h: SpanHandle) -> dict[str, Any]:
        return {
            "type": type_,
            "span_id": str(h.span_id),
            "parent_span_id": str(h.parent_span_id) if h.parent_span_id else None,
            "kind": h.kind,
            "name": h.name,
            "iteration": h.iteration,
            "seq": h.seq,
            "status": h.status,
            "duration_ms": h.duration_ms if type_ == "span_close" else None,
            "cost_usd": float(h.cost_usd) if h.cost_usd is not None else None,
            "tokens_in": h.tokens_in,
            "tokens_out": h.tokens_out,
            "child_run_id": str(h.child_run_id) if h.child_run_id else None,
            "payload": _cap_payload(h.payload) if self.capture_payloads else {},
            "error": h.error_message,
        }

    async def _publish(self, type_: str, handle: SpanHandle) -> None:
        if self.redis is None or self.run_id is None:
            return
        try:
            body = json.dumps(self._envelope(type_, handle), default=str)
            await self.redis.publish(f"execution:{self.run_id}", body)
        except Exception as exc:                                            # pragma: no cover
            logger.debug("trace SSE publish failed (%s): %s", type_, exc)

    async def _persist(self, handle: SpanHandle) -> None:
        """Write one finished span row on its own session (best-effort)."""
        if self.run_id is None:
            return
        try:
            from src.ai.orm.trace import ExecutionTraceEvent
            from src.common.database import AsyncSessionLocal

            row = ExecutionTraceEvent(
                run_id=self.run_id,
                company_id=self.company_id,
                span_id=handle.span_id,
                parent_span_id=handle.parent_span_id,
                iteration=handle.iteration,
                kind=handle.kind,
                name=(handle.name or "")[:512] or None,
                status=handle.status,
                seq=handle.seq,
                started_at=handle.started_at,
                ended_at=datetime.utcnow(),
                duration_ms=handle.duration_ms,
                cost_usd=handle.cost_usd,
                tokens_in=handle.tokens_in,
                tokens_out=handle.tokens_out,
                child_run_id=handle.child_run_id,
                payload=_cap_payload(handle.payload) if self.capture_payloads else None,
                error_message=handle.error_message,
            )
            async with AsyncSessionLocal() as db:
                db.add(row)
                await db.commit()
        except Exception as exc:                                            # pragma: no cover
            logger.debug("trace persist failed: %s", exc)


# ---------------------------------------------------------------------------
# Public ambient API
# ---------------------------------------------------------------------------


@asynccontextmanager
async def span(
    kind: str,
    name: Optional[str] = None,
    *,
    parent_span_id: Optional[UUID] = None,
    iteration: Optional[int] = None,
    **payload: Any,
) -> AsyncIterator[Any]:
    """Open a span around a block of work. No-op when no recorder is bound.

    ``parent`` defaults to the innermost open span in the current async task
    (tracked via a ContextVar that asyncio copies per task, so concurrent DAG
    branches nest correctly).
    """
    recorder = _RECORDER.get()
    if recorder is None:
        # Null span: yield a detached handle so call sites can still use the
        # setter API unconditionally.
        yield SpanHandle(
            span_id=uuid.uuid4(), parent_span_id=None, kind=kind, name=name,
            iteration=iteration, seq=0, payload={},
        )
        return

    parent = parent_span_id if parent_span_id is not None else _CURRENT_SPAN.get()
    handle = await recorder.open(
        kind, name, parent_span_id=parent, iteration=iteration, payload=payload,
    )
    token = _CURRENT_SPAN.set(handle.span_id)
    try:
        yield handle
    except Exception as exc:
        handle.set_error(f"{type(exc).__name__}: {exc}")
        raise
    finally:
        _CURRENT_SPAN.reset(token)
        await recorder.close(handle)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _coerce_uuid(val: Any) -> Optional[UUID]:
    if val is None or isinstance(val, UUID):
        return val
    try:
        return UUID(str(val))
    except (TypeError, ValueError):
        return None


def _cap_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """JSON-friendly + per-field size cap. Returns a NEW dict."""
    out: dict[str, Any] = {}
    for k, v in (payload or {}).items():
        out[str(k)] = _cap_value(v)
    return out


def _cap_value(v: Any) -> Any:
    try:
        encoded = v if isinstance(v, str) else json.dumps(v, default=str)
    except Exception:
        encoded = str(v)
    raw = encoded if isinstance(encoded, str) else str(encoded)
    if len(raw.encode("utf-8", "ignore")) > TRACE_MAX_FIELD_BYTES:
        return {
            "_truncated": True,
            "_original_bytes": len(raw.encode("utf-8", "ignore")),
            "preview": raw[: 4096],
        }
    # Keep JSON-native structures as-is when small enough; fall back to the
    # encoded string for exotic objects.
    if isinstance(v, (str, int, float, bool, type(None), list, dict)):
        return v
    return raw
