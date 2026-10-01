"""Subscriptions are Razorpay Subscriptions; credits come only from payments (BC-03, BC-04, BC-16, BC-28).

Before: subscribing always failed with 422 (the wallet page sent ``plan_tier``,
the API required ``tier_level`` — BC-28); had it got through, verification set
the account to ``subscription`` and granted **no** credits (BC-03); and the
monthly job granted a month of credits to every active subscription and
recorded a "success" payment whether or not anyone had paid, because nothing
could charge month two (BC-04, BC-16).

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
from src.billing import credits_router, cron_service, razorpay_webhook
from src.billing.billing_models import (
    CreditWallet, PaymentTransaction, Subscription, SubscriptionTier,
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
        self.cancelled: list[str] = []
        self.fail_cancel = False
        self.plan = SimpleNamespace(create=self._plan_create)
        self.subscription = SimpleNamespace(create=self._sub_create, fetch=self._sub_fetch,
                                            cancel=self._sub_cancel)
        self.invoice = SimpleNamespace(all=lambda q: {"items": self.invoices.get(q["subscription_id"], [])})

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
        self.cancelled.append(sid)
        self.subs[sid]["status"] = "cancelled"
        return self.subs[sid]


@pytest.fixture
def rzp(monkeypatch):
    fake = FakeRazorpay()

    async def _creds(_db):
        return CREDS

    for module in (credits_router, razorpay_webhook, cron_service):
        if hasattr(module, "get_razorpay_creds"):
            monkeypatch.setattr(module, "get_razorpay_creds", _creds)
    monkeypatch.setattr(credits_router, "_get_razorpay_creds", _creds)
    monkeypatch.setattr(credits_router, "razorpay_client", lambda creds: fake)
    monkeypatch.setattr(cron_service, "razorpay_client", lambda creds: fake)
    return fake


async def _company(db):
    from src.auth.models import Company
    c = Company(name=f"subs-{uuid.uuid4().hex[:6]}", type="TENANT", status="active")
    db.add(c)
    await db.flush()
    return c.id


async def _tier(db, level=None, fee="79.00", bonus="30"):
    level = level or 900 + int(uuid.uuid4().int % 90000)
    tier = SubscriptionTier(name=f"T{level}", tier_level=level, monthly_fee=Decimal(fee),
                            bonus_pct=Decimal(bonus), is_active=True)
    db.add(tier)
    await db.flush()
    return tier


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
    return (await db.execute(select(CreditWallet).where(CreditWallet.company_id == company_id)
                             .execution_options(populate_existing=True))).scalar_one_or_none()


async def _sub(db, rz_id):
    return (await db.execute(select(Subscription).where(Subscription.razorpay_subscription_id == rz_id)
                             .execution_options(populate_existing=True))).scalar_one()


async def _subscribe(db, client, rzp, tier, cycle_days=30):
    res = await client.post("/api/v1/credits/subscriptions", json={"tier_level": tier.tier_level})
    assert res.status_code == 200, res.text
    rz_id = res.json()["razorpay_subscription_id"]
    rzp.subs[rz_id].update(status="active", current_end=int(time.time()) + cycle_days * 86400)
    return rz_id


@pytest.mark.asyncio
async def test_the_wallet_pages_request_creates_a_razorpay_subscription(db, rzp):
    company, tier = await _company(db), await _tier(db)
    async with _client(db, company) as client:
        res = await client.post("/api/v1/credits/subscriptions", json={"tier_level": tier.tier_level})
    assert res.status_code == 200, res.text
    body = res.json()
    rz_id = body["razorpay_subscription_id"]
    assert rzp.subs[rz_id]["plan_id"] == rzp.plans[0]["id"]
    assert rzp.plans[0]["item"]["amount"] == 7900 and rzp.plans[0]["period"] == "monthly"
    sub = await _sub(db, rz_id)
    assert sub.status == "pending_payment" and sub.razorpay_plan_id == rzp.plans[0]["id"]
    assert (await db.get(SubscriptionTier, tier.id)).razorpay_plan_id == rzp.plans[0]["id"]


@pytest.mark.asyncio
async def test_a_second_subscriber_reuses_the_tiers_plan(db, rzp):
    tier = await _tier(db)
    for _ in range(2):
        async with _client(db, await _company(db)) as client:
            assert (await client.post("/api/v1/credits/subscriptions",
                                      json={"tier_level": tier.tier_level})).status_code == 200
    assert len(rzp.plans) == 1


@pytest.mark.asyncio
async def test_verifying_the_first_payment_grants_the_cycle_once(db, rzp):
    company, tier = await _company(db), await _tier(db, fee="79.00", bonus="30")
    async with _client(db, company) as client:
        rz_id = await _subscribe(db, client, rzp, tier)
        verify = {"razorpay_payment_id": "pay_s1", "razorpay_subscription_id": rz_id,
                  "razorpay_signature": _checkout_sig("pay_s1", rz_id)}
        first = await client.post("/api/v1/credits/subscriptions/verify", json=verify)
        again = await client.post("/api/v1/credits/subscriptions/verify", json=verify)
        hook = await _webhook(client, "subscription.charged", rzp.subs[rz_id],
                              {"id": "pay_s1", "amount": 7900, "currency": "USD"})
    assert first.status_code == 200 and first.json()["credits_granted"] is True
    assert again.json()["credits_granted"] is False
    assert hook.json() == {"status": "already_credited"}
    wallet = await _wallet(db, company)
    assert Decimal(str(wallet.subscription_credits)) == Decimal("79")
    assert Decimal(str(wallet.subscription_bonus_credits)) == Decimal("23.7")
    assert wallet.account_model == "subscription"
    assert abs(wallet.sub_credits_expire_at - (datetime.utcnow() + timedelta(days=30))) < timedelta(minutes=5)
    sub = await _sub(db, rz_id)
    assert sub.status == "active"
    charges = (await db.execute(select(PaymentTransaction).where(
        PaymentTransaction.company_id == company))).scalars().all()
    assert [(c.razorpay_payment_id, c.status) for c in charges] == [("pay_s1", "success")]


@pytest.mark.asyncio
async def test_a_bad_checkout_signature_grants_nothing(db, rzp):
    company, tier = await _company(db), await _tier(db)
    async with _client(db, company) as client:
        rz_id = await _subscribe(db, client, rzp, tier)
        res = await client.post("/api/v1/credits/subscriptions/verify", json={
            "razorpay_payment_id": "pay_bad", "razorpay_subscription_id": rz_id,
            "razorpay_signature": "0" * 64})
    assert res.status_code == 400
    assert (await _sub(db, rz_id)).status == "pending_payment"


@pytest.mark.asyncio
async def test_each_monthly_charge_replaces_the_cycles_credits(db, rzp):
    company, tier = await _company(db), await _tier(db, fee="29.00", bonus="20")
    async with _client(db, company) as client:
        rz_id = await _subscribe(db, client, rzp, tier)
        await _webhook(client, "subscription.charged", rzp.subs[rz_id],
                       {"id": "pay_m1", "amount": 2900, "currency": "USD"})
        # spend some of month one
        from src.billing.credit_service import CreditService
        await CreditService(db).consume(company, Decimal("30"))
        rzp.subs[rz_id]["current_end"] += 30 * 86400
        res = await _webhook(client, "subscription.charged", rzp.subs[rz_id],
                             {"id": "pay_m2", "amount": 2900, "currency": "USD"})
    assert res.json() == {"status": "credited"}
    wallet = await _wallet(db, company)
    assert Decimal(str(wallet.subscription_credits)) == Decimal("29")       # no carry-forward
    assert Decimal(str(wallet.subscription_bonus_credits)) == Decimal("5.8")
    assert wallet.sub_credits_expire_at > datetime.utcnow() + timedelta(days=55)


@pytest.mark.asyncio
async def test_failed_charges_and_cancellation_follow_razorpay(db, rzp):
    company, tier = await _company(db), await _tier(db)
    async with _client(db, company) as client:
        rz_id = await _subscribe(db, client, rzp, tier)
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
    assert Decimal(str(wallet.subscription_credits)) == Decimal("79")  # paid for; kept until expiry


@pytest.mark.asyncio
async def test_cancelling_stops_the_razorpay_mandate_first(db, rzp):
    company, tier = await _company(db), await _tier(db)
    async with _client(db, company) as client:
        rz_id = await _subscribe(db, client, rzp, tier)
        sub = await _sub(db, rz_id)
        rzp.fail_cancel = True
        refused = await client.delete(f"/api/v1/credits/subscriptions/{sub.id}")
        assert refused.status_code == 502
        assert (await _sub(db, rz_id)).status == "pending_payment"
        rzp.fail_cancel = False
        ok = await client.delete(f"/api/v1/credits/subscriptions/{sub.id}")
    assert ok.status_code == 200
    assert rzp.cancelled == [rz_id]
    assert (await _sub(db, rz_id)).status == "cancelled"


@pytest.mark.asyncio
async def test_one_live_subscription_per_company(db, rzp):
    company, tier = await _company(db), await _tier(db)
    async with _client(db, company) as client:
        rz_id = await _subscribe(db, client, rzp, tier)
        await _webhook(client, "subscription.charged", rzp.subs[rz_id],
                       {"id": "pay_one", "amount": 7900, "currency": "USD"})
        res = await client.post("/api/v1/credits/subscriptions", json={"tier_level": tier.tier_level})
    assert res.status_code == 409


@pytest.mark.asyncio
async def test_reconciliation_grants_nothing_without_a_paid_invoice(db, rzp):
    """The old monthly job granted a month to every active subscription."""
    company = await _company(db)
    sub = Subscription(company_id=company, plan_tier=2, monthly_fee=Decimal("79"),
                       bonus_pct=Decimal("30"), status="active",
                       razorpay_subscription_id=f"sub_{uuid.uuid4().hex[:10]}")
    db.add(sub)
    await db.flush()
    rzp.subs[sub.razorpay_subscription_id] = {"id": sub.razorpay_subscription_id, "status": "active"}
    result = await CronService(db).run_monthly_subscription_job()
    assert result["credited"] == 0
    wallet = await _wallet(db, company)
    assert wallet is None or Decimal(str(wallet.subscription_credits)) == 0
    txns = (await db.execute(select(PaymentTransaction).where(
        PaymentTransaction.company_id == company))).scalars().all()
    assert txns == []


@pytest.mark.asyncio
async def test_reconciliation_grants_a_paid_cycle_the_webhook_missed(db, rzp):
    company = await _company(db)
    rz_id = f"sub_{uuid.uuid4().hex[:10]}"
    sub = Subscription(company_id=company, plan_tier=1, monthly_fee=Decimal("29"),
                       bonus_pct=Decimal("20"), status="past_due", razorpay_subscription_id=rz_id)
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
    assert Decimal(str(wallet.subscription_credits)) == Decimal("29")
    assert abs(wallet.sub_credits_expire_at - datetime.utcfromtimestamp(end)) < timedelta(seconds=2)
    assert (await _sub(db, rz_id)).status == "active"


@pytest.mark.asyncio
async def test_an_older_payment_recorded_late_does_not_replace_newer_credits(db, rzp):
    company, tier = await _company(db), await _tier(db, fee="29.00", bonus="0")
    async with _client(db, company) as client:
        rz_id = await _subscribe(db, client, rzp, tier, cycle_days=40)
        await _webhook(client, "subscription.charged", rzp.subs[rz_id],
                       {"id": "pay_current", "amount": 2900, "currency": "USD"})
        from src.billing.credit_service import CreditService
        await CreditService(db).consume(company, Decimal("10"))
        left = Decimal(str((await _wallet(db, company)).subscription_credits))
        assert left < Decimal("29")
        earlier = {**rzp.subs[rz_id], "current_end": int(time.time()) + 10 * 86400}
        await _webhook(client, "subscription.charged", earlier,
                       {"id": "pay_earlier", "amount": 2900, "currency": "USD"})
    wallet = await _wallet(db, company)
    assert Decimal(str(wallet.subscription_credits)) == left  # not reset to 29
    assert wallet.sub_credits_expire_at > datetime.utcnow() + timedelta(days=35)


@pytest.mark.asyncio
async def test_a_one_time_order_subscription_ends_with_its_month(db, rzp):
    company = await _company(db)
    sub = Subscription(company_id=company, plan_tier=1, monthly_fee=Decimal("29"),
                       bonus_pct=Decimal("20"), status="active",
                       next_billing_date=datetime.utcnow() - timedelta(days=1))
    db.add(sub)
    await db.flush()
    result = await CronService(db).run_subscription_reconciliation()
    assert result["legacy_ended"] == 1
    assert (await db.get(Subscription, sub.id)).status == "cancelled"


@pytest.mark.asyncio
async def test_changing_a_tiers_fee_retires_its_plan(db, rzp):
    tier = await _tier(db)
    tier.razorpay_plan_id = "plan_old"
    await db.flush()
    async with _client(db, await _company(db), role="app_admin") as client:
        res = await client.put(f"/api/v1/credits/subscription-tiers/{tier.id}", json={"monthly_fee": 99})
    assert res.status_code == 200
    assert (await db.get(SubscriptionTier, tier.id)).razorpay_plan_id is None


@pytest.mark.asyncio
async def test_the_tier_list_says_which_tiers_are_active(db, rzp):
    """BC-30: is_active was missing, so the admin page labelled every tier
    'Archived', and archived tiers were never listed for the admin to restore."""
    active, archived = await _tier(db), await _tier(db)
    archived.is_active = False
    await db.flush()
    async with _client(db, await _company(db), role="app_admin") as admin:
        everything = (await admin.get("/api/v1/credits/subscription-tiers",
                                       params={"include_inactive": "true"})).json()
    async with _client(db, await _company(db), role="tenant_admin") as tenant:
        offered = (await tenant.get("/api/v1/credits/subscription-tiers",
                                    params={"include_inactive": "true"})).json()
    by_id = {t["id"]: t for t in everything}
    assert by_id[str(active.id)]["is_active"] is True
    assert by_id[str(archived.id)]["is_active"] is False
    assert str(archived.id) not in {t["id"] for t in offered}
