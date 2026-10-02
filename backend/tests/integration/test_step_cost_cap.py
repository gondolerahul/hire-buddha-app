"""``governance.max_cost_usd`` stops a run between steps, inside a fragment too (P5.5, R2 §10).

``StepEngine._enforce_cost_cap`` read ``execution_runs.total_cost_usd``.
Since P4.1 only the loop writes that column, between iterations, so a
multi-step fragment or a DAG level could spend past the cap before the guard
saw any of it. The guard now reads the run's spend: its usage rows plus its
children. Real Postgres, rolled back.
"""
from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from src.ai.core.exceptions import BudgetExhaustedError
from src.ai.core.step_engine import StepEngine
from src.ai.models import ExecutionRun, HierarchicalEntity
from src.ai.orm.usage import UsageLog

pytestmark = pytest.mark.needs_db


async def _run_that_spent(db, amount: str):
    from src.auth.models import Company
    c = Company(name=f"p55-{uuid.uuid4().hex[:6]}", type="TENANT", status="active")
    db.add(c)
    await db.flush()
    ent = HierarchicalEntity(company_id=c.id, type="ACTION", status="ACTIVE", name="capped")
    db.add(ent)
    await db.flush()
    run = ExecutionRun(entity_id=ent.id, company_id=c.id, status="RUNNING", input_data={},
                       total_cost_usd=Decimal("0"))           # the column has not moved yet
    db.add(run)
    await db.flush()
    db.add(UsageLog(company_id=c.id, run_id=run.id, raw_quantity=Decimal("1"),
                    calculated_cost=Decimal(amount), attribution="llm"))
    await db.flush()
    return c.id, run


@pytest.mark.asyncio
async def test_spend_in_rows_the_column_has_not_seen_stops_the_next_step(db):
    company, run = await _run_that_spent(db, "0.06")
    with pytest.raises(BudgetExhaustedError):
        await StepEngine(db, None, company)._enforce_cost_cap(run, {"max_cost_usd": 0.05})


@pytest.mark.asyncio
async def test_under_the_cap_the_step_runs(db):
    company, run = await _run_that_spent(db, "0.04")
    await StepEngine(db, None, company)._enforce_cost_cap(run, {"max_cost_usd": 0.05})
