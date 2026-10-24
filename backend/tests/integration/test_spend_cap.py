"""A company's monthly spend cap (GH-18, HD8).

Budget lived only on each entity, so a company with forty agents had forty
budgets and no single lever. ``companies.monthly_spend_cap_usd`` is what the
company may be billed in a calendar month — its billing lines, every
settlement (Phase 15 T3-4, T3-5). At the cap nothing new starts (a run's admission, a call or a
campaign's credit check) and a running run stops at its circuit breaker. No cap
set means none. Real Postgres, rolled back.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from src.ai.core.exceptions import CreditExhaustedError
from src.billing.billing_models import BillingLine
from src.billing.credit_service import CreditService, SpendCapReached

from tests.integration.test_run_credit_guard import _admit, _company, _run

pytestmark = pytest.mark.needs_db


async def _billed_this_month(db, company_id, amount: str):
    today = datetime.utcnow().date()
    db.add(BillingLine(company_id=company_id, period_day=date(today.year, today.month, 1), category="ai_models",
                       grouping_type="entity", grouping_id=uuid.uuid4(), currency="USD",
                       cost_usd=Decimal(amount), billed_usd=Decimal(amount), billed_ccy=Decimal(amount),
                       quantity=Decimal(1), rows=1))
    await db.flush()


async def _cap(db, company_id, cap):
    from src.auth.models import Company
    company = await db.get(Company, company_id)
    company.monthly_spend_cap_usd = None if cap is None else Decimal(cap)
    await db.flush()


@pytest.mark.asyncio
async def test_at_the_cap_a_run_is_not_admitted(db):
    company = await _company(db, "100")
    await _billed_this_month(db, company, "10.00")
    await _cap(db, company, "10.00")
    run, ent = await _run(db, company)
    _, refusal = await _admit(db, run, ent, "0.50")
    assert refusal and "monthly spend cap of $10.00 is reached" in refusal


@pytest.mark.asyncio
async def test_under_the_cap_or_with_none_it_runs(db):
    company = await _company(db, "100")
    await _billed_this_month(db, company, "9.00")
    await _cap(db, company, "10.00")
    run, ent = await _run(db, company)
    assert (await _admit(db, run, ent, "0.50"))[1] is None
    await _cap(db, company, None)
    await _billed_this_month(db, company, "500.00")
    assert await CreditService(db).spend_cap_refusal(company) is None


@pytest.mark.asyncio
async def test_a_running_run_stops_at_the_breaker_when_its_bill_reaches_the_cap(db):
    company = await _company(db, "100")
    await _billed_this_month(db, company, "9.00")
    await _cap(db, company, "10.00")
    run, ent = await _run(db, company)
    guard, refusal = await _admit(db, run, ent, "0.50")
    assert refusal is None
    await guard.check(Decimal("0.01"))                       # its bill so far is far under $1
    with pytest.raises(CreditExhaustedError, match="monthly spend cap"):
        await guard.check(Decimal("5"))                      # 9 + its bill so far passes 10


@pytest.mark.asyncio
async def test_a_call_or_a_campaign_is_refused_at_the_cap_too(db):
    company = await _company(db, "100")
    await _billed_this_month(db, company, "12.00")
    await _cap(db, company, "10.00")
    with pytest.raises(SpendCapReached):
        await CreditService(db).check_sufficient_for_execution(company, entity_type="AGENT")


# ── setting it ───────────────────────────────────────────────────────────────


def _app(db, user):
    from src.auth.company_router import router
    from src.auth.dependencies import get_current_user
    from src.common.database import get_db

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")

    async def _user():
        return user

    async def _db():
        yield db

    app.dependency_overrides[get_current_user] = _user
    app.dependency_overrides[get_db] = _db
    return app


async def _patch(app, company_id, body):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        return await c.patch(f"/api/v1/companies/{company_id}", json=body)


@pytest.mark.asyncio
async def test_a_tenant_admin_sets_and_clears_their_cap(db):
    from src.auth.roles import Role

    company = await _company(db, "1")
    admin = SimpleNamespace(id=uuid.uuid4(), role=Role.TENANT_ADMIN, company_id=company)
    res = await _patch(_app(db, admin), company, {"monthly_spend_cap_usd": 250})
    assert res.status_code == 200, res.text
    assert res.json()["monthly_spend_cap_usd"] == 250
    assert (await _patch(_app(db, admin), company, {"monthly_spend_cap_usd": 0})).status_code == 422
    res = await _patch(_app(db, admin), company, {"monthly_spend_cap_usd": None})
    assert res.status_code == 200 and res.json()["monthly_spend_cap_usd"] is None

    user = SimpleNamespace(id=uuid.uuid4(), role=Role.TENANT_USER, company_id=company)
    assert (await _patch(_app(db, user), company, {"monthly_spend_cap_usd": 1})).status_code == 403
