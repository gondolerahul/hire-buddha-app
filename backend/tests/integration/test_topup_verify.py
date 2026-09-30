"""A top-up is credited with the order's amount, once (BC-01).

Runs ``POST /credits/topup/verify`` against the real Postgres inside the
suite's rolled-back transaction. Before the fix the route credited
``payload.amount`` — whatever the browser sent — and never looked at the
transaction's status, so one valid signature could be replayed indefinitely,
each time for any amount.
"""
from __future__ import annotations

import hashlib
import hmac
import uuid
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select

from src.auth.dependencies import get_current_user
from src.billing import credits_router
from src.billing.billing_models import CreditWallet, PaymentTransaction
from src.common.database import get_db

pytestmark = pytest.mark.needs_db

SECRET = "rzp-test-secret"


def _sig(order_id: str, payment_id: str) -> str:
    return hmac.new(SECRET.encode(), f"{order_id}|{payment_id}".encode(), hashlib.sha256).hexdigest()


async def _company(db) -> uuid.UUID:
    from src.auth.models import Company
    c = Company(name=f"topup-{uuid.uuid4().hex[:6]}", type="TENANT", status="active")
    db.add(c)
    await db.flush()
    return c.id


async def _order(db, company_id, amount="10.00") -> str:
    order_id = f"order_{uuid.uuid4().hex[:14]}"
    db.add(PaymentTransaction(company_id=company_id, razorpay_order_id=order_id,
                              amount=Decimal(amount), currency="USD",
                              transaction_type="topup", status="pending"))
    await db.flush()
    return order_id


def _client(db, company_id, monkeypatch) -> httpx.AsyncClient:
    async def _creds(_db):
        return {"key_id": "rzp_test", "key_secret": SECRET}

    monkeypatch.setattr(credits_router, "_get_razorpay_creds", _creds)
    app = FastAPI()
    app.include_router(credits_router.router)
    user = SimpleNamespace(id=uuid.uuid4(), role="tenant_admin", company_id=company_id)

    async def _user():
        return user

    async def _db():
        yield db

    app.dependency_overrides[get_current_user] = _user
    app.dependency_overrides[get_db] = _db
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


async def _balance(db, company_id) -> Decimal:
    wallet = (await db.execute(
        select(CreditWallet).where(CreditWallet.company_id == company_id)
        .execution_options(populate_existing=True)
    )).scalar_one()
    return Decimal(str(wallet.wallet_balance))


async def _verify(client, order_id, payment_id, amount=10):
    # ``amount`` is what the wallet page used to send; the route now ignores it.
    body = {"razorpay_order_id": order_id, "razorpay_payment_id": payment_id,
            "razorpay_signature": _sig(order_id, payment_id), "amount": amount}
    return await client.post("/api/v1/credits/topup/verify", json=body)


@pytest.mark.asyncio
async def test_credits_the_order_amount_not_the_request_amount(db, monkeypatch):
    company = await _company(db)
    order = await _order(db, company, "10.00")
    async with _client(db, company, monkeypatch) as client:
        res = await _verify(client, order, "pay_1", amount=1000)
    assert res.status_code == 200, res.text
    assert res.json()["credits_added"] == 10.0
    assert await _balance(db, company) == Decimal("10")
    txn = (await db.execute(select(PaymentTransaction).where(
        PaymentTransaction.razorpay_order_id == order))).scalar_one()
    assert txn.status == "success"
    assert Decimal(str(txn.credits_awarded)) == Decimal("10")
    assert txn.razorpay_payment_id == "pay_1"


@pytest.mark.asyncio
async def test_a_replay_credits_nothing(db, monkeypatch):
    company = await _company(db)
    order = await _order(db, company, "10.00")
    async with _client(db, company, monkeypatch) as client:
        first = await _verify(client, order, "pay_2")
        second = await _verify(client, order, "pay_2")
        third = await _verify(client, order, "pay_2")
    assert first.status_code == second.status_code == third.status_code == 200
    assert second.json()["credits_added"] == 0.0
    assert second.json()["message"] == "Payment already credited"
    assert await _balance(db, company) == Decimal("10")


@pytest.mark.asyncio
async def test_bad_signature_is_refused(db, monkeypatch):
    company = await _company(db)
    order = await _order(db, company)
    async with _client(db, company, monkeypatch) as client:
        res = await client.post("/api/v1/credits/topup/verify", json={
            "razorpay_order_id": order, "razorpay_payment_id": "pay_3",
            "razorpay_signature": "0" * 64, "amount": 10})
    assert res.status_code == 400
    txn = (await db.execute(select(PaymentTransaction).where(
        PaymentTransaction.razorpay_order_id == order))).scalar_one()
    assert txn.status == "pending"


@pytest.mark.asyncio
async def test_an_order_that_was_never_created_is_not_credited(db, monkeypatch):
    company = await _company(db)
    async with _client(db, company, monkeypatch) as client:
        res = await _verify(client, "order_made_up", "pay_4")
    assert res.status_code == 404
    wallet = (await db.execute(select(CreditWallet).where(
        CreditWallet.company_id == company))).scalar_one_or_none()
    assert wallet is None or Decimal(str(wallet.wallet_balance)) == 0


@pytest.mark.asyncio
async def test_another_companys_order_is_not_credited_to_the_caller(db, monkeypatch):
    owner = await _company(db)
    caller = await _company(db)
    order = await _order(db, owner, "50.00")
    async with _client(db, caller, monkeypatch) as client:
        res = await _verify(client, order, "pay_5")
    assert res.status_code == 404
    txn = (await db.execute(select(PaymentTransaction).where(
        PaymentTransaction.razorpay_order_id == order))).scalar_one()
    assert txn.status == "pending"


@pytest.mark.asyncio
async def test_an_expired_balance_is_not_revived_by_a_top_up(db, monkeypatch):
    from datetime import datetime, timedelta
    company = await _company(db)
    db.add(CreditWallet(company_id=company, wallet_balance=Decimal("40"),
                        wallet_expires_at=datetime.utcnow() - timedelta(days=1),
                        daily_expires_at=datetime.utcnow() + timedelta(hours=1)))
    await db.flush()
    order = await _order(db, company, "10.00")
    async with _client(db, company, monkeypatch) as client:
        res = await _verify(client, order, "pay_6")
    assert res.status_code == 200
    assert await _balance(db, company) == Decimal("10")
