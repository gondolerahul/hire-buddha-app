"""ai.core.agent_loop_sse — SSE fan-out for AgentLoop telemetry.

AgentLoop telemetry is emitted through :func:`event_async`. Besides the
structured log / OTel sink (``events.event``), each event is republished to the
per-run Redis channel ``execution:{run_id}`` that the SSE endpoint
(``GET /api/v1/ai/executions/{id}/stream``) relays to the browser. The frontend
reducer (``frontend/src/hooks/useExecutionEvents.ts``) switches on a short
``type`` discriminator, so we translate the internal event name to that contract
here.

Extracted from ``agent_loop.py`` (transport ≠ control loop); the loop imports
``event_async`` / ``set_sse_redis`` from here.
"""
from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from contextvars import ContextVar
from typing import Any, AsyncIterator, Optional

from src.ai.core.events import event
from src.ai.core.run_stream import is_terminal_status, publish_run_event

logger = logging.getLogger(__name__)

__all__ = ["set_sse_redis", "event_async", "iteration_batch", "flush_batch", "StepTextStream"]

# An iteration's SSE frames, published together (AK-I9): (run_id, bodies).
# Each iteration used to publish eight or more messages — start, pressure,
# executor invoked/completed, four critics, retries, end — each its own Redis
# publish and JSON encoding; the browser folds them into one slice anyway.
_BATCH: ContextVar[Optional[tuple[str, list[dict[str, Any]]]]] = ContextVar("sse_batch", default=None)

_SSE_REDIS: Any = None
_monotonic = time.monotonic  # one seam for tests

# Internal event name → frontend reducer ``type``. Every key must be a name the
# kernel really emits, and every value a ``case`` in the reducer:
# ``tests/unit/test_sse_event_contract.py`` checks both (AK-11).
_SSE_EVENT_TYPES: dict[str, str] = {
    "agent.loop.iteration_start": "iteration_start",
    "agent.loop.iteration_end": "iteration_end",
    "agent.loop.resumed": "resume",
    "agent.critic.pre_verdict": "critic_pre",
    "agent.critic.post_verdict": "critic_post",
    "agent.critic.alignment": "critic_align",
    "agent.critic.supervisor": "critic_super",
    "agent.retry.picked": "retry_picked",
    "agent.retry.dequeued": "retry_dequeued",
    "agent.replan.triggered": "replan_triggered",
    "agent.bandit.arm_updated": "bandit_arm_updated",
    "agent.task_class.classified": "task_class_classified",
    "agent.cost.charged": "cost_charged",
    "agent.loop.cancelled": "cancelled",
    "agent.loop.run_end": "run_end",
}


def set_sse_redis(client: Any) -> None:
    """Register the redis client used to fan AgentLoop events out to the
    per-run ``execution:{run_id}`` SSE channel.

    Idempotent and safe to call once per run. Concurrent runs publish to
    distinct channels (keyed by the event's ``run_id``), so sharing one
    client is fine.
    """
    global _SSE_REDIS
    _SSE_REDIS = client


async def event_async(name: str, **payload: Any) -> None:
    # 1. Structured telemetry (log + OTel) — unchanged.
    event(name, **payload)

    # 2. Per-run SSE fan-out so the ExecutionDetail iteration timeline
    #    renders live. Best-effort: a publish failure must never break the
    #    control loop.
    sse_type = _SSE_EVENT_TYPES.get(name)
    run_id = payload.get("run_id")
    if sse_type is None or not run_id or _SSE_REDIS is None:
        return
    try:
        body = {k: v for k, v in payload.items() if k != "run_id"}
        body["type"] = sse_type
        # The run's last frame says so (GW-19): ``run_end`` with a finished
        # outcome (not a suspension), or ``cancelled`` with a finished status.
        terminal = (sse_type == "run_end" and is_terminal_status(body.get("outcome"))
                    or sse_type == "cancelled" and is_terminal_status(body.get("status")))
        batch = _BATCH.get()
        if batch is not None and batch[0] == str(run_id) and sse_type != "run_end" and not terminal:
            batch[1].append(body)
            return
        await publish_run_event(_SSE_REDIS, run_id, body, terminal=terminal)
    except Exception as exc:                                               # pragma: no cover
        logger.warning("AgentLoop SSE publish failed for %s: %s", name, exc)


class StepTextStream:
    """A running step's text, as ``step_delta`` frames on the run's channel (LP-I7).

    Published straight away — not batched with the iteration, not logged, not
    an OTel event: it is a view, and the step's output is recorded when the
    step ends. Throttled to a frame every ``FLUSH_SECONDS`` or ``FLUSH_CHARS``.
    Frames: ``{"type": "step_delta", "step": name, "text": ...}``, ``reset``
    (the text so far is void) and ``done``.
    """

    FLUSH_SECONDS = 0.25
    FLUSH_CHARS = 400

    def __init__(self, run_id: Any, step: str):
        self.run_id = str(run_id)
        self.step = step
        self._buffer: list[str] = []
        self._size = 0
        self._last = 0.0

    @staticmethod
    def enabled() -> bool:
        return _SSE_REDIS is not None

    async def _publish(self, **body: Any) -> None:
        if _SSE_REDIS is None:
            return
        try:
            await publish_run_event(_SSE_REDIS, self.run_id, {"type": "step_delta", "step": self.step, **body})
        except Exception as exc:                                           # pragma: no cover
            logger.debug("step_delta publish failed for %s: %s", self.run_id, exc)

    async def _flush(self) -> None:
        if self._buffer:
            text, self._buffer, self._size = "".join(self._buffer), [], 0
            self._last = _monotonic()
            await self._publish(text=text)

    async def delta(self, text: str) -> None:
        self._buffer.append(text)
        self._size += len(text)
        if self._size >= self.FLUSH_CHARS or _monotonic() - self._last >= self.FLUSH_SECONDS:
            await self._flush()

    async def reset(self) -> None:
        self._buffer, self._size = [], 0
        await self._publish(reset=True)

    async def close(self) -> None:
        await self._flush()
        await self._publish(done=True)


async def flush_batch() -> None:
    """Publish the iteration's buffered frames now, as one ``batch`` message."""
    batch = _BATCH.get()
    if batch is None or not batch[1] or _SSE_REDIS is None:
        return
    run_id, bodies = batch
    events = list(bodies)
    bodies.clear()
    try:
        await publish_run_event(_SSE_REDIS, run_id, {"type": "batch", "events": events})
    except Exception as exc:                                               # pragma: no cover
        logger.warning("AgentLoop SSE batch publish failed for %s: %s", run_id, exc)


@asynccontextmanager
async def iteration_batch(run_id: Any) -> AsyncIterator[None]:
    """Buffer one iteration's SSE frames and publish them as one message
    (AK-I9); the structured log / OTel sink still gets every event at once.
    The loop also flushes when the executor starts, so the browser sees an
    iteration begin before its step finishes."""
    token = _BATCH.set((str(run_id), []))
    try:
        yield
    finally:
        await flush_batch()
        _BATCH.reset(token)

