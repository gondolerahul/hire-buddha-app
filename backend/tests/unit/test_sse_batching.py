"""An iteration's SSE frames go out as at most two messages (P8.11 — AK-I9).

Every iteration published each frame on its own — iteration start, budget
pressure, executor invoked and completed, four critic verdicts, retries,
iteration end — one Redis publish and one JSON encoding each, though the
browser folds them into one slice. Now an iteration's frames are buffered and
published as ``batch`` messages: once when the executor starts (so the page
shows the iteration begin) and once when it ends. ``run_end`` still goes
alone, since the stream closes on it.
"""
from __future__ import annotations

import json
from decimal import Decimal

import pytest

from src.ai.core import agent_loop_sse
from src.ai.core.agent_loop import AgentLoop
from src.ai.core.executors.base import EXECUTOR_REGISTRY, ActionResult, register_executor
from src.ai.core.feature_flags import FeatureFlags

from tests.unit.test_agent_loop_robustness import _FakeDB, _FakeRun, _no_credit_gate  # noqa: F401


class _Redis:
    def __init__(self):
        self.published: list[dict] = []

    async def xadd(self, key, fields, **_):
        self.published.append(json.loads(fields["data"]))

    async def expire(self, *_):
        pass


class _Done:
    name = "SingleStep"

    async def execute(self, move, state, db):  # noqa: ARG002
        return ActionResult(success=True, output="ok", cost_usd=Decimal("0"),
                            completed_step_ids=[s["step_id"] for s in move.plan_fragment or []])


@pytest.mark.asyncio
async def test_an_iteration_publishes_two_batches_and_run_end_alone(monkeypatch):
    redis = _Redis()
    original = EXECUTOR_REGISTRY.get("SingleStep")
    register_executor(_Done())
    try:
        run = _FakeRun()
        run.entity.planning = {"static_plan": {"enabled": True, "steps": [
            {"step_id": "s1", "name": "Answer", "type": "ACTION"}]}, "dynamic_planning": {"enabled": False}}
        loop = AgentLoop(db=_FakeDB(run), redis=redis, max_iterations=5, feature_flags=FeatureFlags(db=None))
        await loop.run(run.id)
    finally:
        agent_loop_sse.set_sse_redis(None)
        if original is not None:
            register_executor(original)

    batches = [m for m in redis.published if m.get("type") == "batch"]
    singles = [m["type"] for m in redis.published if m.get("type") != "batch"]
    assert len(batches) == 2                                   # one iteration: start flush, end flush
    first, second = ([e["type"] for e in b["events"]] for b in batches)
    assert first[0] == "iteration_start"
    assert "critic_post" in second and second[-1] == "iteration_end"
    assert "run_end" in singles and "iteration_start" not in singles
