"""A step's spend is usage rows only; the run row is the loop's (P4.1, AK-02).

Phase 11 found parallel DAG steps clobbering each other's ORM writes to
``run.total_cost_usd`` (a ~$6 run settled at ~$0.88), and ``_bump_run_cost``
replaced them with an atomic increment. Since P4.1 no spender writes the run
row at all: each charge is an attributed ``usage_logs`` row with the run id,
and the loop writes the run's total as the sum of those rows
(``governance.run_cost``). Parallel steps only insert rows, so there is nothing
to clobber.
"""
from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from src.ai.step_executor import StepExecutorService


class _CaptureDB:
    """Records every statement passed to ``execute``."""

    def __init__(self) -> None:
        self.executed: list = []
        self.commits = 0
        self.add = MagicMock()

    async def execute(self, statement, *_a, **_kw):
        self.executed.append(statement)
        return SimpleNamespace(scalar_one_or_none=lambda: None)

    async def commit(self):
        self.commits += 1

    async def refresh(self, *_a, **_kw):
        pass


def _writes_the_run_row(db: _CaptureDB) -> bool:
    return any(getattr(getattr(st, "table", None), "name", None) == "execution_runs"
               for st in db.executed)


def test_the_bump_path_is_gone() -> None:
    assert not hasattr(StepExecutorService, "_bump_run_cost")


@pytest.mark.asyncio
async def test_a_steps_llm_call_writes_usage_rows_and_not_the_run() -> None:
    db = _CaptureDB()
    usage = SimpleNamespace(log_usage=AsyncMock(side_effect=[
        SimpleNamespace(calculated_cost=Decimal("0.10")),
        SimpleNamespace(calculated_cost=Decimal("0.40")),
    ]))
    svc = StepExecutorService(db=db, redis=None, company_id=uuid4(), usage_service=usage)
    run = SimpleNamespace(id=uuid4(), company_id=uuid4(), total_cost_usd=Decimal("0"), total_tokens=0)
    log = SimpleNamespace(cost_usd=None)

    await svc._log_usage(run, "gemini-2.5-flash", 1000, 200, log)

    assert [c.kwargs["execution_id"] for c in usage.log_usage.await_args_list] == [run.id, run.id]
    assert log.cost_usd == Decimal("0.50")           # the interaction row keeps its cost
    assert run.total_cost_usd == Decimal("0") and not _writes_the_run_row(db)


@pytest.mark.asyncio
async def test_a_tool_charge_writes_its_row_and_not_the_run(monkeypatch) -> None:
    from src.ai.governance import tool_cost_resolver as tcr

    db = _CaptureDB()
    monkeypatch.setattr(tcr.ToolCostResolver, "charge", AsyncMock(
        return_value=tcr.ToolChargeResult(amount=Decimal("0.03"), source="registry", sku_id=None)))
    svc = StepExecutorService(db=db, redis=None, company_id=uuid4(), usage_service=None)
    run = SimpleNamespace(id=uuid4(), company_id=uuid4(), total_cost_usd=Decimal("0"))

    assert await svc._charge_tool(run, "web_search", 12) == Decimal("0.03")
    assert db.commits == 1 and not _writes_the_run_row(db)
