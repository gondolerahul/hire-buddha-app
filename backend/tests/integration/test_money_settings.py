"""Money settings: company → partner → platform → default, explained and audited (Phase 15 T5-1).

Real Postgres, rolled back; the signed-in user is stubbed.
"""
from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select

from src.common.orm_models import import_all_models

import_all_models()

from src.auth.models import Company  # noqa: E402
from src.auth.roles import Role  # noqa: E402
from src.billing.settings_catalogue import resolve, value  # noqa: E402
from src.common.admin_audit import AdminAuditLog  # noqa: E402
from src.common.settings_store import set_setting  # noqa: E402

pytestmark = pytest.mark.needs_db
STAFF = SimpleNamespace(id=uuid.uuid4(), role=Role.APP_ADMIN, company_id=uuid.uuid4())


async def _company(db, kind="TENANT", parent=None):
    c = Company(name=f"settings-{uuid.uuid4().hex[:6]}", type=kind, status="active", parent_id=parent)
    db.add(c)
    await db.flush()
    return c.id


def _app(db, user):
    from src.auth.dependencies import get_current_user
    from src.billing import settings_router
    from src.common.database import get_db

    app = FastAPI()
    app.include_router(settings_router.router)

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


@pytest.mark.asyncio
async def test_the_most_specific_scope_wins_and_says_so(db, monkeypatch):
    from dataclasses import replace

    from src.billing import settings_catalogue as catalogue

    partner = await _company(db, kind="PARTNER")
    tenant = await _company(db, parent=partner)
    key = "wallet.negative_tolerance_usd"
    # No money setting is set per partner yet (partner types come with WS15-8): give this one the scope.
    monkeypatch.setitem(catalogue.CATALOGUE, key, replace(catalogue.CATALOGUE[key], scopes=(
        "platform", "partner", "company")))
    assert (await resolve(db, key, tenant)).source in ("default", "platform")
    await set_setting(db, key, "1", scope="platform", actor=STAFF)
    await set_setting(db, key, "3", scope="partner", scope_id=partner, actor=STAFF)
    assert (await resolve(db, key, tenant)) .value == Decimal("3")
    await set_setting(db, key, "5", scope="company", scope_id=tenant, actor=STAFF)
    resolved = await resolve(db, key, tenant)
    assert (resolved.value, resolved.source, resolved.scope_id) == (Decimal("5"), "company", tenant)
    assert await value(db, key) == Decimal("1")                                # the platform's
    assert await value(db, key, await _company(db)) == Decimal("1")            # a direct tenant


@pytest.mark.asyncio
async def test_staff_set_explain_and_clear_a_setting_and_it_is_audited(db):
    tenant = await _company(db)
    key = "admission.min_balance.AGENT"
    res = await _call(db, STAFF, "PUT", f"/api/v1/admin/billing-settings/{key}",
                      json={"value": "0.25", "scope": "company", "scope_id": str(tenant), "reason": "enterprise"})
    assert res.status_code == 200, res.text
    listed = (await _call(db, STAFF, "GET", "/api/v1/admin/billing-settings",
                          params={"company_id": str(tenant)})).json()["settings"]
    row = next(s for s in listed if s["key"] == key)
    assert (row["value"], row["source"], row["default"]) == ("0.25", "company", "0.05")
    history = (await _call(db, STAFF, "GET", f"/api/v1/admin/billing-settings/{key}/history")).json()
    assert history[0]["action"] == "set" and history[0]["reason"] == "enterprise"
    removed = await _call(db, STAFF, "DELETE", f"/api/v1/admin/billing-settings/{key}",
                          params={"scope": "company", "scope_id": str(tenant)})
    assert removed.json()["removed"] is True
    assert await value(db, key, tenant) == Decimal("0.05")
    actions = (await db.execute(select(AdminAuditLog.action).where(
        AdminAuditLog.object_type == "setting", AdminAuditLog.object_key == key,
        AdminAuditLog.target_company_id == tenant))).scalars().all()
    assert sorted(actions) == ["delete", "set"]


@pytest.mark.asyncio
@pytest.mark.parametrize("body, status", [
    ({"value": -1}, 422),                                                   # out of bounds
    ({"value": 10, "scope": "company"}, 422),                               # a company scope names its company
    ({"value": 10, "scope": "company", "scope_id": str(uuid.uuid4())}, 404),
    ({"value": 10, "scope": "partner", "scope_id": str(uuid.uuid4())}, 422),  # not a partner-scoped setting
    ({"value": 10, "scope": "plan", "scope_id": str(uuid.uuid4())}, 422),   # plans come with T6-1
])
async def test_bad_settings_are_refused(db, body, status):
    res = await _call(db, STAFF, "PUT", "/api/v1/admin/billing-settings/admission.hold_history_runs"
                      if body.get("scope") != "company" else "/api/v1/admin/billing-settings/alerts.low_balance_pct",
                      json=body)
    assert res.status_code == status, res.text


@pytest.mark.asyncio
async def test_only_staff_touch_money_settings(db):
    tenant_admin = SimpleNamespace(id=uuid.uuid4(), role=Role.TENANT_ADMIN, company_id=uuid.uuid4())
    assert (await _call(db, tenant_admin, "GET", "/api/v1/admin/billing-settings")).status_code == 403
    assert (await _call(db, tenant_admin, "PUT", "/api/v1/admin/billing-settings/wallet.topup_min_usd",
                        json={"value": 1})).status_code == 403
    assert (await _call(db, STAFF, "PUT", "/api/v1/admin/billing-settings/not.a.key",
                        json={"value": 1})).status_code == 404
