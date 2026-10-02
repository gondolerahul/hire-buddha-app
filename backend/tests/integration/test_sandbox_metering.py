"""A sandbox call is a priced usage row on its run (P5.5, R2 §10).

Sandbox seconds are billed against the ``sandbox-runtime`` SKU; the SKU came
from a separate seed environments skipped, so sandbox work was free. The
standard registry seed now creates it. Real Postgres, rolled back.
"""
from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from decimal import Decimal

import pytest
from sqlalchemy import select

from src.ai.models import ExecutionRun, HierarchicalEntity
from src.ai.orm.usage import UsageLog
from src.ai.tools.sandbox.metering import meter_sandbox_usage
from src.common.config import settings
from src.config.models import IntegrationRegistry

pytestmark = pytest.mark.needs_db


@pytest.mark.asyncio
async def test_sandbox_seconds_are_charged_to_the_run(db, monkeypatch):
    import src.common.database as database
    from src.auth.models import Company

    @asynccontextmanager
    async def _session():
        yield db
    monkeypatch.setattr(database, "AsyncSessionLocal", _session)

    c = Company(name=f"p55s-{uuid.uuid4().hex[:6]}", type="TENANT", status="active")
    db.add(c)
    await db.flush()
    db.add(IntegrationRegistry(company_id=c.id, provider_name="hirebuddha", model_name="sandbox-runtime",
                               service_sku=settings.SANDBOX_COST_SKU, component_type="sandbox",
                               service_category="SANDBOX", status="active",
                               internal_cost=Decimal("0.0001"), cost_unit="second"))
    ent = HierarchicalEntity(company_id=c.id, type="SKILL", status="ACTIVE", name="scripted")
    db.add(ent)
    await db.flush()
    run = ExecutionRun(entity_id=ent.id, company_id=c.id, status="RUNNING", input_data={})
    db.add(run)
    await db.flush()

    await meter_sandbox_usage({"company_id": str(c.id), "run_id": str(run.id)},
                              duration_ms=2500, runtime_name="subprocess")

    row = (await db.execute(select(UsageLog).where(UsageLog.run_id == run.id))).scalar_one()
    assert row.attribution == "sandbox"
    assert row.calculated_cost == pytest.approx(Decimal("0.00025"))


def test_the_standard_seed_creates_the_sandbox_sku():
    from pathlib import Path
    seed = (Path(__file__).resolve().parents[2] / "db-scripts" / "seed_integration_registry.py").read_text(encoding="utf-8")
    assert "seed_sandbox_sku" in seed
