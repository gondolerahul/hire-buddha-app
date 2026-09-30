"""Every tool call is priced once, by one table, with a line item (BC-07…BC-11, BC-29).

Before: two hand-copied price tables in step_executor (the resolver built to
replace them had no callers); a tenant without its own registry row paid $0
for tools (no platform fallback) and ``cost_unit`` was ignored; any CUSTOM_API
row priced every tool; a fixed-cost charge had no usage_logs row; the image
tool billed the wallet a second time itself; and a step's LLM spend was
tagged ``tool``. Real Postgres, rolled back per test.
"""
from __future__ import annotations

import inspect
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

from src.ai.models import ExecutionRun, HierarchicalEntity, LLMInteractionLog
from src.ai.orm.usage import UsageLog
from src.ai.step_executor import StepExecutorService
from src.ai.usage_service import UsageService
from src.billing.billing_models import BillingEvent
from src.config.models import IntegrationRegistry

pytestmark = pytest.mark.needs_db


async def _tenant_run(db):
    from src.auth.models import Company
    c = Company(name=f"meter-{uuid.uuid4().hex[:6]}", type="TENANT", status="active")
    db.add(c)
    await db.flush()
    ent = HierarchicalEntity(company_id=c.id, type="AGENT", status="ACTIVE", name="meter")
    db.add(ent)
    await db.flush()
    run = ExecutionRun(entity_id=ent.id, company_id=c.id, status="RUNNING", input_data={},
                       total_cost_usd=Decimal("0"))
    db.add(run)
    await db.flush()
    return c.id, run


async def _app_company(db):
    from src.auth.models import Company
    app = (await db.execute(select(Company.id).where(Company.type == "APP").limit(1))).scalar()
    if app is None:
        c = Company(name="platform", type="APP", status="active")
        db.add(c)
        await db.flush()
        app = c.id
    return app


def _sku(company_id, sku, cost, unit="per_request", category="API"):
    return IntegrationRegistry(company_id=company_id, provider_name="test", service_sku=sku,
                               component_type="tool", internal_cost=Decimal(cost), cost_unit=unit,
                               status="active", service_category=category)


def _executor(db, company_id):
    return StepExecutorService(db, None, company_id, UsageService(db))


async def _rows(db, run_id):
    return (await db.execute(select(UsageLog).where(UsageLog.run_id == run_id))).scalars().all()


async def _cost(db, run_id) -> Decimal:
    return Decimal(str((await db.execute(select(ExecutionRun.total_cost_usd).where(
        ExecutionRun.id == run_id))).scalar()))


@pytest.mark.asyncio
async def test_a_fixed_cost_tool_is_charged_once_with_a_line_item(db):
    company, run = await _tenant_run(db)
    amount = await _executor(db, company)._charge_tool(run, "image_generation", 120)
    assert amount == Decimal("0.04")
    assert await _cost(db, run.id) == Decimal("0.04")
    rows = await _rows(db, run.id)
    assert [(r.sku_id, Decimal(str(r.calculated_cost)), r.attribution, r.log_metadata["tool"])
            for r in rows] == [(None, Decimal("0.04"), "tool", "image_generation")]


@pytest.mark.asyncio
async def test_a_tenant_without_its_own_row_pays_the_platform_price(db):
    company, run = await _tenant_run(db)
    tool = f"metered_tool_{uuid.uuid4().hex[:6]}"
    db.add(_sku(await _app_company(db), tool, "0.02"))
    await db.flush()
    amount = await _executor(db, company)._charge_tool(run, tool)
    assert amount == Decimal("0.02")
    assert await _cost(db, run.id) == Decimal("0.02")
    assert len(await _rows(db, run.id)) == 1


@pytest.mark.asyncio
async def test_a_per_thousand_price_is_charged_per_call(db):
    company, run = await _tenant_run(db)
    tool = f"metered_tool_{uuid.uuid4().hex[:6]}"
    db.add(_sku(company, tool, "5.00", unit="per_1000_requests"))
    await db.flush()
    assert await _executor(db, company)._charge_tool(run, tool) == Decimal("0.005")


@pytest.mark.asyncio
async def test_a_custom_api_row_does_not_price_other_tools(db):
    company, run = await _tenant_run(db)
    db.add(_sku(company, f"my_crm_{uuid.uuid4().hex[:4]}", "0.75", category="CUSTOM_API"))
    await db.flush()
    assert await _executor(db, company)._charge_tool(run, "calculator") == Decimal("0")
    assert await _cost(db, run.id) == Decimal("0")


@pytest.mark.asyncio
async def test_a_steps_llm_spend_is_attributed_to_the_step(db):
    company, run = await _tenant_run(db)
    model = f"meter-model-{uuid.uuid4().hex[:6]}"
    db.add_all([_sku(company, f"{model}-in", "1.00", unit="per_million_tokens", category="LLM"),
                _sku(company, f"{model}-out", "2.00", unit="per_million_tokens", category="LLM")])
    log = LLMInteractionLog(run_id=run.id, model_provider="test", model_name=model,
                            input_prompt="p", output_response="o", prompt_tokens=1000,
                            completion_tokens=500, latency_ms=1)
    db.add(log)
    await db.flush()
    await _executor(db, company)._log_usage(run, model, 1000, 500, log)
    rows = await _rows(db, run.id)
    assert sorted(r.attribution for r in rows) == ["actor_step", "actor_step"]
    assert await _cost(db, run.id) == Decimal("0.002")   # 1000 x $1/M + 500 x $2/M


@pytest.mark.asyncio
async def test_the_image_tool_no_longer_bills_the_wallet_itself(db):
    """BC-08: the tool used to record a billing event and consume credits on
    its own, on top of the executor's charge and the run's settlement."""
    from src.ai.tools.media import image_generation
    source = inspect.getsource(image_generation)
    for name in ("record_billing_event", "CreditService", "BillingService"):
        assert name not in source.split("# No billing here")[0], name
    company, run = await _tenant_run(db)
    await _executor(db, company)._charge_tool(run, "image_generation")
    events = (await db.execute(select(BillingEvent).where(BillingEvent.company_id == company))).scalars().all()
    assert events == []


@pytest.mark.asyncio
async def test_a_fixed_cost_charge_appears_in_the_usage_breakdown(db):
    from src.ai.reports_service import ReportsService
    company, run = await _tenant_run(db)
    await _executor(db, company)._charge_tool(run, "image_generation")
    report = await ReportsService(db).get_usage_breakdown(company)
    by_service = {c["service"]: c for c in report["channels"]}
    assert by_service["image_generation"]["category"] == "TOOL"
    assert by_service["image_generation"]["total_cost_usd"] == 0.04
