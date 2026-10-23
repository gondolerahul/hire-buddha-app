"""A company's own price is its registry row (BC-12, BC-13; Phase 15 T3-2, T1-4).

Before Phase 15 a company's carrier rate and image price were *overrides* on
``billing_config`` (``base_cost_telephony``, ``base_cost_image_gen``), applied
at three places in three ways (BC-13 fixed the worst of it), and calls were
billed per started minute (BC-12). Now the override is the company's own
registry row — migrated by ``control_0012`` — priced per second like every
other telephony SKU, and the overrides are refused by the API. Real Postgres,
rolled back.
"""
from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI

from src.ai.governance.tool_cost_resolver import ToolCostResolver
from src.auth.dependencies import get_current_user
from src.billing import billing_router
from src.billing.billing_service import BillingService
from src.common.database import get_db
from src.config.models import IntegrationRegistry

pytestmark = pytest.mark.needs_db


async def _company(db) -> uuid.UUID:
    from src.auth.models import Company
    c = Company(name=f"override-{uuid.uuid4().hex[:6]}", type="TENANT", status="active")
    db.add(c)
    await db.flush()
    return c.id


async def _row(db, company, sku, cost, unit, category):
    db.add(IntegrationRegistry(company_id=company, provider_name="override", service_sku=sku,
                               service_category=category, component_type=category.lower(),
                               internal_cost=Decimal(cost), cost_unit_code=unit, status="active"))
    await db.flush()


@pytest.mark.asyncio
async def test_a_companys_carrier_rate_is_its_row_billed_per_second(db):
    from src.voice.usage_logger import VoiceUsageLogger

    company = await _company(db)
    await _row(db, company, "in-out", "0.01", "PER_MINUTE", "COMMUNICATION")      # what base_cost_telephony became
    meter = VoiceUsageLogger(db)
    meter.log_live_model_usage = AsyncMock(return_value=Decimal("0.20"))           # the speech model's audio
    usage = await meter.log_voice_session_usage(
        session_id=uuid.uuid4(), company_id=company, provider="twilio", duration_seconds=150)
    # 150 s at $0.01/min = $0.025, plus the model's $0.20 — not 3 started minutes.
    assert (usage.telephony_cost, usage.total_cost, usage.telephony_seconds) == (
        Decimal("0.025"), Decimal("0.225"), Decimal("150"))


@pytest.mark.asyncio
async def test_the_billing_event_records_the_cost_and_seconds_it_is_given(db):
    company = await _company(db)
    event = await BillingService(db).record_billing_event(
        company_id=company, base_cost=Decimal("0.225"), grouping_type="agent",
        grouping_value="a", telephony_out_seconds=Decimal("150"), event_category="telephony")
    assert Decimal(str(event.base_cost)) == Decimal("0.225")
    assert Decimal(str(event.telephony_out_seconds)) == Decimal("150")


@pytest.mark.asyncio
async def test_a_companys_image_price_is_its_row(db):
    company = await _company(db)
    await _row(db, company, "image_generation", "0.07", "PER_IMAGE", "IMAGE_GENERATION")
    amount, source, _ = await ToolCostResolver(db, company).resolve("image_generation")
    assert (amount, source) == (Decimal("0.07"), "registry")


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
@pytest.mark.parametrize("body", [{"base_cost_telephony": 0.01}, {"base_cost_image_gen": 0.07},
                                  {"base_cost_llm": 0.5}])
async def test_the_overrides_are_refused(db, body):
    async with _client(db) as client:
        res = await client.put("/api/v1/billing/config", json=body)
    assert res.status_code == 422
