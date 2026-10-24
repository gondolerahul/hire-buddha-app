"""Subscriptions to plans, in the company's currency, with GST; credits come only from payments.

Before Phase 15 subscribing failed with 422 (BC-28), verification granted no
credits (BC-03), and the monthly job granted a month to every active
subscription whether anyone had paid (BC-04, BC-16). M15.3 (T6-1, T6-3, T6-4)
moved subscriptions from tiers to versioned plans charged in the company's
currency — a gateway plan per (plan version, currency, rate, GST) — with each
paid cycle credited net of GST and invoiced; an upgrade applies now, a
downgrade and a cancellation at the cycle's end; a renewal follows a price or
rate change.

Razorpay is replaced by an in-memory fake; everything else — routes, services,
the real Postgres (rolled back per test) — is real.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select

from src.auth.dependencies import get_current_user
from src.billing import credits_router, razorpay_webhook
from src.billing.billing_models import (
    CreditWallet, FxRate, Invoice, PaymentTransaction, Plan, PlanGatewayPlan, PlanVersion, Subscription,
)
from src.billing.cron_service import CronService
from src.common.database import get_db

pytestmark = pytest.mark.needs_db

KEY_SECRET = "rzp-key-secret"
WEBHOOK_SECRET = "rzp-webhook-secret"
CREDS = {"key_id": "rzp_test", "key_secret": KEY_SECRET, "webhook_secret": WEBHOOK_SECRET}


class FakeRazorpay:
    def __init__(self):
        self.plans: list[dict] = []
        self.subs: dict[str, dict] = {}
        self.invoices: dict[str, list] = {}
        self.cancelled: list[tuple[str, dict]] = []
        self.edits: list[tuple[str, dict]] = []
        self.refunds: list[tuple[str, dict]] = []
        self.orders: list[dict] = []
        self.fail_cancel = False
        self.plan = SimpleNamespace(create=self._plan_create)
        self.subscription = SimpleNamespace(create=self._sub_create, fetch=self._sub_fetch,
                                            cancel=self._sub_cancel, edit=self._sub_edit)
        self.invoice = SimpleNamespace(all=lambda q: {"items": self.invoices.get(q["subscription_id"], [])})
        self.payment = SimpleNamespace(refund=self._refund)
        self.order = SimpleNamespace(create=self._order_create)

    def _plan_create(self, data):
        plan = {"id": f"plan_{uuid.uuid4().hex[:10]}", **data}
        self.plans.append(plan)
        return plan

    def _sub_create(self, data):
        sid = f"sub_{uuid.uuid4().hex[:10]}"
        self.subs[sid] = {"id": sid, "status": "created", "current_end": None, **data}
        return self.subs[sid]

    def _sub_fetch(self, sid):
        return self.subs[sid]

    def _sub_cancel(self, sid, data=None):
        if self.fail_cancel:
            raise RuntimeError("Razorpay unavailable")
        self.cancelled.append((sid, data or {}))
        if not (data or {}).get("cancel_at_cycle_end"):
            self.subs[sid]["status"] = "cancelled"
        return self.subs[sid]

    def _sub_edit(self, sid, data):
        self.edits.append((sid, data))
        if data.get("schedule_change_at") == "now":
            self.subs[sid]["plan_id"] = data["plan_id"]
        return self.subs[sid]

    def _refund(self, payment_id, data):
        self.refunds.append((payment_id, data))
        return {"id": f"rfnd_{uuid.uuid4().hex[:10]}", **data}

    def _order_create(self, data):
        order = {"id": f"order_{uuid.uuid4().hex[:10]}", **data}
        self.orders.append(order)
        return order


@pytest.fixture
def rzp(monkeypatch):
    from src.billing.gateways import razorpay as gateway_module

    fake = FakeRazorpay()

    async def _creds(_db):
        return CREDS

    monkeypatch.setattr(gateway_module, "get_razorpay_creds", _creds)
    monkeypatch.setattr(gateway_module, "razorpay_client", lambda creds: fake)
    monkeypatch.setattr(razorpay_webhook, "get_razorpay_creds", _creds)
    return fake


async def _company(db, currency="USD", country=None, state=None):
    from src.auth.models import Company
    country = country or ("US" if currency == "USD" else "IN")
    c = Company(name=f"subs-{uuid.uuid4().hex[:6]}", type="TENANT", status="active", billing_currency=currency,
                country_code=country, billing_state=state)
    db.add(c)
    await db.flush()
    return c.id


async def _plan(db, level=None, fee="79.00", bonus="30", overrides=None):
    level = level or 900 + int(uuid.uuid4().int % 90000)
    plan = Plan(code=f"p{level}", name=f"Plan {level}", tier_level=level, monthly_fee_usd=Decimal(fee),
                bonus_pct=Decimal(bonus), currency_overrides=overrides or {}, active=True, version=1)
    db.add(plan)
    await db.flush()
    db.add(PlanVersion(plan_id=plan.id, version=1, name=plan.name, monthly_fee_usd=plan.monthly_fee_usd,
                       bonus_pct=plan.bonus_pct, currency_overrides=plan.currency_overrides, active=True))
    await db.flush()
    return plan


def _client(db, company_id, role="tenant_admin") -> httpx.AsyncClient:
    app = FastAPI()
    app.include_router(credits_router.router)
    app.include_router(razorpay_webhook.router)

    async def _user():
        return SimpleNamespace(id=uuid.uuid4(), role=role, company_id=company_id)

    async def _db():
        yield db

    app.dependency_overrides[get_current_user] = _user
    app.dependency_overrides[get_db] = _db
    from src.common.tenancy.session import get_control_db
    app.dependency_overrides[get_control_db] = _db
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


def _checkout_sig(payment_id, sub_id):
    return hmac.new(KEY_SECRET.encode(), f"{payment_id}|{sub_id}".encode(), hashlib.sha256).hexdigest()


async def _webhook(client, event, sub_entity, payment=None):
    payload = {"subscription": {"entity": sub_entity}}
    if payment:
        payload["payment"] = {"entity": payment}
    body = json.dumps({"event": event, "payload": payload}).encode()
    sig = hmac.new(WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
    return await client.post("/api/v1/credits/razorpay/webhook", content=body,
                             headers={"X-Razorpay-Signature": sig, "Content-Type": "application/json"})


async def _wallet(db, company_id):
    """The wallet with its subscription lots summed (lots, not buckets)."""
    from src.billing.wallet import WalletService
    row = (await db.execute(select(CreditWallet).where(CreditWallet.company_id == company_id)
                            .execution_options(populate_existing=True))).scalar_one_or_none()
    if row is None:
        return None
    lots = (await WalletService(db).balance(company_id))["lots"]
    sub_lots = [lot for lot in lots if lot["kind"] == "subscription"]
    return SimpleNamespace(
        account_model=row.account_model, currency=row.currency,
        subscription_credits=sum((lot["remaining"] for lot in sub_lots), Decimal(0)),
        subscription_bonus_credits=sum((lot["remaining"] for lot in lots if lot["kind"] == "subscription_bonus"),
                                       Decimal(0)),
        sub_credits_expire_at=max((lot["expires_at"] for lot in sub_lots), default=None))


async def _sub(db, rz_id):
    return (await db.execute(select(Subscription).where(Subscription.razorpay_subscription_id == rz_id)
                             .execution_options(populate_existing=True))).scalar_one()


async def _subscribe(client, rzp, plan, cycle_days=30):
    res = await client.post("/api/v1/credits/subscriptions", json={"plan_id": str(plan.id)})
    assert res.status_code == 200, res.text
    rz_id = res.json()["razorpay_subscription_id"]
    rzp.subs[rz_id].update(status="active", current_end=int(time.time()) + cycle_days * 86400)
    return rz_id


async def _verify(client, rz_id, payment_id):
    return await client.post("/api/v1/credits/subscriptions/verify", json={
        "razorpay_payment_id": payment_id, "razorpay_subscription_id": rz_id,
        "razorpay_signature": _checkout_sig(payment_id, rz_id)})


@pytest.mark.asyncio
async def test_subscribing_charges_the_plan_in_rupees_with_gst(db, rzp):
    company = await _company(db, "INR", state="KA")
    plan = await _plan(db, fee="12", overrides={"INR": "1000"})
    async with _client(db, company) as client:
        res = await client.post("/api/v1/credits/subscriptions", json={"plan_id": str(plan.id)})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["currency"] == "INR"
    assert (Decimal(body["net"]), Decimal(body["tax"]), Decimal(body["amount"])) == (1000, 180, 1180)
    assert rzp.plans[0]["item"] == {**rzp.plans[0]["item"], "amount": 118000, "currency": "INR"}
    sub = await _sub(db, body["razorpay_subscription_id"])
    assert sub.status == "pending_payment" and sub.plan_id == plan.id and sub.currency == "INR"
    assert sub.amount_ccy == Decimal(1000) and sub.razorpay_plan_id == rzp.plans[0]["id"]


@pytest.mark.asyncio
async def test_subscribers_share_a_gateway_plan_per_price(db, rzp):
    plan = await _plan(db)
    for _ in range(2):
        async with _client(db, await _company(db)) as client:
            assert (await client.post("/api/v1/credits/subscriptions",
                                      json={"plan_id": str(plan.id)})).status_code == 200
    assert len(rzp.plans) == 1
    rows = (await db.execute(select(PlanGatewayPlan).where(PlanGatewayPlan.plan_id == plan.id))).scalars().all()
    assert len(rows) == 1 and rows[0].currency == "USD" and rows[0].tax_rate == 0      # export: no GST


@pytest.mark.asyncio
async def test_the_level_still_names_a_plan(db, rzp):
    """The wallet page sent ``tier_level`` before plans; it still subscribes."""
    plan = await _plan(db)
    async with _client(db, await _company(db)) as client:
        res = await client.post("/api/v1/credits/subscriptions", json={"tier_level": plan.tier_level})
    assert res.status_code == 200 and res.json()["plan_id"] == str(plan.id)


@pytest.mark.asyncio
async def test_verifying_the_first_payment_grants_the_cycle_once_with_an_invoice(db, rzp):
    company, plan = await _company(db), await _plan(db, fee="79.00", bonus="30")
    async with _client(db, company) as client:
        rz_id = await _subscribe(client, rzp, plan)
        first = await _verify(client, rz_id, "pay_s1")
        again = await _verify(client, rz_id, "pay_s1")
        hook = await _webhook(client, "subscription.charged", rzp.subs[rz_id],
                              {"id": "pay_s1", "amount": 7900, "currency": "USD"})
    assert first.status_code == 200 and first.json()["credits_granted"] is True
    assert again.json()["credits_granted"] is False
    assert hook.json() == {"status": "already_credited"}
    wallet = await _wallet(db, company)
    assert wallet.subscription_credits == Decimal("79")
    assert wallet.subscription_bonus_credits == Decimal("23.7")
    assert wallet.account_model == "subscription"
    assert abs(wallet.sub_credits_expire_at - (datetime.utcnow() + timedelta(days=30))) < timedelta(minutes=5)
    assert (await _sub(db, rz_id)).status == "active"
    charges = (await db.execute(select(PaymentTransaction).where(
        PaymentTransaction.company_id == company))).scalars().all()
    assert [(c.razorpay_payment_id, c.status, c.purpose) for c in charges] == [("pay_s1", "success", "subscription")]
    invoice = await db.get(Invoice, charges[0].invoice_id)
    assert invoice.regime == "export" and invoice.total == Decimal("79") and invoice.tax == 0


@pytest.mark.asyncio
async def test_a_rupee_cycle_credits_the_net_and_invoices_cgst_and_sgst(db, rzp):
    company = await _company(db, "INR", state="KA")
    plan = await _plan(db, fee="12", bonus="10", overrides={"INR": "1000"})
    async with _client(db, company) as client:
        rz_id = await _subscribe(client, rzp, plan)
        res = await _verify(client, rz_id, "pay_inr")
    assert res.status_code == 200 and res.json()["credits_granted"] is True
    wallet = await _wallet(db, company)
    assert wallet.currency == "INR"
    assert wallet.subscription_credits == Decimal("1000")          # what was paid, net of GST
    assert wallet.subscription_bonus_credits == Decimal("100")
    payment = (await db.execute(select(PaymentTransaction).where(
        PaymentTransaction.razorpay_payment_id == "pay_inr"))).scalar_one()
    assert (payment.net_amount, payment.tax_amount, payment.gross_amount) == (Decimal(1000), Decimal(180), Decimal(1180))
    invoice = await db.get(Invoice, payment.invoice_id)
    assert (invoice.cgst, invoice.sgst, invoice.igst, invoice.total) == (Decimal(90), Decimal(90), 0, Decimal(1180))
    assert invoice.number.startswith("HB/")


@pytest.mark.asyncio
async def test_a_bad_checkout_signature_grants_nothing(db, rzp):
    company, plan = await _company(db), await _plan(db)
    async with _client(db, company) as client:
        rz_id = await _subscribe(client, rzp, plan)
        res = await client.post("/api/v1/credits/subscriptions/verify", json={
            "razorpay_payment_id": "pay_bad", "razorpay_subscription_id": rz_id, "razorpay_signature": "0" * 64})
    assert res.status_code == 400
    assert (await _sub(db, rz_id)).status == "pending_payment"


@pytest.mark.asyncio
async def test_each_monthly_charge_replaces_the_cycles_credits(db, rzp):
    company, plan = await _company(db), await _plan(db, fee="29.00", bonus="20")
    async with _client(db, company) as client:
        rz_id = await _subscribe(client, rzp, plan)
        await _webhook(client, "subscription.charged", rzp.subs[rz_id],
                       {"id": "pay_m1", "amount": 2900, "currency": "USD"})
        from src.billing.wallet import WalletService
        await WalletService(db).deduct(company, Decimal("30"), source_type="test")
        rzp.subs[rz_id]["current_end"] += 30 * 86400
        res = await _webhook(client, "subscription.charged", rzp.subs[rz_id],
                             {"id": "pay_m2", "amount": 2900, "currency": "USD"})
    assert res.json() == {"status": "credited"}
    wallet = await _wallet(db, company)
    assert wallet.subscription_credits == Decimal("29")       # no carry-forward
    assert wallet.subscription_bonus_credits == Decimal("5.8")
    assert wallet.sub_credits_expire_at > datetime.utcnow() + timedelta(days=55)


@pytest.mark.asyncio
async def test_failed_charges_and_the_end_follow_razorpay(db, rzp):
    company, plan = await _company(db), await _plan(db)
    async with _client(db, company) as client:
        rz_id = await _subscribe(client, rzp, plan)
        await _webhook(client, "subscription.charged", rzp.subs[rz_id],
                       {"id": "pay_f1", "amount": 7900, "currency": "USD"})
        halted = await _webhook(client, "subscription.halted", {**rzp.subs[rz_id], "status": "halted"})
        assert halted.json() == {"status": "status_past_due"}
        assert (await _sub(db, rz_id)).status == "past_due"
        ended = await _webhook(client, "subscription.cancelled", {**rzp.subs[rz_id], "status": "cancelled"})
    assert ended.json() == {"status": "status_cancelled"}
    assert (await _sub(db, rz_id)).status == "cancelled"
    wallet = await _wallet(db, company)
    assert wallet.account_model == "pay_as_you_go"
    assert wallet.subscription_credits == Decimal("79")  # paid for; kept until expiry


@pytest.mark.asyncio
async def test_cancelling_ends_the_subscription_at_the_cycles_end(db, rzp):
    company, plan = await _company(db), await _plan(db)
    async with _client(db, company) as client:
        rz_id = await _subscribe(client, rzp, plan)
        await _verify(client, rz_id, "pay_c1")
        sub = await _sub(db, rz_id)
        res = await client.delete(f"/api/v1/credits/subscriptions/{sub.id}")
    assert res.status_code == 200, res.text
    assert rzp.cancelled == [(rz_id, {"cancel_at_cycle_end": 1})]
    sub = await _sub(db, rz_id)
    assert sub.status == "active" and sub.cancel_at_cycle_end is True     # paid through the cycle


@pytest.mark.asyncio
async def test_cancelling_stops_the_mandate_first(db, rzp):
    company, plan = await _company(db), await _plan(db)
    async with _client(db, company) as client:
        rz_id = await _subscribe(client, rzp, plan)
        sub = await _sub(db, rz_id)
        rzp.fail_cancel = True
        refused = await client.delete(f"/api/v1/credits/subscriptions/{sub.id}", params={"immediately": "true"})
        assert refused.status_code == 502
        assert (await _sub(db, rz_id)).status == "pending_payment"
        rzp.fail_cancel = False
        ok = await client.delete(f"/api/v1/credits/subscriptions/{sub.id}", params={"immediately": "true"})
    assert ok.status_code == 200
    assert rzp.cancelled == [(rz_id, {"cancel_at_cycle_end": 0})]
    assert (await _sub(db, rz_id)).status == "cancelled"


@pytest.mark.asyncio
async def test_one_live_subscription_per_company(db, rzp):
    company, plan = await _company(db), await _plan(db)
    async with _client(db, company) as client:
        rz_id = await _subscribe(client, rzp, plan)
        await _webhook(client, "subscription.charged", rzp.subs[rz_id],
                       {"id": "pay_one", "amount": 7900, "currency": "USD"})
        res = await client.post("/api/v1/credits/subscriptions", json={"plan_id": str(plan.id)})
    assert res.status_code == 409


@pytest.mark.asyncio
async def test_an_upgrade_applies_now_and_a_downgrade_at_the_cycles_end(db, rzp):
    company = await _company(db)
    low, high = await _plan(db, fee="29", bonus="0"), await _plan(db, fee="79", bonus="30")
    high.tier_level, low.tier_level = low.tier_level + 1, low.tier_level
    await db.flush()
    async with _client(db, company) as client:
        rz_id = await _subscribe(client, rzp, low)
        await _verify(client, rz_id, "pay_u1")
        up = await client.post("/api/v1/credits/subscriptions/change", json={"plan_id": str(high.id)})
        assert up.status_code == 200, up.text
        assert up.json()["change"] == "upgrade"
        assert rzp.edits[-1][1]["schedule_change_at"] == "now"
        sub = await _sub(db, rz_id)
        assert sub.plan_id == high.id and sub.pending_plan_id is None
        down = await client.post("/api/v1/credits/subscriptions/change", json={"plan_id": str(low.id)})
    assert down.json()["change"] == "downgrade"
    assert rzp.edits[-1][1]["schedule_change_at"] == "cycle_end"
    sub = await _sub(db, rz_id)
    assert sub.plan_id == high.id and sub.pending_plan_id == low.id       # until the cycle ends


@pytest.mark.asyncio
async def test_a_downgrade_takes_effect_with_the_next_cycles_charge(db, rzp):
    company = await _company(db)
    low, high = await _plan(db, fee="29", bonus="0"), await _plan(db, fee="79", bonus="30")
    high.tier_level = low.tier_level + 1
    await db.flush()
    async with _client(db, company) as client:
        rz_id = await _subscribe(client, rzp, high)
        await _verify(client, rz_id, "pay_d1")
        await client.post("/api/v1/credits/subscriptions/change", json={"plan_id": str(low.id)})
        rzp.subs[rz_id]["current_end"] += 30 * 86400
        await _webhook(client, "subscription.charged", rzp.subs[rz_id],
                       {"id": "pay_d2", "amount": 2900, "currency": "USD"})
    sub = await _sub(db, rz_id)
    assert sub.plan_id == low.id and sub.pending_plan_id is None
    wallet = await _wallet(db, company)
    assert wallet.subscription_credits == Decimal("29") and wallet.subscription_bonus_credits == 0


@pytest.mark.asyncio
async def test_a_renewal_follows_a_new_fx_rate(db, rzp):
    """A plan without a rupee price is charged at the rate of the day; a new rate reaches the next renewal."""
    company = await _company(db, "INR", state="KA")
    plan = await _plan(db, fee="10", bonus="0")
    async with _client(db, company) as client:
        rz_id = await _subscribe(client, rzp, plan)
        await _verify(client, rz_id, "pay_fx1")
    before = len(rzp.plans)
    db.add(FxRate(currency="INR", units_per_usd=Decimal("95.5"), effective_from=datetime.utcnow() - timedelta(seconds=1)))
    await db.flush()
    result = await CronService(db).run_subscription_reconciliation()
    assert result.get("repriced", 0) >= 1
    assert len(rzp.plans) == before + 1
    assert rzp.plans[-1]["item"]["amount"] == 112690                     # ₹955 + 18% GST, in paise
    assert rzp.edits[-1] == (rz_id, {"plan_id": rzp.plans[-1]["id"], "schedule_change_at": "cycle_end",
                                     "customer_notify": 1})
    sub = await _sub(db, rz_id)
    assert sub.pending_gateway_plan_ref is not None and sub.amount_ccy != Decimal("955")   # this cycle unchanged


@pytest.mark.asyncio
async def test_reconciliation_grants_nothing_without_a_paid_invoice(db, rzp):
    """The old monthly job granted a month to every active subscription."""
    company = await _company(db)
    sub = Subscription(company_id=company, plan_tier=2, monthly_fee=Decimal("79"), bonus_pct=Decimal("30"),
                       status="active", razorpay_subscription_id=f"sub_{uuid.uuid4().hex[:10]}")
    db.add(sub)
    await db.flush()
    rzp.subs[sub.razorpay_subscription_id] = {"id": sub.razorpay_subscription_id, "status": "active"}
    result = await CronService(db).run_monthly_subscription_job()
    assert result["credited"] == 0
    wallet = await _wallet(db, company)
    assert wallet is None or wallet.subscription_credits == 0
    txns = (await db.execute(select(PaymentTransaction).where(PaymentTransaction.company_id == company))).scalars().all()
    assert txns == []


@pytest.mark.asyncio
async def test_reconciliation_grants_a_paid_cycle_the_webhook_missed(db, rzp):
    company = await _company(db)
    rz_id = f"sub_{uuid.uuid4().hex[:10]}"
    sub = Subscription(company_id=company, plan_tier=1, monthly_fee=Decimal("29"), bonus_pct=Decimal("20"),
                       status="past_due", razorpay_subscription_id=rz_id)
    db.add(sub)
    await db.flush()
    end = int(time.time()) + 20 * 86400
    rzp.subs[rz_id] = {"id": rz_id, "status": "active"}
    rzp.invoices[rz_id] = [
        {"status": "paid", "payment_id": "pay_old", "amount_paid": 2900, "billing_end": end - 30 * 86400},
        {"status": "paid", "payment_id": "pay_new", "amount_paid": 2900, "billing_end": end},
        {"status": "issued", "payment_id": None, "amount": 2900, "billing_end": end + 30 * 86400},
    ]
    first = await CronService(db).run_subscription_reconciliation()
    second = await CronService(db).run_subscription_reconciliation()
    assert first["credited"] == 2 and second["credited"] == 0
    wallet = await _wallet(db, company)
    assert wallet.subscription_credits == Decimal("29")
    assert abs(wallet.sub_credits_expire_at - datetime.utcfromtimestamp(end)) < timedelta(seconds=2)
    assert (await _sub(db, rz_id)).status == "active"


@pytest.mark.asyncio
async def test_an_older_payment_recorded_late_does_not_replace_newer_credits(db, rzp):
    company, plan = await _company(db), await _plan(db, fee="29.00", bonus="0")
    async with _client(db, company) as client:
        rz_id = await _subscribe(client, rzp, plan, cycle_days=40)
        await _webhook(client, "subscription.charged", rzp.subs[rz_id],
                       {"id": "pay_current", "amount": 2900, "currency": "USD"})
        from src.billing.wallet import WalletService
        await WalletService(db).deduct(company, Decimal("10"), source_type="test")
        left = (await _wallet(db, company)).subscription_credits
        assert left < Decimal("29")
        earlier = {**rzp.subs[rz_id], "current_end": int(time.time()) + 10 * 86400}
        await _webhook(client, "subscription.charged", earlier,
                       {"id": "pay_earlier", "amount": 2900, "currency": "USD"})
    wallet = await _wallet(db, company)
    assert wallet.subscription_credits == left  # not reset to 29
    assert wallet.sub_credits_expire_at > datetime.utcnow() + timedelta(days=35)


@pytest.mark.asyncio
async def test_a_one_time_order_subscription_ends_with_its_month(db, rzp):
    company = await _company(db)
    sub = Subscription(company_id=company, plan_tier=1, monthly_fee=Decimal("29"), bonus_pct=Decimal("20"),
                       status="active", next_billing_date=datetime.utcnow() - timedelta(days=1))
    db.add(sub)
    await db.flush()
    result = await CronService(db).run_subscription_reconciliation()
    assert result["legacy_ended"] == 1
    assert (await db.get(Subscription, sub.id)).status == "cancelled"


@pytest.mark.asyncio
async def test_pay_as_you_go_cannot_be_subscribed_to(db, rzp):
    payg = (await db.execute(select(Plan).where(Plan.tier_level == 0))).scalar_one()
    async with _client(db, await _company(db)) as client:
        res = await client.post("/api/v1/credits/subscriptions", json={"plan_id": str(payg.id)})
    assert res.status_code == 404
