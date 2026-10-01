"""AK-01 — the run's final status comes from its steps' outcomes.

Before the fix ``_final_status`` returned COMPLETED whenever no plan step was
left *ready*; a failed step is no longer ready, so a plan whose every step
failed was COMPLETED, billed and counted as a success. Now: COMPLETED only when
every required step succeeded, FAILED when none did, PARTIAL_COMPLETE between.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

from src.ai.core.agent_loop import AgentLoop
from src.ai.core.agent_state import AgentState
from src.ai.core.executors.base import EXECUTOR_REGISTRY, ActionResult, register_executor
from src.ai.core.executors.dag import DAGExecutor
from src.ai.core.executors.single_step import SingleStepExecutor
from src.ai.core.feature_flags import FeatureFlags
from src.ai.core.strategist import Move
from src.ai.schemas.enums import EntityType, RunStatus

from tests.unit.test_agent_loop_billing_and_fallback import (  # noqa: F401
    _FakeDB,
    _FakeRun,
    _no_credit_gate,
    _static_entity,
)


def _state(steps: list[dict]) -> AgentState:
    st = AgentState(
        run_id=uuid4(), entity_id=uuid4(), company_id=uuid4(),
        entity_type=EntityType.AGENT,
    )
    st.plan_steps = steps
    return st


def _steps(*ids: str, optional: tuple[str, ...] = ()) -> list[dict]:
    return [{"step_id": i, "name": i, "required": i not in optional} for i in ids]


# ── _final_status ────────────────────────────────────────────────────────────


def test_every_step_failed_is_failed():
    st = _state(_steps("a", "b"))
    st.mark_step_failed("a", "boom")
    st.mark_step_failed("b", "boom")
    assert not st.plan_ready_steps()
    assert AgentLoop._final_status(st) == RunStatus.FAILED.value


def test_some_steps_failed_is_partial():
    st = _state(_steps("a", "b"))
    st.mark_step_complete("a")
    st.mark_step_failed("b", "boom")
    assert AgentLoop._final_status(st) == RunStatus.PARTIAL_COMPLETE.value


def test_every_required_step_succeeded_is_completed():
    st = _state(_steps("a", "b", optional=("b",)))
    st.mark_step_complete("a")
    st.mark_step_failed("b", "boom")
    assert AgentLoop._final_status(st) == RunStatus.COMPLETED.value


def test_a_retry_that_succeeds_clears_the_failure():
    st = _state(_steps("a"))
    st.mark_step_failed("a", "boom")
    st.mark_step_complete("a")
    assert st.failed_steps == {}
    assert AgentLoop._final_status(st) == RunStatus.COMPLETED.value


def test_unrun_steps_are_not_success():
    st = _state(_steps("a", "b"))
    st.mark_step_complete("a")
    assert AgentLoop._final_status(st) == RunStatus.PARTIAL_COMPLETE.value
    assert AgentLoop._final_status(_state(_steps("a"))) == RunStatus.FAILED.value


def test_failed_steps_survive_snapshot():
    st = _state(_steps("a"))
    st.mark_step_failed("a", "boom")
    again = AgentState.restore(st.snapshot())
    assert again.failed_steps == {"a": "boom"}


# ── executors report a step's error as a failure ────────────────────────────


@pytest.mark.asyncio
async def test_single_step_reports_an_error_result_as_failed(monkeypatch):
    class _Engine:
        def __init__(self, *a, **k):
            pass

        def _ensure_services(self, _cid):
            pass

        async def _execute_step_wrapper(self, run, entity, step, ctx):  # noqa: ARG002
            return {"step_id": "s1", "output": "[ERROR] nope", "error": "tool failed"}

    @asynccontextmanager
    async def _session():
        yield object()

    async def _reload(_db, _rid):
        return SimpleNamespace(total_cost_usd=0, entity=SimpleNamespace())

    monkeypatch.setattr("src.ai.core.step_engine.StepEngine", _Engine)
    monkeypatch.setattr("src.common.database.AsyncSessionLocal", _session)
    monkeypatch.setattr(SingleStepExecutor, "_reload_run", staticmethod(_reload))

    st = _state(_steps("s1"))
    move = Move(move_id="m", goal_id=None, executor="SingleStep",
                plan_fragment=[{"step_id": "s1", "name": "s1", "type": "ACTION"}],
                rationale="t")
    res = await SingleStepExecutor().execute(move, st, db=None)
    assert res.success is False
    assert res.completed_step_ids == []
    assert res.failed_steps == {"s1": "tool failed"}


@pytest.mark.asyncio
async def test_dag_reports_errored_steps_as_failed(monkeypatch):
    class _Engine:
        def __init__(self, *a, **k):
            pass

        def _ensure_services(self, _cid):
            pass

        async def _execute_steps_dag(self, run, entity, steps, ctx):  # noqa: ARG002
            return [{"step_id": "a", "output": "ok"},
                    {"step_id": "b", "output": "", "error": "boom"}]

    async def _reload(_db, _rid):
        return SimpleNamespace(entity=SimpleNamespace())

    monkeypatch.setattr("src.ai.core.step_engine.StepEngine", _Engine)
    monkeypatch.setattr(DAGExecutor, "_reload_run", staticmethod(_reload))

    st = _state(_steps("a", "b"))
    move = Move(move_id="m", goal_id=None, executor="DAG",
                plan_fragment=_steps("a", "b"), rationale="t")
    res = await DAGExecutor().execute(move, st, db=None)
    assert res.completed_step_ids == ["a"]
    assert res.failed_steps == {"b": "boom"}


# ── end to end: the loop records the failure and the run is FAILED ──────────


class _FailingSingleStep:
    name = "SingleStep"

    async def execute(self, move, state, db):  # noqa: ARG002
        sid = str(move.plan_fragment[0]["step_id"])
        return ActionResult(output="", cost_usd=Decimal("0.01"), success=False,
                            error="tool failed", failed_steps={sid: "tool failed"})


@pytest.fixture
def failing_single_step():
    original = EXECUTOR_REGISTRY.get("SingleStep")
    register_executor(_FailingSingleStep())
    try:
        yield
    finally:
        if original is not None:
            register_executor(original)


@pytest.mark.asyncio
async def test_a_run_whose_only_step_failed_is_failed(failing_single_step, monkeypatch):
    async def _settle(self, run, name):  # noqa: ARG001
        return Decimal("0")

    from src.ai.governance.governance_service import GovernanceService
    monkeypatch.setattr(GovernanceService, "settle_billing", _settle)

    entity = _static_entity(uuid4(), uuid4())
    run = _FakeRun(entity)
    loop = AgentLoop(db=_FakeDB(run), redis=None, feature_flags=FeatureFlags(db=None))
    await loop.run(run.id)

    assert run.status == RunStatus.FAILED.value
    assert "tool failed" in (run.error_message or "")
    steps = (run.result_data or {}).get("steps") or []
    assert steps and steps[0].get("error") == "tool failed"
