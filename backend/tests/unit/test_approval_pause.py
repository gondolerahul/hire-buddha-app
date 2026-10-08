"""A HITL checkpoint parks the run instead of holding a worker (GH-07, PO-20).

The checkpoint waited inside the step for up to its ``timeout_ms`` (five
minutes by default), holding an Arq worker slot the whole time; a few pending
approvals starved the pool. Now it raises ``HITLPending``: the executor reports
it, the loop snapshots the run, sets it PAUSED and returns, and the decision
resumes it at the same step (``AgentLoop.resume_after_approval``). The
database side — approvals, the sweep, the endpoint — is in
tests/integration/test_hitl_parking.py.
"""
from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from decimal import Decimal
from types import SimpleNamespace

import pytest

from src.ai.core import approval_pause
from src.ai.core.agent_loop import AgentLoop
from src.ai.core.agent_state import AgentState
from src.ai.core.events import capture_test_events
from src.ai.core.exceptions import HITLPending
from src.ai.core.executors.base import EXECUTOR_REGISTRY, ActionResult, register_executor
from src.ai.core.executors.dag import DAGExecutor
from src.ai.core.executors.single_step import SingleStepExecutor
from src.ai.core.feature_flags import FeatureFlags
from src.ai.core.strategist import Move
from src.ai.planning.critic_pipeline import NoOpCriticPipeline
from src.ai.schemas.enums import EntityType, RunStatus

from tests.unit.test_agent_loop_billing_and_fallback import _FakeDB, _FakeRun, _no_credit_gate  # noqa: F401


def _pending(phase="BEFORE", step_id="s1"):
    return HITLPending("a-1", trigger=f"{phase}_STEP: {step_id}", phase=phase, step_id=step_id,
                       deadline="2099-01-01T00:00:00+00:00", timeout_ms=300000)


def _state():
    return AgentState(run_id=uuid.uuid4(), entity_id=uuid.uuid4(), company_id=uuid.uuid4(),
                      entity_type=EntityType.SKILL)


def _move(executor, *ids):
    return Move(move_id="m", goal_id=None, executor=executor, rationale="t",
                plan_fragment=[{"step_id": i, "name": i, "type": "ACTION"} for i in ids])


async def _reload(_db, _rid):
    return SimpleNamespace(total_cost_usd=0, entity=SimpleNamespace())


# ── the executors report the wait ───────────────────────────────────────────


@pytest.fixture
def engine(monkeypatch):
    """A step engine whose step ``s1`` meets a checkpoint; others run."""
    class _Engine:
        phase = "BEFORE"
        ran: list[str] = []

        def __init__(self, *a, **k):
            pass

        def _ensure_services(self, _cid):
            pass

        async def _execute_step_wrapper(self, run, entity, step, ctx):  # noqa: ARG002
            if step.step_id == "s1":
                pending = _pending(self.phase)
                if self.phase == "AFTER":
                    _Engine.ran.append("s1")
                    pending.step_result = {"step_id": "s1", "output": "drafted"}
                raise pending
            _Engine.ran.append(step.step_id)
            return {"step_id": step.step_id, "output": "ok"}

        async def _execute_steps_dag(self, run, entity, steps, ctx, results_map=None):  # noqa: ARG002
            results_map["s0"] = {"step_id": "s0", "output": "first level"}
            raise _pending(self.phase)

    @asynccontextmanager
    async def _session():
        yield object()

    async def _no_rows(_db, _rid):
        return Decimal("0")

    _Engine.ran = []
    monkeypatch.setattr("src.ai.core.step_engine.StepEngine", _Engine)
    monkeypatch.setattr("src.common.database.AsyncSessionLocal", _session)
    monkeypatch.setattr("src.ai.core.executors.single_step.run_entity", _reload)
    monkeypatch.setattr("src.ai.core.executors.dag.run_entity", _reload)
    monkeypatch.setattr(SingleStepExecutor, "_reload_run", staticmethod(_reload))
    monkeypatch.setattr(SingleStepExecutor, "_rows_cost", staticmethod(_no_rows))
    monkeypatch.setattr(DAGExecutor, "_reload_run", staticmethod(_reload))
    return _Engine


@pytest.mark.asyncio
async def test_before_a_step_nothing_runs_and_the_wait_is_reported(engine):
    res = await SingleStepExecutor().execute(_move("SingleStep", "s1", "s2"), _state(), db=None)
    assert res.awaiting_approval["approval_id"] == "a-1"
    assert res.completed_step_ids == [] and res.failed_steps == {}
    assert engine.ran == []                       # s1 waits, and s2 does not run past it


@pytest.mark.asyncio
async def test_after_a_step_its_result_is_kept(engine):
    engine.phase = "AFTER"
    res = await SingleStepExecutor().execute(_move("SingleStep", "s1", "s2"), _state(), db=None)
    assert res.awaiting_approval["phase"] == "AFTER"
    assert res.completed_step_ids == ["s1"] and res.output == "drafted"
    assert engine.ran == ["s1"]


@pytest.mark.asyncio
async def test_a_dag_keeps_the_steps_that_finished(engine):
    res = await DAGExecutor().execute(_move("DAG", "s0", "s1"), _state(), db=None)
    assert res.awaiting_approval["step_id"] == "s1"
    assert res.completed_step_ids == ["s0"]


# ── the loop parks, and the decision resumes it ─────────────────────────────


def _entity():
    return SimpleNamespace(
        id=uuid.uuid4(), company_id=uuid.uuid4(), name="mailer", type="SKILL",
        goal="Send the email", description="fake", identity=None, hierarchy=None, logic_gate=None,
        planning={"static_plan": {"enabled": True, "steps": [
            {"step_id": "s1", "order": 1, "name": "Send email", "type": "ACTION", "required": True},
        ]}, "dynamic_planning": {"enabled": False}},
        capabilities=None, governance={"max_cost_usd": 5.0, "timeout_ms": 600_000},
        io_contract=None, observability=None, metadata_extensions=None,
    )


class _Checkpointed:
    """s1 meets a checkpoint until a person has decided; then it runs."""
    name = "SingleStep"

    def __init__(self):
        self.decided = False
        self.calls: list[list[str]] = []

    async def execute(self, move, state, db):  # noqa: ARG002
        ids = [str(s["step_id"]) for s in move.plan_fragment]
        self.calls.append(ids)
        if not self.decided:
            return ActionResult(success=True, awaiting_approval=_pending().marker())
        return ActionResult(success=True, output="sent", cost_usd=Decimal("0"), completed_step_ids=ids)


class _CountingCritics(NoOpCriticPipeline):
    def __init__(self):
        self.after = 0

    async def post_action(self, state, observation):
        self.after += 1
        return await super().post_action(state, observation)


@pytest.fixture
def parked(monkeypatch):
    """Drive a run into the checkpoint; record the deadline job and any bill."""
    executor = _Checkpointed()
    original = EXECUTOR_REGISTRY.get("SingleStep")
    register_executor(executor)
    jobs: list = []
    bills: list = []

    async def _enqueue(function, *args, **kwargs):
        jobs.append((function, args, kwargs))

    async def _settle(self, run, entity_name):  # noqa: ARG001
        bills.append(run.id)
        return Decimal("0")

    from src.ai.governance.governance_service import GovernanceService
    monkeypatch.setattr("src.common.job_queue.enqueue_job", _enqueue)
    monkeypatch.setattr(GovernanceService, "settle_billing", _settle)
    run = _FakeRun(_entity())
    yield SimpleNamespace(run=run, db=_FakeDB(run), executor=executor, jobs=jobs, bills=bills)
    if original is not None:
        register_executor(original)


def _loop(db, critics=None):
    return AgentLoop(db=db, redis=None, critic_pipeline=critics or NoOpCriticPipeline(),
                     max_iterations=10, feature_flags=FeatureFlags(db=None))


@pytest.mark.asyncio
async def test_the_run_parks_paused_and_gives_the_worker_back(parked):
    critics = _CountingCritics()
    with capture_test_events() as events:
        outcome = await _loop(parked.db, critics).run(parked.run.id)

    assert outcome["status"] == RunStatus.PAUSED.value
    assert parked.run.status == RunStatus.PAUSED.value
    snapshot = parked.run.context_state["__agent_state_snapshot__"]
    assert snapshot["awaiting_approval"]["approval_id"] == "a-1"
    # The step goes back, as it was, to be dispatched again after the decision.
    assert [s["step_id"] for s in snapshot["retry_queue"][0]["plan_fragment"]] == ["s1"]
    assert snapshot["completed_step_ids"] == []
    # A job at the approval's deadline; not finalised, not billed, not judged.
    [(function, args, kwargs)] = parked.jobs
    assert function == "resume_paused_run" and args == (str(parked.run.id),)
    assert kwargs["_job_id"] == "hitl-deadline:a-1" and kwargs["_defer_by"] > 0
    assert parked.bills == [] and critics.after == 0
    assert "agent.loop.paused_on_approval" in [e.name for e in events]


async def _resume(parked, monkeypatch, decision, notes=""):
    async def _decision(db, marker, now=None):  # noqa: ARG001
        return decision, notes

    async def _claim(db, run_id):  # noqa: ARG001
        parked.run.status = RunStatus.RUNNING.value
        return True

    consumed: list = []

    async def _consume(db, approval_id):  # noqa: ARG001
        consumed.append(approval_id)

    monkeypatch.setattr(approval_pause, "decision_for", _decision)
    monkeypatch.setattr(approval_pause, "claim", _claim)
    monkeypatch.setattr("src.ai.governance.hitl_gate.consume", _consume)
    outcome = await _loop(parked.db).resume_after_approval(parked.run.id)
    return outcome, consumed


@pytest.mark.asyncio
async def test_an_approval_resumes_the_run_at_the_same_step(parked, monkeypatch):
    await _loop(parked.db).run(parked.run.id)
    parked.executor.decided = True
    outcome, consumed = await _resume(parked, monkeypatch, "APPROVED")

    assert outcome["status"] == RunStatus.COMPLETED.value
    assert parked.executor.calls == [["s1"], ["s1"]]     # the same step, once more
    assert consumed == []                                # a BEFORE step uses it when it runs
    assert parked.bills == [parked.run.id]               # billed once, at the end


@pytest.mark.asyncio
async def test_a_rejection_on_resume_ends_the_run_cancelled(parked, monkeypatch):
    await _loop(parked.db).run(parked.run.id)
    outcome, consumed = await _resume(parked, monkeypatch, "REJECTED", "wrong customer")

    assert outcome["status"] == RunStatus.CANCELLED.value
    assert "wrong customer" in outcome["error"]
    assert parked.executor.calls == [["s1"]]             # the step never ran again
    assert consumed == ["a-1"]
    assert parked.bills == [parked.run.id]


@pytest.mark.asyncio
async def test_no_decision_by_the_deadline_ends_the_run_failed(parked, monkeypatch):
    await _loop(parked.db).run(parked.run.id)
    outcome, _ = await _resume(parked, monkeypatch, "TIMEOUT")
    assert outcome["status"] == RunStatus.FAILED.value
    assert "timed out" in outcome["error"]


@pytest.mark.asyncio
async def test_a_resume_while_pending_does_nothing(parked, monkeypatch):
    await _loop(parked.db).run(parked.run.id)

    async def _still_pending(db, marker, now=None):  # noqa: ARG001
        return "PENDING", ""

    monkeypatch.setattr(approval_pause, "decision_for", _still_pending)
    outcome = await _loop(parked.db).resume_after_approval(parked.run.id)
    assert outcome == {"run_id": str(parked.run.id), "status": "PAUSED", "resumed": False}
    assert parked.executor.calls == [["s1"]] and parked.run.status == RunStatus.PAUSED.value
