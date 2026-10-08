"""A person's decision ends the run (GH-25, AK-08, HD7).

A rejected HITL checkpoint raised a bare ``Exception``. The executor turned it
into an ordinary step failure, so the critics judged the reviewer's "no", a
retry could ask them again, and the run went on with its other steps. Nothing
ever produced a ``blocked`` observation either (AK-08). Now the decision is
typed: a rejection ends the run CANCELLED with the reviewer's reason, an
unanswered checkpoint ends it FAILED, and neither reaches a critic. How
governance raises the decision is in tests/integration/test_hitl_parking.py.
"""
from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from decimal import Decimal
from types import SimpleNamespace

import pytest

from src.ai.core.agent_loop import AgentLoop
from src.ai.core.agent_state import AgentState
from src.ai.core.events import capture_test_events
from src.ai.core.exceptions import HITLRejected, HITLTimeout
from src.ai.core.executors.base import EXECUTOR_REGISTRY, ActionResult, register_executor
from src.ai.core.executors.dag import DAGExecutor
from src.ai.core.executors.single_step import SingleStepExecutor
from src.ai.core.feature_flags import FeatureFlags
from src.ai.core.observer import Observer
from src.ai.core.strategist import Move
from src.ai.planning.critic_pipeline import NoOpCriticPipeline
from src.ai.schemas.enums import EntityType, RunStatus

from tests.unit.test_agent_loop_billing_and_fallback import _FakeDB, _FakeRun, _no_credit_gate  # noqa: F401

REASON = "Execution blocked by human reviewer: BEFORE_STEP 'Send email' — wrong customer"


# ── the loop ────────────────────────────────────────────────────────────────


def _two_step_entity():
    return SimpleNamespace(
        id=uuid.uuid4(), company_id=uuid.uuid4(), name="mailer", type="SKILL",
        goal="Send the emails", description="fake", identity=None, hierarchy=None,
        logic_gate=None,
        planning={"static_plan": {"enabled": True, "steps": [
            {"step_id": "s1", "order": 1, "name": "Send email", "type": "ACTION", "required": True},
            {"step_id": "s2", "order": 2, "name": "Log it", "type": "ACTION", "required": True},
        ]}, "dynamic_planning": {"enabled": False}},
        capabilities=None, governance={"max_cost_usd": 5.0, "timeout_ms": 600_000},
        io_contract=None, observability=None, metadata_extensions=None,
    )


class _CountingCritics(NoOpCriticPipeline):
    def __init__(self):
        self.after = 0

    async def post_action(self, state, observation):
        self.after += 1
        return await super().post_action(state, observation)

    async def finalize_iteration(self, state):
        self.after += 1
        return None


class _StoppedByAPerson:
    """Step s1 meets a person's decision; any other step runs. Stands in for
    both the SingleStep and the DAG executor (two ready steps go to the DAG)."""

    def __init__(self, kind: str, calls: list[list[str]]):
        self.kind = kind
        self.calls = calls

    async def execute(self, move, state, db):  # noqa: ARG002
        ids = [str(s["step_id"]) for s in move.plan_fragment]
        self.calls.append(ids)
        if "s1" not in ids:
            return ActionResult(success=True, output="ran", cost_usd=Decimal("0"), completed_step_ids=ids)
        return ActionResult(success=False, error=REASON, cost_usd=Decimal("0"),
                            failed_steps={"s1": REASON},
                            blocked={"kind": self.kind, "reason": REASON, "step_id": "s1"})


async def _drive(kind: str):
    calls: list[list[str]] = []
    critics = _CountingCritics()
    originals = {n: EXECUTOR_REGISTRY.get(n) for n in ("SingleStep", "DAG")}
    for n in originals:
        fake = _StoppedByAPerson(kind, calls)
        fake.name = n
        register_executor(fake)
    try:
        run = _FakeRun(_two_step_entity())
        loop = AgentLoop(db=_FakeDB(run), redis=None, critic_pipeline=critics,
                         max_iterations=10, feature_flags=FeatureFlags(db=None))
        with capture_test_events() as events:
            outcome = await loop.run(run.id)
    finally:
        for original in originals.values():
            if original is not None:
                register_executor(original)
    return outcome, run, calls, critics, events


@pytest.mark.asyncio
async def test_a_rejection_ends_the_run_cancelled_with_the_reviewers_reason():
    outcome, run, calls, critics, events = await _drive("hitl_rejected")
    assert outcome["status"] == RunStatus.CANCELLED.value
    assert outcome["error"] == REASON and "wrong customer" in run.error_message
    assert len(calls) == 1              # nothing ran after the decision
    assert critics.after == 0           # no critic judged the reviewer, no retry was picked
    [decision] = [e for e in events if e.name == "agent.loop.human_decision"]
    assert decision.payload["kind"] == "hitl_rejected" and decision.payload["step_id"] == "s1"
    assert "agent.retry.picked" not in [e.name for e in events]


@pytest.mark.asyncio
async def test_an_unanswered_checkpoint_ends_the_run_failed():
    outcome, _run, calls, critics, _events = await _drive("hitl_timeout")
    assert outcome["status"] == RunStatus.FAILED.value
    assert outcome["error"] == REASON
    assert len(calls) == 1 and critics.after == 0


# ── the observation (AK-08) ─────────────────────────────────────────────────


def _state():
    return AgentState(run_id=uuid.uuid4(), entity_id=uuid.uuid4(), company_id=uuid.uuid4(),
                      entity_type=EntityType.SKILL)


def test_a_persons_decision_is_a_blocked_observation_and_a_blocker():
    state = _state()
    result = ActionResult(success=False, error=REASON,
                          blocked={"kind": "hitl_rejected", "reason": REASON, "step_id": "s1"})
    observation = Observer().parse(result, state)
    assert observation.outcome == "blocked" and observation.blocked_by == "hitl_rejected"
    state.apply_observation(observation)
    assert [b.kind for b in state.blockers] == ["hitl_decision"]


def test_an_ordinary_failure_is_still_a_failure():
    observation = Observer().parse(ActionResult(success=False, error="tool failed"), _state())
    assert observation.outcome == "fail" and observation.blocked_by == ""


# ── the executors pass the decision up ──────────────────────────────────────


class _Engine:
    raises: Exception = HITLRejected(REASON)

    def __init__(self, *a, **k):
        pass

    def _ensure_services(self, _cid):
        pass

    async def _execute_step_wrapper(self, run, entity, step, ctx):  # noqa: ARG002
        raise self.raises

    async def _execute_steps_dag(self, run, entity, steps, ctx, results_map=None):  # noqa: ARG002
        raise self.raises


async def _reload(_db, _rid):
    return SimpleNamespace(total_cost_usd=0, entity=SimpleNamespace())


def _move(executor, *ids):
    return Move(move_id="m", goal_id=None, executor=executor, rationale="t",
                plan_fragment=[{"step_id": i, "name": i, "type": "ACTION"} for i in ids])


@pytest.mark.asyncio
async def test_single_step_reports_the_decision_and_stops(monkeypatch):
    @asynccontextmanager
    async def _session():
        yield object()

    async def _no_rows(_db, _rid):
        return Decimal("0")

    monkeypatch.setattr("src.ai.core.step_engine.StepEngine", _Engine)
    monkeypatch.setattr("src.common.database.AsyncSessionLocal", _session)
    monkeypatch.setattr("src.ai.core.executors.single_step.run_entity", _reload)
    monkeypatch.setattr(SingleStepExecutor, "_reload_run", staticmethod(_reload))
    monkeypatch.setattr(SingleStepExecutor, "_rows_cost", staticmethod(_no_rows))
    res = await SingleStepExecutor().execute(_move("SingleStep", "s1", "s2"), _state(), db=None)
    assert res.blocked == {"kind": "hitl_rejected", "reason": REASON, "step_id": "s1"}
    assert res.failed_steps == {"s1": REASON} and res.completed_step_ids == []


@pytest.mark.asyncio
async def test_dag_reports_the_decision(monkeypatch):
    monkeypatch.setattr(_Engine, "raises", HITLTimeout("HITL checkpoint timed out after 200ms"))
    monkeypatch.setattr("src.ai.core.step_engine.StepEngine", _Engine)
    monkeypatch.setattr("src.ai.core.executors.dag.run_entity", _reload)
    monkeypatch.setattr(DAGExecutor, "_reload_run", staticmethod(_reload))
    res = await DAGExecutor().execute(_move("DAG", "a", "b"), _state(), db=None)
    assert res.blocked is not None and res.blocked["kind"] == "hitl_timeout"
    assert "timed out" in res.blocked["reason"]

