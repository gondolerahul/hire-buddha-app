"""The M15.2 staff APIs: wallets, the currency tool, daily credits, price items, company locks
(Phase 15 T2-7, T4-1, T5-3…T5-5), and the company's own ledger. Real Postgres, rolled back;
the signed-in user is stubbed.
"""
from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select

from src.auth.models import Company
from src.auth.roles import Role
from src.billing.billing_models import WalletLot
from src.billing.wallet import WalletService
from src.common.admin_audit import AdminAuditLog
from tests.harness.wallet import available, fund

pytestmark = pytest.mark.needs_db


def _app(db, user) -> FastAPI:
    from src.auth.dependencies import get_current_user
    from src.billing import daily_credits_router, locks, price_items_router, wallet_router
    from src.common.database import get_db

    app = FastAPI()
    for module in (wallet_router, daily_credits_router, price_items_router, locks):
        app.include_router(module.router)

    async def _user():
        return user

    async def _db():
        yield db

    app.dependency_overrides[get_current_user] = _user
    app.dependency_overrides[get_db] = _db
    return app


async def _call(db, user, method, path, **kw):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=_app(db, user)), base_url="http://t") as c:
        return await c.request(method, path, **kw)


def _user(role, company_id=None):
    return SimpleNamespace(id=uuid.uuid4(), role=Role(role), company_id=company_id or uuid.uuid4())


STAFF = _user("app_admin")


async def _company(db, currency="INR", kind="TENANT", parent=None):
    c = Company(name=f"m152-{uuid.uuid4().hex[:6]}", type=kind, status="active", billing_currency=currency,
                parent_id=parent)
    db.add(c)
    await db.flush()
    return c.id


async def _audited(db, object_type, key):
    return (await db.execute(select(AdminAuditLog.action).where(AdminAuditLog.object_type == object_type,
                                                                AdminAuditLog.object_key == key))).scalars().all()


# ── wallets ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_staff_see_a_wallet_with_its_lots_and_ledger_and_tenants_cannot(db):
    company = await _company(db)
    await fund(db, company, "2")
    res = await _call(db, STAFF, "GET", f"/api/v1/admin/wallets/{company}")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["wallet"]["currency"] == "INR" and Decimal(body["wallet"]["available"]) == 200
    assert body["problems"] == [] and [e["kind"] for e in body["entries"]] == ["grant"]
    listed = (await _call(db, STAFF, "GET", "/api/v1/admin/wallets", params={"q": "m152-"})).json()
    assert any(w["company_id"] == str(company) for w in listed["wallets"])
    tenant = _user("tenant_admin", company)
    assert (await _call(db, tenant, "GET", f"/api/v1/admin/wallets/{company}")).status_code == 403


@pytest.mark.asyncio
async def test_an_adjustment_is_audited_and_needs_a_reason(db):
    company = await _company(db)
    res = await _call(db, STAFF, "POST", f"/api/v1/admin/wallets/{company}/adjust",
                      json={"amount": "-150", "reason": "missed charge"})
    assert res.status_code == 200 and res.json()["debt"] == "150.0000000000"
    assert (await _call(db, STAFF, "POST", f"/api/v1/admin/wallets/{company}/adjust",
                        json={"amount": "10"})).status_code == 422
    assert await _audited(db, "wallet", str(company)) == ["adjust"]


@pytest.mark.asyncio
async def test_the_company_reads_its_own_ledger_without_staff_fields(db):
    company = await _company(db)
    await fund(db, company, "1")
    await WalletService(db).deduct(company, Decimal("30"), source_type="settlement", source_id="run:x",
                                   category="ai_models")
    res = await _call(db, _user("tenant_user", company), "GET", "/api/v1/credits/ledger")
    entries = res.json()["entries"]
    assert [e["kind"] for e in entries] == ["deduct", "grant"]
    assert all("actor_id" not in e and "source_id" not in e and "cost" not in str(e) for e in entries)


# ── the currency tool (T2-7) ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_changing_the_currency_converts_lots_and_debt_at_one_rate(db):
    company = await _company(db, currency="USD")
    await fund(db, company, "3")
    await WalletService(db).deduct(company, Decimal("1"), source_type="test")
    res = await _call(db, STAFF, "POST", f"/api/v1/admin/wallets/{company}/currency",
                      json={"currency": "INR", "reason": "billed in India"})
    assert res.status_code == 200, res.text
    assert res.json()["from"] == "USD" and res.json()["to"] == "INR"
    assert await available(db, company) == Decimal("200")
    assert (await db.get(Company, company)).billing_currency == "INR"
    lot = (await db.execute(select(WalletLot).where(WalletLot.company_id == company))).scalar_one()
    assert lot.currency == "INR" and lot.remaining == Decimal("200")
    assert await WalletService(db).check(company) == []
    assert await _audited(db, "company_currency", str(company)) == ["change_currency"]
    again = await _call(db, STAFF, "POST", f"/api/v1/admin/wallets/{company}/currency",
                        json={"currency": "INR", "reason": "again"})
    assert again.status_code == 409


@pytest.mark.asyncio
async def test_the_currency_cannot_change_under_a_live_subscription(db):
    from src.billing.billing_models import Subscription
    company = await _company(db, currency="USD")
    db.add(Subscription(company_id=company, plan_tier=1, monthly_fee=Decimal("29"), bonus_pct=Decimal("0"),
                        status="active"))
    await db.flush()
    res = await _call(db, STAFF, "POST", f"/api/v1/admin/wallets/{company}/currency",
                      json={"currency": "INR", "reason": "move"})
    assert res.status_code == 409 and "subscription" in res.json()["detail"]


@pytest.mark.asyncio
async def test_a_debt_is_converted_too(db):
    company = await _company(db, currency="INR")
    await WalletService(db).deduct(company, Decimal("250"), source_type="test")
    res = await _call(db, STAFF, "POST", f"/api/v1/admin/wallets/{company}/currency",
                      json={"currency": "USD", "reason": "move"})
    assert res.status_code == 200
    wallet = await WalletService(db).get(company)
    assert wallet.currency == "USD" and wallet.debt == Decimal("2.5")
    assert await WalletService(db).check(company) == []


# ── daily credits (T5-5) ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_policy_is_validated_previewed_and_audited(db):
    from sqlalchemy import update

    from src.billing.billing_models import DailyCreditPolicy
    await db.execute(update(DailyCreditPolicy).values(active=False))
    bad = await _call(db, STAFF, "POST", "/api/v1/admin/daily-credits/policies", json={
        "name": "Trial", "audience": "direct", "duration_days": 30,
        "bands": [{"from_day": 1, "to_day": 10, "amount_usd": 2}, {"from_day": 5, "to_day": 30, "amount_usd": 1}]})
    assert bad.status_code == 422 and "overlap" in bad.text
    assert (await _call(db, STAFF, "POST", "/api/v1/admin/daily-credits/policies", json={
        "name": "Trial", "audience": "direct", "duration_days": 45, "bands": []})).status_code == 422
    body = {"name": "Direct trial", "audience": "direct", "duration_days": 30,
            "bands": [{"from_day": 1, "to_day": 10, "amount_usd": "2.00"},
                      {"from_day": 11, "to_day": 30, "amount_usd": "0.50"}]}
    made = await _call(db, STAFF, "POST", "/api/v1/admin/daily-credits/policies", json=body)
    assert made.status_code == 201, made.text
    second = await _call(db, STAFF, "POST", "/api/v1/admin/daily-credits/policies", json={**body, "name": "Other"})
    assert second.status_code == 409
    preview = (await _call(db, STAFF, "POST", "/api/v1/admin/daily-credits/preview",
                           json={"duration_days": 30, "bands": body["bands"], "currency": "INR"})).json()
    assert [(d["from_day"], d["to_day"], Decimal(d["amount"])) for d in preview["days"]] == [
        (1, 10, Decimal("200")), (11, 30, Decimal("50"))]
    company = await _company(db)
    today = (await _call(db, STAFF, "GET", f"/api/v1/admin/daily-credits/companies/{company}")).json()
    assert today["source"] == "direct" and Decimal(today["amount"]) == 200
    assert await _audited(db, "daily_credit_policy", made.json()["id"]) == ["create"]
    tenant = _user("tenant_admin", company)
    assert (await _call(db, tenant, "GET", "/api/v1/admin/daily-credits/policies")).status_code == 403


@pytest.mark.asyncio
async def test_an_override_is_set_and_removed(db):
    company = await _company(db)
    res = await _call(db, STAFF, "PUT", f"/api/v1/admin/daily-credits/overrides/{company}",
                      json={"mode": "custom", "amount_usd": "0.75", "reason": "pilot"})
    assert res.status_code == 200 and res.json()["mode"] == "custom"
    today = (await _call(db, STAFF, "GET", f"/api/v1/admin/daily-credits/companies/{company}")).json()
    assert today["source"] == "override_custom" and Decimal(today["amount"]) == 75
    assert (await _call(db, STAFF, "PUT", f"/api/v1/admin/daily-credits/overrides/{company}",
                        json={"mode": "custom", "reason": "no amount"})).status_code == 422
    assert (await _call(db, STAFF, "DELETE", f"/api/v1/admin/daily-credits/overrides/{company}")).json()["removed"]


# ── price items (T5-3) ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_number_rent_is_2000_rupees_and_an_edit_is_a_version(db):
    from src.billing.price_items import price_for
    rent = await price_for(db, "phone_number_rent", "INR")
    assert (rent.amount, rent.overridden) == (Decimal("2000"), True)
    before = rent.version
    assert (await price_for(db, "phone_number_rent", "USD")).amount == Decimal("20")
    res = await _call(db, STAFF, "PUT", "/api/v1/admin/price-items/phone_number_rent",
                      json={"amount_usd": "25", "currency_overrides": {"INR": "2400"}, "reason": "new carrier rate"})
    assert res.status_code == 200, res.text
    assert res.json()["version"] == before + 1
    assert res.json()["prices"]["INR"] == {"amount": "2400", "overridden": True}
    assert (await price_for(db, "phone_number_rent", "INR")).amount == Decimal("2400")
    versions = (await _call(db, STAFF, "GET", "/api/v1/admin/price-items/phone_number_rent/versions")).json()
    assert [v["version"] for v in versions][:2] == [before + 1, before]
    cleared = await _call(db, STAFF, "PUT", "/api/v1/admin/price-items/phone_number_rent",
                          json={"amount_usd": "25", "currency_overrides": {"INR": None}})
    assert cleared.json()["prices"]["INR"] == {"amount": "2500.0000000000", "overridden": False}   # follows FX
    assert (await _call(db, STAFF, "PUT", "/api/v1/admin/price-items/phone_number_rent",
                        json={"amount_usd": "25", "currency_overrides": {"XYZ": 1}})).status_code == 422
    assert (await _audited(db, "price_item", "phone_number_rent")).count("set") >= 2


# ── locks (T5-4) ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_partners_lock_binds_the_tenant_and_staffs_binds_the_partner(db):
    from src.billing.locks import require_unlocked

    partner = await _company(db, kind="PARTNER")
    tenant = await _company(db, parent=partner)
    partner_admin, tenant_admin = _user("partner_admin", partner), _user("tenant_admin", tenant)
    assert (await _call(db, tenant_admin, "PUT", f"/api/v1/companies/{tenant}/locks/spend_cap",
                        json={})).status_code == 403
    res = await _call(db, partner_admin, "PUT", f"/api/v1/companies/{tenant}/locks/spend_cap",
                      json={"reason": "agreed budget"})
    assert res.status_code == 200 and res.json()["locked_by_role"] == "partner"
    with pytest.raises(Exception) as refused:
        await require_unlocked(db, tenant, "spend_cap", tenant_admin)
    assert "locked by your partner: agreed budget" in str(refused.value.detail)
    await require_unlocked(db, tenant, "spend_cap", partner_admin)       # the partner is not bound by its own
    staff_lock = await _call(db, STAFF, "PUT", f"/api/v1/companies/{tenant}/locks/plan", json={})
    assert staff_lock.json()["locked_by_role"] == "app_admin"
    with pytest.raises(Exception):
        await require_unlocked(db, tenant, "plan", partner_admin)
    assert (await _call(db, partner_admin, "DELETE", f"/api/v1/companies/{tenant}/locks/plan")).status_code == 403
    await require_unlocked(db, tenant, "plan", STAFF)                    # staff never
    listed = (await _call(db, tenant_admin, "GET", f"/api/v1/companies/{tenant}/locks")).json()
    assert sorted(lock["key"] for lock in listed) == ["plan", "spend_cap"]
