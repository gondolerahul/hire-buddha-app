"""A run's tool-call limits hold across its steps (P3.3, TL-11).

Before: the counts lived in ``context['tool_call_counts']``, reset at the start
of every step, and the limit itself was never set. Now a run's calls are its
``tool_interaction_logs`` rows. Real Postgres, rolled back per test.
"""
from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

from src.ai.models import ExecutionRun, HierarchicalEntity, ToolInteractionLog
from src.ai.schemas import PlanStep, StepType
from src.ai.step_executor import StepExecutorService
from src.ai.tools.base import Tool, ToolRegistry
from src.ai.usage_service import UsageService

pytestmark = pytest.mark.needs_db


class _Counter(Tool):
    name = "p33_counter"
    description = "counts its calls"

    def __init__(self):
        self.log: list[str] = []  # a registered tool is frozen (TX-02)

    @property
    def calls(self) -> int:
        return len(self.log)

    async def run(self, input_data):
        self.log.append(input_data)
        return f"call {self.calls}"


@pytest.fixture
def counter():
    tool = _Counter()
    ToolRegistry.register(tool)
    yield tool
    ToolRegistry._tools.pop(tool.name, None)


async def _run_with_limit(db, limit: int):
    from src.auth.models import Company
    c = Company(name=f"limits-{uuid.uuid4().hex[:6]}", type="TENANT", status="active")
    db.add(c)
    await db.flush()
    ent = HierarchicalEntity(
        company_id=c.id, type="ACTION", status="ACTIVE", name="limited",
        capabilities={"tools": [{"tool_id": "p33_counter", "rate_limit_per_run": limit}]},
    )
    db.add(ent)
    await db.flush()
    run = ExecutionRun(entity_id=ent.id, company_id=c.id, status="RUNNING", input_data={},
                       total_cost_usd=Decimal("0"))
    db.add(run)
    await db.flush()
    return c.id, ent, run


def _step(n: int) -> PlanStep:
    return PlanStep(step_id=f"s{n}", name=f"count {n}", type=StepType.TOOL_CALL,
                    target={"tool_id": "p33_counter", "prompt_template": "go"})


@pytest.mark.asyncio
async def test_a_per_run_limit_holds_across_steps(db, counter):
    company, entity, run = await _run_with_limit(db, 2)
    svc = StepExecutorService(db, None, company, UsageService(db))
    results = [await svc._execute_tool_call(run, entity, _step(n), {}) for n in range(1, 4)]

    assert counter.calls == 2
    assert "error" not in results[0] and "error" not in results[1]
    assert "2 time(s) per run" in results[2]["error"]
    logs = (await db.execute(select(ToolInteractionLog).where(
        ToolInteractionLog.run_id == run.id).order_by(ToolInteractionLog.created_at))).scalars().all()
    assert [bool(log.log_metadata and log.log_metadata.get("refused")) for log in logs] == [False, False, True]


@pytest.mark.asyncio
async def test_another_run_starts_with_its_own_count(db, counter):
    company, entity, first = await _run_with_limit(db, 1)
    svc = StepExecutorService(db, None, company, UsageService(db))
    await svc._execute_tool_call(first, entity, _step(1), {})
    second = ExecutionRun(entity_id=entity.id, company_id=company, status="RUNNING", input_data={},
                          total_cost_usd=Decimal("0"))
    db.add(second)
    await db.flush()
    result = await svc._execute_tool_call(second, entity, _step(1), {})
    assert "error" not in result and counter.calls == 2
