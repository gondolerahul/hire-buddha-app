"""Unit tests for async child dispatch (suspend/resume).

Covers the pure/loosely-coupled pieces of the mechanism designed in
``docs/phase12/designs/async_child_dispatch.md``:

* the ``WAITING_ON_CHILDREN`` status + transitions,
* the ``ActionResult.awaiting_children`` marker,
* ``AgentState`` snapshot/restore round-trip of ``awaiting_children``,
* ``AgentLoop._fold_children`` (terminal vs pending children),
* ``AgentLoop.resume`` idempotency guard.

The full worker-driven end-to-end path (child job → resume_parent_run) is
exercised hermetically by ``tests/parity/test_async_child_parity.py`` via the
in-process arq drainer (``tests/parity/worker_sim.py``); this file keeps the
unit-level coverage of the individual pieces plus the per-parent concurrency
cap.
"""
from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest

from src.ai.core.agent_state import AgentState
from src.ai.core.budget import Budget
from src.ai.core.executors.base import ActionResult
from src.ai.schemas.enums import EntityType, RunStatus, VALID_TRANSITIONS


# ---------------------------------------------------------------------------
# enum + marker
# ---------------------------------------------------------------------------


def test_waiting_on_children_status_exists() -> None:
    assert RunStatus.WAITING_ON_CHILDREN.value == "WAITING_ON_CHILDREN"


def test_running_can_transition_to_waiting() -> None:
    assert "WAITING_ON_CHILDREN" in VALID_TRANSITIONS["RUNNING"]


def test_waiting_resumes_or_fails() -> None:
    nxt = VALID_TRANSITIONS["WAITING_ON_CHILDREN"]
    assert {"RESUMING", "RUNNING", "FAILED", "CANCELLED"} <= nxt


def test_action_result_awaiting_children_defaults_empty() -> None:
    ar = ActionResult()
    assert ar.awaiting_children == []


# ---------------------------------------------------------------------------
# AgentState snapshot round-trip
# ---------------------------------------------------------------------------


def _make_state() -> AgentState:
    return AgentState(
        run_id=uuid4(), entity_id=uuid4(), company_id=uuid4(),
        entity_type=EntityType.PROCESS, budget=Budget(),
    )


def test_agent_state_roundtrips_awaiting_children() -> None:
    state = _make_state()
    state.awaiting_children = [
        {"run_id": str(uuid4()), "step_id": "step_2", "status": "PENDING"},
    ]
    state.completed_step_ids = {"step_1"}
    restored = AgentState.restore(state.snapshot())
    assert restored.awaiting_children == state.awaiting_children
    assert restored.completed_step_ids == {"step_1"}


def test_suspend_requested_is_transient_not_snapshotted() -> None:
    state = _make_state()
    state.suspend_requested = True
    # Not part of the persisted snapshot; restore defaults it to False.
    assert "suspend_requested" not in state.snapshot()
    assert AgentState.restore(state.snapshot()).suspend_requested is False


# ---------------------------------------------------------------------------
# _fold_children
# ---------------------------------------------------------------------------


class _FakeChildRun:
    def __init__(self, status, *, output="done", cost="0.50", tokens=100):
        self.status = status
        self.result_data = {"output": output}
        self.total_cost_usd = cost
        self.total_tokens = tokens


def _loop_with_children(children_by_id):
    from src.ai.core.agent_loop import AgentLoop

    loop = AgentLoop(db=None, redis=None)

    async def _fake_reload(run_id):
        return children_by_id.get(str(run_id))

    loop._reload_run = _fake_reload          # type: ignore[assignment]
    return loop


@pytest.mark.asyncio
async def test_fold_children_all_terminal_marks_step_and_folds_cost() -> None:
    child_id = str(uuid4())
    state = _make_state()
    state.plan_steps = [{"step_id": "child_step", "type": "CHILD_ENTITY_INVOCATION"}]
    state.awaiting_children = [
        {"run_id": child_id, "step_id": "child_step", "status": "PENDING"},
    ]
    loop = _loop_with_children({
        child_id: _FakeChildRun(RunStatus.COMPLETED.value, output="child output", cost="0.75"),
    })

    all_terminal, any_failed = await loop._fold_children(state)

    assert all_terminal is True
    assert any_failed is False
    assert "child_step" in state.completed_step_ids
    assert state.context_state["child_step"] == "child output"
    assert state.budget.usd_used == Decimal("0.75")


@pytest.mark.asyncio
async def test_fold_children_pending_child_not_all_terminal() -> None:
    child_id = str(uuid4())
    state = _make_state()
    state.awaiting_children = [
        {"run_id": child_id, "step_id": "child_step", "status": "PENDING"},
    ]
    loop = _loop_with_children({
        child_id: _FakeChildRun(RunStatus.RUNNING.value),
    })

    all_terminal, any_failed = await loop._fold_children(state)

    assert all_terminal is False
    assert "child_step" not in state.completed_step_ids


@pytest.mark.asyncio
async def test_fold_children_failed_child_flags_failure() -> None:
    child_id = str(uuid4())
    state = _make_state()
    state.awaiting_children = [
        {"run_id": child_id, "step_id": "child_step", "status": "PENDING"},
    ]
    loop = _loop_with_children({
        child_id: _FakeChildRun(RunStatus.FAILED.value),
    })

    all_terminal, any_failed = await loop._fold_children(state)

    assert all_terminal is True
    assert any_failed is True


# ---------------------------------------------------------------------------
# resume idempotency guard
# ---------------------------------------------------------------------------


class _FakeRun:
    def __init__(self, status):
        self.status = status
        self.context_state = {}
        self.entity = None


@pytest.mark.asyncio
async def test_resume_skips_when_not_waiting() -> None:
    from src.ai.core.agent_loop import AgentLoop

    loop = AgentLoop(db=None, redis=None)
    run = _FakeRun(RunStatus.RUNNING.value)

    async def _fake_reload(run_id):
        return run

    loop._reload_run = _fake_reload          # type: ignore[assignment]

    result = await loop.resume(uuid4())
    assert result["resumed"] is False
    assert result["status"] == RunStatus.RUNNING.value


# ---------------------------------------------------------------------------
# ChildEntityExecutor async dispatch — returns the awaiting marker + enqueues
# ---------------------------------------------------------------------------


def _dispatch_fakes(monkeypatch, *, fail_on=None):
    created: list = []
    enqueued: list = []

    class _FakeChild:
        def __init__(self):
            self.id = uuid4()

    class _FakeStepExec:
        async def create_child_run(self, run, entity, step_obj, ctx):
            if step_obj.step_id == fail_on:
                from src.ai.core.exceptions import CompositionError
                raise CompositionError("past max_recursion_depth")
            child = _FakeChild()
            created.append((step_obj.step_id, child.id))
            return child

    class _FakeEngine:
        _step_executor = _FakeStepExec()

    class _FakeArqRedis:
        def __init__(self, _pool):
            pass

        async def enqueue_job(self, name, *args, _queue_name=None, **kwargs):
            enqueued.append((name, args, _queue_name))

    # Patch the ArqRedis enqueue_child_run builds from the parent's client.
    monkeypatch.setattr("src.common.job_queue.ArqRedis", _FakeArqRedis)

    class _FakeRedis:
        connection_pool = object()

    return _FakeEngine(), _FakeRedis(), created, enqueued


class _Step:
    def __init__(self, step_id):
        self.step_id = step_id
        self.name = step_id


class _FakeParentRun:
    id = uuid4()


@pytest.mark.asyncio
async def test_child_executor_async_dispatch_returns_awaiting_and_enqueues(monkeypatch) -> None:
    from src.ai.core.executors import child_entity as ce

    engine, redis, created, enqueued = _dispatch_fakes(monkeypatch)
    result = await ce.ChildEntityExecutor()._dispatch_async(
        engine, redis, run=_FakeParentRun(), entity=None,
        steps=[_Step("child_step")], state=_make_state(), start=0.0,
    )

    (step_id, child_id), = created
    assert result.success is True
    assert result.awaiting_children == [
        {"run_id": str(child_id), "step_id": "child_step", "status": "PENDING"}
    ]
    assert result.completed_step_ids == []          # step completes only on resume
    # On the child-run queue, which has its own worker (SA-07).
    assert enqueued == [("run_execution_recursive", (str(child_id),), "children")]


@pytest.mark.asyncio
async def test_a_batch_of_children_is_dispatched_together(monkeypatch) -> None:
    """AK-07: the ready children of one move run concurrently, as one batch."""
    from src.ai.core.executors import child_entity as ce

    engine, redis, created, enqueued = _dispatch_fakes(monkeypatch)
    result = await ce.ChildEntityExecutor()._dispatch_async(
        engine, redis, run=_FakeParentRun(), entity=None,
        steps=[_Step("a"), _Step("b"), _Step("c")], state=_make_state(), start=0.0,
    )
    assert [c["step_id"] for c in result.awaiting_children] == ["a", "b", "c"]
    assert len(enqueued) == 3 and len(result.children_run_ids) == 3


@pytest.mark.asyncio
async def test_a_refused_child_stops_the_batch_and_keeps_the_dispatched_ones(monkeypatch) -> None:
    from src.ai.core.executors import child_entity as ce

    engine, redis, created, enqueued = _dispatch_fakes(monkeypatch, fail_on="b")
    result = await ce.ChildEntityExecutor()._dispatch_async(
        engine, redis, run=_FakeParentRun(), entity=None,
        steps=[_Step("a"), _Step("b"), _Step("c")], state=_make_state(), start=0.0,
    )
    assert result.success is True
    assert [c["step_id"] for c in result.awaiting_children] == ["a"]

    engine, redis, created, enqueued = _dispatch_fakes(monkeypatch, fail_on="a")
    refused = await ce.ChildEntityExecutor()._dispatch_async(
        engine, redis, run=_FakeParentRun(), entity=None,
        steps=[_Step("a")], state=_make_state(), start=0.0,
    )
    assert refused.success is False and "max_recursion_depth" in (refused.error or "")
    assert enqueued == []


# ---------------------------------------------------------------------------
# per-parent concurrency cap
# ---------------------------------------------------------------------------


def test_the_cap_reads_governance_and_falls_back_to_the_default() -> None:
    from src.ai.governance.composition import DEFAULT_MAX_CONCURRENT_CHILDREN, max_concurrent_children

    assert max_concurrent_children({"max_concurrent_children": 3}) == 3
    assert max_concurrent_children({}) == DEFAULT_MAX_CONCURRENT_CHILDREN
    assert max_concurrent_children(None) == DEFAULT_MAX_CONCURRENT_CHILDREN
    # Garbage / non-positive overrides fall back to the default (not a crash,
    # not an accidental "0 allowed").
    assert max_concurrent_children({"max_concurrent_children": "x"}) == DEFAULT_MAX_CONCURRENT_CHILDREN
    assert max_concurrent_children({"max_concurrent_children": 0}) == DEFAULT_MAX_CONCURRENT_CHILDREN
