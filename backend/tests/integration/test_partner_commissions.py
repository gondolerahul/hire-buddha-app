"""Commissions, fees, statements (Phase 15 T8-6…T8-10, tech design §11.4–§11.7). Real Postgres, rolled back.

* The §11.6 worked example through a real top-up: Gold P0 20 %, Gold P1 3 %,
  Silver P2 with no revenue of its own this month 0 % (the platform keeps it).
* A Silver referral earns as long as the customer pays — 13 months on — and
  stops when the partner lapses (held) or is terminated (O-8).
* A refund claws back on every level; a setup fee is split by its rule; the
  annual partnership fee earns nobody anything (K-12).
* Statements: payable entries less TDS; below the minimum they carry forward;
  paid, the ledger nets to zero. The margin guard holds what the margin does
  not cover.
"""
from __future__ import annotations

import hashlib
import hmac
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select

from src.partners import commission, statements
from src.partners.models import PartnerLedgerEntry, PartnerProfile, PartnerStatement
from tests.harness.partners import own_revenue, partner, tenant, user
from tests.integration.test_subscriptions import CREDS, KEY_SECRET, FakeRazorpay

pytestmark = pytest.mark.needs_db
D = Decimal


@pytest.fixture
def rzp(monkeypatch):
    from src.billing.gateways import razorpay as gateway_module

    fake = FakeRazorpay()

    async def _creds(_db):
        return CREDS

    monkeypatch.setattr(gateway_module, "get_razorpay_creds", _creds)
    monkeypatch.setattr(gateway_module, "razorpay_client", lambda creds: fake)
    return fake


def _app(db, actor) -> FastAPI:
    from src.auth import dependencies, router as auth_router
    from src.billing import credits_router, invoices_router
    from src.common.database import get_db
    from src.common.tenancy.session import get_control_db
    from src.partners import admin_router, portal_router, tenant_router

    app = FastAPI()
    for module in (credits_router, invoices_router, portal_router, tenant_router, admin_router):
        app.include_router(module.router)

    async def _u():
        return actor

    async def _db():
        yield db

    for dep in (dependencies.get_current_user, auth_router.get_current_user):
        app.dependency_overrides[dep] = _u
    for dep in (get_db, get_control_db):
        app.dependency_overrides[dep] = _db
    return app


async def _call(db, actor, method, path, **kw):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=_app(db, actor)), base_url="http://t") as c:
        return await c.request(method, path, **kw)


def _sig(order_id, payment_id):
    return hmac.new(KEY_SECRET.encode(), f"{order_id}|{payment_id}".encode(), hashlib.sha256).hexdigest()


async def _top_up(db, tenant_id, amount):
    admin = user("tenant_admin", tenant_id)
    order = (await _call(db, admin, "POST", "/api/v1/credits/topup", json={"amount": amount})).json()
    pid = f"pay_{uuid.uuid4().hex[:10]}"
    res = await _call(db, admin, "POST", "/api/v1/credits/topup/verify", json={
        "razorpay_order_id": order["order_id"], "razorpay_payment_id": pid,
        "razorpay_signature": _sig(order["order_id"], pid)})
    assert res.status_code == 200, res.text
    return order, pid


async def _entries(db, **where):
    query = select(PartnerLedgerEntry)
    for key, value in where.items():
        query = query.where(getattr(PartnerLedgerEntry, key) == value)
    return (await db.execute(query.where(PartnerLedgerEntry.source_type != "test")
                             .execution_options(populate_existing=True))).scalars().all()


@pytest.mark.asyncio
async def test_the_worked_example_through_a_top_up(db, rzp):
    p2 = await partner(db, "SILVER")
    p1 = await partner(db, "GOLD", recruiter=p2)
    p0 = await partner(db, "GOLD", recruiter=p1)
    await own_revenue(db, p1)                          # P1 sells this month; P2 does not
    t = await tenant(db, p0)
    await _top_up(db, t, "100000")
    rows = {(e.partner_id, e.level): e for e in await _entries(db, tenant_id=t)}
    assert rows[(p0, 0)].amount == D(20000) and rows[(p0, 0)].kind == "commission"
    assert rows[(p1, 1)].amount == D(3000) and rows[(p1, 1)].kind == "override"
    assert (p2, 2) not in rows                                            # no compression: the platform's
    assert rows[(p0, 0)].base_amount == D(100000) and rows[(p0, 0)].status == "accrued"
    assert rows[(p1, 1)].origin_partner_id == p0
    # The sweep (and a second callback) write nothing twice.
    await commission.sweep(db)
    assert len(await _entries(db, tenant_id=t)) == 2


@pytest.mark.asyncio
async def test_a_silver_referral_earns_after_a_year_and_stops_when_the_partner_lapses(db):
    from src.billing.billing_models import PaymentTransaction

    silver = await partner(db, "SILVER")
    t = await tenant(db, silver, "referred", since_days_ago=400)
    payment = PaymentTransaction(company_id=t, amount=D(1180), currency="INR", transaction_type="topup",
                                 purpose="topup", status="success", net_amount=D(1000), tax_amount=D(180),
                                 gross_amount=D(1180), razorpay_order_id=f"order_{uuid.uuid4().hex[:8]}")
    db.add(payment)
    await db.flush()
    rows = await commission.distribute(db, tenant_id=t, revenue_kind="usage_topup", base=D(1000), currency="INR",
                                       source_type="payment", source_id=str(payment.id))
    assert [(r.amount, r.status) for r in rows] == [(D(100), "accrued")]           # 10 %, 13 months on (O-8)
    profile = await db.get(PartnerProfile, silver)
    profile.status = "lapsed"
    await db.flush()
    held = await commission.distribute(db, tenant_id=t, revenue_kind="usage_topup", base=D(1000), currency="INR",
                                       source_type="payment", source_id="second")
    assert [(r.status, r.hold_reason) for r in held] == [("held", "lapsed")]
    profile.status = "terminated"
    await db.flush()
    assert await commission.distribute(db, tenant_id=t, revenue_kind="usage_topup", base=D(1000), currency="INR",
                                       source_type="payment", source_id="third") == []


@pytest.mark.asyncio
async def test_kyc_not_verified_holds_until_it_is(db):
    from src.partners.lifecycle import set_kyc

    gold = await partner(db, "GOLD", kyc="pending")
    t = await tenant(db, gold)
    [row] = await commission.distribute(db, tenant_id=t, revenue_kind="subscription", base=D(5000), currency="INR",
                                        source_type="payment", source_id="sub1")
    assert (row.status, row.hold_reason, row.amount) == ("held", "kyc", D(1000))
    await set_kyc(db, await db.get(PartnerProfile, gold), "verified", actor=user("app_admin", gold), reason="test")
    await db.refresh(row)
    assert row.status == "accrued"


@pytest.mark.asyncio
async def test_a_refund_claws_back_every_level(db, rzp):
    p1 = await partner(db, "GOLD")
    p0 = await partner(db, "GOLD", recruiter=p1)
    await own_revenue(db, p1)
    t = await tenant(db, p0)
    await _top_up(db, t, "10000")
    from src.billing.billing_models import PaymentTransaction
    payment = (await db.execute(select(PaymentTransaction).where(PaymentTransaction.company_id == t))).scalar_one()
    res = await _call(db, user("app_admin", t), "POST", f"/api/v1/admin/payments/{payment.id}/refund",
                      json={"net": "5000", "reason": "test: half back"})
    assert res.status_code == 200, res.text
    claws = {(e.partner_id, e.level): e.amount for e in await _entries(db, tenant_id=t, kind="clawback")}
    assert claws == {(p0, 0): D(-1000), (p1, 1): D(-150)}


@pytest.mark.asyncio
async def test_a_setup_fee_is_split_by_its_rule_and_paid_outside_the_wallet(db, rzp):
    from tests.harness.wallet import available

    p1 = await partner(db, "GOLD")
    p0 = await partner(db, "GOLD", recruiter=p1)
    await own_revenue(db, p1)
    t = await tenant(db, p0)
    gold_admin = user("partner_admin", p0)
    too_much = await _call(db, gold_admin, "POST", "/api/v1/partner/charges",
                           json={"tenant_id": str(t), "fee_kind": "setup", "amount": "9999999"})
    assert too_much.status_code == 422
    raised = await _call(db, gold_admin, "POST", "/api/v1/partner/charges",
                         json={"tenant_id": str(t), "fee_kind": "setup", "amount": "50000",
                               "description": "CRM setup"})
    assert raised.status_code == 201, raised.text
    charge_id = raised.json()["id"]
    before = await available(db, t)
    admin = user("tenant_admin", t)
    order = (await _call(db, admin, "POST", f"/api/v1/charges/{charge_id}/order")).json()
    assert (D(order["net"]), D(order["amount"])) == (D(50000), D(59000))
    pid = "pay_setup"
    done = await _call(db, admin, "POST", f"/api/v1/charges/{charge_id}/verify", json={
        "razorpay_order_id": order["order_id"], "razorpay_payment_id": pid,
        "razorpay_signature": _sig(order["order_id"], pid)})
    assert done.status_code == 200 and done.json()["charge"]["status"] == "paid" and done.json()["invoice_id"]
    assert await available(db, t) == before                                  # not wallet credit
    shares = {(e.partner_id, e.level): e for e in await _entries(db, tenant_id=t)}
    assert shares[(p0, 0)].amount == D(37500) and shares[(p0, 0)].kind == "fee_share"     # 75 %
    assert shares[(p1, 1)].amount == D(1500)                                              # 3 %


@pytest.mark.asyncio
async def test_the_partnership_fee_earns_nobody_anything(db, rzp):
    from src.billing.price_items import set_price_item
    from src.partners.lifecycle import new_agreement, sign

    recruiter = await partner(db, "GOLD")
    await own_revenue(db, recruiter)
    p = await partner(db, "GOLD", recruiter=recruiter, status="approved")
    await set_price_item(db, "partner_annual_fee_gold", amount_usd=D(100), currency_overrides={"INR": "10000"},
                         active=True, actor=None, reason="test")
    profile = await db.get(PartnerProfile, p)
    await new_agreement(db, profile)
    admin = user("partner_admin", p)
    await sign(db, profile, admin)
    assert profile.status == "approved"                                   # the fee is due first
    order = (await _call(db, admin, "POST", "/api/v1/partner/me/fee/order")).json()
    assert D(order["amount"]) == D(11800)
    res = await _call(db, admin, "POST", "/api/v1/partner/me/fee/verify", json={
        "razorpay_order_id": order["order_id"], "razorpay_payment_id": "pay_fee",
        "razorpay_signature": _sig(order["order_id"], "pay_fee")})
    assert res.status_code == 200 and res.json()["status"] == "active" and res.json()["invoice_id"]
    assert abs((await db.get(PartnerProfile, p)).fee_paid_until - (datetime.utcnow() + timedelta(days=365))) \
        < timedelta(minutes=5)
    count = (await db.execute(select(func.count()).select_from(PartnerLedgerEntry).where(
        PartnerLedgerEntry.partner_id.in_((p, recruiter)), PartnerLedgerEntry.source_type != "test"))).scalar()
    assert count == 0


@pytest.mark.asyncio
async def test_the_fee_lifecycle_lapses_holds_and_forfeits(db):
    from src.billing.price_items import set_price_item
    from src.partners.fees import lifecycle

    await set_price_item(db, "partner_annual_fee_gold", amount_usd=D(100), currency_overrides={}, active=True,
                         actor=None, reason="test")
    p = await partner(db, "GOLD")
    profile = await db.get(PartnerProfile, p)
    profile.fee_paid_until = datetime.utcnow() + timedelta(days=10)
    t = await tenant(db, p)
    await db.flush()
    await lifecycle(db)
    await db.refresh(profile)
    assert profile.status == "renewal_due"
    [earned] = await commission.distribute(db, tenant_id=t, revenue_kind="usage_topup", base=D(1000),
                                           currency="INR", source_type="payment", source_id="before-lapse")
    profile.fee_paid_until = datetime.utcnow() - timedelta(days=1)
    await db.flush()
    await lifecycle(db)
    await db.refresh(profile)
    assert profile.status == "lapsed"
    [held] = await commission.distribute(db, tenant_id=t, revenue_kind="usage_topup", base=D(1000), currency="INR",
                                         source_type="payment", source_id="while-lapsed")
    assert held.status == "held"
    profile.fee_paid_until = datetime.utcnow() - timedelta(days=40)
    await db.flush()
    await lifecycle(db)
    await db.refresh(profile)
    await db.refresh(held)
    await db.refresh(earned)
    assert profile.status == "suspended" and held.status == "reversed" and earned.status == "reversed"


@pytest.mark.asyncio
async def test_a_statement_is_its_payable_entries_less_tds_and_paid_nets_to_zero(db):
    p = await partner(db, "GOLD")
    t = await tenant(db, p, since_days_ago=90)
    rows = await commission.distribute(db, tenant_id=t, revenue_kind="usage_topup", base=D(100000), currency="INR",
                                       source_type="payment", source_id="stmt", at=datetime.utcnow() - timedelta(days=45))
    assert rows[0].amount == D(20000)
    await statements.release(db)
    await db.refresh(rows[0])
    assert rows[0].status == "payable"
    last_month = (date.today().replace(day=1) - timedelta(days=1)).replace(day=1)
    out = await statements.build(db, last_month)
    assert out["statements"] >= 1
    stmt = (await db.execute(select(PartnerStatement).where(PartnerStatement.partner_id == p))).scalar_one()
    assert (stmt.gross, stmt.tds, stmt.net) == (D(20000), D(1000), D(19000))          # TDS 5 %
    staff = user("app_admin", p)
    res = await _call(db, staff, "POST", f"/api/v1/admin/partners/statements/{stmt.id}/approve")
    assert res.status_code == 200, res.text
    csv = await _call(db, staff, "GET", "/api/v1/admin/partners/statements/export.csv")
    assert "1234567890" in csv.text and "HDFC0001234" in csv.text
    res = await _call(db, staff, "POST", f"/api/v1/admin/partners/statements/{stmt.id}/paid",
                      json={"payout_ref": "NEFT-1"})
    assert res.json()["status"] == "paid"
    balance = (await db.execute(select(func.sum(PartnerLedgerEntry.amount)).where(
        PartnerLedgerEntry.partner_id == p, PartnerLedgerEntry.status != "reversed",
        PartnerLedgerEntry.source_type != "test"))).scalar()
    assert D(str(balance)) == 0
    pdf = await _call(db, user("partner_admin", p), "GET", f"/api/v1/partner/statements/{stmt.id}/pdf")
    assert pdf.content.startswith(b"%PDF")


@pytest.mark.asyncio
async def test_below_the_minimum_payout_carries_forward(db):
    p = await partner(db, "GOLD")
    t = await tenant(db, p, since_days_ago=90)
    await commission.distribute(db, tenant_id=t, revenue_kind="usage_topup", base=D(100), currency="INR",
                                source_type="payment", source_id="tiny", at=datetime.utcnow() - timedelta(days=45))
    await statements.release(db)
    last_month = (date.today().replace(day=1) - timedelta(days=1)).replace(day=1)
    await statements.build(db, last_month)
    assert (await db.execute(select(PartnerStatement).where(PartnerStatement.partner_id == p))).first() is None


@pytest.mark.asyncio
async def test_the_margin_guard_holds_what_the_margin_does_not_cover(db):
    from src.billing.billing_models import BillingLine

    p = await partner(db, "GOLD")
    t = await tenant(db, p, since_days_ago=90)
    at = datetime.utcnow().replace(day=2, hour=12)
    month = at.date().replace(day=1)
    db.add(BillingLine(company_id=t, period_day=at.date(), category="ai_models", grouping_type="company",
                       grouping_id=None, currency="INR", cost_usd=D(80), billed_usd=D(100), billed_ccy=D(10000),
                       quantity=D(1), rows=1))
    await db.flush()
    [row] = await commission.distribute(db, tenant_id=t, revenue_kind="usage_topup", base=D(10000), currency="INR",
                                        source_type="payment", source_id="guard", at=at)
    out = await statements.margin_guard(db, month)                  # margin $20 × 50 % = $10 < the commission
    await db.refresh(row)
    assert out["held"] == 1 and (row.status, row.hold_reason) == ("held", "margin_guard")


@pytest.mark.asyncio
async def test_the_simulator_shows_the_worked_example(db):
    res = await _call(db, user("app_admin", uuid.uuid4()), "POST", "/api/v1/admin/partners/simulate", json={
        "revenue_kind": "usage_topup", "base": "100000", "billed": "100000", "cost": "40000",
        "chain": [{"type": "GOLD"}, {"type": "GOLD", "own_revenue_usd": 500},
                  {"type": "SILVER", "own_revenue_usd": 0}]})
    assert res.status_code == 200, res.text
    body = res.json()
    assert [D(s["amount"]) for s in body["shares"]] == [D(20000), D(3000), D(0)]
    assert body["shares"][2]["why"] == "no own paid revenue this month"
    assert D(body["platform"]) == D(77000) and D(body["margin_guard"]["allowed"]) == D(30000)


@pytest.mark.asyncio
async def test_staff_version_the_rules(db):
    staff = user("app_admin", uuid.uuid4())
    res = await _call(db, staff, "PUT", "/api/v1/admin/partners/rules/commission", json={
        "partner_type": "GOLD", "revenue_kind": "usage_topup", "level": 0, "rate_pct": "22", "cap_pct": "25",
        "reason": "test"})
    assert res.status_code == 200 and res.json()["version"] == 2
    bad = await _call(db, staff, "PUT", "/api/v1/admin/partners/rules/fee", json={
        "partner_type": "GOLD", "fee_kind": "setup", "min_usd": "100", "max_usd": "1000",
        "split": {"originator": 80, "level1": 3, "level2": 2, "platform": 20}})
    assert bad.status_code == 422                                           # 105 %
    rules = (await _call(db, staff, "GET", "/api/v1/admin/partners/rules")).json()
    gold0 = [r for r in rules["commission_rules"] if r["partner_type"] == "GOLD" and r["level"] == 0
             and r["revenue_kind"] == "usage_topup"]
    assert [D(r["rate_pct"]) for r in gold0] == [D(22)]
