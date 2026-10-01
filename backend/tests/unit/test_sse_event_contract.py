"""AK-11 / AK-I10 — the SSE event-name contract between the kernel and the browser.

``agent_loop_sse._SSE_EVENT_TYPES`` translates an internal event name into the
``type`` the execution page's reducer switches on. Two typos once made the
``resume`` and ``replan_triggered`` frames unreachable with no error anywhere:
the map said ``agent.loop.resume`` / ``agent.loop.replan`` while the loop emits
``agent.loop.resumed`` / ``agent.replan.triggered``. These tests hold both ends.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from src.ai.core import agent_loop_sse
from src.ai.core.agent_loop_sse import _SSE_EVENT_TYPES

BACKEND_SRC = Path(__file__).resolve().parents[2] / "src"
REDUCER = (
    Path(__file__).resolve().parents[3]
    / "frontend" / "src" / "hooks" / "useExecutionEvents.ts"
)


def _emitted_event_names() -> set[str]:
    """Every name passed as the first argument to ``event_async`` in the backend."""
    pattern = re.compile(r'event_async\(\s*"([^"]+)"')
    names: set[str] = set()
    for path in BACKEND_SRC.rglob("*.py"):
        names.update(pattern.findall(path.read_text(encoding="utf-8")))
    return names


def test_every_mapped_event_is_actually_emitted() -> None:
    emitted = _emitted_event_names()
    never_emitted = sorted(set(_SSE_EVENT_TYPES) - emitted)
    assert not never_emitted, (
        f"SSE map keys no code emits (the browser never sees them): {never_emitted}"
    )


@pytest.mark.skipif(not REDUCER.exists(), reason="frontend checkout not present")
def test_every_mapped_type_is_handled_by_the_reducer() -> None:
    cases = set(re.findall(r"case '([a-z_]+)'", REDUCER.read_text(encoding="utf-8")))
    # ``cancelled`` and ``run_end`` close the stream in the SSE endpoint rather
    # than updating the reducer's iteration state.
    stream_control = {"cancelled", "run_end"}
    unhandled = sorted(set(_SSE_EVENT_TYPES.values()) - cases - stream_control)
    assert not unhandled, f"SSE types the reducer has no case for: {unhandled}"


@pytest.mark.parametrize(
    "emitted, sse_type",
    [
        ("agent.loop.resumed", "resume"),
        ("agent.replan.triggered", "replan_triggered"),
        ("agent.bandit.arm_updated", "bandit_arm_updated"),
        ("agent.task_class.classified", "task_class_classified"),
    ],
)
def test_events_the_reducer_handles_reach_the_browser(emitted: str, sse_type: str) -> None:
    assert _SSE_EVENT_TYPES.get(emitted) == sse_type


class _RecordingRedis:
    def __init__(self) -> None:
        self.published: list[tuple[str, str]] = []

    async def publish(self, channel: str, body: str) -> None:
        self.published.append((channel, body))


async def test_a_resume_frame_is_published_to_the_run_channel() -> None:
    import json

    redis = _RecordingRedis()
    agent_loop_sse.set_sse_redis(redis)
    try:
        await agent_loop_sse.event_async(
            "agent.loop.resumed", run_id="run-1", iteration=4, from_iteration=4,
        )
    finally:
        agent_loop_sse.set_sse_redis(None)
    assert len(redis.published) == 1
    channel, body = redis.published[0]
    assert channel == "execution:run-1"
    frame = json.loads(body)
    assert frame["type"] == "resume" and frame["from_iteration"] == 4
