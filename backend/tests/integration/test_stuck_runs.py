"""A parent stuck in WAITING_ON_CHILDREN is resumed or failed (AK-03).

When the resume a finishing child enqueues is lost, nothing looked at the
parent again: never finalised, billed or failed, its credit hold never
released. The sweeper re-enqueues a lost resume, and fails and settles a
parent that waited past the timeout. Real Postgres, rolled back.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.needs_db

NOW = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)


async def _parent_waiting_on(db, company_id, child_status, waited_s, *, stamp=True):
    from src.ai.core.agent_state import AgentState
    from src.ai.orm.entity import HierarchicalEntity
    from src.ai.orm.execution import ExecutionRun
    from src.ai.schemas.enums import EntityType

    process = HierarchicalEntity(company_id=company_id, type="PROCESS", name=f"ak03-p-{uuid.uuid4().hex[:6]}")
    agent = HierarchicalEntity(company_id=company_id, type="AGENT", name=f"ak03-a-{uuid.uuid4().hex[:6]}")
    db.add_all([process, agent])
    await db.flush()
    since = NOW - timedelta(seconds=waited_s)
    parent = ExecutionRun(company_id=company_id, entity_id=process.id, input_data={"input": "x"},
                          status="WAITING_ON_CHILDREN", started_at=since)
    db.add(parent)
    await db.flush()
    child = ExecutionRun(company_id=company_id, entity_id=agent.id, parent_run_id=parent.id,
                         input_data={"input": "x"}, status=child_status, depth=1)
    db.add(child)
    await db.flush()

    state = AgentState(run_id=parent.id, entity_id=process.id, company_id=company_id,
                       entity_type=EntityType.PROCESS)
    state.plan_steps = [{"step_id": "s1", "name": "delegate", "type": "CHILD_ENTITY_INVOCATION",
                         "target": {"entity_id": str(agent.id)}}]
    state.awaiting_children = [{"run_id": str(child.id), "step_id": "s1", "status": "PENDING"}]
    cs = {"__agent_state_snapshot__": state.snapshot()}
    if stamp:
        cs["__suspended_at__"] = since.isoformat()
    parent.context_state = cs
    await db.flush()
    return parent, child


async def _row(db, run_id):
    return (await db.execute(
        text("SELECT status, error_message, completed_at FROM execution_runs WHERE id = :id"),
        {"id": run_id},
    )).one()


@pytest.fixture
def enqueued(monkeypatch):
    calls: list = []

    async def _enqueue(function, *args, **kwargs):  # noqa: ARG001
        calls.append((function, args))

    monkeypatch.setattr("src.common.job_queue.enqueue_job", _enqueue)
    return calls


@pytest.fixture
def settled(monkeypatch):
    calls: list = []

    async def _settle(self, run):  # noqa: ANN001
        calls.append(run.id)

    from src.ai.core.credit_guard import CreditGuard
    monkeypatch.setattr(CreditGuard, "settle", _settle)
    return calls


async def _sweep(db):
    from src.ai.core.stuck_runs import sweep_waiting_runs

    return await sweep_waiting_runs(db, None, grace_s=120, timeout_s=3600, now=NOW)


@pytest.mark.asyncio
async def test_a_lost_resume_is_enqueued_again(db, test_company_id, enqueued, settled):
    parent, _ = await _parent_waiting_on(db, test_company_id, "COMPLETED", waited_s=600)

    assert (await _sweep(db))["resumed"] >= 1
    assert ("resume_parent_run", (str(parent.id),)) in enqueued
    assert (await _row(db, parent.id)).status == "WAITING_ON_CHILDREN"
    assert parent.id not in settled


@pytest.mark.asyncio
async def test_a_parent_waiting_past_the_timeout_fails_and_settles(db, test_company_id, enqueued, settled):
    parent, child = await _parent_waiting_on(db, test_company_id, "RUNNING", waited_s=7200)

    assert (await _sweep(db))["expired"] >= 1
    status, error, completed_at = await _row(db, parent.id)
    assert status == "FAILED"
    assert "timed out" in error
    assert completed_at is not None
    assert parent.id in settled
    assert (await _row(db, child.id)).status == "CANCELLED"
    # A late resume after the sweep is a no-op.
    from src.ai.core.agent_loop import AgentLoop
    assert (await AgentLoop(db, None).resume(parent.id))["resumed"] is False


@pytest.mark.asyncio
async def test_a_run_without_a_suspension_stamp_counts_from_its_start(db, test_company_id, enqueued, settled):
    parent, _ = await _parent_waiting_on(db, test_company_id, "RUNNING", waited_s=7200, stamp=False)

    await _sweep(db)
    assert (await _row(db, parent.id)).status == "FAILED"


@pytest.mark.asyncio
async def test_a_parent_inside_the_timeout_is_left_alone(db, test_company_id, enqueued, settled):
    parent, child = await _parent_waiting_on(db, test_company_id, "RUNNING", waited_s=60)

    await _sweep(db)
    assert (await _row(db, parent.id)).status == "WAITING_ON_CHILDREN"
    assert (await _row(db, child.id)).status == "RUNNING"
    assert not [c for c in enqueued if c[1] == (str(parent.id),)]
