"""ai.core.run_stream — the frames a run's live page reads, and how each is sent.

Every frame the run page shows — iteration events, trace spans, step text,
HITL notices, cancellation — is appended to the run's Redis stream
``run_events:{run_id}`` (``XADD … MAXLEN ~ 1000``, kept a day after the last
frame). ``GET /api/v1/ai/executions/{id}/stream`` reads it and sends each
frame with its stream id as the SSE ``id:``, so a client that reconnects with
``Last-Event-ID`` gets everything it missed, and one that connects mid-run
gets the run so far (GW-18). It used to be Redis pub/sub: a frame published
while nobody listened was gone, and the run page polled every 3 s to make up
for it.

A frame that ends the run carries ``"terminal": true``, and the stream stops
on that field, not on what a payload happens to contain (GW-19): a tool
result or a child's status reading ``"status": "COMPLETED"`` used to close
the parent's stream mid-run, and a ``PARTIAL_COMPLETE`` run's stream never
closed at all.
"""
from __future__ import annotations

import json
import re
from typing import Any, Mapping, Optional, Union

from src.ai.schemas.enums import TERMINAL_RUN_STATUSES

__all__ = [
    "stream_key", "publish_run_event", "read_run_events", "start_id",
    "is_terminal", "is_terminal_status", "MAXLEN", "TTL_SECONDS",
]

# Frames kept per run (approximate trimming): the page backfills older
# iterations from the trace and health-record endpoints.
MAXLEN = 1000
# How long a run's frames outlive its last one.
TTL_SECONDS = 24 * 3600

_STREAM_ID = re.compile(r"^\d+-\d+$")


def stream_key(run_id: Any) -> str:
    return f"run_events:{run_id}"


def is_terminal_status(status: Any) -> bool:
    """A run in this status is finished: nothing more will be published."""
    return str(status) in TERMINAL_RUN_STATUSES


async def publish_run_event(redis: Any, run_id: Any, body: Mapping[str, Any], *,
                            terminal: bool = False) -> str:
    """Append one frame to the run's stream; ``terminal`` marks the last one.

    Returns the frame's stream id. Raises what the Redis client raises: every
    caller treats the live view as best effort and catches it.
    """
    frame = dict(body)
    if terminal:
        frame["terminal"] = True
    key = stream_key(run_id)
    entry_id = await redis.xadd(key, {"data": json.dumps(frame, default=str)},
                                maxlen=MAXLEN, approximate=True)
    await redis.expire(key, TTL_SECONDS)
    return entry_id.decode() if isinstance(entry_id, bytes) else str(entry_id)


def start_id(last_event_id: Optional[str]) -> str:
    """Where a stream resumes: after the client's last frame, else from the start."""
    if last_event_id and _STREAM_ID.match(last_event_id.strip()):
        return last_event_id.strip()
    return "0-0"


async def read_run_events(redis: Any, run_id: Any, after: str, *,
                          block_ms: Optional[int] = None, count: int = 100) -> list[tuple[str, str]]:
    """The run's frames after ``after``, as ``(id, json)``; waits up to
    ``block_ms`` for one when there are none (``None``: do not wait)."""
    reply = await redis.xread({stream_key(run_id): after}, count=count, block=block_ms)
    frames: list[tuple[str, str]] = []
    for _key, entries in reply or []:
        for entry_id, fields in entries:
            data = fields.get(b"data", fields.get("data"))
            frames.append((
                entry_id.decode() if isinstance(entry_id, bytes) else str(entry_id),
                data.decode() if isinstance(data, bytes) else str(data),
            ))
    return frames


def is_terminal(data: Union[str, bytes]) -> bool:
    """Whether a published frame is the run's last."""
    try:
        frame = json.loads(data)
    except (TypeError, ValueError):
        return False
    return isinstance(frame, dict) and frame.get("terminal") is True
