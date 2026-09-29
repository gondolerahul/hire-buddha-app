"""The costing and billing reports expose raw provider cost — app_admin only (PO-04).

Both routes return BillingEvent rows carrying ``base_cost``; with the platform's
multiplier known, that is the margin. Billing events are recorded under the
tenant company that ran the work, so the app_admin view spans every company
unless a ``company_id`` filter is given.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from src.auth.dependencies import get_current_user
from src.billing import billing_router as billing_router_module
from src.common.database import get_db

APP_COMPANY = uuid.uuid4()
TENANT_COMPANY = uuid.uuid4()

ROLES_DENIED = ["app_user", "partner_admin", "partner_user", "tenant_admin", "tenant_user"]
REPORT_PATHS = ["/api/v1/reports/costing", "/api/v1/reports/billing"]


def _make_app(role: str, calls: list) -> FastAPI:
    app = FastAPI()
    app.include_router(billing_router_module.router)
    company = APP_COMPANY if role.startswith("app_") else TENANT_COMPANY
    user = SimpleNamespace(id=uuid.uuid4(), role=role, company_id=company)

    async def _user():
        return user

    async def _db():
        yield None

    app.dependency_overrides[get_current_user] = _user
    app.dependency_overrides[get_db] = _db
    return app


@pytest.fixture
def calls(monkeypatch):
    recorded: list = []

    async def fake_report(self, company_id=None, period_month=None, grouping_type=None):
        recorded.append({"company_id": company_id, "grouping_type": grouping_type})
        return []

    monkeypatch.setattr(billing_router_module.BillingService, "get_costing_report", fake_report)
    return recorded


async def _get(app: FastAPI, path: str) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        return await client.get(path)


@pytest.mark.asyncio
@pytest.mark.parametrize("path", REPORT_PATHS)
@pytest.mark.parametrize("role", ROLES_DENIED)
async def test_non_app_admin_is_refused(role, path, calls):
    res = await _get(_make_app(role, calls), path)
    assert res.status_code == 403
    assert calls == []  # the query never ran


@pytest.mark.asyncio
@pytest.mark.parametrize("path", REPORT_PATHS)
async def test_app_admin_sees_every_company_by_default(path, calls):
    res = await _get(_make_app("app_admin", calls), path)
    assert res.status_code == 200
    # Not scoped to the APP company — tenant events live under tenant companies.
    assert calls == [{"company_id": None, "grouping_type": None}]


@pytest.mark.asyncio
@pytest.mark.parametrize("path", REPORT_PATHS)
async def test_app_admin_can_filter_to_one_company(path, calls):
    res = await _get(_make_app("app_admin", calls), f"{path}?company_id={TENANT_COMPANY}")
    assert res.status_code == 200
    assert calls == [{"company_id": TENANT_COMPANY, "grouping_type": None}]
