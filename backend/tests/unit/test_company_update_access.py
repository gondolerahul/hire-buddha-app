"""Who may rename a company and who may suspend it (AU-03, AU-15).

``PATCH /companies/{id}`` guarded on company match only: any user — a
``tenant_user`` included — could suspend their own company and lock its admins
out, while a ``partner_admin`` could not touch the tenants it created.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from src.auth import company_router
from src.auth.dependencies import get_current_user
from src.common.database import get_db

APP_CO = uuid.uuid4()
PARTNER_CO = uuid.uuid4()
TENANT_CO = uuid.uuid4()          # a tenant of PARTNER_CO
OTHER_TENANT_CO = uuid.uuid4()    # not PARTNER_CO's


def _companies():
    return {
        APP_CO: SimpleNamespace(id=APP_CO, name="HireBuddha", type="APP", parent_id=None),
        PARTNER_CO: SimpleNamespace(id=PARTNER_CO, name="Partner", type="PARTNER", parent_id=None),
        TENANT_CO: SimpleNamespace(id=TENANT_CO, name="Tenant", type="TENANT", parent_id=PARTNER_CO),
        OTHER_TENANT_CO: SimpleNamespace(id=OTHER_TENANT_CO, name="Other", type="TENANT", parent_id=None),
    }


class _Result:
    def __init__(self, value):
        self._value = value

    def scalars(self):
        return self

    def first(self):
        return self._value


class FakeDB:
    def __init__(self):
        self.companies = _companies()
        for c in self.companies.values():
            c.status, c.logo_url, c.onboarding_status = "active", None, "completed"
        self.commits = 0

    async def execute(self, stmt):
        company_id = next(iter(stmt.compile().params.values()))
        return _Result(self.companies.get(company_id))

    async def commit(self):
        self.commits += 1

    async def refresh(self, obj):
        pass


async def _patch(role: str, own_company, target, body):
    db = FakeDB()
    user = SimpleNamespace(id=uuid.uuid4(), role=role, company_id=own_company)
    app = FastAPI()
    app.include_router(company_router.router)

    async def _user():
        return user

    async def _db():
        yield db

    app.dependency_overrides[get_current_user] = _user
    app.dependency_overrides[get_db] = _db
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client:
        res = await client.patch(f"/companies/{target}", json=body)
    return res, db.companies[target] if target in db.companies else None, db


@pytest.mark.asyncio
@pytest.mark.parametrize("role,company", [
    ("tenant_user", TENANT_CO), ("tenant_admin", TENANT_CO), ("partner_user", PARTNER_CO),
    ("partner_admin", PARTNER_CO), ("app_user", APP_CO), ("app_admin", APP_CO),
])
async def test_no_one_suspends_their_own_company(role, company):
    res, row, db = await _patch(role, company, company, {"status": "suspended"})
    assert res.status_code == 403
    assert row.status == "active" and db.commits == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("role,company", [
    ("tenant_user", TENANT_CO), ("partner_user", PARTNER_CO), ("app_user", APP_CO),
])
async def test_plain_users_cannot_rename_their_company(role, company):
    res, row, _ = await _patch(role, company, company, {"name": "Mine now"})
    assert res.status_code == 403 and row.name != "Mine now"


@pytest.mark.asyncio
@pytest.mark.parametrize("role,company", [("tenant_admin", TENANT_CO), ("partner_admin", PARTNER_CO)])
async def test_admins_rename_their_own_company_and_resend_its_status(role, company):
    res, row, _ = await _patch(role, company, company, {"name": "Renamed", "status": "active"})
    assert res.status_code == 200 and row.name == "Renamed"


@pytest.mark.asyncio
async def test_partner_admin_manages_its_own_tenants():
    res, row, _ = await _patch("partner_admin", PARTNER_CO, TENANT_CO, {"name": "Acme", "status": "suspended"})
    assert res.status_code == 200
    assert row.name == "Acme" and row.status == "suspended"


@pytest.mark.asyncio
async def test_partner_admin_cannot_touch_another_partners_tenant():
    res, row, _ = await _patch("partner_admin", PARTNER_CO, OTHER_TENANT_CO, {"status": "suspended"})
    assert res.status_code == 403 and row.status == "active"


@pytest.mark.asyncio
async def test_tenant_admin_cannot_touch_another_company():
    res, row, _ = await _patch("tenant_admin", TENANT_CO, OTHER_TENANT_CO, {"name": "x"})
    assert res.status_code == 403 and row.name == "Other"


@pytest.mark.asyncio
async def test_app_admin_suspends_any_other_company():
    res, row, _ = await _patch("app_admin", APP_CO, PARTNER_CO, {"status": "suspended"})
    assert res.status_code == 200 and row.status == "suspended"


@pytest.mark.asyncio
async def test_status_must_be_active_or_suspended():
    res, row, _ = await _patch("app_admin", APP_CO, TENANT_CO, {"status": "deleted"})
    assert res.status_code == 422 and row.status == "active"
