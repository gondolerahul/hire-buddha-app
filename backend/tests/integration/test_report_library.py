"""The report library (Phase 15 T9-4…T9-7, T9-9, T9-12). Real Postgres, rolled back.

* Money views: a business sees its own billed amounts in its own currency and
  never cost; a partner sees its customers' billed amounts only; staff see cost.
* Scope: a business sees only itself, a partner only its customers, staff
  everyone or one company.
* Audience: a report is refused outside its workspace, role, staff function
  or partner type; acting staff get the business's reports and not the console's.
* Exports: CSV, XLSX and PDF of the same payload.
* Staff functions open the console's read endpoints of their desk only.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI

from tests.harness.partners import partner, tenant, user

pytestmark = pytest.mark.needs_db
D = Decimal


def _app(db, actor) -> FastAPI:
    from src.auth import dependencies, router as auth_router
    from src.common.database import get_db
    from src.common.tenancy.session import get_control_db
    from src.partners import admin_router
    from src.reports import router as reports_router

    app = FastAPI()
    app.include_router(reports_router.router)
    app.include_router(admin_router.router)

    async def _u():
        return actor

    async def _db():
        yield db

    for dep in (dependencies.get_current_user, auth_router.get_current_user):
        app.dependency_overrides[dep] = _u
    for dep in (get_db, get_control_db):
        app.dependency_overrides[dep] = _db
    return app


async def _get(db, actor, path, **kw):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=_app(db, actor)), base_url="http://t") as c:
        return await c.get(path, **kw)


@pytest_asyncio.fixture(autouse=True)
async def own_sessions(monkeypatch):
    """Sessions of their own (some reports open control sessions) on an engine with no pool: the app's pool
    may hold a connection an earlier test opened on its closed event loop."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    from src.common import database
    from src.common.config import settings

    engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    monkeypatch.setattr(database, "AsyncSessionLocal", async_sessionmaker(engine, expire_on_commit=False))
    monkeypatch.setattr(database, "engine", engine)
    yield
    await engine.dispose()


def _staff(role: str, company_id, functions=()):
    base = user(role, company_id)
    return SimpleNamespace(**vars(base), staff_functions=list(functions))


async def _platform(db):
    from src.auth.platform import platform_company_id
    return await platform_company_id(db)


async def _usage(db, company_id, *, billed_ccy: str, billed_usd: str, cost_usd: str, currency: str = "INR",
                 category: str = "ai_models"):
    from src.billing.billing_models import BillingLine

    db.add(BillingLine(company_id=company_id, period_day=datetime.utcnow().date(), category=category,
                       grouping_type="company", grouping_id=None, currency=currency, cost_usd=D(cost_usd),
                       billed_usd=D(billed_usd), billed_ccy=D(billed_ccy), quantity=D(1), rows=1))
    await db.flush()


def _billed(body) -> Decimal:
    return sum((D(str(r["billed"])) for r in body["rows"]), D(0))


@pytest.mark.asyncio
async def test_a_business_sees_its_own_billed_amounts_in_its_currency_and_no_cost(db):
    mine, other = await tenant(db), await tenant(db)
    await _usage(db, mine, billed_ccy="10000", billed_usd="100", cost_usd="80")
    await _usage(db, other, billed_ccy="5000", billed_usd="50", cost_usd="40")
    res = await _get(db, user("tenant_admin", mine), "/api/v1/reports/R-T02", params={"period": "30d"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["currency"] == "INR" and _billed(body) == D("10000")
    assert not any(c.get("cost") for c in body["columns"]) and "cost_usd" not in res.text


@pytest.mark.asyncio
async def test_staff_see_cost_and_every_company_or_one(db):
    a, b = await tenant(db), await tenant(db)
    await _usage(db, a, billed_ccy="10000", billed_usd="100", cost_usd="80")
    await _usage(db, b, billed_ccy="5000", billed_usd="50", cost_usd="40")
    admin = user("app_admin", await _platform(db))
    one = await _get(db, admin, "/api/v1/reports/R-A02", params={"period": "30d", "company_id": str(a)})
    assert one.status_code == 200, one.text
    assert any(c.get("cost") for c in one.json()["columns"]) or any(t.get("cost") for t in one.json()["tiles"])
    everyone = await _get(db, admin, "/api/v1/reports/R-A02", params={"period": "30d"})
    assert everyone.status_code == 200 and everyone.json() != one.json()


@pytest.mark.asyncio
async def test_a_partner_sees_only_its_customers(db):
    p = await partner(db, "GOLD")
    mine, other = await tenant(db, p), await tenant(db)
    await _usage(db, mine, billed_ccy="10000", billed_usd="100", cost_usd="80")
    await _usage(db, other, billed_ccy="5000", billed_usd="50", cost_usd="40")
    res = await _get(db, user("partner_admin", p), "/api/v1/reports/R-P03", params={"period": "30d"})
    assert res.status_code == 200, res.text
    assert str(other) not in res.text and not any(c.get("cost") for c in res.json()["columns"])
    refused = await _get(db, user("partner_admin", p), "/api/v1/reports/R-P03", params={"company_id": str(other)})
    assert refused.status_code == 403


@pytest.mark.asyncio
async def test_reports_are_refused_outside_their_audience(db):
    t = await tenant(db)
    platform = await _platform(db)
    assert (await _get(db, user("tenant_user", t), "/api/v1/reports/R-T02")).status_code == 403
    assert (await _get(db, user("tenant_admin", t), "/api/v1/reports/R-A01")).status_code == 403
    assert (await _get(db, _staff("app_user", platform, ["sales"]), "/api/v1/reports/R-A02")).status_code == 403
    assert (await _get(db, _staff("app_user", platform, ["finance"]), "/api/v1/reports/R-A02")).status_code == 200
    silver = await partner(db, "SILVER")
    assert (await _get(db, user("partner_admin", silver), "/api/v1/reports/R-P03")).status_code == 403
    catalogue = (await _get(db, user("tenant_user", t), "/api/v1/reports")).json()
    assert catalogue["workspace"] == "business" and "R-T14" in {r["id"] for r in catalogue["reports"]}
    assert "R-T02" not in {r["id"] for r in catalogue["reports"]}


@pytest.mark.asyncio
async def test_acting_staff_get_the_business_reports(db):
    t = await tenant(db)
    await _usage(db, t, billed_ccy="10000", billed_usd="100", cost_usd="80")
    admin = user("app_admin", await _platform(db))
    headers = {"X-Company-Id": str(t)}
    catalogue = (await _get(db, admin, "/api/v1/reports", headers=headers)).json()
    assert catalogue["workspace"] == "business"
    res = await _get(db, admin, "/api/v1/reports/R-T02", params={"period": "30d"}, headers=headers)
    assert res.status_code == 200 and _billed(res.json()) == D("10000") and "cost_usd" not in res.text
    assert (await _get(db, admin, "/api/v1/reports/R-A01", headers=headers)).status_code == 403


@pytest.mark.asyncio
async def test_exports_are_the_same_report(db):
    t = await tenant(db)
    await _usage(db, t, billed_ccy="10000", billed_usd="100", cost_usd="80")
    actor = user("tenant_admin", t)
    csv = await _get(db, actor, "/api/v1/reports/R-T02", params={"period": "30d", "format": "csv"})
    assert csv.status_code == 200 and "Billed" in csv.text and "10000" in csv.text.replace(",", "")
    xlsx = await _get(db, actor, "/api/v1/reports/R-T02", params={"period": "30d", "format": "xlsx"})
    assert xlsx.status_code == 200 and xlsx.content[:2] == b"PK"
    pdf = await _get(db, actor, "/api/v1/reports/R-T02", params={"period": "30d", "format": "pdf"})
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"


@pytest.mark.asyncio
async def test_every_report_answers_for_its_audience(db):
    """Each report of each workspace runs on seeded data (a smoke over the whole library)."""
    from src.reports import framework as fw

    p = await partner(db, "GOLD")
    t = await tenant(db, p)
    await _usage(db, t, billed_ccy="10000", billed_usd="100", cost_usd="80")
    platform = await _platform(db)
    silver = await partner(db, "SILVER")
    await tenant(db, silver, "referred")
    viewers = {"console": user("app_admin", platform), "partner": user("partner_admin", p),
               "business": user("tenant_admin", t)}
    failures = []
    for definition in fw.load().values():
        actor = viewers[definition.workspaces[0]]
        if definition.partner_types and "GOLD" not in definition.partner_types:
            actor = user("partner_admin", silver)
        if definition.roles and str(actor.role) not in definition.roles:
            actor = user(definition.roles[0], actor.company_id)
        res = await _get(db, actor, f"/api/v1/reports/{definition.id}", params={"period": "30d"})
        if res.status_code != 200:
            failures.append((definition.id, res.status_code, res.text[:200]))
    assert failures == []


@pytest.mark.asyncio
async def test_staff_functions_open_their_desks_read_endpoints_only(db):
    platform = await _platform(db)
    sales, finance = _staff("app_user", platform, ["sales"]), _staff("app_user", platform, ["finance"])
    assert (await _get(db, sales, "/api/v1/admin/partners")).status_code == 200
    assert (await _get(db, sales, "/api/v1/admin/partners/statements")).status_code == 403
    assert (await _get(db, finance, "/api/v1/admin/partners/statements")).status_code == 200
    assert (await _get(db, finance, "/api/v1/admin/partners/leads")).status_code == 403
    nobody = _staff("app_user", platform, [])
    assert (await _get(db, nobody, "/api/v1/admin/partners")).status_code == 403
    assert uuid.UUID(str(platform))
