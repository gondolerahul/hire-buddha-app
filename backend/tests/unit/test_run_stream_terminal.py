"""GW-19: the run stream ends on a frame that says it is the last.

``GET /ai/executions/{id}/stream`` used to stop on the substring
``"status": "COMPLETED"`` (or FAILED / CANCELLED) anywhere in a frame. A tool
result or a child's status inside a span's payload closed the parent's stream
mid-run, and a ``PARTIAL_COMPLETE`` run's stream never closed. The last frame
now carries ``"terminal": true``, and the stream stops on that field only.
"""
from __future__ import annotations

import json
from types import SimpleNamespace
from uuid import uuid4

import pytest

from src.ai.core import agent_loop_sse
from src.ai.core.run_stream import is_terminal


class _PubSub:
    def __init__(self, frames):
        self.frames = frames

    async def subscribe(self, channel):
        self.channel = channel

    async def unsubscribe(self, channel):
        pass

    async def listen(self):
        for frame in self.frames:
            yield {"type": "message", "data": json.dumps(frame).encode()}


class _StreamRedis:
    def __init__(self, frames):
        self._pubsub = _PubSub(frames)

    def pubsub(self):
        return self._pubsub

    async def close(self):
        pass


async def _relay(monkeypatch, frames) -> list[dict]:
    from src.ai import router as ai_router

    class _Service:
        def __init__(self, db):
            pass

        async def get_execution(self, *args, **kwargs):
            return None

    monkeypatch.setattr(ai_router, "AIService", _Service)
    monkeypatch.setattr("redis.asyncio.from_url", lambda *a, **k: _StreamRedis(frames))
    user = SimpleNamespace(company_id=uuid4(), role="admin")
    response = await ai_router.stream_execution(uuid4(), db=None, current_user=user)
    out = []
    async for chunk in response.body_iterator:
        text = chunk if isinstance(chunk, str) else chunk.decode()
        for line in text.splitlines():
            if line.startswith("data: "):
                out.append(json.loads(line[len("data: "):]))
    return out


@pytest.mark.asyncio
async def test_a_status_word_inside_a_payload_does_not_end_the_stream(monkeypatch):
    frames = [
        {"type": "span_close", "kind": "child", "status": "success",
         "payload": {"child": {"status": "COMPLETED"}}},
        {"type": "iteration_end", "iteration": 1, "outcome": "success"},
        {"type": "run_end", "outcome": "COMPLETED", "terminal": True},
        {"type": "never_sent"},
    ]
    relayed = await _relay(monkeypatch, frames)
    assert [f.get("type") for f in relayed[1:]] == ["span_close", "iteration_end", "run_end"]


@pytest.mark.asyncio
async def test_a_partially_complete_run_ends_its_stream(monkeypatch):
    frames = [
        {"type": "run_end", "outcome": "PARTIAL_COMPLETE", "terminal": True},
        {"type": "never_sent"},
    ]
    relayed = await _relay(monkeypatch, frames)
    assert [f.get("type") for f in relayed[1:]] == ["run_end"]


class _Recorder:
    def __init__(self):
        self.frames: list[dict] = []

    async def publish(self, channel, data):
        self.frames.append(json.loads(data))


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome, terminal", [
    ("COMPLETED", True), ("FAILED", True), ("PARTIAL_COMPLETE", True), ("CANCELLED", True),
    ("PAUSED", False), ("WAITING_ON_CHILDREN", False),
])
async def test_run_end_is_terminal_only_for_a_finished_run(monkeypatch, outcome, terminal):
    redis = _Recorder()
    monkeypatch.setattr(agent_loop_sse, "_SSE_REDIS", redis)
    await agent_loop_sse.event_async("agent.loop.run_end", run_id=str(uuid4()), outcome=outcome)
    [frame] = redis.frames
    assert frame["type"] == "run_end"
    assert frame.get("terminal", False) is terminal
    assert "status" not in frame  # no status word stamped in for a substring match


@pytest.mark.asyncio
async def test_a_cancelled_run_sends_a_terminal_frame(monkeypatch):
    redis = _Recorder()
    monkeypatch.setattr(agent_loop_sse, "_SSE_REDIS", redis)
    await agent_loop_sse.event_async("agent.loop.cancelled", run_id=str(uuid4()),
                                     iteration=3, status="CANCELLED")
    assert redis.frames[0]["terminal"] is True


def test_only_the_field_is_terminal():
    assert is_terminal(json.dumps({"type": "run_end", "terminal": True}))
    assert not is_terminal(json.dumps({"type": "x", "payload": {"status": "COMPLETED"}}))
    assert not is_terminal(json.dumps({"status": "FAILED"}))
    assert not is_terminal("not json")
