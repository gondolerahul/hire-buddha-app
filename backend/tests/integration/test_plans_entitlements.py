"""Plans and entitlements (Phase 15 T6-1, T6-2; tech design §10.2, §12.1). Real Postgres, rolled back.

* Plans are versioned: a price, bonus or name change is a new version; the
  level and sort are not. Pay-as-you-go (level 0) has no fee and cannot be
  archived; it is the plan of every company without a live subscription.
* A company's entitlement is its override, else its plan's, else the
  catalogue's default (everything on at launch); staff and the platform
  company are never locked. A locked feature is a 403 ``feature_locked``.
* The impact of a change — companies that would lose a feature or get a lower
  limit — is shown before it is saved.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest
from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy import select

from src.auth.models import Company
from src.auth.roles import Role
from src.billing import features, plans
from src.billing.billing_models import (
    CompanyEntitlementOverride, Plan, PlanEntitlement, PlanVersion, Subscription,
)

pytestmark = pytest.mark.needs_db


@pytest.fixture(autouse=True)
def _fresh_caches():
    features.forget()
    plans.forget()
    yield
    features.forget()
    plans.forget()


def _user(role, company_id=None):
    return SimpleNamespace(id=uuid.uuid4(), role=Role(role), company_id=company_id or uuid.uuid4())


def _app(db, user) -> FastAPI:
    from src.auth import dependencies, router as auth_router
    from src.billing import plans_router
    from src.common.database import get_db
    from src.common.tenancy.session import get_control_db

    app = FastAPI()
    app.include_router(plans_router.router)

    @app.get("/gated")
    async def gated(_=Depends(features.require_feature("feature.voice.outbound_campaigns"))):
        return {"ok": True}

    async def _u():
        return user

    async def _db():
        yield db

    for dep in (dependencies.get_current_user, auth_router.get_current_user):
        app.dependency_overrides[dep] = _u
    for dep in (get_db, get_control_db):
        app.dependency_overrides[dep] = _db
    return app


async def _call(db, user, method, path, **kw):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=_app(db, user)), base_url="http://t") as c:
        return await c.request(method, path, **kw)


STAFF = _user("app_admin")


async def _company(db, currency="INR"):
    c = Company(name=f"plans-{uuid.uuid4().hex[:6]}", type="TENANT", status="active", billing_currency=currency,
                country_code="IN" if currency == "INR" else "US")
    db.add(c)
    await db.flush()
    return c.id


async def _plan(db, **kw):
    import random

    taken = set((await db.execute(select(Plan.tier_level))).scalars().all())
    level = kw.pop("tier_level", random.choice([n for n in range(10, 101) if n not in taken]))
    res = await _call(db, STAFF, "POST", "/api/v1/admin/plans", json={
        "code": f"t{level}", "name": f"Test {level}", "tier_level": level, "monthly_fee_usd": "50", **kw})
    assert res.status_code == 201, res.text
    return res.json()


async def _on_plan(db, company_id, plan_id):
    db.add(Subscription(company_id=company_id, plan_id=uuid.UUID(plan_id), plan_tier=1, monthly_fee=Decimal(50),
                        bonus_pct=Decimal(0), status="active"))
    await db.flush()
    plans.forget(company_id)
    features.forget(company_id)


@pytest.mark.asyncio
async def test_the_seeded_plans_start_with_pay_as_you_go(db):
    rows = (await db.execute(select(Plan).order_by(Plan.tier_level))).scalars().all()
    payg = rows[0]
    assert (payg.code, payg.tier_level, payg.monthly_fee_usd) == ("payg", 0, 0)
    assert len(rows) >= 2


@pytest.mark.asyncio
async def test_a_company_without_a_subscription_is_on_pay_as_you_go(db):
    company = await _company(db)
    res = await _call(db, _user("tenant_admin", company), "GET", "/api/v1/me/entitlements")
    assert res.status_code == 200
    body = res.json()
    assert body["plan"]["tier_level"] == 0
    assert all(e["enabled"] for e in body["entitlements"].values())          # everything on at launch


@pytest.mark.asyncio
async def test_the_plans_on_offer_are_priced_in_the_companys_currency(db):
    company = await _company(db)
    created = await _plan(db, currency_overrides={"INR": "4000"}, bonus_pct="10")
    res = await _call(db, _user("tenant_user", company), "GET", "/api/v1/plans")
    assert res.status_code == 200
    body = res.json()
    offer = {p["id"]: p for p in body["plans"]}[created["id"]]
    assert (body["currency"], Decimal(offer["monthly_fee"]), Decimal(offer["tax_rate"])) == ("INR", 4000, 18)
    assert offer["current"] is False and "feature.voice.inbound" in offer["entitlements"]
    assert {f["key"] for f in body["features"]} >= {"feature.phone_numbers", "limit.users"}


@pytest.mark.asyncio
async def test_a_price_change_is_a_new_version_and_a_level_change_is_not(db):
    created = await _plan(db)
    pid = created["id"]
    moved = await _call(db, STAFF, "PUT", f"/api/v1/admin/plans/{pid}", json={"sort": 99})
    assert moved.json()["version"] == 1
    repriced = await _call(db, STAFF, "PUT", f"/api/v1/admin/plans/{pid}",
                           json={"monthly_fee_usd": "60", "reason": "test: new price"})
    assert repriced.json()["version"] == 2
    versions = (await _call(db, STAFF, "GET", f"/api/v1/admin/plans/{pid}/versions")).json()
    assert [(v["version"], Decimal(v["monthly_fee_usd"])) for v in versions] == [(2, 60), (1, 50)]
    assert versions[0]["reason"] == "test: new price"
    rows = (await db.execute(select(PlanVersion).where(PlanVersion.plan_id == uuid.UUID(pid)))).scalars().all()
    assert len(rows) == 2


@pytest.mark.asyncio
async def test_pay_as_you_go_has_no_fee_and_stays(db):
    payg = (await db.execute(select(Plan).where(Plan.tier_level == 0))).scalar_one()
    fee = await _call(db, STAFF, "PUT", f"/api/v1/admin/plans/{payg.id}", json={"monthly_fee_usd": "5"})
    archive = await _call(db, STAFF, "POST", f"/api/v1/admin/plans/{payg.id}/archive")
    assert (fee.status_code, archive.status_code) == (422, 422)


@pytest.mark.asyncio
async def test_a_plans_tolerance_is_a_plan_scope_setting(db):
    created = await _plan(db, negative_tolerance_usd="7.5")
    rows = (await _call(db, STAFF, "GET", "/api/v1/admin/plans")).json()
    mine = {p["id"]: p for p in rows}[created["id"]]
    assert Decimal(mine["negative_tolerance_usd"]) == Decimal("7.5")


@pytest.mark.asyncio
async def test_the_impact_is_shown_before_a_feature_is_taken_away(db):
    created = await _plan(db)
    await _on_plan(db, await _company(db), created["id"])
    change = {"entitlements": [{"feature_key": "feature.voice.outbound_campaigns", "enabled": False}]}
    impact = (await _call(db, STAFF, "POST", f"/api/v1/admin/plans/{created['id']}/entitlements/impact",
                          json=change)).json()["impact"]
    assert [(i["feature_key"], i["change"], i["companies"]) for i in impact] == [
        ("feature.voice.outbound_campaigns", "loses", 1)]
    assert impact[0]["text"].startswith(f"1 company on {created['name']} would lose")
    assert (await db.execute(select(PlanEntitlement).where(
        PlanEntitlement.plan_id == uuid.UUID(created["id"])))).first() is None       # nothing saved yet


@pytest.mark.asyncio
async def test_a_plan_without_a_feature_locks_it_for_its_companies(db):
    created = await _plan(db)
    company = await _company(db)
    await _on_plan(db, company, created["id"])
    res = await _call(db, STAFF, "PUT", f"/api/v1/admin/plans/{created['id']}/entitlements", json={
        "entitlements": [{"feature_key": "feature.voice.outbound_campaigns", "enabled": False},
                         {"feature_key": "limit.users", "enabled": True, "limit_value": 3}],
        "reason": "test"})
    assert res.status_code == 200, res.text
    refused = await _call(db, _user("tenant_admin", company), "GET", "/gated")
    assert refused.status_code == 403
    assert refused.json()["detail"]["code"] == "feature_locked"
    assert refused.json()["detail"]["feature"] == "feature.voice.outbound_campaigns"
    assert (await _call(db, _user("app_admin", company), "GET", "/gated")).status_code == 200      # staff
    assert await features.limit_of(db, company, "limit.users") == 3
    assert await features.check_limit(db, company, "limit.users", 2) is None
    assert await features.check_limit(db, company, "limit.users", 3)


@pytest.mark.asyncio
async def test_an_override_wins_over_the_plan_until_it_expires(db):
    created = await _plan(db)
    company = await _company(db)
    await _on_plan(db, company, created["id"])
    await _call(db, STAFF, "PUT", f"/api/v1/admin/plans/{created['id']}/entitlements", json={
        "entitlements": [{"feature_key": "feature.voice.outbound_campaigns", "enabled": False}]})
    res = await _call(db, STAFF, "PUT", f"/api/v1/admin/companies/{company}/entitlements/"
                                        "feature.voice.outbound_campaigns",
                      json={"enabled": True, "reason": "test: a pilot"})
    assert res.status_code == 200, res.text
    view = (await _call(db, STAFF, "GET", f"/api/v1/admin/companies/{company}/entitlements")).json()
    assert view["entitlements"]["feature.voice.outbound_campaigns"] == {"enabled": True, "limit": None,
                                                                       "source": "override"}
    row = await db.get(CompanyEntitlementOverride, (company, "feature.voice.outbound_campaigns"))
    row.until = datetime.utcnow() - timedelta(minutes=1)
    await db.flush()
    features.forget(company)
    assert (await features.entitlement(db, company, "feature.voice.outbound_campaigns")).enabled is False


@pytest.mark.asyncio
async def test_a_locked_call_kind_is_refused_at_admission(db):
    from src.voice.call_admission import call_refusal

    created = await _plan(db)
    company = await _company(db)
    await _on_plan(db, company, created["id"])
    await _call(db, STAFF, "PUT", f"/api/v1/admin/plans/{created['id']}/entitlements", json={
        "entitlements": [{"feature_key": "feature.voice.inbound", "enabled": False}]})
    refusal = await call_refusal(db, company, direction="inbound", checkpoint="tata_webhook")
    assert refusal and "plan" in refusal.lower()


@pytest.mark.asyncio
async def test_unknown_features_are_refused(db):
    created = await _plan(db)
    res = await _call(db, STAFF, "PUT", f"/api/v1/admin/plans/{created['id']}/entitlements",
                      json={"entitlements": [{"feature_key": "feature.teleportation", "enabled": True}]})
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_only_staff_manage_plans(db):
    company = await _company(db)
    for role in ("tenant_admin", "partner_admin"):
        res = await _call(db, _user(role, company), "GET", "/api/v1/admin/plans")
        assert res.status_code == 403
    with pytest.raises(HTTPException):
        raise features.feature_locked("feature.records", "x")
