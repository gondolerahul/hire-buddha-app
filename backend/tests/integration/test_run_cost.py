"""A run's cost is the sum of its usage rows plus its children's totals (P4.1, AK-02).

Before: five paths bumped ``execution_runs.total_cost_usd``, the loop kept its
own tally and reconciled the two with ``max()`` in an order nothing enforced,
and the default planner, the judge and the alignment check wrote usage rows
with no run — spend the run, and its bill, never saw. Real Postgres, rolled back.
"""
from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from src.ai.governance.run_cost import refresh_run_cost, run_spend
from src.ai.models import ExecutionRun, HierarchicalEntity
from src.ai.orm.usage import UsageLog
from src.ai.usage_service import UsageService
from src.config.models import IntegrationRegistry

pytestmark = pytest.mark.needs_db

MODEL = "p41-model"


async def _company_with_prices(db):
    from src.auth.models import Company
    c = Company(name=f"p41-{uuid.uuid4().hex[:6]}", type="TENANT", status="active")
    db.add(c)
    await db.flush()
    db.add_all([
        IntegrationRegistry(company_id=c.id, provider_name="test", service_sku=f"{MODEL}-in",
                            component_type="input_token", internal_cost=Decimal("1.00"),
                            cost_unit="per_1M_tokens", status="active", service_category="LLM"),
        IntegrationRegistry(company_id=c.id, provider_name="test", service_sku=f"{MODEL}-out",
                            component_type="output_token", internal_cost=Decimal("4.00"),
                            cost_unit="per_1M_tokens", status="active", service_category="LLM"),
        IntegrationRegistry(company_id=c.id, provider_name="test", service_sku="p41_tool",
                            component_type="tool", internal_cost=Decimal("0.05"),
                            cost_unit="per_request", status="active", service_category="API"),
    ])
    ent = HierarchicalEntity(company_id=c.id, type="AGENT", status="ACTIVE", name="spender")
    db.add(ent)
    await db.flush()
    return c.id, ent.id


async def _run(db, company, entity, **kw):
    kw.setdefault("total_cost_usd", Decimal("0"))
    run = ExecutionRun(entity_id=entity, company_id=company, status="RUNNING", input_data={}, **kw)
    db.add(run)
    await db.flush()
    return run


@pytest.mark.asyncio
async def test_a_runs_spend_is_its_rows_and_tokens_count_only_llm_rows(db):
    company, entity = await _company_with_prices(db)
    run = await _run(db, company, entity)
    usage = UsageService(db)
    await usage.log_usage(company, f"{MODEL}-in", 1_000_000, execution_id=run.id, attribution="planner")
    await usage.log_usage(company, f"{MODEL}-out", 250_000, execution_id=run.id, attribution="critic_post")
    await usage.log_usage(company, "p41_tool", 1, execution_id=run.id, attribution="tool")

    spend = await run_spend(db, run.id)
    assert spend.cost_usd == Decimal("2.05")         # 1.00 + 1.00 + 0.05
    assert spend.tokens == 1_250_000                  # the tool's quantity is not tokens


@pytest.mark.asyncio
async def test_children_count_and_retries_do_not(db):
    company, entity = await _company_with_prices(db)
    parent = await _run(db, company, entity)
    await UsageService(db).log_usage(company, "p41_tool", 1, execution_id=parent.id)
    await _run(db, company, entity, parent_run_id=parent.id,
               total_cost_usd=Decimal("1.50"), total_tokens=300)
    await _run(db, company, entity, retry_of_run_id=parent.id,
               total_cost_usd=Decimal("7.00"), total_tokens=999)

    spend = await run_spend(db, parent.id)
    assert spend.cost_usd == Decimal("1.55") and spend.tokens == 300


@pytest.mark.asyncio
async def test_refresh_writes_the_spend_onto_the_run(db):
    company, entity = await _company_with_prices(db)
    run = await _run(db, company, entity)
    await UsageService(db).log_usage(company, "p41_tool", 2, execution_id=run.id)
    spend = await refresh_run_cost(db, run.id)
    await db.refresh(run)
    assert spend.cost_usd == Decimal("0.10") == Decimal(str(run.total_cost_usd))


@pytest.mark.asyncio
async def test_the_loops_budget_is_set_from_the_runs_rows(db):
    """Critic, planner and step spend all reach the budget, in any order."""
    from src.ai.core.agent_loop import AgentLoop
    from src.ai.core.budget import Budget

    company, entity = await _company_with_prices(db)
    run = await _run(db, company, entity)
    usage = UsageService(db)
    await usage.log_usage(company, f"{MODEL}-out", 500_000, execution_id=run.id, attribution="critic_post")
    loop = AgentLoop(db=db, redis=None)
    loop._run_id = run.id
    state = SimpleNamespace(budget=Budget(usd_used=Decimal("9.99")))   # a stale tally is replaced
    await loop._refresh_spend(state)
    assert state.budget.usd_used == Decimal("2.00") and state.budget.tokens_used == 500_000
    await usage.log_usage(company, "p41_tool", 1, execution_id=run.id, attribution="tool")
    await loop._refresh_spend(state)
    assert state.budget.usd_used == Decimal("2.05")


@pytest.mark.asyncio
async def test_planning_and_alignment_rows_belong_to_the_run(db, monkeypatch):
    """The v2 planner, its judge and the alignment check wrote rows with no run."""
    from src.ai.planning.goal_alignment import GoalAlignmentVerifier
    from src.ai.planning.plan_generator import PlanContext, PlanGenerator
    from src.ai.planning.plan_judge import PlanJudge

    company, entity = await _company_with_prices(db)
    run = await _run(db, company, entity)
    resp = SimpleNamespace(model_name=MODEL, prompt_tokens=1000, completion_tokens=100,
                           output='{"aligned": true, "confidence": 0.9, "issues": []}')

    gen = PlanGenerator(llm_router=None, db=db)
    await gen._log_attributed_usage(PlanContext(entity=None, company_id=company, run_id=run.id),
                                    resp, "planner")
    await PlanJudge(None, db=db)._log_attributed_usage(company, resp, "planner", run.id)

    class _Router:
        def __init__(self, **_kw):
            pass

        async def call_llm(self, **_kw):
            return resp

    import src.ai.llm.router as router_mod
    monkeypatch.setattr(router_mod, "LLMRouter", _Router)
    await GoalAlignmentVerifier(db, company, run_id=run.id).verify_step_alignment(
        entity_goal="g", task_desc="t", step_output="some output", step_name="s")

    rows = (await db.execute(select(UsageLog).where(UsageLog.company_id == company))).scalars().all()
    assert len(rows) == 6 and all(r.run_id == run.id for r in rows)
    assert (await run_spend(db, run.id)).tokens == 3 * 1100
