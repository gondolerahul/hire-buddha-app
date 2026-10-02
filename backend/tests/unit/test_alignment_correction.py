"""Goal drift steers the next step (P7.5 — PC-03).

The alignment critic is an LLM call that says how far a step wandered from
the goal and how to correct it. The loop recorded the drift number and dropped
``correction_hint``. Now the hint is the next move's correction, once, and it
survives a snapshot.
"""
from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest

from src.ai.core.agent_loop import AgentLoop
from src.ai.core.agent_state import AgentState, AlignmentVerdict, Budget
from src.ai.core.executors.base import EXECUTOR_REGISTRY, ActionResult, register_executor
from src.ai.core.feature_flags import FeatureFlags
from src.ai.planning.critic_pipeline import NoOpCriticPipeline
from src.ai.schemas.enums import EntityType

from tests.unit.test_agent_loop_robustness import _FakeDB, _FakeRun, _no_credit_gate  # noqa: F401


class _Seen:
    name = "SingleStep"

    def __init__(self):
        self.fragments: list = []

    async def execute(self, move, state, db):  # noqa: ARG002
        self.fragments.append(move.plan_fragment)
        return ActionResult(success=True, output="a poem about cats", cost_usd=Decimal("0"),
                            completed_step_ids=[s["step_id"] for s in move.plan_fragment or []])


class _DriftsOnce(NoOpCriticPipeline):
    async def alignment(self, state, observation):  # noqa: ARG002
        if state.iteration == 1:
            return AlignmentVerdict(aligned=False, drift=0.7, correction_hint="the brief is about dogs")
        return AlignmentVerdict(aligned=True, drift=0.0)


@pytest.fixture
def seen():
    original = EXECUTOR_REGISTRY.get("SingleStep")
    executor = _Seen()
    register_executor(executor)
    try:
        yield executor
    finally:
        if original is not None:
            register_executor(original)


@pytest.mark.asyncio
async def test_the_drift_hint_reaches_the_next_step_once(seen):
    run = _FakeRun()
    run.entity.planning = {"static_plan": {"enabled": True, "steps": [
        {"step_id": f"s{i}", "name": f"Step {i}", "type": "ACTION",
         "target": {"input_dependencies": [f"s{i - 1}"] if i > 1 else []}}
        for i in (1, 2, 3)]}, "dynamic_planning": {"enabled": False}}
    loop = AgentLoop(db=_FakeDB(run), redis=None, critic_pipeline=_DriftsOnce(), max_iterations=10,
                     feature_flags=FeatureFlags(db=None))
    await loop.run(run.id)

    hints = [(f[0].get("directive") or {}).get("prompt_hint") for f in seen.fragments]
    assert hints == [None, "The run is drifting from its goal: the brief is about dogs", None]


def test_a_pending_correction_survives_a_snapshot():
    state = AgentState(run_id=uuid4(), entity_id=uuid4(), company_id=uuid4(), entity_type=EntityType.AGENT,
                       budget=Budget.from_governance(max_cost_usd=1.0, timeout_ms=60_000))
    state.pending_correction = "stay on dogs"
    assert AgentState.restore(state.snapshot()).pending_correction == "stay on dogs"
