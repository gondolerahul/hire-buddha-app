"""The iteration cap follows the plan (P8.11 — AK-I8).

Every run had the flat 50: an ACTION with one step could spin 50 iterations,
and a PROCESS orchestrating three agents had no more room than it. Now the cap
is each step once plus its retries plus room for planning, at least 8, never
above the constructor's hard cap; a run with no plan keeps the hard cap.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.ai.core.agent_loop import AgentLoop
from src.ai.core.feature_flags import FeatureFlags
from src.ai.schemas.enums import RunStatus

from tests.unit.test_agent_loop_robustness import _FakeDB, _FakeRun, _no_credit_gate, never_completes  # noqa: F401


def test_the_cap_follows_plan_size_and_retries():
    from src.ai.planning.retry_strategies import iteration_cap
    entity = SimpleNamespace(logic_gate=None)                   # default bound: 2 retries
    assert iteration_cap(entity, 0, 50) == 50                   # no plan yet: the hard cap
    assert iteration_cap(entity, 1, 50) == 8                    # the floor
    assert iteration_cap(entity, 6, 50) == 23                   # 6 × (1 + 2) + 5
    assert iteration_cap(entity, 30, 50) == 50                  # never above the hard cap
    strict = SimpleNamespace(logic_gate={"retry_policy": {"max_retries": 0}})
    assert iteration_cap(strict, 6, 50) == 11


@pytest.mark.asyncio
async def test_a_one_step_run_that_never_finishes_stops_at_its_cap(never_completes):
    run = _FakeRun()
    run.entity.planning = {"static_plan": {"enabled": True, "steps": [
        {"step_id": "s1", "name": "Spin", "type": "ACTION"}]}, "dynamic_planning": {"enabled": False}}
    loop = AgentLoop(db=_FakeDB(run), redis=None, max_iterations=50, feature_flags=FeatureFlags(db=None))
    outcome = await loop.run(run.id)
    assert outcome["iterations"] == 8 and outcome["status"] == RunStatus.FAILED.value
