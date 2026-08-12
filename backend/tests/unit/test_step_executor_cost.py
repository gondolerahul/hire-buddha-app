"""Phase 11 — StepExecutorService._bump_run_cost regression tests.

Guards the billing leak surfaced by the doc-factory-process canary: the
parallel DAG path runs each step in its own AsyncSession with its own copy of
the run row, so an in-place ``run.total_cost_usd += delta`` was flushed as an
*absolute* full-row write and concurrent steps clobbered each other — a ~$6 run
settled at ~$0.88.

``_bump_run_cost`` must instead emit an ATOMIC
``SET total_cost_usd = total_cost_usd + :delta`` UPDATE (concurrency-safe under
a row lock) and refresh the in-memory object so it mirrors the new value
without being marked dirty.
"""
from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

from src.ai.step_executor import StepExecutorService


class _CaptureDB:
    """Records the statements passed to ``execute`` and ``refresh`` calls."""

    def __init__(self) -> None:
        self.executed: list = []
        self.refreshed: list = []
        self.commits: int = 0

    async def execute(self, statement, *_a, **_kw):
        self.executed.append(statement)
        return SimpleNamespace(scalar_one_or_none=lambda: None)

    async def commit(self):
        self.commits += 1

    async def refresh(self, obj, attribute_names=None):
        self.refreshed.append((obj, attribute_names))


def _svc(db) -> StepExecutorService:
    return StepExecutorService(
        db=db, redis=None, company_id=uuid4(), usage_service=None,
    )


@pytest.mark.asyncio
async def test_bump_run_cost_emits_atomic_increment() -> None:
    db = _CaptureDB()
    svc = _svc(db)
    run = SimpleNamespace(id=uuid4(), total_cost_usd=Decimal("1.00"), total_tokens=100)

    await svc._bump_run_cost(run, Decimal("0.50"), 200)

    assert len(db.executed) == 1
    sql = str(db.executed[0].compile(compile_kwargs={"literal_binds": True})).lower()
    # An atomic read-modify-write references the column on BOTH sides; an
    # absolute clobbering write (the bug) would only have it on the left.
    flat = sql.replace(" ", "")
    assert "update execution_runs" in sql
    assert "total_cost_usd=(coalesce(execution_runs.total_cost_usd,0)+0.50)" in flat
    assert "total_tokens=(coalesce(execution_runs.total_tokens,0)+200)" in flat
    # In-memory mirror is refreshed (not left stale / dirty) for the two columns.
    assert db.refreshed == [(run, ["total_cost_usd", "total_tokens"])]
    # Committed immediately so the run-row lock doesn't serialise parallel steps.
    assert db.commits == 1


@pytest.mark.asyncio
async def test_bump_run_cost_is_noop_for_zero_delta() -> None:
    db = _CaptureDB()
    svc = _svc(db)
    run = SimpleNamespace(id=uuid4(), total_cost_usd=Decimal("0"), total_tokens=0)

    await svc._bump_run_cost(run, Decimal("0"), 0)

    assert db.executed == []
    assert db.refreshed == []
    assert db.commits == 0
