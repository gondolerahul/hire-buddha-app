"""Phase 15 T0-6: the partner dashboard has its own data, counts runs once, and scores health one way.

* The partner admin dashboard called the app-admin-only ``partner-performance``
  report, got 403, and showed nothing (P-27): ``GET /partner/analytics/revenue``
  is the partner's own, in billed amounts.
* ``/partner/analytics/summary`` summed every run's cost, child runs included,
  though a child's cost is already in its parent's (P-25); and its wallet total
  was the top-up bucket alone.
* ``/partner/tenants`` and ``/reports/analytics/tenant-health`` scored the same
  tenant two ways (C-13): both now use ``tenant_health.score``.

Real Postgres (rolled back); single tenancy, so a tenant's runs are on the same session.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

import src.main  # noqa: F401  (every model mapped)
from src.ai import reports_router
from src.auth import partner_router
from src.auth.dependencies import get_current_user
from src.auth.models import Company
from src.auth.tenant_health import TenantSignals, score
from src.billing.billing_models import BillingEvent
from src.common.database import get_db

pytestmark = pytest.mark.needs_db


def test_one_score():
    healthy = score(TenantSignals(runs_7d=10, runs_30d=20, completed_30d=20, agents=5, credit_usd=10))
    assert healthy == {"health_score": 100.0, "health_level": "green", "at_risk": False, "health_reasons": []}
    idle = score(TenantSignals(credit_usd=1))
    assert idle["health_level"] == "red" and idle["at_risk"] is True
    assert "no runs in the last 7 days" in idle["health_reasons"] and "credit is low" in idle["health_reasons"]
    failing = score(TenantSignals(runs_7d=10, runs_30d=10, completed_30d=6, failed_30d=4, agents=5, credit_usd=50))
    assert failing["at_risk"] is True and "4 of 10 runs failed in the last 30 days" in failing["health_reasons"]


def _client(db, role: str, company_id) -> httpx.AsyncClient:
    app = FastAPI()
    app.include_router(partner_router.router)
    app.include_router(reports_router.router)
    user = SimpleNamespace(id=uuid.uuid4(), role=role, company_id=company_id)

    async def _user():
        return user

    async def _db():
        yield db

    app.dependency_overrides[get_current_user] = _user
    app.dependency_overrides[get_db] = _db
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


async def _company(db, kind: str, parent=None, status="active") -> Company:
    c = Company(name=f"t06-{kind.lower()}-{uuid.uuid4().hex[:6]}", type=kind, status=status, parent_id=parent,
                billing_currency="USD")
    db.add(c)
    await db.flush()
    return c


@pytest.fixture
async def portfolio(db):
    from src.ai.orm import ExecutionRun, HierarchicalEntity

    partner = await _company(db, "PARTNER")
    busy = await _company(db, "TENANT", partner.id)
    quiet = await _company(db, "TENANT", partner.id, status="suspended")
    elsewhere = await _company(db, "TENANT", (await _company(db, "PARTNER")).id)

    agent = HierarchicalEntity(company_id=busy.id, type="AGENT", status="ACTIVE", name="t06-agent")
    db.add(agent)
    await db.flush()
    parent = ExecutionRun(entity_id=agent.id, company_id=busy.id, status="COMPLETED", input_data={},
                          total_cost_usd=Decimal("1.00"))
    db.add(parent)
    await db.flush()
    db.add_all([
        ExecutionRun(entity_id=agent.id, company_id=busy.id, status="COMPLETED", input_data={},
                     parent_run_id=parent.id, depth=1, total_cost_usd=Decimal("0.40")),   # inside the parent's 1.00
        ExecutionRun(entity_id=agent.id, company_id=busy.id, status="FAILED", input_data={},
                     total_cost_usd=Decimal("0.50")),
    ])
    # Credit of every kind (Phase 15 M15.2: lots): 1 + 2 + 3 + 4.
    from tests.harness.wallet import fund
    for kind, usd in (("daily", "1"), ("topup", "2"), ("subscription", "3"), ("subscription_bonus", "4")):
        await fund(db, busy.id, usd, kind=kind)
    today = datetime.utcnow().date()
    this_month = date(today.year, today.month, 1)
    last_month = date(today.year - (today.month == 1), (today.month - 2) % 12 + 1, 1)
    for company, month, billed in [(busy, this_month, "12.50"), (busy, last_month, "7.25"),
                                   (quiet, last_month, "3.00"), (elsewhere, this_month, "99.00")]:
        db.add(BillingEvent(company_id=company.id, period_month=month, grouping_type="process",
                            grouping_value="x", base_cost=Decimal("1"), total_billing=Decimal(billed)))
    await db.flush()
    return SimpleNamespace(partner=partner, busy=busy, quiet=quiet, elsewhere=elsewhere)


@pytest.mark.asyncio
async def test_the_partner_sees_what_its_own_tenants_were_billed(db, portfolio):
    async with _client(db, "partner_admin", portfolio.partner.id) as client:
        response = await client.get("/partner/analytics/revenue", params={"months": 3})
        forbidden = await client.get("/api/v1/reports/analytics/partner-performance")
    assert forbidden.status_code == 403            # still staff-only; the dashboard no longer calls it
    assert response.status_code == 200
    body = response.json()
    assert body["totals"] == {"tenants": 2, "active_tenants": 1, "suspended_tenants": 1,
                              "billed_this_month": 12.5, "billed_period": 22.75}
    assert [m["billed"] for m in body["monthly"]][-2:] == [10.25, 12.5]
    assert [(t["company_id"], t["billed_period"]) for t in body["tenants"]] == [
        (str(portfolio.busy.id), 19.75), (str(portfolio.quiet.id), 3.0)]
    assert not any("cost" in key for key in body["totals"]) and "base_cost" not in str(body)


@pytest.mark.asyncio
async def test_a_child_run_is_not_counted_twice_and_every_bucket_is_credit(db, portfolio):
    async with _client(db, "partner_admin", portfolio.partner.id) as client:
        summary = (await client.get("/partner/analytics/summary")).json()
    assert summary["total_executions"] == 2                    # two top-level runs
    assert summary["total_cost_usd"] == 1.5                     # 1.00 + 0.50, not + 0.40 again
    assert summary["total_wallet_balance"] == 10.0              # 1 + 2 + 3 + 4


@pytest.mark.asyncio
async def test_both_screens_give_a_tenant_the_same_health(db, portfolio):
    async with _client(db, "partner_admin", portfolio.partner.id) as client:
        listed = (await client.get("/partner/tenants")).json()["tenants"]
        report = (await client.get("/api/v1/reports/analytics/tenant-health")).json()["tenants"]
    by_list = {t["id"]: (t["health_score"], t["health_level"]) for t in listed}
    by_report = {t["company_id"]: (t["health_score"], t["health_level"]) for t in report}
    assert by_list == by_report and set(by_list) == {str(portfolio.busy.id), str(portfolio.quiet.id)}

    busy = next(t for t in listed if t["id"] == str(portfolio.busy.id))
    # 2 runs this week (6) + 1 of 2 completed (15) + USD 10 of credit (25) + 1 agent (3)
    assert (busy["health_score"], busy["entity_count"], busy["recent_executions_7d"]) == (49.0, 1, 2)
    assert busy["wallet_balance"] == 10.0
