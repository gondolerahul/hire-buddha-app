"""The pre-critic judges the steps and its verdict changes what runs (P7.4 —
PC-01, PC-02, AK-16).

Plan moves — nearly every move — skipped the pre-critic, because it was shown
only an executor name and a step count and its BLOCK made the deterministic
Strategist re-propose the same move until the breaker tripped. A REVISE was
billed and ignored, and a block cost an iteration. Now it sees the steps; a
BLOCK fails them (see test_agent_loop_billing_and_fallback), a REVISE hands
them its concerns, and a block takes no iteration.
"""
from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

from src.ai.core.agent_loop import AgentLoop
from src.ai.core.agent_state import AgentState, Budget, PreCriticVerdict
from src.ai.core.executors.base import EXECUTOR_REGISTRY, ActionResult, register_executor
from src.ai.core.feature_flags import FeatureFlags
from src.ai.core.strategist import Move
from src.ai.planning.critic_pipeline import NoOpCriticPipeline, RealCriticPipeline
from src.ai.schemas.enums import EntityType

from tests.unit.test_agent_loop_robustness import _FakeDB, _FakeRun, _no_credit_gate  # noqa: F401

STEP = {"step_id": "s1", "name": "Draft", "type": "ACTION", "description": "Draft the quarterly letter",
        "target": {"prompt_template": "Write to {{input}}"}}


class _Seen:
    name = "SingleStep"

    def __init__(self):
        self.fragments: list = []

    async def execute(self, move, state, db):  # noqa: ARG002
        self.fragments.append(move.plan_fragment)
        return ActionResult(success=True, output="ok", cost_usd=Decimal("0"),
                            completed_step_ids=[s["step_id"] for s in move.plan_fragment or []])


class _Revises(NoOpCriticPipeline):
    async def pre_action(self, move, state):  # noqa: ARG002
        return PreCriticVerdict(kind="REVISE", concerns=["address it to the board"])


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
async def test_a_revise_hands_its_concerns_to_the_step(seen):
    run = _FakeRun()
    run.entity.planning = {"static_plan": {"enabled": True, "steps": [STEP]}, "dynamic_planning": {"enabled": False}}
    loop = AgentLoop(db=_FakeDB(run), redis=None, critic_pipeline=_Revises(), max_iterations=5,
                     feature_flags=FeatureFlags(db=None))
    outcome = await loop.run(run.id)
    [[step]] = seen.fragments
    assert step["directive"]["prompt_hint"] == "The pre-action review asks: address it to the board"
    assert outcome["iterations"] == 1


class _LLM:
    def __init__(self, verdict="PASS"):
        self.prompts: list[str] = []
        self.verdict = verdict

    async def call_llm(self, **kw):
        self.prompts.append(kw["user_prompt"])
        return SimpleNamespace(output='{"verdict": "%s", "concerns": []}' % self.verdict, cost_usd=0,
                               prompt_tokens=1, completion_tokens=1, model_name="m", provider="p")


def _state() -> AgentState:
    return AgentState(run_id=uuid4(), entity_id=uuid4(), company_id=uuid4(), entity_type=EntityType.AGENT,
                      budget=Budget.from_governance(max_cost_usd=1.0, timeout_ms=60_000))


@pytest.mark.asyncio
async def test_the_pre_critic_sees_the_step_and_records_its_id(monkeypatch):
    llm = _LLM()
    pipe = RealCriticPipeline(db=None, llm_router=llm, cortex_service=None, config={"entity_goal": "letters"})
    monkeypatch.setattr(pipe, "_log_critic_usage", _noop)
    move = Move(move_id="m1", goal_id=None, executor="SingleStep", plan_fragment=[STEP], rationale="next step")
    await pipe.pre_action(move, _state())
    [prompt] = llm.prompts
    assert "Draft the quarterly letter" in prompt and "Write to {{input}}" in prompt
    # The record knows the step, so the per-step retry bound can count it.
    assert pipe._current_record.step_id == "s1"


async def _noop(*_a, **_k):
    return None
