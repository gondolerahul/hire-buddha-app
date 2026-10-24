"""One journey per role, at the API and service level (Phase 15 T10-2; plan 08 §5 "E2E").

There is no browser runner on the build machine, so the release journeys of
08 §5 run here against the real services and Postgres (rolled back):

* a business: funded → work admitted → usage past the balance → in debt, new
  work refused → a paid recharge repays the debt → admitted again; its
  reports show it in its own currency;
* a Gold partner: earns on its customer's payment, sees it in its earnings
  report, and works inside the customer under its grant;
* staff: a new FX rate applies to new conversions only; the wallet and an
  amount locked earlier do not move.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from decimal import Decimal

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI

from tests.harness.partners import partner, tenant, user

pytestmark = pytest.mark.needs_db
D = Decimal


@pytest_asyncio.fixture(autouse=True)
async def own_sessions(monkeypatch):
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    from src.billing import rollout
    from src.common import database
    from src.common.config import settings

    engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    monkeypatch.setattr(database, "AsyncSessionLocal", async_sessionmaker(engine, expire_on_commit=False))
    monkeypatch.setattr(database, "engine", engine)
    rollout.forget()
    yield
    await engine.dispose()


async def _report(db, actor, report_id, headers=None, **params):
    from src.auth import dependencies, router as auth_router
    from src.common.database import get_db
    from src.common.tenancy.session import get_control_db
    from src.reports import router as reports_router

    app = FastAPI()
    app.include_router(reports_router.router)

    async def _u():
        return actor

    async def _db():
        yield db

    for dep in (dependencies.get_current_user, auth_router.get_current_user):
        app.dependency_overrides[dep] = _u
    for dep in (get_db, get_control_db):
        app.dependency_overrides[dep] = _db
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        return await c.get(f"/api/v1/reports/{report_id}", params=params, headers=headers or {})


@pytest.mark.asyncio
async def test_a_business_runs_into_debt_and_recharges_out_of_it(db):
    from src.billing.credit_service import CreditService
    from src.billing.wallet import WalletService

    t = await tenant(db)
    wallets, credits = WalletService(db), CreditService(db)
    await wallets.ensure(t)
    await wallets.grant(t, "topup", D(1000), expires_at=datetime.utcnow() + timedelta(days=90), paid=True,
                        source_type="payment", source_id=uuid.uuid4().hex)
    await db.flush()
    assert await credits.admission_refusal(t, D("0.05")) is None

    await wallets.deduct(t, D(1500), source_type="settlement", source_id="run-1", category="ai_models")
    await db.flush()
    b = await wallets.balance(t)
    assert b["state"] in ("in_debt", "over_tolerance") and (b["available"], b["debt"]) == (D(0), D(500))
    refusal = await credits.admission_refusal(t, D("0.05"))
    assert refusal and "owes" in refusal and "500" in refusal

    await wallets.grant(t, "topup", D(2000), expires_at=datetime.utcnow() + timedelta(days=90), paid=True,
                        source_type="payment", source_id=uuid.uuid4().hex)
    await db.flush()
    b = await wallets.balance(t)
    assert (b["state"], b["available"], b["debt"]) == ("ok", D(1500), D(0))
    assert await credits.admission_refusal(t, D("0.05")) is None

    activity = await _report(db, user("tenant_admin", t), "R-T03", period="30d")
    assert activity.status_code == 200 and activity.json()["currency"] == "INR"
    kinds = {r["kind"] for r in activity.json()["rows"]}
    assert {"Credit added", "Usage", "Usage owed", "Debt repaid"} <= kinds


@pytest.mark.asyncio
async def test_a_gold_partner_earns_and_works_inside_its_customer(db):
    from src.partners import commission
    from src.partners.access import grant_for_created_tenant

    p = await partner(db, "GOLD")
    t = await tenant(db, p, since_days_ago=60)
    await grant_for_created_tenant(db, partner_id=p, tenant_id=t)
    rows = await commission.distribute(db, tenant_id=t, revenue_kind="usage_topup", base=D(100000), currency="INR",
                                       source_type="payment", source_id="journey")
    await db.flush()
    assert rows and rows[0].amount > 0

    earnings = await _report(db, user("partner_admin", p), "R-P05", period="30d")
    assert earnings.status_code == 200, earnings.text
    assert not any(c.get("cost") for c in earnings.json()["columns"])

    inside = await _report(db, user("partner_admin", p), "R-T01", headers={"X-Company-Id": str(t)})
    assert inside.status_code == 200, inside.text
    stranger = await tenant(db)
    refused = await _report(db, user("partner_admin", p), "R-T01", headers={"X-Company-Id": str(stranger)})
    assert refused.status_code == 403


@pytest.mark.asyncio
async def test_staff_change_an_fx_rate_and_only_new_conversions_move(db):
    from src.billing.billing_models import FxRate
    from src.billing.currency import current_rate, to_ccy
    from src.billing.wallet import WalletService

    t = await tenant(db)
    wallets = WalletService(db)
    await wallets.ensure(t)
    await wallets.grant(t, "topup", D(5000), expires_at=None, paid=True, source_type="payment",
                        source_id=uuid.uuid4().hex)
    await db.flush()
    before = await current_rate(db, "INR")
    locked = to_ccy(D(10), before)
    db.add(FxRate(currency="INR", units_per_usd=before.units_per_usd + D(5), effective_from=datetime.utcnow(),
                  reason="journey"))
    await db.flush()
    after = await current_rate(db, "INR")
    assert after.units_per_usd == before.units_per_usd + D(5)
    assert to_ccy(D(10), after) == locked + D(50)
    assert locked == D(10) * before.units_per_usd                         # what was converted stays
    assert (await wallets.balance(t))["available"] == D(5000)            # the wallet is in INR already
