"""The entity's retry policy bounds and paces corrective retries (P7.2 — PC-07).

``logic_gate.retry_policy`` (``max_retries``, ``backoff_strategy``,
``backoff_multiplier``) was authored in the builder and read by nothing: the
bound was the constant ``MAX_RETRIES_PER_STEP = 2`` and a retry ran at once —
against a rate limit, the one retry sure to fail again. Now the policy is the
bound and each queued retry waits its backoff before it runs.
"""
from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

from src.ai.core.agent_loop import AgentLoop
from src.ai.core.agent_state import PostCriticVerdict
from src.ai.core.executors.base import EXECUTOR_REGISTRY, ActionResult, register_executor
from src.ai.core.feature_flags import FeatureFlags
from src.ai.planning.critic_pipeline import NoOpCriticPipeline
from src.ai.planning.failure_tags import FailureTag
from src.ai.planning.step_health_record import StepHealthRecord
from src.ai.schemas.enums import RunStatus
from src.ai.schemas.reasoning import RetryPolicy

from tests.unit.test_agent_loop_robustness import _FakeDB, _FakeRun, _no_credit_gate  # noqa: F401


class _Counts:
    name = "SingleStep"

    def __init__(self):
        self.calls = 0

    async def execute(self, move, state, db):  # noqa: ARG002
        self.calls += 1
        ids = [s["step_id"] for s in move.plan_fragment or []]
        return ActionResult(success=True, output="not JSON", cost_usd=Decimal("0"), completed_step_ids=ids)


class _AlwaysWrongFormat(NoOpCriticPipeline):
    async def post_action(self, state, observation):  # noqa: ARG002
        return PostCriticVerdict(kind="REVISE", tags=[FailureTag.WRONG_FORMAT], suggestion="answer in JSON")

    async def finalize_iteration(self, state):
        record = StepHealthRecord(step_id="s1", iteration=state.iteration, post_critic_verdict="REVISE",
                                  post_critic_tags=[FailureTag.WRONG_FORMAT],
                                  post_critic_suggestion="answer in JSON")
        state.health_records.append(record)
        return record


@pytest.fixture
def counts():
    original = EXECUTOR_REGISTRY.get("SingleStep")
    executor = _Counts()
    register_executor(executor)
    try:
        yield executor
    finally:
        if original is not None:
            register_executor(original)


async def _drive(monkeypatch, logic_gate):
    import src.ai.core.agent_loop as al
    slept: list[float] = []

    async def _sleep(seconds):
        slept.append(seconds)

    monkeypatch.setattr(al.asyncio, "sleep", _sleep)
    run = _FakeRun()
    run.entity.logic_gate = logic_gate
    run.entity.planning = {"static_plan": {"enabled": True, "steps": [
        {"step_id": "s1", "name": "Answer", "type": "ACTION"}]}, "dynamic_planning": {"enabled": False}}
    loop = AgentLoop(db=_FakeDB(run), redis=None, critic_pipeline=_AlwaysWrongFormat(),
                     max_iterations=20, feature_flags=FeatureFlags(db=None))
    outcome = await loop.run(run.id)
    return outcome, slept


@pytest.mark.asyncio
async def test_the_policy_bounds_the_retries_and_each_waits_its_backoff(counts, monkeypatch):
    gate = {"reasoning_config": {}, "retry_policy": {
        "max_retries": 1, "backoff_strategy": "LINEAR", "backoff_multiplier": 3.0}}
    outcome, slept = await _drive(monkeypatch, gate)
    assert counts.calls == 2            # the attempt and one retry
    assert slept == [3.0]               # LINEAR: 3 × attempt 1
    assert outcome["status"] in (RunStatus.COMPLETED.value, RunStatus.PARTIAL_COMPLETE.value)


@pytest.mark.asyncio
async def test_without_a_policy_the_old_bound_holds(counts, monkeypatch):
    _outcome, slept = await _drive(monkeypatch, None)
    assert counts.calls == 3            # MAX_RETRIES_PER_STEP = 2
    assert slept == [2.0, 4.0]          # the schema's EXPONENTIAL ×2


def test_backoff_shapes_and_cap():
    from src.ai.planning.retry_strategies import MAX_BACKOFF_S, backoff_seconds
    exp = RetryPolicy(backoff_strategy="EXPONENTIAL", backoff_multiplier=2.0)
    assert [backoff_seconds(exp, n) for n in (1, 2, 3)] == [2.0, 4.0, 8.0]
    assert backoff_seconds(exp, 10) == MAX_BACKOFF_S
    assert backoff_seconds(RetryPolicy(backoff_strategy="NONE"), 3) == 0.0


def test_retry_on_is_retired_but_stored_entities_still_read():
    from src.ai.planning.retry_strategies import retry_policy
    entity = SimpleNamespace(logic_gate={"retry_policy": {
        "max_retries": 4, "retry_on": ["TOOL_FAILURE", "LLM_ERROR"]}})
    policy = retry_policy(entity)
    assert policy.max_retries == 4 and "retry_on" not in policy.model_dump()
