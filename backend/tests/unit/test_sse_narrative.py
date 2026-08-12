"""SSE narrative streaming — Phase 12 `07` §6 (review gap #5).

The execution stream must carry the iteration *narrative*, not just status
transitions. ``event_async`` republishes mapped loop events to the per-run
``execution:{id}`` channel; this locks in that an ``iteration_end`` event's
``narrative`` (and ``reflection``) survive that fan-out.
"""
from __future__ import annotations

import json

import pytest

from src.ai.core import agent_loop_sse


class _FakeRedis:
    def __init__(self):
        self.published = []

    async def publish(self, channel, body):
        self.published.append((channel, body))


@pytest.mark.asyncio
async def test_iteration_end_carries_narrative() -> None:
    fake = _FakeRedis()
    agent_loop_sse.set_sse_redis(fake)
    try:
        await agent_loop_sse.event_async(
            "agent.loop.iteration_end",
            run_id="run-123",
            iteration=2,
            outcome="success",
            narrative="searched the web and summarised 3 sources",
            reflection="worked: found the answer",
        )
    finally:
        agent_loop_sse.set_sse_redis(None)

    assert fake.published, "expected an SSE publish"
    channel, body = fake.published[0]
    assert channel == "execution:run-123"
    payload = json.loads(body)
    assert payload["type"] == "iteration_end"
    assert payload["narrative"] == "searched the web and summarised 3 sources"
    assert "run_id" not in payload  # stripped by the fan-out
