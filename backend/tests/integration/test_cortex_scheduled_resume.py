"""A scheduled CORTEX resume queues its run, and keeps the schedule if it cannot (MC-24).

``cortex_resume_scheduled`` wrapped the worker's pool in a second ``ArqRedis``,
which raised; the error was logged per tree and the commit after the loop kept
a ``PENDING`` run nobody would pick up and a tree with its schedule cleared —
never woken again. Now the run is committed, then queued on the worker's own
pool, and only then is the schedule cleared. Real Postgres, rolled back.
"""
from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

import pytest

pytestmark = pytest.mark.needs_db


class _Pool:
    """The worker's ArqRedis pool: records jobs, or refuses them."""

    def __init__(self, events: list[str], fail: bool = False, on_enqueue=None):
        self.events, self.fail, self.on_enqueue = events, fail, on_enqueue
        self.jobs: list[tuple[str, tuple]] = []

    async def set(self, *_a, **_k):  # the trace carrier, when a span is open
        return True

    async def enqueue_job(self, function, *args, **_kwargs):
        self.events.append("enqueue")
        if self.fail:
            raise ConnectionError("redis went away")
        if self.on_enqueue is not None:
            await self.on_enqueue(args[0])
        self.jobs.append((function, args))
        return object()


@pytest.fixture
def events(db, monkeypatch) -> list[str]:
    """The job's sessions are the test session; its commits are recorded."""
    from src.ai.core import arq_jobs

    seen: list[str] = []
    real_commit = db.commit

    async def _commit():
        seen.append("commit")
        await real_commit()

    @asynccontextmanager
    async def _session():
        yield db

    monkeypatch.setattr(db, "commit", _commit)
    monkeypatch.setattr(arq_jobs, "AsyncSessionLocal", _session)
    return seen


async def _suspended_tree(db, company_id, *, due_in=timedelta(minutes=-5)):
    from src.ai.memory.cortex_models import CortexTree, CortexTreeStatus
    from src.ai.orm.entity import HierarchicalEntity

    entity = HierarchicalEntity(company_id=company_id, type="AGENT", name=f"mc24-{uuid.uuid4().hex[:6]}")
    db.add(entity)
    await db.flush()
    tree = CortexTree(
        company_id=company_id, entity_id=entity.id, task_description="weekly digest",
        status=CortexTreeStatus.SUSPENDED,
        next_resume_at=datetime.utcnow() + due_in,
    )
    db.add(tree)
    await db.flush()
    return tree


async def _runs_for(db, tree_id):
    from sqlalchemy import select

    from src.ai.orm.execution import ExecutionRun

    rows = (await db.execute(select(ExecutionRun).where(
        ExecutionRun.input_data["cortex_tree_id"].astext == str(tree_id)))).scalars().all()
    return list(rows)


@pytest.mark.asyncio
async def test_a_due_tree_gets_a_committed_run_then_a_job_then_loses_its_schedule(db, test_company_id, events):
    from src.ai.core.arq_jobs import cortex_resume_scheduled

    tree = await _suspended_tree(db, test_company_id)
    later = await _suspended_tree(db, test_company_id, due_in=timedelta(hours=1))
    pool = _Pool(events)

    result = await cortex_resume_scheduled({"redis": pool})

    [run] = await _runs_for(db, tree.id)
    assert run.status == "PENDING" and run.entity_id == tree.entity_id
    assert ("run_execution_recursive", (str(run.id),)) in pool.jobs
    # The run is committed before its job exists; the schedule goes after.
    first = events.index("enqueue")
    assert "commit" in events[:first] and "commit" in events[first + 1:]
    await db.refresh(tree)
    assert tree.next_resume_at is None
    assert result["resumed"] >= 1
    # Not due yet: no run, schedule kept.
    assert await _runs_for(db, later.id) == []
    await db.refresh(later)
    assert later.next_resume_at is not None


@pytest.mark.asyncio
async def test_a_job_that_cannot_be_queued_fails_its_run_and_keeps_the_schedule(db, test_company_id, events):
    from src.ai.core.arq_jobs import cortex_resume_scheduled

    tree = await _suspended_tree(db, test_company_id)
    scheduled_for = tree.next_resume_at

    result = await cortex_resume_scheduled({"redis": _Pool(events, fail=True)})

    [run] = await _runs_for(db, tree.id)
    assert run.status == "FAILED"
    assert "could not be queued" in run.error_message and run.completed_at is not None
    await db.refresh(tree)
    assert tree.next_resume_at == scheduled_for  # the next tick tries again
    assert result["failed"] >= 1


@pytest.mark.asyncio
async def test_a_tree_rescheduled_while_its_run_is_queued_keeps_the_new_time(db, test_company_id, events):
    from sqlalchemy import update

    from src.ai.core.arq_jobs import cortex_resume_scheduled
    from src.ai.memory.cortex_models import CortexTree

    tree = await _suspended_tree(db, test_company_id)
    tomorrow = datetime.utcnow().replace(microsecond=0) + timedelta(days=1)

    async def _reschedule(_run_id):
        await db.execute(update(CortexTree).where(CortexTree.id == tree.id).values(next_resume_at=tomorrow))

    await cortex_resume_scheduled({"redis": _Pool(events, on_enqueue=_reschedule)})

    await db.refresh(tree)
    assert tree.next_resume_at == tomorrow


@pytest.mark.asyncio
async def test_without_a_pool_nothing_is_woken(db, test_company_id, events):
    from src.ai.core.arq_jobs import cortex_resume_scheduled

    tree = await _suspended_tree(db, test_company_id)

    assert await cortex_resume_scheduled({}) == {"resumed": 0, "failed": 0}
    assert await _runs_for(db, tree.id) == []
