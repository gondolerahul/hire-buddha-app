"""Phase 15 T0-3, T0-4: only a company's admins pay; a top-up is within bounds, in cents.

Before, any user of a company (``tenant_user`` included) could top up,
subscribe or cancel the subscription (B-15), and a top-up had no bounds:
``int(amount * 100)`` silently dropped sub-cent amounts (B-14). Real Postgres
(rolled back); Razorpay is a fake.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from src.auth.dependencies import get_current_user
from src.billing import credits_router
from src.common.database import get_db

pytestmark = pytest.mark.needs_db


class _Orders:
    def __init__(self):
        self.created = []

    def create(self, data):
        self.created.append(data)
        return {"id": f"order_{uuid.uuid4().hex[:14]}"}


@pytest.fixture
def razorpay(monkeypatch):
    orders = _Orders()

    async def _creds(_db):
        return {"key_id": "rzp_test", "key_secret": "s", "webhook_secret": None}

    class _Client:
        def __init__(self, auth):
            self.order = orders

    monkeypatch.setattr(credits_router, "_get_razorpay_creds", _creds)
    monkeypatch.setattr("razorpay.Client", _Client)
    return orders


def _client(db, role: str, company_id) -> httpx.AsyncClient:
    app = FastAPI()
    app.include_router(credits_router.router)
    user = SimpleNamespace(id=uuid.uuid4(), role=role, company_id=company_id)

    async def _user():
        return user

    async def _db():
        yield db

    app.dependency_overrides[get_current_user] = _user
    app.dependency_overrides[get_db] = _db
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["tenant_user", "partner_user", "app_user"])
async def test_a_non_admin_cannot_pay_subscribe_or_cancel(db, test_company_id, razorpay, role):
    async with _client(db, role, test_company_id) as client:
        answers = [
            await client.post("/api/v1/credits/topup", json={"amount": "10"}),
            await client.post("/api/v1/credits/topup/verify", json={
                "razorpay_order_id": "o", "razorpay_payment_id": "p", "razorpay_signature": "s"}),
            await client.post("/api/v1/credits/subscriptions", json={"tier_level": 1}),
            await client.post("/api/v1/credits/subscriptions/verify", json={
                "razorpay_payment_id": "p", "razorpay_subscription_id": "s", "razorpay_signature": "s"}),
            await client.delete(f"/api/v1/credits/subscriptions/{uuid.uuid4()}"),
        ]
        options = (await client.get("/api/v1/credits/topup-options")).json()
        balance = await client.get("/api/v1/credits/balance")
    assert [a.status_code for a in answers] == [403] * 5
    assert razorpay.created == []
    assert options["can_pay"] is False and balance.status_code == 200   # still sees the wallet


@pytest.mark.asyncio
@pytest.mark.parametrize("amount", ["4.99", "10000.01", "10.005", "-5", "0"])
async def test_a_top_up_outside_the_bounds_or_finer_than_a_cent_is_refused(db, test_company_id, razorpay, amount):
    async with _client(db, "tenant_admin", test_company_id) as client:
        response = await client.post("/api/v1/credits/topup", json={"amount": amount})
    assert response.status_code == 422 and razorpay.created == []


@pytest.mark.asyncio
@pytest.mark.parametrize("amount,cents", [("5", 500), ("12.34", 1234), ("10000", 1_000_000)])
async def test_an_admin_tops_up_the_exact_amount(db, test_company_id, razorpay, amount, cents):
    async with _client(db, "tenant_admin", test_company_id) as client:
        response = await client.post("/api/v1/credits/topup", json={"amount": amount})
        options = (await client.get("/api/v1/credits/topup-options")).json()
    assert response.status_code == 200
    assert razorpay.created[-1]["amount"] == cents
    assert options == {"currency": "USD", "min": 5.0, "max": 10000.0, "presets": [10, 25, 50, 100], "can_pay": True}
