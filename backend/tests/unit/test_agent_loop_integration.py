"""Phase 11 Track 2 — AgentLoop integration test with a stub executor.

This test does NOT need DB / Redis / LLM. It constructs an in-memory
fake DB session that satisfies the AgentLoop's narrow needs, registers
a fake executor that completes a single plan step, and asserts the
loop drives a full iteration with the expected events and final state.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from src.ai.core.agent_loop import AgentLoop
from src.ai.core.executors.base import (
    EXECUTOR_REGISTRY,
    ActionResult,
    register_executor,
)
from src.ai.core.events import capture_test_events
from src.ai.core.feature_flags import FeatureFlags
from src.ai.schemas.enums import EntityType, RunStatus


# ---------------------------------------------------------------------------
# Stub DB / run / entity
# ---------------------------------------------------------------------------


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
        self.entity: SimpleNamespace = _make_entity(self.entity_id, self.company_id)


def _make_entity(entity_id: UUID, company_id: UUID) -> SimpleNamespace:
    """SKILL entity with a single plan step."""
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
        planning={
            "static_plan": {
                "enabled": True,
                "steps": [
                    {
                        "step_id": "s1",
                        "order": 1,
                        "name": "do_it",
                        "type": "ACTION",
                        "required": True,
                    }
                ],
            }
        },
        capabilities=None,
        governance={"max_cost_usd": 1.0, "timeout_ms": 60_000},
        io_contract=None,
        observability=None,
        metadata_extensions=None,
    )


class _FakeResult:
    """SQLAlchemy AsyncResult facsimile."""
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value

    def scalar_one(self):
        if self._value is None:
            raise LookupError("no result")
        return self._value


class _FakeDB:
    """Minimal AsyncSession stand-in: returns the same run on every query."""
    def __init__(self, run: _FakeRun):
        self.run = run
        self.commit_count = 0
        self.rollback_count = 0

    async def execute(self, *_args, **_kwargs):
        return _FakeResult(self.run)

    async def commit(self):
        self.commit_count += 1

    async def rollback(self):
        self.rollback_count += 1

    async def refresh(self, _obj):
        return


# ---------------------------------------------------------------------------
# A fake executor we can swap in for "SingleStep" to drive the loop without DB.
# ---------------------------------------------------------------------------


class _FakeSingleStepExecutor:
    name = "SingleStep"

    def __init__(self):
        self.calls = 0

    async def execute(self, move, state, db):  # noqa: ARG002
        self.calls += 1
        return ActionResult(
            output="step ran",
            cost_usd=Decimal("0.01"),
            latency_ms=50,
            success=True,
            completed_step_ids=[str(move.plan_fragment[0]["step_id"])]
                if move.plan_fragment else [],
        )


@pytest.fixture
def swap_single_step():
    """Replace the registered SingleStepExecutor with a fake for the test,
    restore the original on teardown."""
    original = EXECUTOR_REGISTRY.get("SingleStep")
    fake = _FakeSingleStepExecutor()
    register_executor(fake)
    try:
        yield fake
    finally:
        if original is not None:
            register_executor(original)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_agent_loop_runs_one_step_to_completion(swap_single_step):
    run = _FakeRun()
    db = _FakeDB(run)
    loop = AgentLoop(db=db, redis=None, feature_flags=FeatureFlags(db=None))

    with capture_test_events() as evts:
        outcome = await loop.run(run.id)

    assert swap_single_step.calls >= 1
    assert outcome["status"] in {RunStatus.COMPLETED.value, RunStatus.PARTIAL_COMPLETE.value}
    assert outcome["iterations"] >= 1

    names = {e.name for e in evts}
    assert "agent.loop.run_start" in names
    assert "agent.loop.iteration_start" in names
    assert "agent.loop.iteration_end" in names
    assert "agent.executor.invoked" in names
    assert "agent.executor.completed" in names
    assert "agent.loop.run_end" in names


@pytest.mark.asyncio
async def test_agent_loop_terminates_on_iteration_cap(swap_single_step):
    """If the strategist keeps picking the same uncompletable step,
    the hard iteration cap eventually fires."""
    class _NeverCompletes:
        name = "SingleStep"
        async def execute(self, move, state, db):     # noqa: ARG002
            # Don't mark the step complete; loop should hit the cap.
            return ActionResult(
                success=True,
                output="noop",
                cost_usd=Decimal("0"),
                completed_step_ids=[],
            )
    register_executor(_NeverCompletes())

    run = _FakeRun()
    db = _FakeDB(run)
    loop = AgentLoop(db=db, redis=None, max_iterations=3,
                     feature_flags=FeatureFlags(db=None))
    outcome = await loop.run(run.id)
    assert outcome["iterations"] == 3
    assert outcome["status"] in {RunStatus.FAILED.value,
                                 RunStatus.PARTIAL_COMPLETE.value}


@pytest.mark.asyncio
async def test_agent_loop_handles_missing_entity():
    """Run lookup returns None ⇒ AgentLoop raises LookupError."""
    class _EmptyDB:
        async def execute(self, *_a, **_kw):
            return _FakeResult(None)
        async def commit(self): pass
        async def rollback(self): pass

    loop = AgentLoop(db=_EmptyDB(), redis=None,
                     feature_flags=FeatureFlags(db=None))
    with pytest.raises(LookupError):
        await loop.run(uuid4())


@pytest.mark.asyncio
async def test_agent_loop_executor_exception_does_not_crash_loop(swap_single_step):
    """A raising executor turns into a failed-step Observation; the loop
    survives and decides to ABORT (no more progress possible)."""
    class _Raises:
        name = "SingleStep"
        async def execute(self, move, state, db):     # noqa: ARG002
            raise RuntimeError("oh no")
    register_executor(_Raises())

    run = _FakeRun()
    db = _FakeDB(run)
    loop = AgentLoop(db=db, redis=None, max_iterations=3,
                     feature_flags=FeatureFlags(db=None))
    outcome = await loop.run(run.id)
    assert outcome["iterations"] >= 1
    # Outcome status is determined by the strategist; with no plan progress
    # the loop falls through to PARTIAL_COMPLETE or FAILED — either is OK.
    assert outcome["status"] in {RunStatus.FAILED.value,
                                 RunStatus.PARTIAL_COMPLETE.value}
