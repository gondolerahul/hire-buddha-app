"""Phase 11 Track 2 — AgentLoop BUG 1 regressions.

Covers the architecture defects surfaced by the doc-factory-process canary
(see backend/src/ai/core/agent_loop.py and
backend/src/ai/core/executors/single_step.py):

  1. SingleStep with an empty plan_fragment must NOT hand the whole run to
     ``ExecutionEngine.execute_run`` (which re-plans, runs the entire DAG,
     settles billing, and marks the run COMPLETED inside one loop iteration —
     defeating the loop and re-billing). It must be a zero-cost no-op.

  2. A dynamic-planning entity (static_plan disabled) must get a plan
     reconciled up front (``_ensure_plan``) so the loop drives steps one at a
     time — and STILL never calls ``execute_run``.

  3. Now that the loop owns the run lifecycle, it must settle billing itself
     for top-level runs (previously only the legacy full-run fallback did).

Pure unit tests: no DB / Redis / LLM. They reuse the in-memory fakes from
test_agent_loop_integration.py.
"""
from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from src.ai.core.agent_loop import AgentLoop
from src.ai.core.agent_state import AgentState
from src.ai.core.events import capture_test_events
from src.ai.core.executors.base import (
    EXECUTOR_REGISTRY,
    ActionResult,
    register_executor,
)
from src.ai.core.executors.single_step import SingleStepExecutor
from src.ai.core.strategist import Move
from src.ai.core.feature_flags import FeatureFlags
from src.ai.planning.critic_pipeline import NoOpCriticPipeline
from src.ai.core.agent_state import PreCriticVerdict
from src.ai.schemas.enums import EntityType, RunStatus


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


def _dynamic_entity(entity_id: UUID, company_id: UUID) -> SimpleNamespace:
    """A PROCESS configured for dynamic planning — no static plan steps.

    This is the doc-factory-process shape: bootstrap finds no plan_steps, so
    the loop must reconcile one before the Strategist can dispatch.
    """
    return SimpleNamespace(
        id=entity_id,
        company_id=company_id,
        name="dynamic_process",
        type="PROCESS",
        goal="Route the request to the right specialist and deliver.",
        description="fake",
        identity=None,
        hierarchy=None,
        logic_gate=None,
        planning={
            "static_plan": {"enabled": False},
            "dynamic_planning": {"enabled": True, "planning_prompt": "plan it"},
        },
        capabilities=None,
        governance={"max_cost_usd": 25.0, "timeout_ms": 600_000},
        io_contract=None,
        observability=None,
        metadata_extensions=None,
    )


class _FakeRun:
    def __init__(self, entity: SimpleNamespace):
        self.id = uuid4()
        self.entity_id = entity.id
        self.company_id = entity.company_id
        self.user_id = None
        self.parent_run_id = None
        self.status = RunStatus.PENDING.value
        self.input_data = {"input": "make me an xlsx"}
        self.dynamic_plan = None
        self.result_data = None
        self.context_state = None
        self.total_cost_usd = Decimal("0")
        self.total_tokens = 0
        self.error_message = None
        self.started_at = None
        self.completed_at = None
        self.entity = entity


class _FakeResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value

    def scalar_one(self):
        if self._value is None:
            raise LookupError("no result")
        return self._value


class _FakeDB:
    def __init__(self, run: _FakeRun):
        self.run = run

    async def execute(self, *_args, **_kwargs):
        return _FakeResult(self.run)

    async def commit(self):
        pass

    async def rollback(self):
        pass

    async def refresh(self, _obj):
        return


class _FakeSingleStep:
    """Completes whatever step it's handed; records its calls."""
    name = "SingleStep"

    def __init__(self):
        self.calls = 0
        self.fragments: list = []

    async def execute(self, move, state, db):  # noqa: ARG002
        self.calls += 1
        self.fragments.append(move.plan_fragment)
        return ActionResult(
            output="step ran",
            cost_usd=Decimal("0.01"),
            latency_ms=10,
            success=True,
            completed_step_ids=[str(move.plan_fragment[0]["step_id"])]
            if move.plan_fragment else [],
        )


@pytest.fixture
def swap_single_step():
    original = EXECUTOR_REGISTRY.get("SingleStep")
    fake = _FakeSingleStep()
    register_executor(fake)
    try:
        yield fake
    finally:
        if original is not None:
            register_executor(original)


@pytest.fixture
def explode_execute_run():
    """BUG 1 was the AgentLoop secretly invoking the legacy full-run lifecycle.

    The legacy ``ExecutionEngine.execute_run`` plan-walker has since been deleted
    (C4): there is no full-run engine for the loop to call, so the regression is
    structurally impossible. Retained as a no-op counter (always 0) so the
    asserting tests still document the invariant.
    """
    return {"n": 0}


# ---------------------------------------------------------------------------
# 1. SingleStep no-fragment is a no-op, never execute_run
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_single_step_no_fragment_is_noop_not_full_run(explode_execute_run):
    state = AgentState(
        run_id=uuid4(), entity_id=uuid4(), company_id=uuid4(),
        entity_type=EntityType.PROCESS,
    )
    move = Move(
        move_id=str(uuid4()),
        goal_id=None,
        executor="SingleStep",
        plan_fragment=None,           # the trigger for the old full-run fallback
        rationale="default fallback",
    )

    result = await SingleStepExecutor().execute(move, state, db=None)

    # No legacy lifecycle was run …
    assert explode_execute_run["n"] == 0
    # … and the no-op makes no progress / spends nothing / doesn't fail the run.
    assert result.success is True
    assert result.cost_usd == Decimal("0")
    assert result.completed_step_ids == []
    assert result.output == ""


# ---------------------------------------------------------------------------
# 2. Dynamic-planning entity: plan reconciled, driven step-by-step, no full run
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dynamic_plan_is_reconciled_and_driven_without_execute_run(
    swap_single_step, explode_execute_run, monkeypatch,
):
    entity = _dynamic_entity(uuid4(), uuid4())
    run = _FakeRun(entity)
    db = _FakeDB(run)

    reconciled = {
        "steps": [
            {
                "step_id": "s1", "order": 1, "name": "route",
                "type": "ACTION", "target": {}, "required": True,
            }
        ]
    }

    async def _fake_reconcile(self, _run, _entity, _input):  # noqa: ANN001, ARG001
        return reconciled

    from src.ai.planning.planner_service import PlannerService
    monkeypatch.setattr(PlannerService, "reconcile", _fake_reconcile)

    loop = AgentLoop(db=db, redis=None, feature_flags=FeatureFlags(db=None))
    with capture_test_events() as evts:
        outcome = await loop.run(run.id)

    names = [e.name for e in evts]
    # The loop reconciled a plan up front …
    assert "agent.loop.plan_reconciled" in names
    # … persisted it onto the run …
    assert run.dynamic_plan == reconciled
    # … dispatched the reconciled step via SingleStep WITH a concrete fragment …
    assert swap_single_step.calls >= 1
    assert swap_single_step.fragments[0] == reconciled["steps"]
    # … and NEVER fell back to the legacy full run.
    assert explode_execute_run["n"] == 0
    assert outcome["status"] in {
        RunStatus.COMPLETED.value, RunStatus.PARTIAL_COMPLETE.value,
    }


@pytest.mark.asyncio
async def test_ensure_plan_noop_when_plan_already_present(monkeypatch):
    """If the loop already has plan_steps, _ensure_plan must not re-plan."""
    entity = _dynamic_entity(uuid4(), uuid4())
    run = _FakeRun(entity)
    db = _FakeDB(run)
    loop = AgentLoop(db=db, redis=None, feature_flags=FeatureFlags(db=None))
    loop._run_id = run.id
    loop._entity = entity

    called = {"n": 0}

    async def _fake_reconcile(self, *_a, **_kw):  # noqa: ANN001, ARG001
        called["n"] += 1
        return {"steps": []}

    from src.ai.planning.planner_service import PlannerService
    monkeypatch.setattr(PlannerService, "reconcile", _fake_reconcile)

    state = AgentState(
        run_id=run.id, entity_id=entity.id, company_id=entity.company_id,
        entity_type=EntityType.PROCESS,
        plan_steps=[{"step_id": "existing", "name": "x", "type": "ACTION"}],
    )
    await loop._ensure_plan(state)
    assert called["n"] == 0
    assert state.plan_steps == [{"step_id": "existing", "name": "x", "type": "ACTION"}]


# ---------------------------------------------------------------------------
# 3. AgentLoop settles billing for top-level runs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_agent_loop_settles_billing_once(swap_single_step, monkeypatch):
    entity = _dynamic_entity(uuid4(), uuid4())
    run = _FakeRun(entity)
    db = _FakeDB(run)

    async def _fake_reconcile(self, _run, _entity, _input):  # noqa: ANN001, ARG001
        return {"steps": [{
            "step_id": "s1", "order": 1, "name": "route",
            "type": "ACTION", "target": {}, "required": True,
        }]}

    from src.ai.planning.planner_service import PlannerService
    monkeypatch.setattr(PlannerService, "reconcile", _fake_reconcile)

    settled: list = []

    async def _fake_settle(self, billed_run, entity_name):  # noqa: ANN001, ARG001
        settled.append((billed_run, entity_name))
        return Decimal("0.42")

    from src.ai.governance.governance_service import GovernanceService
    monkeypatch.setattr(GovernanceService, "settle_billing", _fake_settle)

    loop = AgentLoop(db=db, redis=None, feature_flags=FeatureFlags(db=None))
    with capture_test_events() as evts:
        await loop.run(run.id)

    # Settled exactly once, for THIS run, with the entity name.
    assert len(settled) == 1
    assert settled[0][0].id == run.id
    assert settled[0][1] == entity.name
    assert "agent.loop.billing_settled" in [e.name for e in evts]


def _static_entity(entity_id: UUID, company_id: UUID) -> SimpleNamespace:
    """A SKILL with a ready static plan step — produces a plan-driven move."""
    return SimpleNamespace(
        id=entity_id,
        company_id=company_id,
        name="static_skill",
        type="SKILL",
        goal="Do the thing",
        description="fake",
        identity=None,
        hierarchy=None,
        logic_gate=None,
        planning={
            "static_plan": {
                "enabled": True,
                "steps": [{
                    "step_id": "s1", "order": 1, "name": "do_it",
                    "type": "ACTION", "required": True,
                }],
            }
        },
        capabilities=None,
        governance={"max_cost_usd": 5.0, "timeout_ms": 600_000},
        io_contract=None,
        observability=None,
        metadata_extensions=None,
    )


class _RecordingAlwaysBlocks(NoOpCriticPipeline):
    """Pre-critic that BLOCKs every move and counts how often it's consulted."""

    def __init__(self):
        self.pre_calls = 0

    async def pre_action(self, move, state):  # noqa: ARG002
        self.pre_calls += 1
        return PreCriticVerdict(kind="BLOCK", concerns=["nope"])


@pytest.mark.asyncio
async def test_pre_critic_skipped_for_plan_driven_moves(swap_single_step):
    """A plan-driven move (plan_fragment present) must NOT be sent to the
    pre-critic — otherwise an always-BLOCK critic + deterministic Strategist
    dead-ends the run at the circuit breaker (Phase 11 incident #2 follow-up).
    """
    entity = _static_entity(uuid4(), uuid4())
    run = _FakeRun(entity)
    db = _FakeDB(run)
    critic = _RecordingAlwaysBlocks()

    loop = AgentLoop(
        db=db, redis=None, critic_pipeline=critic, max_iterations=10,
        feature_flags=FeatureFlags(db=None),
    )
    with capture_test_events() as evts:
        outcome = await loop.run(run.id)

    names = [e.name for e in evts]
    # Pre-critic was never consulted for the plan-driven step …
    assert critic.pre_calls == 0
    # … so the move executed, the breaker never fired, and the run finished.
    assert "agent.loop.pre_critic_circuit_break" not in names
    assert "agent.loop.pre_critic_block" not in names
    assert swap_single_step.calls >= 1
    assert outcome["status"] in {
        RunStatus.COMPLETED.value, RunStatus.PARTIAL_COMPLETE.value,
    }


@pytest.mark.asyncio
async def test_pre_critic_still_runs_for_open_ended_moves(swap_single_step):
    """A move with NO plan_fragment (open-ended) still goes through the
    pre-critic — that's where a BLOCK is actionable."""
    # No-plan SKILL → Strategist default → SingleStep with no plan_fragment.
    entity = SimpleNamespace(
        id=uuid4(), company_id=uuid4(), name="noplan", type="SKILL",
        goal="g", description="d", identity=None, hierarchy=None,
        logic_gate=None,
        planning={"static_plan": {"enabled": False},
                  "dynamic_planning": {"enabled": False}},
        capabilities=None,
        governance={"max_cost_usd": 5.0, "timeout_ms": 600_000},
        io_contract=None, observability=None, metadata_extensions=None,
    )
    run = _FakeRun(entity)
    db = _FakeDB(run)
    critic = _RecordingAlwaysBlocks()

    loop = AgentLoop(
        db=db, redis=None, critic_pipeline=critic, max_iterations=10,
        max_consecutive_pre_critic_blocks=3,
        feature_flags=FeatureFlags(db=None),
    )
    with capture_test_events() as evts:
        outcome = await loop.run(run.id)

    # Open-ended move WAS sent to the pre-critic, blocked 3x → breaker abort.
    assert critic.pre_calls == 3
    assert "agent.loop.pre_critic_circuit_break" in [e.name for e in evts]
    assert outcome["iterations"] == 3


@pytest.mark.asyncio
async def test_child_run_does_not_settle_billing(swap_single_step, monkeypatch):
    """Child runs (parent_run_id set) must not settle — only top-level runs do."""
    entity = _dynamic_entity(uuid4(), uuid4())
    run = _FakeRun(entity)
    run.parent_run_id = uuid4()        # mark as a child run
    db = _FakeDB(run)

    async def _fake_reconcile(self, _run, _entity, _input):  # noqa: ANN001, ARG001
        return {"steps": [{
            "step_id": "s1", "order": 1, "name": "route",
            "type": "ACTION", "target": {}, "required": True,
        }]}

    from src.ai.planning.planner_service import PlannerService
    monkeypatch.setattr(PlannerService, "reconcile", _fake_reconcile)

    settled: list = []

    async def _fake_settle(self, billed_run, entity_name):  # noqa: ANN001, ARG001
        settled.append((billed_run, entity_name))
        return Decimal("0")

    from src.ai.governance.governance_service import GovernanceService
    monkeypatch.setattr(GovernanceService, "settle_billing", _fake_settle)

    loop = AgentLoop(db=db, redis=None, feature_flags=FeatureFlags(db=None))
    await loop.run(run.id)

    assert settled == []


# ---------------------------------------------------------------------------
# 4. Cost + LLM-interaction-log persistence
#
# Regression for the doc-factory-process incident: agent_loop runs finished
# with total_cost_usd=0 and ZERO llm_interaction_logs even though the planner
# LLM and the critic pipeline really ran. Two root causes:
#   (a) _persist_final opened with a blind ``rollback()`` that discarded the
#       loop's still-pending writes (the planner's LLMInteractionLog + the
#       run.total_cost_usd bump); it now commits-then-reloads.
#   (b) critic LLM spend was written to usage_logs but never folded into
#       run.total_cost_usd, so settle_billing short-circuited at $0.
# ---------------------------------------------------------------------------


class _TxnFakeDB:
    """A fake AsyncSession that models commit/rollback durability.

    Unlike the trivial ``_FakeDB`` above, this one tracks pending vs committed
    ``add()``s and snapshots ``run.total_cost_usd`` at each commit so a
    ``rollback()`` actually restores the last-committed value. That lets the
    test prove the planner's LLMInteractionLog SURVIVES finalization (i.e. it
    is committed, not rolled back) and that the run's cost is durable.
    """

    def __init__(self, run: _FakeRun):
        self.run = run
        self._pending: list = []
        self.committed: list = []
        self._cost_snapshot = run.total_cost_usd
        self.commit_count = 0
        self.rollback_count = 0

    async def execute(self, stmt, *_a, **_kw):
        name = None
        try:
            descs = stmt.column_descriptions
            if len(descs) == 1:
                name = descs[0].get("name")
        except Exception:
            name = None
        if name == "total_cost_usd":
            return _FakeResult(self.run.total_cost_usd)
        if name == "status":
            return _FakeResult(self.run.status)
        return _FakeResult(self.run)

    def add(self, obj):
        self._pending.append(obj)

    async def commit(self):
        self.commit_count += 1
        self.committed.extend(self._pending)
        self._pending = []
        self._cost_snapshot = self.run.total_cost_usd

    async def rollback(self):
        self.rollback_count += 1
        self._pending = []
        # Restore the run's cost to the last committed value — this is what a
        # real session rollback does, and what used to wipe agent_loop cost.
        self.run.total_cost_usd = self._cost_snapshot

    async def refresh(self, _obj):
        return


class _CostingCritic(NoOpCriticPipeline):
    """A critic whose finalize_iteration reports a non-zero per-iteration cost
    on its StepHealthRecord (as the RealCriticPipeline does), so the loop has
    real critic spend to fold into total_cost_usd."""

    async def finalize_iteration(self, state):
        from src.ai.planning.step_health_record import StepHealthRecord
        rec = StepHealthRecord(iteration=state.iteration)
        rec.post_critic_cost_usd = Decimal("0.05")
        return rec


@pytest.mark.asyncio
async def test_agent_loop_persists_llm_log_and_nonzero_cost(
    swap_single_step, monkeypatch,
):
    """An agent_loop run with ≥1 LLM call must persist ≥1 llm_interaction_log
    and a non-zero total_cost_usd, and hand that non-zero cost to settle_billing.
    """
    from src.ai.models import LLMInteractionLog

    entity = _dynamic_entity(uuid4(), uuid4())
    run = _FakeRun(entity)
    db = _TxnFakeDB(run)

    # The real planner writes an LLMInteractionLog and bumps run.total_cost_usd;
    # simulate exactly that side-effect on the loop's shared session.
    async def _fake_reconcile(self, run_, _entity, _input):  # noqa: ANN001, ARG001
        self.db.add(LLMInteractionLog(
            run_id=run_.id,
            model_provider="mock",
            model_name="mock-model",
            input_prompt="System: plan\nUser: do it",
            output_response="planned",
            prompt_tokens=100,
            completion_tokens=40,
            latency_ms=5,
            reasoning_mode="PLANNER",
            step_name="__planner__",
        ))
        run_.total_cost_usd = (run_.total_cost_usd or Decimal("0")) + Decimal("0.10")
        return {"steps": [{
            "step_id": "s1", "order": 1, "name": "route",
            "type": "ACTION", "target": {}, "required": True,
        }]}

    from src.ai.planning.planner_service import PlannerService
    monkeypatch.setattr(PlannerService, "reconcile", _fake_reconcile)

    # Capture the cost handed to settle_billing (task 3: it must be non-zero so
    # the run bills, rather than short-circuiting at $0 with billed_amount NULL).
    settled: list = []

    async def _fake_settle(self, billed_run, entity_name):  # noqa: ANN001, ARG001
        cost = Decimal(str(billed_run.total_cost_usd or 0))
        settled.append(cost)
        if cost <= 0:
            billed_run.billed_amount = Decimal("0")
            return Decimal("0")
        billed_run.billed_amount = cost * Decimal("2")   # stand-in TB markup
        return billed_run.billed_amount

    from src.ai.governance.governance_service import GovernanceService
    monkeypatch.setattr(GovernanceService, "settle_billing", _fake_settle)

    loop = AgentLoop(
        db=db, redis=None, critic_pipeline=_CostingCritic(),
        feature_flags=FeatureFlags(db=None),
    )
    outcome = await loop.run(run.id)

    # ≥1 llm_interaction_log was COMMITTED (survived _persist_final, not rolled back).
    planner_logs = [o for o in db.committed if isinstance(o, LLMInteractionLog)]
    assert len(planner_logs) >= 1

    # The happy path never rolls back: _persist_final commits-then-reloads
    # rather than opening with a blind rollback() that would discard the loop's
    # still-pending writes. A regression to the old rollback-first would trip this.
    assert db.rollback_count == 0

    # Non-zero total cost that includes BOTH the planner spend (0.10) and the
    # per-iteration critic spend (≥0.05) — strictly exceeding the planner-only
    # 0.10 proves critic cost is folded into total_cost_usd (and didn't get
    # discarded by _persist_final's session reset). The exact figure depends on
    # how many iterations the one-step plan takes, so we don't pin it.
    assert float(run.total_cost_usd) > 0.10
    assert float(outcome["total_cost_usd"]) > 0.10
    assert float(outcome["total_cost_usd"]) == pytest.approx(float(run.total_cost_usd))

    # settle_billing received the real non-zero cost and stamped billed_amount
    # (it would otherwise short-circuit at $0 / billed_amount NULL).
    assert len(settled) == 1
    assert settled[0] > Decimal("0.10")
    assert run.billed_amount > 0
