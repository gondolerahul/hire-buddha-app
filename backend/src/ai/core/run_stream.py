"""ai.core.run_stream — the frames a run's live page reads, and how each is sent.

Every frame the run page shows — iteration events, trace spans, step text,
HITL notices, cancellation — is published here, on the run's channel
``execution:{run_id}``, which ``GET /api/v1/ai/executions/{id}/stream``
relays to the browser.

A frame that ends the run carries ``"terminal": true``, and the stream stops
on that field, not on what a payload happens to contain (GW-19): a tool
result or a child's status reading ``"status": "COMPLETED"`` used to close
the parent's stream mid-run, and a ``PARTIAL_COMPLETE`` run's stream never
closed at all.
"""
from __future__ import annotations

import json
from typing import Any, Mapping, Union

from src.ai.schemas.enums import TERMINAL_RUN_STATUSES

__all__ = ["channel", "publish_run_event", "is_terminal", "is_terminal_status"]


def channel(run_id: Any) -> str:
    return f"execution:{run_id}"


def is_terminal_status(status: Any) -> bool:
    """A run in this status is finished: nothing more will be published."""
    return str(status) in TERMINAL_RUN_STATUSES


async def publish_run_event(redis: Any, run_id: Any, body: Mapping[str, Any], *,
                            terminal: bool = False) -> None:
    """Publish one frame on the run's channel; ``terminal`` marks the last one.

    Raises what the Redis client raises: every caller treats the live view as
    best effort and catches it.
    """
    frame = dict(body)
    if terminal:
        frame["terminal"] = True
    await redis.publish(channel(run_id), json.dumps(frame, default=str))


def is_terminal(data: Union[str, bytes]) -> bool:
    """Whether a published frame is the run's last."""
    try:
        frame = json.loads(data)
    except (TypeError, ValueError):
        return False
    return isinstance(frame, dict) and frame.get("terminal") is True
