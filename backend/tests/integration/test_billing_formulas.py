"""Phase 15 WS15-3: versioned formulas, rating at write, billing lines, the shadow comparison.

* T3-2 the price formula is a version in ``billing_formulas`` (company → platform
  → identity); ``spf`` folds into ``pf``; the cost overrides became registry rows.
* T3-3 every usage row carries its billed amount, formula and category; a run is
  rated with one formula version; Σ billed = TB(Σ cost).
* T3-4 a settlement adds billing lines per category, in the company's currency.
* T3-7 each settlement is priced both ways; they agree.

Real Postgres at the control head (rolled back).
"""
from __future__ import annotations

import importlib.util
import random
import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select, text

import src.main  # noqa: F401  (every model mapped)
from src.ai.orm.usage import UsageLog
from src.auth.dependencies import get_current_user
from src.billing import billing_router, shadow_router
from src.billing.billing_models import BillingFormula, BillingLine, BillingShadowDiff
from src.billing.formulas import IDENTITY, Formula, forget_run_formulas, formula_for, formula_for_run, set_formula
from src.billing.units import Dimension
from src.common.database import get_db

pytestmark = pytest.mark.needs_db

STAFF = SimpleNamespace(id=uuid.uuid4(), role="app_admin", company_id=None)


@pytest.fixture(autouse=True)
def _fresh_formulas():
    forget_run_formulas()
    yield
    forget_run_formulas()


@pytest.fixture
async def no_platform_formula(db):
    """Start from the identity: hide any platform formula this database holds (rolled back)."""
    await db.execute(text("UPDATE billing_formulas SET effective_from = now() + interval '100 years' "
                          "WHERE scope = 'platform'"))
    await db.flush()


def _client(db, routers, role="app_admin") -> httpx.AsyncClient:
    app = FastAPI()
    for r in routers:
        app.include_router(r.router)
    user = SimpleNamespace(id=uuid.uuid4(), role=role, company_id=uuid.uuid4())

    async def _user():
        return user

    async def _db():
        yield db

    app.dependency_overrides[get_current_user] = _user
    app.dependency_overrides[get_db] = _db
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


# ── T3-2 formulas ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_resolution_company_then_platform_then_identity(db, test_company_id, no_platform_formula):
    assert await formula_for(db, test_company_id) == IDENTITY
    await set_formula(db, scope="platform", scope_id=None, mf=Decimal("1.5"), pf=Decimal("0.2"), d=Decimal("0"),
                      actor=STAFF, reason="launch")
    assert (await formula_for(db, test_company_id)).mf == Decimal("1.5")
    await set_formula(db, scope="company", scope_id=test_company_id, mf=Decimal("2"), pf=Decimal(0), d=Decimal("0.1"),
                      actor=STAFF, reason="enterprise deal")
    company = await formula_for(db, test_company_id)
    assert (company.mf, company.scope) == (Decimal(2), "company")
    assert company.rate(Decimal("1.234567")) == Decimal("2.2222206")
    # Ending the company's override puts it back on the platform's formula.
    await set_formula(db, scope="company", scope_id=test_company_id, mf=Decimal(2), pf=Decimal(0), d=Decimal("0.1"),
                      actor=STAFF, active=False, reason="deal ended")
    assert (await formula_for(db, test_company_id)).mf == Decimal("1.5")
    # A version in the future is not in effect yet.
    await set_formula(db, scope="platform", scope_id=None, mf=Decimal(3), pf=Decimal(0), d=Decimal(0), actor=STAFF,
                      effective_from=datetime.utcnow() + timedelta(days=1))
    assert (await formula_for(db, test_company_id)).mf == Decimal("1.5")
    audit = (await db.execute(text("SELECT count(*) FROM admin_audit_log WHERE object_type = 'billing_formula' "
                                   "AND (target_company_id = :c OR object_key = 'platform')"),
                              {"c": str(test_company_id)})).scalar()
    assert audit >= 4


@pytest.mark.asyncio
async def test_the_config_api_writes_versions_and_refuses_retired_fields(db, no_platform_formula):
    async with _client(db, [billing_router]) as client:
        saved = await client.put("/api/v1/billing/config", json={"multiplier_factor": 1.2, "platform_fee_pct": 0.1,
                                                                 "reason": "Q4 review"})
        spf = await client.put("/api/v1/billing/config", json={"sales_partner_fee_pct": 0.05})
        zero_spf = await client.put("/api/v1/billing/config", json={"sales_partner_fee_pct": 0, "discount_pct": 0.02})
        override = await client.put("/api/v1/billing/config", json={"base_cost_telephony": 0.01})
        tenant = await (lambda c: c.get("/api/v1/billing/config"))(client)
    assert saved.status_code == 200 and saved.json()["config"]["multiplier_factor"] == 1.2
    assert saved.json()["history"][0]["reason"] == "Q4 review"
    assert spf.status_code == 422 and "commission" in spf.json()["detail"]
    assert zero_spf.status_code == 200 and zero_spf.json()["config"]["discount_pct"] == 0.02
    assert zero_spf.json()["config"]["multiplier_factor"] == 1.2                  # the other fields carried over
    assert override.status_code == 422 and "registry row" in override.json()["detail"]
    assert tenant.json()["config"]["platform_fee_pct"] == 0.1
    async with _client(db, [billing_router], role="tenant_admin") as client:
        assert (await client.get("/api/v1/billing/config")).status_code == 403


def _migration():
    path = Path(__file__).resolve().parents[2] / "migrations/control/versions/control_0012_billing_formulas.py"
    spec = importlib.util.spec_from_file_location("control_0012", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.asyncio
async def test_the_migration_folds_spf_and_turns_overrides_into_rows(db, test_company_id):
    await db.execute(text("DELETE FROM billing_formulas"))
    await db.execute(text("UPDATE billing_config SET is_active = false"))
    await db.execute(text(
        "INSERT INTO billing_config (id, company_id, config_name, multiplier_factor, platform_fee_pct, "
        "sales_partner_fee_pct, discount_pct, default_daily_credits, base_cost_telephony, base_cost_image_gen, "
        "is_active, created_at, updated_at) VALUES "
        "(gen_random_uuid(), NULL, 'global', 1.5, 0.2, 0.1, 0.05, 1, NULL, NULL, true, now(), now()), "
        "(gen_random_uuid(), :c, 'co', 2, 0, 0, 0.1, 0, 0.012, 0.03, true, now(), now())"),
        {"c": str(test_company_id)})
    await db.flush()
    await db.run_sync(lambda session: _migration().migrate_configs(session.connection()))
    platform = await formula_for(db, uuid.uuid4())
    assert (platform.mf, platform.pf, platform.d) == (Decimal("1.5"), Decimal("0.3"), Decimal("0.05"))
    assert platform.rate(Decimal("0.40")) == Decimal("0.75")                     # 02 §4: unchanged price
    rows = {r.service_sku: r for r in (await db.execute(text(
        "SELECT service_sku, internal_cost, cost_unit_code, service_metadata FROM integration_registry "
        "WHERE company_id = :c"), {"c": str(test_company_id)})).all()}
    assert rows["in-out"].cost_unit_code == "PER_MINUTE" and rows["in-out"].internal_cost == Decimal("0.012")
    assert rows["tata-tele-voice-in-out"].internal_cost == Decimal("0.012")
    assert rows["image_generation"].cost_unit_code == "PER_IMAGE"
    assert rows["image_generation"].service_metadata["migrated_from"] == "billing_config.base_cost_image_gen"


# ── T3-3 rating at write ─────────────────────────────────────────────────────

async def _seed_sku(db, company_id, sku, cost, code, category="LLM"):
    from src.config.models import IntegrationRegistry
    db.add(IntegrationRegistry(company_id=company_id, provider_name="test", service_sku=sku, service_category=category,
                               component_type="x", internal_cost=Decimal(cost), cost_unit_code=code, status="active"))
    await db.flush()


@pytest.mark.asyncio
async def test_a_row_is_rated_when_written_and_a_run_keeps_its_formula(db, test_company_id, no_platform_formula):
    from src.ai.usage_service import UsageService

    await set_formula(db, scope="company", scope_id=test_company_id, mf=Decimal(2), pf=Decimal("0.1"), d=Decimal(0),
                      actor=STAFF)
    await _seed_sku(db, test_company_id, "t33-model-in", "1.00", "PER_1M_TOKENS")
    await _seed_sku(db, test_company_id, "t33-sandbox", "0.00002", "PER_SECOND", category="SANDBOX")
    run_id = uuid.uuid4()
    svc = UsageService(db)
    first = await svc.log_usage(test_company_id, "t33-model-in", 500_000, run_id, attribution="planner",
                                dimension=Dimension.TOKEN)
    assert (first.calculated_cost, first.billed_usd, first.category) == (Decimal("0.5"), Decimal("1.1"), "ai_models")
    assert first.formula_id is not None
    # A new version mid-run does not reprice the run's later rows.
    await set_formula(db, scope="company", scope_id=test_company_id, mf=Decimal(5), pf=Decimal(0), d=Decimal(0),
                      actor=STAFF)
    second = await svc.log_usage(test_company_id, "t33-sandbox", 10, run_id, attribution="sandbox",
                                 dimension=Dimension.SECOND)
    assert second.formula_id == first.formula_id and second.category == "sandbox"
    assert second.billed_usd == Decimal("0.00044")
    other_run = await svc.log_usage(test_company_id, "t33-sandbox", 10, uuid.uuid4(), attribution="sandbox",
                                    dimension=Dimension.SECOND)
    assert other_run.billed_usd == Decimal("0.001")                              # the new version
    unpriced = await svc.log_usage(test_company_id, "t33-nothing-in", 10, run_id, attribution="actor_step",
                                   dimension=Dimension.TOKEN)
    assert (unpriced.billed_usd, unpriced.log_metadata["cost_source"]) == (Decimal(0), "missing")


def test_rating_each_row_bills_what_rating_the_total_bills():
    """Σ TB(cᵢ) = TB(Σ cᵢ) for any formula and any rows (the property T3-3 rests on)."""
    rng = random.Random(15)
    for _ in range(200):
        f = Formula(Decimal(rng.randint(1, 500)) / 100, Decimal(rng.randint(0, 100)) / 100,
                    Decimal(rng.randint(0, 100)) / 100)
        costs = [Decimal(rng.randint(0, 10**9)) / Decimal(10**10) for _ in range(rng.randint(1, 40))]
        assert sum((f.rate(c) for c in costs), Decimal(0)) == f.rate(sum(costs, Decimal(0)))


@pytest.mark.asyncio
async def test_a_media_tool_is_billed_as_media(db, test_company_id, no_platform_formula):
    from src.ai.governance.tool_cost_resolver import ToolCostResolver

    run = SimpleNamespace(id=uuid.uuid4(), company_id=test_company_id)
    await ToolCostResolver(db, test_company_id, run_id=run.id).charge(run=run, tool_id="image_generation", units=2)
    await ToolCostResolver(db, test_company_id, run_id=run.id).charge(run=run, tool_id="calculator")
    await db.flush()
    rows = (await db.execute(select(UsageLog).where(UsageLog.run_id == run.id))).scalars().all()
    assert [(r.category, r.billed_usd) for r in rows] == [("media", Decimal("0.08"))]   # calculator is free: no row


# ── T3-4 lines, T3-7 shadow ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_settlement_adds_lines_in_the_company_currency_and_a_shadow_row(db, test_company_id, no_platform_formula):
    from src.ai.orm import ExecutionRun, HierarchicalEntity
    from src.billing.shadow import record_settlement

    await set_formula(db, scope="company", scope_id=test_company_id, mf=Decimal("1.5"), pf=Decimal("0.2"),
                      d=Decimal(0), actor=STAFF)
    agent = HierarchicalEntity(company_id=test_company_id, type="AGENT", status="ACTIVE", name="t34")
    db.add(agent)
    await db.flush()
    parent = ExecutionRun(entity_id=agent.id, company_id=test_company_id, status="COMPLETED", input_data={})
    db.add(parent)
    await db.flush()
    child = ExecutionRun(entity_id=agent.id, company_id=test_company_id, status="COMPLETED", input_data={},
                         parent_run_id=parent.id, depth=1)
    db.add(child)
    await db.flush()
    formula = await formula_for_run(db, test_company_id, parent.id)
    for run_id, attribution, cost in [(parent.id, "planner", "0.10"), (child.id, "actor_step", "0.30"),
                                      (child.id, "sandbox", "0.02")]:
        row = UsageLog(company_id=test_company_id, run_id=run_id, raw_quantity=Decimal(1),
                       calculated_cost=Decimal(cost), attribution=attribution)
        from src.billing.rating import rate_row
        await rate_row(db, row)
        db.add(row)
    await db.flush()

    total = Decimal("0.42")
    for _ in range(2):                                    # two settlements on one day add up
        await record_settlement(db, db, company_id=test_company_id, run_id=parent.id, subject_type="run",
                                grouping_type="entity", grouping_id=agent.id, v1_cost_usd=total,
                                v1_billed_usd=formula.rate(total))
    lines = {line.category: line for line in (await db.execute(
        select(BillingLine).where(BillingLine.company_id == test_company_id))).scalars().all()}
    assert set(lines) == {"ai_models", "sandbox"}
    ai = lines["ai_models"]
    assert (ai.currency, ai.rows, ai.cost_usd) == ("INR", 4, Decimal("0.8"))
    assert ai.billed_usd == Decimal("1.44") and ai.billed_ccy == Decimal("144")     # 1.8 × 0.8; × 100 INR
    shadows = (await db.execute(select(BillingShadowDiff).where(
        BillingShadowDiff.subject_id == parent.id))).scalars().all()
    assert len(shadows) == 2 and all(s.diff_usd == 0 and s.rows == 3 for s in shadows)
    assert shadows[0].v2_billed_usd == Decimal("0.756")


@pytest.mark.asyncio
async def test_the_shadow_page_and_its_mode(db, test_company_id):
    async with _client(db, [shadow_router]) as client:
        report = (await client.get("/api/v1/admin/billing-shadow", params={"days": 1})).json()
        on = await client.put("/api/v1/admin/billing-shadow/mode", json={"mode": "on"})
        off = await client.put("/api/v1/admin/billing-shadow/mode", json={"mode": "off", "reason": "test"})
    assert report["mode"] == "shadow" and "summary" in report
    assert on.status_code == 422 and off.json() == {"mode": "off"}
    from src.billing.shadow import record_shadow
    assert await record_shadow(db, company_id=test_company_id, subject_type="run", subject_id=None, rows=[],
                               v1_cost_usd=Decimal(1), v1_billed_usd=Decimal(1)) is None   # off: nothing
    async with _client(db, [shadow_router], role="tenant_admin") as client:
        assert (await client.get("/api/v1/admin/billing-shadow")).status_code == 403
