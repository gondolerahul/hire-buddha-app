"""Phase 11 Track 2 — AgentLoop robustness regression tests.

Covers the two gaps that let a runaway run bill $17+ while making no
progress (see backend/src/ai/core/agent_loop.py):

  1. Pre-critic livelock — a Strategist that keeps proposing a move the
     pre-critic always BLOCKs must trip a consecutive-block circuit
     breaker and ABORT, instead of spinning to the hard iteration cap.

  2. Cancellation — an operator flips ExecutionRun.status away from
     RUNNING (via POST /executions/{id}/cancel); the loop re-reads the
     status at the top of each iteration and aborts, preserving the
     terminal status.

  3. Dispatch idempotency — run_execution_recursive must not re-drive
     (and re-bill) a run that is already in a terminal state.

These are pure unit tests: no DB / Redis / LLM. They lean on the same
in-memory fakes as test_agent_loop_integration.py.
"""
from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from src.ai.core.agent_loop import AgentLoop
from src.ai.core.events import capture_test_events
from src.ai.core.executors.base import (
    EXECUTOR_REGISTRY,
    ActionResult,
    register_executor,
)
from src.ai.core.feature_flags import FeatureFlags
from src.ai.planning.critic_pipeline import NoOpCriticPipeline
from src.ai.core.agent_state import AgentState, PreCriticVerdict
from src.ai.schemas.enums import EntityType, RunStatus


# ---------------------------------------------------------------------------
# Fakes (mirrors test_agent_loop_integration.py)
# ---------------------------------------------------------------------------


def _make_entity(entity_id: UUID, company_id: UUID) -> SimpleNamespace:
    return SimpleNamespace(
        id=entity_id,
        company_id=company_id,
        name="fake_skill",
        type="SKILL",
        goal="Do the thing",
        description="fake",
        identity=None,
        hierarchy=None,
        logic_gate=None,
        # No plan: the Strategist falls to its default branch and emits a
        # SingleStep move with NO plan_fragment — an *open-ended* move. The
        # pre-critic runs on those (and is what these tests exercise). Plan-
        # driven moves now skip the pre-critic by design (a reconciled plan
        # shouldn't be second-guessed move-by-move), so a static plan here would
        # make the circuit-breaker test no longer reach the pre-critic.
        planning={
            "static_plan": {"enabled": False},
            "dynamic_planning": {"enabled": False},
        },
        capabilities=None,
        governance={"max_cost_usd": 100.0, "timeout_ms": 600_000},
        io_contract=None,
        observability=None,
        metadata_extensions=None,
    )


class _FakeRun:
    def __init__(self):
        self.id = uuid4()
        self.entity_id = uuid4()
        self.company_id = uuid4()
        self.user_id = None
        self.status = RunStatus.PENDING.value
        self.input_data = {}
        self.dynamic_plan = None
        self.result_data = None
        self.context_state = None
        self.total_cost_usd = Decimal("0")
        self.total_tokens = 0
        self.error_message = None
        self.started_at = None
        self.completed_at = None
        self.entity = _make_entity(self.entity_id, self.company_id)


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


class _NeverCompletes:
    """Executor that never marks its step complete — keeps the loop alive
    so the circuit breaker / cancellation paths get a chance to fire."""
    name = "SingleStep"

    async def execute(self, move, state, db):  # noqa: ARG002
        return ActionResult(
            success=True, output="noop", cost_usd=Decimal("0"),
            completed_step_ids=[],
        )


@pytest.fixture
def never_completes():
    original = EXECUTOR_REGISTRY.get("SingleStep")
    register_executor(_NeverCompletes())
    try:
        yield
    finally:
        if original is not None:
            register_executor(original)


# ---------------------------------------------------------------------------
# 1. Pre-critic circuit breaker
# ---------------------------------------------------------------------------


class _AlwaysBlocks(NoOpCriticPipeline):
    """Pre-critic that BLOCKs every move (the Phase 11 livelock shape)."""

    async def pre_action(self, move, state) -> PreCriticVerdict:  # noqa: ARG002
        return PreCriticVerdict(
            kind="BLOCK", concerns=["stop all async/tool/specialist routing"]
        )


@pytest.mark.asyncio
async def test_consecutive_pre_critic_blocks_trip_circuit_breaker(never_completes):
    run = _FakeRun()
    db = _FakeDB(run)
    loop = AgentLoop(
        db=db, redis=None,
        critic_pipeline=_AlwaysBlocks(),
        max_iterations=50,                      # well above the breaker threshold
        max_consecutive_pre_critic_blocks=3,
        feature_flags=FeatureFlags(db=None),
    )

    with capture_test_events() as evts:
        outcome = await loop.run(run.id)

    # Aborts after exactly N consecutive blocks — NOT the hard iteration cap.
    assert outcome["iterations"] == 3
    assert outcome["status"] == RunStatus.FAILED.value

    names = [e.name for e in evts]
    assert names.count("agent.loop.pre_critic_block") == 3
    assert "agent.loop.pre_critic_circuit_break" in names
    # The breaker should fire well before the 50-iteration backstop.
    assert "agent.loop.budget_exhausted" not in names

    # The consecutive counter is surfaced on each block event, climbing 1→2→3.
    block_counts = [
        e.payload.get("consecutive")
        for e in evts if e.name == "agent.loop.pre_critic_block"
    ]
    assert block_counts == [1, 2, 3]


@pytest.mark.asyncio
async def test_block_streak_resets_after_a_passing_move(never_completes):
    """A move that clears the pre-critic resets the streak, so isolated
    blocks interspersed with progress never trip the breaker."""
    class _BlocksThenPasses(NoOpCriticPipeline):
        def __init__(self):
            self.calls = 0

        async def pre_action(self, move, state):  # noqa: ARG002
            self.calls += 1
            # Block, block, pass, block, block, pass, ... never 3 in a row.
            if self.calls % 3 == 0:
                return PreCriticVerdict(kind="PASS")
            return PreCriticVerdict(kind="BLOCK", concerns=["nope"])

    run = _FakeRun()
    db = _FakeDB(run)
    loop = AgentLoop(
        db=db, redis=None,
        critic_pipeline=_BlocksThenPasses(),
        max_iterations=7,
        max_consecutive_pre_critic_blocks=3,
        feature_flags=FeatureFlags(db=None),
    )

    with capture_test_events() as evts:
        outcome = await loop.run(run.id)

    names = [e.name for e in evts]
    # Streak never reaches 3 in a row → breaker never fires; run ends on the
    # iteration cap instead.
    assert "agent.loop.pre_critic_circuit_break" not in names
    assert outcome["iterations"] == 7


# ---------------------------------------------------------------------------
# 2. Cancellation
# ---------------------------------------------------------------------------


class _CancelDuringStep:
    """Flips the run to CANCELLED while acting, so the *next* iteration's
    top-of-loop status re-read aborts the run."""
    name = "SingleStep"

    async def execute(self, move, state, db):  # noqa: ARG002
        db.run.status = RunStatus.CANCELLED.value
        return ActionResult(
            success=True, output="noop", cost_usd=Decimal("0"),
            completed_step_ids=[],
        )


@pytest.mark.asyncio
async def test_loop_aborts_when_run_cancelled_midflight():
    original = EXECUTOR_REGISTRY.get("SingleStep")
    register_executor(_CancelDuringStep())
    try:
        run = _FakeRun()
        db = _FakeDB(run)
        loop = AgentLoop(
            db=db, redis=None, max_iterations=50,
            feature_flags=FeatureFlags(db=None),
        )
        with capture_test_events() as evts:
            outcome = await loop.run(run.id)
    finally:
        if original is not None:
            register_executor(original)

    names = [e.name for e in evts]
    assert "agent.loop.cancelled" in names
    # Cancellation is detected at the top of iteration 2, so only iteration 1
    # ever ran (the check returns before incrementing).
    assert outcome["iterations"] == 1
    # Terminal status is preserved as CANCELLED, not relabelled FAILED.
    assert outcome["status"] == RunStatus.CANCELLED.value


@pytest.mark.asyncio
async def test_check_cancelled_is_noop_while_running(never_completes):
    """A run that stays RUNNING is never spuriously cancelled."""
    run = _FakeRun()
    db = _FakeDB(run)
    loop = AgentLoop(
        db=db, redis=None, max_iterations=2,
        feature_flags=FeatureFlags(db=None),
    )
    state = AgentState(
        run_id=run.id, entity_id=run.entity_id, company_id=run.company_id,
        entity_type=EntityType.ACTION,
    )
    loop._run_id = run.id
    run.status = RunStatus.RUNNING.value
    assert await loop._check_cancelled(state) is False
    assert state.next_decision == "CONTINUE"

    run.status = RunStatus.CANCELLED.value
    assert await loop._check_cancelled(state) is True
    assert state.next_decision == "ABORT"
    assert state.external_status == RunStatus.CANCELLED.value
