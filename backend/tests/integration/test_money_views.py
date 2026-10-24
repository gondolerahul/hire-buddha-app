"""The money-view contract (Phase 15 T9-3, REQ-BL-3, Q7; tech design §5.2).

A tenant's or a partner's person never receives a cost field — a provider
cost, a margin — from the platform API: only billed amounts, in their
company's currency. Staff see both. The middleware does it for every JSON
response; these tests call the money endpoints of §5.2 through the real app as
each kind of viewer and walk every key of the answer. Real Postgres, rolled back.
"""
from __future__ import annotations

import json
import uuid
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest
from fastapi import Depends, FastAPI, Request

from src.billing.money_view import MoneyViewMiddleware, billed_only, is_cost_key, remember_viewer

pytestmark = pytest.mark.needs_db


def _cost_keys(payload, path="") -> list:
    found = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            if is_cost_key(key):
                found.append(f"{path}.{key}")
            found += _cost_keys(value, f"{path}.{key}")
    elif isinstance(payload, list):
        for i, value in enumerate(payload):
            found += _cost_keys(value, f"{path}[{i}]")
    return found


def test_the_key_rule():
    for key in ("total_cost_usd", "calculated_cost", "cost_usd", "base_cost", "estimated_cost", "max_cost_usd",
                "margin", "internal_cost", "cost"):
        assert is_cost_key(key), key
    for key in ("billed_amount", "billed_usd", "billed_ccy", "total_billing", "amount", "currency", "tokens"):
        assert not is_cost_key(key), key


def test_billed_only_walks_everything_and_converts_billed_usd():
    rate = SimpleNamespace(currency="INR", units_per_usd=Decimal("100"))
    out = billed_only({"total_cost_usd": 1.0, "billed_amount": 2.5, "runs": [
        {"calculated_cost": "0.1", "billed_usd": "0.25", "name": "a", "steps": [{"estimated_cost": 1}]}]}, rate)
    assert out == {"billed_amount": 250.0, "billed_currency": "INR",
                   "runs": [{"billed_usd": "25.00", "name": "a", "steps": [{}], "billed_currency": "INR"}]}


def _toy(company_id, role):
    app = FastAPI()
    app.add_middleware(MoneyViewMiddleware)

    async def viewer(request: Request):
        remember_viewer(request, SimpleNamespace(role=role, company_id=company_id))

    @app.get("/api/v1/thing", dependencies=[Depends(viewer)])
    async def thing():
        return {"total_cost_usd": 1.5, "billed_amount": 3, "items": [{"cost_usd": 1, "billed_usd": 1}]}

    @app.get("/data/v1/orders", dependencies=[Depends(viewer)])
    async def orders():
        return [{"cost": 12, "name": "a business's own field"}]

    return app


async def _get(app, path):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        return await c.get(path)


@pytest.mark.asyncio
async def test_the_middleware_shows_tenants_billed_only_and_staff_everything(monkeypatch):
    company_id = uuid.uuid4()

    async def rate(viewer_company):
        assert viewer_company == company_id
        return SimpleNamespace(currency="USD", units_per_usd=Decimal("1"))

    monkeypatch.setattr("src.billing.money_view.viewer_rate", rate)
    tenant = await _get(_toy(company_id, "tenant_admin"), "/api/v1/thing")
    assert tenant.json() == {"billed_amount": 3.0, "billed_currency": "USD",
                             "items": [{"billed_usd": 1.0, "billed_currency": "USD"}]}
    assert int(tenant.headers["content-length"]) == len(tenant.content)
    staff = await _get(_toy(company_id, "app_admin"), "/api/v1/thing")
    assert staff.json()["total_cost_usd"] == 1.5
    business_data = await _get(_toy(company_id, "tenant_user"), "/data/v1/orders")
    assert business_data.json() == [{"cost": 12, "name": "a business's own field"}]


@pytest.mark.asyncio
async def test_the_viewers_currency_is_its_companys():
    """The middleware reads the viewer's company in its own session: a committed company, removed after."""
    from sqlalchemy import delete

    from src.auth.models import Company
    from src.billing import money_view
    from src.common.tenancy.session import control_session

    company_id = uuid.uuid4()
    async with control_session() as db:
        db.add(Company(id=company_id, name=f"mv-{company_id.hex[:6]}", type="TENANT", status="active",
                       billing_currency="USD"))
        await db.commit()
    try:
        money_view.forget()
        rate = await money_view.viewer_rate(company_id)
        assert rate.currency == "USD" and rate.units_per_usd == 1
    finally:
        money_view.forget()
        async with control_session() as db:
            await db.execute(delete(Company).where(Company.id == company_id))
            await db.commit()


# ── the real endpoints ───────────────────────────────────────────────────────

ENDPOINTS = [
    "/api/v1/ai/executions",
    "/api/v1/ai/executions/{run}",
    "/api/v1/credits/balance",
    "/api/v1/credits/ledger",
    "/api/v1/reports/analytics/usage-breakdown",
    "/api/v1/reports/analytics/personal-tasks",
    "/api/v1/reports/analytics/credit-forecast",
    "/api/v1/reports/analytics/agent-errors",
    "/api/v1/reports/analytics/campaign-analytics",
    "/api/v1/streaming/voice-sessions",
    "/api/v1/campaigns",
]
PARTNER_ENDPOINTS = ["/api/v1/partner/analytics/summary", "/api/v1/partner/tenants",
                     "/api/v1/partner/analytics/revenue", "/api/v1/reports/analytics/tenant-health"]


@pytest.fixture
def real_app(db, monkeypatch):
    from src.auth.dependencies import get_current_user
    from src.common.database import get_db
    from src.main import app

    holder = {}

    async def _user(request: Request):
        remember_viewer(request, holder["user"])
        return holder["user"]

    async def _db():
        yield db

    app.dependency_overrides[get_current_user] = _user
    app.dependency_overrides[get_db] = _db

    async def rate(company_id):
        return SimpleNamespace(currency="INR", units_per_usd=Decimal("100"))

    monkeypatch.setattr("src.billing.money_view.viewer_rate", rate)   # the viewer's company is uncommitted
    yield holder, app
    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(get_db, None)


async def _seed(db):
    from src.ai.orm import ExecutionRun, HierarchicalEntity
    from src.ai.orm.usage import UsageLog
    from src.auth.models import Company
    from tests.harness.wallet import fund

    partner = Company(name=f"mv-p-{uuid.uuid4().hex[:6]}", type="PARTNER", status="active")
    db.add(partner)
    await db.flush()
    tenant = Company(name=f"mv-t-{uuid.uuid4().hex[:6]}", type="TENANT", status="active", parent_id=partner.id)
    db.add(tenant)
    await db.flush()
    await fund(db, tenant.id, "5")
    agent = HierarchicalEntity(company_id=tenant.id, type="AGENT", status="ACTIVE", name="mv agent",
                               governance={"max_cost_usd": 1.0})
    db.add(agent)
    await db.flush()
    run = ExecutionRun(entity_id=agent.id, company_id=tenant.id, status="COMPLETED", input_data={},
                       total_cost_usd=Decimal("0.40"), billed_amount=Decimal("0.60"))
    db.add(run)
    await db.flush()
    db.add(UsageLog(company_id=tenant.id, run_id=run.id, raw_quantity=Decimal(1), calculated_cost=Decimal("0.40"),
                    billed_usd=Decimal("0.60"), category="ai_models", attribution="actor_step"))
    await db.flush()
    return SimpleNamespace(partner=partner.id, tenant=tenant.id, run=run.id, agent=agent.id)


async def _walk(app, path):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        res = await c.get(path)
    assert res.status_code == 200, (path, res.status_code, res.text[:300])
    return res, json.loads(res.content or b"null")


@pytest.mark.asyncio
async def test_a_tenants_people_get_no_cost_field_from_the_money_endpoints(db, real_app):
    from src.auth.roles import Role
    holder, app = real_app
    seed = await _seed(db)
    for role in (Role.TENANT_ADMIN, Role.TENANT_USER):
        holder["user"] = SimpleNamespace(id=uuid.uuid4(), role=role, company_id=seed.tenant,
                                         email="mv@example.com", company=None, is_active=True)
        for path in ENDPOINTS:
            res, body = await _walk(app, path.format(run=seed.run))
            assert _cost_keys(body) == [], (role, path)
    _, run = await _walk(app, f"/api/v1/ai/executions/{seed.run}")
    assert run["billed_amount"] == pytest.approx(60.0) and run["billed_currency"] == "INR"
    _, entity = await _walk(app, f"/api/v1/ai/entities/{seed.agent}")
    assert "max_cost_usd" not in entity["governance"] and entity["governance"]["max_bill"] is not None


@pytest.mark.asyncio
async def test_a_partners_people_get_no_cost_field(db, real_app):
    from src.auth.roles import Role
    holder, app = real_app
    seed = await _seed(db)
    holder["user"] = SimpleNamespace(id=uuid.uuid4(), role=Role.PARTNER_ADMIN, company_id=seed.partner,
                                     email="mv-p@example.com", company=None, is_active=True)
    for path in PARTNER_ENDPOINTS:
        res, body = await _walk(app, path)
        assert _cost_keys(body) == [], path


@pytest.mark.asyncio
async def test_staff_still_see_cost(db, real_app):
    from src.auth.roles import Role
    holder, app = real_app
    seed = await _seed(db)
    holder["user"] = SimpleNamespace(id=uuid.uuid4(), role=Role.APP_ADMIN, company_id=seed.tenant,
                                     email="mv-s@example.com", company=None, is_active=True)
    _, run = await _walk(app, f"/api/v1/ai/executions/{seed.run}")
    assert run["total_cost_usd"] == pytest.approx(0.40) and run["billed_amount"] == pytest.approx(0.60)
