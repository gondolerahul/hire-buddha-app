"""Unit economics per entity version (P5.5, R2 §10).

With runs pinned to versions, a report can say what each version costs and
how often it succeeds — the evidence a skill change needs. Real Postgres,
rolled back.
"""
from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from src.ai.orm import ExecutionRun, HierarchicalEntity
from src.ai.reports_service import ReportsService

pytestmark = pytest.mark.needs_db


@pytest.mark.asyncio
async def test_each_version_has_its_runs_outcomes_and_spend(db):
    from src.auth.models import Company
    c = Company(name=f"p55e-{uuid.uuid4().hex[:6]}", type="TENANT", status="active")
    db.add(c)
    await db.flush()
    ent = HierarchicalEntity(company_id=c.id, type="SKILL", status="ACTIVE", name="measured", goal="v1")
    db.add(ent)
    await db.flush()

    async def run(status, cost, **kw):
        r = ExecutionRun(entity_id=ent.id, company_id=c.id, status=status, input_data={},
                         total_cost_usd=Decimal(cost), total_tokens=100, **kw)
        db.add(r)
        await db.flush()
        return r

    v1 = (await run("COMPLETED", "0.10")).entity_version_id
    await run("FAILED", "0.30")
    ent.goal = "v2"
    await db.flush()
    await run("COMPLETED", "0.05")
    old = await run("COMPLETED", "0.01")
    old.entity_version_id = None                     # a run from before versions
    await db.flush()

    rows = await ReportsService(db).get_version_economics(ent.id)

    assert [(r["version_number"], r["runs"], r["completed"], r["failed"]) for r in rows] == [
        (2, 1, 1, 0), (1, 2, 1, 1), (None, 1, 1, 0)]
    v1_row = rows[1]
    assert v1_row["version_id"] == str(v1)
    assert (v1_row["success_rate"], v1_row["total_cost_usd"]) == (0.5, pytest.approx(0.40))
    assert v1_row["mean_cost_usd"] == pytest.approx(0.20)
