"""Razorpay's server-to-server webhook credits top-ups, once (BC-I5).

Before it existed a payment was credited only if the payer's browser stayed
open long enough to call ``/credits/topup/verify``. The webhook and the
browser callback share ``PaymentService.credit_topup``, so whichever arrives
second credits nothing.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select

from src.auth.dependencies import get_current_user
from src.billing import credits_router, razorpay_webhook
from src.billing.billing_models import CreditWallet, PaymentTransaction
from src.common.database import get_db

pytestmark = pytest.mark.needs_db

KEY_SECRET = "rzp-key-secret"
WEBHOOK_SECRET = "rzp-webhook-secret"


async def _creds(_db):
    return {"key_id": "rzp_test", "key_secret": KEY_SECRET, "webhook_secret": WEBHOOK_SECRET}


def _client(db, monkeypatch, company_id=None) -> httpx.AsyncClient:
    monkeypatch.setattr(razorpay_webhook, "get_razorpay_creds", _creds)
    monkeypatch.setattr(credits_router, "_get_razorpay_creds", _creds)
    app = FastAPI()
    app.include_router(razorpay_webhook.router)
    app.include_router(credits_router.router)

    async def _db():
        yield db

    async def _user():
        return SimpleNamespace(id=uuid.uuid4(), role="tenant_admin", company_id=company_id)

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_current_user] = _user
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


def _event(kind: str, order_id: str, payment_id: str, amount_cents: int, **payment) -> bytes:
    entity = {"id": payment_id, "entity": "payment", "order_id": order_id,
              "amount": amount_cents, "currency": "USD", **payment}
    return json.dumps({"entity": "event", "event": kind,
                       "payload": {"payment": {"entity": entity}}}).encode()


async def _post(client, body: bytes, secret: str = WEBHOOK_SECRET):
    sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return await client.post("/api/v1/credits/razorpay/webhook", content=body,
                             headers={"X-Razorpay-Signature": sig, "Content-Type": "application/json",
                                      "X-Razorpay-Event-Id": uuid.uuid4().hex})


async def _company_and_order(db, amount="25.00"):
    from src.auth.models import Company
    c = Company(name=f"webhook-{uuid.uuid4().hex[:6]}", type="TENANT", status="active")
    db.add(c)
    await db.flush()
    order_id = f"order_{uuid.uuid4().hex[:14]}"
    db.add(PaymentTransaction(company_id=c.id, razorpay_order_id=order_id, amount=Decimal(amount),
                              currency="USD", transaction_type="topup", status="pending"))
    await db.flush()
    return c.id, order_id


async def _balance(db, company_id) -> Decimal:
    w = (await db.execute(select(CreditWallet).where(CreditWallet.company_id == company_id)
                          .execution_options(populate_existing=True))).scalar_one_or_none()
    return Decimal(str(w.wallet_balance)) if w else Decimal("0")


async def _txn(db, order_id) -> PaymentTransaction:
    return (await db.execute(select(PaymentTransaction).where(
        PaymentTransaction.razorpay_order_id == order_id)
        .execution_options(populate_existing=True))).scalar_one()


@pytest.mark.asyncio
async def test_captured_payment_credits_the_order_once(db, monkeypatch):
    company, order = await _company_and_order(db)
    body = _event("payment.captured", order, "pay_w1", 2500)
    async with _client(db, monkeypatch) as client:
        first = await _post(client, body)
        again = await _post(client, body)
    assert first.status_code == 200 and first.json() == {"status": "credited"}
    assert again.json() == {"status": "already_credited"}
    assert await _balance(db, company) == Decimal("25")
    assert (await _txn(db, order)).status == "success"


@pytest.mark.asyncio
async def test_webhook_then_browser_callback_credits_once(db, monkeypatch):
    company, order = await _company_and_order(db)
    async with _client(db, monkeypatch, company) as client:
        await _post(client, _event("payment.captured", order, "pay_w2", 2500))
        sig = hmac.new(KEY_SECRET.encode(), f"{order}|pay_w2".encode(), hashlib.sha256).hexdigest()
        res = await client.post("/api/v1/credits/topup/verify", json={
            "razorpay_order_id": order, "razorpay_payment_id": "pay_w2", "razorpay_signature": sig})
    assert res.json()["credits_added"] == 0.0
    assert await _balance(db, company) == Decimal("25")


@pytest.mark.asyncio
async def test_bad_signature_is_refused_and_credits_nothing(db, monkeypatch):
    company, order = await _company_and_order(db)
    async with _client(db, monkeypatch) as client:
        res = await _post(client, _event("payment.captured", order, "pay_w3", 2500), secret="wrong")
    assert res.status_code == 400
    assert await _balance(db, company) == Decimal("0")


@pytest.mark.asyncio
async def test_no_webhook_secret_is_503(db, monkeypatch):
    async def _no_secret(_db):
        return {"key_id": "rzp_test", "key_secret": KEY_SECRET}

    async with _client(db, monkeypatch) as client:
        monkeypatch.setattr(razorpay_webhook, "get_razorpay_creds", _no_secret)
        res = await _post(client, b"{}")
    assert res.status_code == 503


@pytest.mark.asyncio
async def test_a_payment_for_a_different_amount_is_not_credited(db, monkeypatch):
    company, order = await _company_and_order(db, "25.00")
    async with _client(db, monkeypatch) as client:
        res = await _post(client, _event("payment.captured", order, "pay_w4", 100))
    assert res.json() == {"status": "amount_mismatch"}
    assert await _balance(db, company) == Decimal("0")
    assert (await _txn(db, order)).status == "pending"


@pytest.mark.asyncio
async def test_a_failed_attempt_is_recorded_and_a_later_success_still_credits(db, monkeypatch):
    company, order = await _company_and_order(db)
    async with _client(db, monkeypatch) as client:
        failed = await _post(client, _event("payment.failed", order, "pay_w5", 2500,
                                            error_code="BAD_REQUEST_ERROR",
                                            error_description="Card declined"))
        txn = await _txn(db, order)
        assert failed.json() == {"status": "recorded_failure"}
        assert txn.status == "failed"
        assert txn.transaction_metadata["error_description"] == "Card declined"
        ok = await _post(client, _event("payment.captured", order, "pay_w6", 2500))
    assert ok.json() == {"status": "credited"}
    assert await _balance(db, company) == Decimal("25")


@pytest.mark.asyncio
async def test_payments_that_are_not_top_ups_are_ignored(db, monkeypatch):
    async with _client(db, monkeypatch) as client:
        captured = await _post(client, _event("payment.captured", "order_unknown", "pay_w7", 2500))
        other = await _post(client, json.dumps({"event": "refund.created", "payload": {}}).encode())
    assert captured.json() == {"status": "ignored"}
    assert other.json() == {"status": "ignored"}
