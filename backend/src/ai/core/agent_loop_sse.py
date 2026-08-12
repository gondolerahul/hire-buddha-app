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

import json
import logging
from typing import Any

from src.ai.core.events import event

logger = logging.getLogger(__name__)

__all__ = ["set_sse_redis", "event_async"]

_SSE_REDIS: Any = None

# Internal event name → frontend reducer ``type``.
_SSE_EVENT_TYPES: dict[str, str] = {
    "agent.loop.iteration_start": "iteration_start",
    "agent.loop.iteration_end": "iteration_end",
    "agent.loop.resume": "resume",
    "agent.critic.pre_verdict": "critic_pre",
    "agent.critic.post_verdict": "critic_post",
    "agent.critic.alignment": "critic_align",
    "agent.critic.supervisor": "critic_super",
    "agent.retry.picked": "retry_picked",
    "agent.retry.dequeued": "retry_dequeued",
    "agent.loop.replan": "replan_triggered",
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
        # Terminal event: also stamp ``status`` so the SSE generator closes
        # the stream (it breaks on a COMPLETED/FAILED status payload).
        if sse_type == "run_end" and "outcome" in body:
            body["status"] = body["outcome"]
        await _SSE_REDIS.publish(
            f"execution:{run_id}", json.dumps(body, default=str),
        )
    except Exception as exc:                                               # pragma: no cover
        logger.warning("AgentLoop SSE publish failed for %s: %s", name, exc)
