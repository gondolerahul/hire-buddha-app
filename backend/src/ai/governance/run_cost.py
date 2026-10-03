"""governance/run_cost.py — a run's cost is the sum of its usage rows (P4.1, AK-02).

Every spender — a step's LLM call, a tool, the planner, a critic, a debate, a
CORTEX summary, an embedding — writes one attributed ``usage_logs`` row with
its ``run_id``. None of them touches ``execution_runs.total_cost_usd``.

A run's spend is its own rows plus the recorded totals of its structural
children (``parent_run_id``; a retry or refinement is not a child since
EP-03). Only the run's owner — the loop, or a voice call — writes that spend
onto the run row, with :func:`refresh_run_cost`, and the loop's budget is set
from it. Before, five paths bumped the column, the loop kept its own tally and
reconciled the two with ``max()`` in an order nothing enforced, and spend from
the default planner, the alignment check and every replan never reached the
run at all.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import func, select, update

__all__ = ["RunSpend", "run_spend", "refresh_run_cost"]


@dataclass(frozen=True)
class RunSpend:
    cost_usd: Decimal
    tokens: int


async def run_spend(db: Any, run_id: Optional[UUID]) -> RunSpend:
    """The run's own usage rows plus its children's recorded totals."""
    if run_id is None:
        return RunSpend(Decimal("0"), 0)
    from src.ai.orm.execution import ExecutionRun
    from src.ai.orm.usage import UsageLog
    from src.config.models import IntegrationRegistry, ServiceCategory

    own_cost, own_tokens = (await db.execute(
        select(
            func.coalesce(func.sum(UsageLog.calculated_cost), 0),
            func.coalesce(func.sum(UsageLog.raw_quantity).filter(
                IntegrationRegistry.service_category == ServiceCategory.LLM), 0),
        )
        .select_from(UsageLog)
        .outerjoin(IntegrationRegistry, IntegrationRegistry.id == UsageLog.sku_id)
        .where(UsageLog.run_id == run_id)
    )).one()
    child_cost, child_tokens = (await db.execute(
        select(
            func.coalesce(func.sum(ExecutionRun.total_cost_usd), 0),
            func.coalesce(func.sum(ExecutionRun.total_tokens), 0),
        ).where(ExecutionRun.parent_run_id == run_id)
    )).one()
    return RunSpend(
        cost_usd=Decimal(str(own_cost)) + Decimal(str(child_cost)),
        tokens=int(own_tokens or 0) + int(child_tokens or 0),
    )


async def refresh_run_cost(db: Any, run_id: Optional[UUID], *, commit: bool = True) -> RunSpend:
    """Write the run's spend onto its row and return it. For the run's owner."""
    spend = await run_spend(db, run_id)
    if run_id is None:
        return spend
    from src.ai.orm.execution import ExecutionRun

    await db.execute(
        update(ExecutionRun).where(ExecutionRun.id == run_id).values(
            total_cost_usd=spend.cost_usd, total_tokens=spend.tokens,
        )
    )
    if commit:
        await db.commit()
    return spend
