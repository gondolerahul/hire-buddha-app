"""Phase 15 WS15-2: currencies, FX, and a company's currency from its country.

* T2-1 rates are append-only and the current one is the latest already in effect;
  conversions are exact; a gateway amount is the one rounding (K-1).
* T2-2/T2-3 a company's billing currency follows its country when it is made
  (India → INR, elsewhere → USD, O-5); onboarding may change it only while no
  money has moved (FX-1).
* T2-4 only staff change rates, settings and country profiles, each audited;
  a rate cannot start in the past (FX-6).

Real Postgres at the control head (rolled back).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from sqlalchemy import select, text

import src.main  # noqa: F401  (every model mapped)
from src.auth.dependencies import get_current_user
from src.auth.models import Company
from src.billing import currency_router
from src.billing.billing_models import FxRate
from src.billing.currency import (
    USD_RATE, Rate, current_rate, currency_for_country, gateway_minor_units, to_ccy, to_usd,
)
from src.common.database import get_db

pytestmark = pytest.mark.needs_db


def _client(db, role: str = "app_admin", company_id=None, *, signed_in: bool = True) -> httpx.AsyncClient:
    app = FastAPI()
    app.include_router(currency_router.router)
    user = SimpleNamespace(id=uuid.uuid4(), role=role, company_id=company_id or uuid.uuid4())

    async def _user():
        return user

    async def _db():
        yield db

    if signed_in:
        app.dependency_overrides[get_current_user] = _user
    app.dependency_overrides[get_db] = _db
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


async def _audit(db, object_type: str, key: str):
    return (await db.execute(text(
        "SELECT action, old_value, new_value, reason FROM admin_audit_log "
        "WHERE object_type = :t AND object_key = :k ORDER BY at, id"), {"t": object_type, "k": key})).all()


@pytest.mark.asyncio
async def test_the_seeded_rate_and_exact_conversions(db):
    inr = await current_rate(db, "INR")
    assert inr.units_per_usd == 100 and inr.id is not None
    assert await current_rate(db, "usd") == USD_RATE
    assert to_ccy(Decimal("0.0045"), inr) == Decimal("0.45")
    assert to_usd(Decimal("2000"), inr) == 20
    assert to_ccy(Decimal("1") / 3, Rate("INR", Decimal(100))) == Decimal(100) / 3   # no rounding (FX-5)


def test_a_gateway_amount_is_the_one_rounding():
    assert gateway_minor_units(Decimal("1180")) == 118000
    assert gateway_minor_units(Decimal("10.005")) == 1001          # half up
    assert gateway_minor_units(Decimal("0.004")) == 0


@pytest.mark.asyncio
async def test_the_current_rate_is_the_latest_already_in_effect(db):
    now = datetime.utcnow()
    db.add_all([FxRate(currency="INR", units_per_usd=Decimal("84"), effective_from=now - timedelta(minutes=1)),
                FxRate(currency="INR", units_per_usd=Decimal("90"), effective_from=now + timedelta(days=1))])
    await db.flush()
    assert (await current_rate(db, "INR")).units_per_usd == 84
    assert (await current_rate(db, "INR", at=now + timedelta(days=2))).units_per_usd == 90


@pytest.mark.asyncio
async def test_a_country_gives_a_currency(db):
    assert await currency_for_country(db, "IN") == "INR"
    assert await currency_for_country(db, "us") == "USD"     # every other country (O-5)
    assert await currency_for_country(db, None) == "INR"     # the default setting (REQ-BL-2)
    async with _client(db) as client:
        await client.put("/api/v1/admin/currency-settings", json={"default_currency": "USD"})
    assert await currency_for_country(db, None) == "USD"


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["tenant_admin", "partner_admin", "app_user"])
async def test_only_staff_change_money_settings(db, role):
    async with _client(db, role) as client:
        answers = [
            await client.post("/api/v1/admin/fx-rates", json={"currency": "INR", "units_per_usd": 90, "reason": "x x x"}),
            await client.put("/api/v1/admin/currency-settings", json={"display_currency": "USD"}),
            await client.put("/api/v1/admin/country-profiles/US", json={"tax_regime": "NONE"}),
            await client.get("/api/v1/admin/fx-rates"),
        ]
    assert [a.status_code for a in answers] == [403] * 4


@pytest.mark.asyncio
async def test_staff_add_a_rate_with_a_reason_and_it_is_audited(db):
    async with _client(db) as client:
        preview = (await client.get("/api/v1/admin/fx-rates/preview",
                                    params={"currency": "INR", "units_per_usd": 90})).json()
        no_reason = await client.post("/api/v1/admin/fx-rates", json={"currency": "INR", "units_per_usd": 90})
        usd = await client.post("/api/v1/admin/fx-rates", json={"currency": "USD", "units_per_usd": 2, "reason": "nope"})
        past = await client.post("/api/v1/admin/fx-rates", json={
            "currency": "INR", "units_per_usd": 90, "reason": "backdated",
            "effective_from": (datetime.utcnow() - timedelta(days=1)).isoformat()})
        zero = await client.post("/api/v1/admin/fx-rates", json={"currency": "INR", "units_per_usd": 0, "reason": "zero"})
        added = await client.post("/api/v1/admin/fx-rates", json={"currency": "INR", "units_per_usd": 90,
                                                                  "reason": "RBI reference, 23 Oct"})
        history = (await client.get("/api/v1/admin/fx-rates", params={"currency": "INR"})).json()
    assert preview["examples"][1] == {"usd": 20.0, "current": 2000.0, "proposed": 1800.0}
    assert preview["change_pct"] == -10.0
    assert [a.status_code for a in (no_reason, usd, past, zero)] == [422, 422, 422, 422]
    assert added.status_code == 201 and history[0]["units_per_usd"] == 90.0
    assert (await current_rate(db, "INR")).units_per_usd == 90
    audit = await _audit(db, "fx_rate", "INR")
    assert audit[-1].old_value["units_per_usd"] == "100.0000000000"
    assert audit[-1].new_value["units_per_usd"] == "90" and audit[-1].reason == "RBI reference, 23 Oct"


@pytest.mark.asyncio
async def test_country_profiles_and_settings_are_audited(db):
    async with _client(db) as client:
        profile = await client.put("/api/v1/admin/country-profiles/GB",
                                   json={"phone_country_code": "+44", "reason": "dialling"})
        bad = await client.put("/api/v1/admin/country-profiles/GB", json={"billing_currency": "EUR"})
        settings = await client.put("/api/v1/admin/currency-settings", json={"display_currency": "USD"})
    assert profile.status_code == 200 and profile.json()["phone_country_code"] == "+44"
    assert bad.status_code == 404                         # EUR is not a currency here
    assert settings.json() == {"display_currency": "USD", "default_currency": "INR"}
    assert (await _audit(db, "country_profile", "GB"))[-1].new_value == {"phone_country_code": "+44"}
    assert (await _audit(db, "setting", "billing.display_currency"))[-1].old_value == "INR"


@pytest.mark.asyncio
async def test_the_country_list_needs_no_sign_in(db):
    async with _client(db, signed_in=False) as client:
        countries = (await client.get("/api/v1/countries")).json()
    by_code = {c["code"]: c for c in countries}
    assert len(countries) == 249 and by_code["IN"]["currency"] == "INR" and by_code["US"]["currency"] == "USD"


# ── a company's currency follows its country (T2-2, T2-3) ────────────────────

@pytest.mark.asyncio
async def test_self_sign_up_takes_the_country(db):
    from src.auth.schemas import UserCreate
    from src.auth.service import create_user

    user = await create_user(db, UserCreate(email=f"p15-{uuid.uuid4().hex[:8]}@example.com",
                                            password="a-long-enough-password-1", full_name="P15",
                                            country_code="us"))
    company = (await db.execute(select(Company).where(Company.id == user.company_id))).scalar_one()
    assert (company.country_code, company.billing_currency) == ("US", "USD")


@pytest.mark.asyncio
async def test_an_unknown_country_is_refused(db):
    from src.auth.geography import set_geography

    with pytest.raises(HTTPException) as refused:
        await set_geography(db, SimpleNamespace(), "ZZ")
    assert refused.value.status_code == 422


@pytest.mark.asyncio
async def test_onboarding_may_change_the_currency_only_until_money_moves(db, test_company_id):
    from src.ai.orm.usage import UsageLog
    from src.auth.geography import set_geography

    company = (await db.execute(select(Company).where(Company.id == test_company_id))).scalar_one()
    await set_geography(db, company, "AE", initial=False)
    assert company.billing_currency == "USD"
    db.add(UsageLog(company_id=test_company_id, raw_quantity=Decimal(1), calculated_cost=Decimal("0.01"),
                    attribution="tool"))
    await db.flush()
    with pytest.raises(HTTPException) as refused:
        await set_geography(db, company, "IN", initial=False)
    assert refused.value.status_code == 409 and company.billing_currency == "USD"
    await set_geography(db, company, "US", initial=False)          # same currency: allowed
    assert company.country_code == "US"


def test_the_billing_profile_is_validated():
    from pydantic import ValidationError

    from src.auth.schemas import CompanyUpdate

    ok = CompanyUpdate(gstin="29abcde1234f1z5", billing_state="ka", legal_name="Acme Pvt Ltd")
    assert (ok.gstin, ok.billing_state) == ("29ABCDE1234F1Z5", "KA")
    with pytest.raises(ValidationError):
        CompanyUpdate(gstin="not-a-gstin")
    with pytest.raises(ValidationError):
        CompanyUpdate(billing_state="Karnataka")


@pytest.mark.asyncio
async def test_me_says_how_the_company_is_billed(db, test_company_id):
    from src.auth.router import read_users_me

    user = SimpleNamespace(id=uuid.uuid4(), email="me@example.com", full_name="Me", company_id=test_company_id,
                           role="tenant_admin", is_active=True, profile_picture_url=None)
    me = await read_users_me(current_user=user, db=db)
    assert (me.country_code, me.billing_currency) == ("IN", "INR")
