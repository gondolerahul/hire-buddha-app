"""A child that failed for a passing reason gets one more run; a queue outage
says so (P7.12 — AK-19, AK-20).

A ``ChildEntity`` move is never retried on a critic's REVISE — re-running a
whole sub-agent rarely changes the verdict. But a child that failed on a rate
limit or a timeout failed the parent with no second attempt. Now such a
child's step is reopened once, and the next move dispatches it again. A Redis
error during dispatch read like a configuration problem; it now says the queue
is unreachable, and the step stays ready.
"""
from __future__ import annotations

from uuid import uuid4

import pytest

from src.ai.core.agent_state import AgentState
from src.ai.schemas.enums import RunStatus

from tests.unit.test_async_child_dispatch import _dispatch_fakes, _FakeChildRun, _FakeParentRun, _loop_with_children, _make_state, _Step


def _failed(error: str) -> _FakeChildRun:
    child = _FakeChildRun(RunStatus.FAILED.value)
    child.error_message = error
    return child


@pytest.mark.asyncio
async def test_a_transient_child_failure_reopens_its_step_once():
    state = _make_state()
    state.plan_steps = [{"step_id": "research", "type": "CHILD_ENTITY_INVOCATION"}]
    first, second = str(uuid4()), str(uuid4())
    state.awaiting_children = [{"run_id": first, "step_id": "research", "status": "PENDING"}]
    loop = _loop_with_children({
        first: _failed("429 RESOURCE_EXHAUSTED: quota exceeded"),
        second: _failed("429 RESOURCE_EXHAUSTED: quota exceeded"),
    })

    all_terminal, any_failed = await loop._fold_children(state)
    assert (all_terminal, any_failed) == (True, False)
    assert [s["step_id"] for s in state.plan_ready_steps()] == ["research"]   # dispatched again
    assert state.child_retries == {"research": 1}
    assert AgentState.restore(state.snapshot()).child_retries == {"research": 1}

    # The second run fails the same way: no third attempt.
    state.awaiting_children = [{"run_id": second, "step_id": "research", "status": "PENDING"}]
    _all, any_failed = await loop._fold_children(state)
    assert any_failed is True and "research" in state.failed_steps


@pytest.mark.asyncio
async def test_a_real_failure_is_not_retried():
    state = _make_state()
    child = str(uuid4())
    state.awaiting_children = [{"run_id": child, "step_id": "write", "status": "PENDING"}]
    loop = _loop_with_children({child: _failed("ValueError: the brief has no audience")})
    _all, any_failed = await loop._fold_children(state)
    assert any_failed is True and state.child_retries == {}


def test_what_counts_as_transient():
    from src.ai.core.executors.child_entity import is_transient_failure
    assert is_transient_failure("Timeout after 60000ms")
    assert is_transient_failure("503 Service Unavailable")
    assert not is_transient_failure("Execution blocked by human reviewer")


@pytest.mark.asyncio
async def test_a_queue_outage_says_so_and_leaves_the_step_ready(monkeypatch):
    from src.ai.core.executors import child_entity as ce

    engine, redis, created, _enqueued = _dispatch_fakes(monkeypatch)

    async def _down(_redis, _run_id):
        raise ConnectionError("Error 10061 connecting to localhost:6379")

    monkeypatch.setattr("src.common.job_queue.enqueue_child_run", _down)
    result = await ce.ChildEntityExecutor()._dispatch_async(
        engine, redis, run=_FakeParentRun(), entity=None, steps=[_Step("research")], state=_make_state(),
        start=0.0)
    assert result.success is False
    assert "job queue (Redis) is unreachable" in result.error and "stays ready" in result.error
    assert result.failed_steps == {} and result.completed_step_ids == []
