"""Pricing is read and written by app_admin only, and validated (BC-19, BC-20, BC-21, BC-26).

Before: any signed-in user could read the billing config — the platform's
multiplier and fees, i.e. its markup (BC-26); a partner_admin could write it,
including the global row every tenant inherits (BC-19), and create or edit the
platform-wide subscription tiers; the tier list needed no sign-in at all
(BC-20); and nothing range-checked the fee fractions, so 15 meant 1500% (BC-21).
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from src.auth.dependencies import get_current_user
from src.billing import billing_router, credits_router
from src.common.database import get_db

OTHER_ROLES = ["app_user", "partner_admin", "partner_user", "tenant_admin", "tenant_user"]


class _Result:
    def scalars(self):
        return self

    def all(self):
        return []

    def scalar_one_or_none(self):
        return None


class _DB:
    async def execute(self, *_a, **_k):
        return _Result()


def _app(role: str | None) -> FastAPI:
    app = FastAPI()
    app.include_router(billing_router.router)
    app.include_router(credits_router.router)
    if role is not None:
        async def _user():
            return SimpleNamespace(id=uuid.uuid4(), role=role, company_id=uuid.uuid4())
        app.dependency_overrides[get_current_user] = _user

    async def _db():
        yield _DB()
    app.dependency_overrides[get_db] = _db
    return app


@pytest.fixture
def config_calls(monkeypatch):
    calls: list = []
    config = SimpleNamespace(
        id=uuid.uuid4(), company_id=None, config_name="default", multiplier_factor=1.3,
        platform_fee_pct=0.15, sales_partner_fee_pct=0.1, discount_pct=0, default_daily_credits=5,
        base_cost_telephony=None, base_cost_image_gen=None, is_active=True, updated_at=None)

    async def _get(self, company_id):
        calls.append(("get", company_id))
        return config

    async def _update(self, company_id, **fields):
        calls.append(("update", company_id, fields))
        return config

    monkeypatch.setattr(billing_router.BillingService, "get_billing_config", _get)
    monkeypatch.setattr(billing_router.BillingService, "update_billing_config", _update)
    return calls


async def _call(app, method, path, **kw):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        return await c.request(method, path, **kw)


@pytest.mark.asyncio
@pytest.mark.parametrize("role", OTHER_ROLES)
async def test_only_app_admin_reads_the_billing_config(role, config_calls):
    assert (await _call(_app(role), "GET", "/api/v1/billing/config")).status_code == 403
    assert config_calls == []
    assert (await _call(_app("app_admin"), "GET", "/api/v1/billing/config")).status_code == 200


@pytest.mark.asyncio
@pytest.mark.parametrize("role", OTHER_ROLES)
async def test_only_app_admin_writes_the_billing_config(role, config_calls):
    res = await _call(_app(role), "PUT", "/api/v1/billing/config",
                      json={"company_id": None, "multiplier_factor": 0.1})
    assert res.status_code == 403
    assert config_calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [
    {"platform_fee_pct": 15},          # meant 15%, would have been 1500%
    {"sales_partner_fee_pct": -0.1},
    {"discount_pct": 1.5},
    {"multiplier_factor": 0},
    {"default_daily_credits": -1},
    {"base_cost_telephony": -0.01},
])
async def test_out_of_range_pricing_is_refused(body, config_calls):
    res = await _call(_app("app_admin"), "PUT", "/api/v1/billing/config", json=body)
    assert res.status_code == 422
    assert config_calls == []


@pytest.mark.asyncio
async def test_fractions_in_range_are_saved(config_calls):
    res = await _call(_app("app_admin"), "PUT", "/api/v1/billing/config",
                      json={"platform_fee_pct": 0.15, "discount_pct": 0, "multiplier_factor": 1.3})
    assert res.status_code == 200
    from decimal import Decimal
    assert config_calls[0][2] == {"platform_fee_pct": Decimal("0.15"), "discount_pct": Decimal("0"),
                                  "multiplier_factor": Decimal("1.3")}


@pytest.mark.asyncio
async def test_the_tier_list_needs_a_signed_in_user():
    assert (await _call(_app(None), "GET", "/api/v1/credits/subscription-tiers")).status_code == 401
    assert (await _call(_app("tenant_user"), "GET", "/api/v1/credits/subscription-tiers")).status_code == 200


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["partner_admin", "tenant_admin"])
async def test_only_app_admin_writes_tiers(role):
    app = _app(role)
    created = await _call(app, "POST", "/api/v1/credits/subscription-tiers",
                          json={"name": "X", "tier_level": 9, "monthly_fee": 1, "bonus_pct": 0})
    updated = await _call(app, "PUT", f"/api/v1/credits/subscription-tiers/{uuid.uuid4()}",
                          json={"monthly_fee": 1})
    assert (created.status_code, updated.status_code) == (403, 403)


@pytest.mark.asyncio
async def test_a_tier_bonus_is_a_percentage_up_to_100():
    res = await _call(_app("app_admin"), "POST", "/api/v1/credits/subscription-tiers",
                      json={"name": "X", "tier_level": 9, "monthly_fee": 10, "bonus_pct": 150})
    assert res.status_code == 422
