"""Base-cost overrides change what is charged, once, and minutes round one way (BC-12, BC-13).

Before: ``base_cost_telephony`` replaced a call's *whole* cost (dropping the
speech model's audio) and only in the billing event — the wallet was charged
without it; ``base_cost_llm`` was read and ignored; ``base_cost_image_gen``
applied only to the image tool's own (double) billing event; an override
once set could not be cleared; and the usage log rounded telephony minutes up
while the billing event recorded fractional minutes. Real Postgres, rolled back.
"""
from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select

from src.ai.governance.tool_cost_resolver import ToolCostResolver
from src.auth.dependencies import get_current_user
from src.billing import billing_router
from src.billing.billing_models import BillingConfig, BillingEvent
from src.billing.billing_service import BillingService
from src.common.database import get_db
from src.voice.usage_logger import billed_minutes

pytestmark = pytest.mark.needs_db


async def _company(db, **overrides):
    from src.auth.models import Company
    c = Company(name=f"override-{uuid.uuid4().hex[:6]}", type="TENANT", status="active")
    db.add(c)
    await db.flush()
    if overrides:
        db.add(BillingConfig(company_id=c.id, multiplier_factor=Decimal("1"), platform_fee_pct=0,
                             sales_partner_fee_pct=0, discount_pct=0, default_daily_credits=0,
                             **{k: Decimal(v) for k, v in overrides.items()}))
        await db.flush()
    return c.id


def test_minutes_are_billed_per_started_minute():
    assert [billed_minutes(s) for s in (0, 1, 60, 61, 125)] == [0, 1, 1, 2, 3]


@pytest.mark.asyncio
async def test_the_telephony_override_replaces_only_the_carrier_part(db):
    company = await _company(db, base_cost_telephony="0.01")
    # A 3-minute call: $0.06 carrier + $0.20 speech model.
    base = await BillingService(db).voice_base_cost(
        company, total_cost=Decimal("0.26"), telephony_cost=Decimal("0.06"),
        telephony_minutes=Decimal("3"))
    assert base == Decimal("0.23")                  # 0.20 + 3 x 0.01, not 3 x 0.01


@pytest.mark.asyncio
async def test_without_an_override_the_logged_cost_stands(db):
    company = await _company(db)
    base = await BillingService(db).voice_base_cost(
        company, total_cost=Decimal("0.26"), telephony_cost=Decimal("0.06"),
        telephony_minutes=Decimal("3"))
    assert base == Decimal("0.26")


@pytest.mark.asyncio
async def test_the_billing_event_records_the_cost_it_is_given(db):
    """The override is applied before the charge, so the event must not re-apply it."""
    company = await _company(db, base_cost_telephony="0.01")
    event = await BillingService(db).record_billing_event(
        company_id=company, base_cost=Decimal("0.23"), grouping_type="agent",
        grouping_value="a", telephony_out_minutes=Decimal("3"), event_category="telephony")
    assert Decimal(str(event.base_cost)) == Decimal("0.23")
    assert Decimal(str(event.telephony_out_minutes)) == Decimal("3")


@pytest.mark.asyncio
async def test_the_image_override_prices_image_generation(db):
    company = await _company(db, base_cost_image_gen="0.07")
    amount, source, _ = await ToolCostResolver(db, company).resolve("image_generation")
    assert (amount, source) == (Decimal("0.07"), "config")


def _client(db, role="app_admin"):
    app = FastAPI()
    app.include_router(billing_router.router)

    async def _user():
        return SimpleNamespace(id=uuid.uuid4(), role=role, company_id=uuid.uuid4())

    async def _db():
        yield db

    app.dependency_overrides[get_current_user] = _user
    app.dependency_overrides[get_db] = _db
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


@pytest.mark.asyncio
async def test_an_override_can_be_cleared(db):
    company = await _company(db, base_cost_telephony="0.01", base_cost_image_gen="0.07")
    async with _client(db) as client:
        res = await client.put("/api/v1/billing/config", json={
            "company_id": str(company), "base_cost_telephony": None, "multiplier_factor": None})
    assert res.status_code == 200, res.text
    config = (await db.execute(select(BillingConfig).where(BillingConfig.company_id == company)
                               .execution_options(populate_existing=True))).scalar_one()
    assert config.base_cost_telephony is None                     # cleared
    assert Decimal(str(config.base_cost_image_gen)) == Decimal("0.07")   # untouched
    assert Decimal(str(config.multiplier_factor)) == Decimal("1")         # a formula field is never cleared


@pytest.mark.asyncio
async def test_the_retired_llm_override_is_refused(db):
    async with _client(db) as client:
        res = await client.put("/api/v1/billing/config", json={"base_cost_llm": 0.5})
    assert res.status_code == 422
