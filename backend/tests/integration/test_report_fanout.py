"""Reports across tenants add up every tenant database (Phase 14 M2-4).

With split tenancy an app admin's global view (and a partner's tenant health)
used to read only the database the request was in. Now a report's queries run
on each tenant database and the rows are combined: counts and sums add up, and
averages are worked out from the combined sums — equal to what one shared
database gave. Two real tenant databases (``t_devacme01``, ``t_devbeta001``).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy import text

from tests.integration.test_tenant_routing import _drop_entity, _entity, tenants  # noqa: F401 — fixture

pytestmark = [pytest.mark.needs_db]


async def _runs(company_id, name, runs):
    """An agent with runs ``[(status, execution_ms, cost)]``; returns the agent and run ids."""
    from src.ai.orm.execution import ExecutionRun
    from src.common.tenancy.session import tenant_session

    async with tenant_session(company_id) as db:
        agent = await _entity(db, company_id, name)
        ids = []
        for status, ms, cost in runs:
            run = ExecutionRun(entity_id=agent.id, company_id=company_id, status=status,
                               execution_time_ms=ms, total_cost_usd=cost, input_data={},
                               completed_at=datetime.utcnow())  # the KPI view counts finished runs
            db.add(run)
            await db.flush()
            ids.append(run.id)
        await db.commit()
    return agent.id, ids


async def _llm_calls(company_id, run_id, model, latencies):
    from src.ai.orm.execution import LLMInteractionLog, ToolInteractionLog
    from src.common.tenancy.session import tenant_session

    async with tenant_session(company_id) as db:
        for ms in latencies:
            db.add(LLMInteractionLog(run_id=run_id, company_id=company_id, model_provider="test", model_name=model,
                                     input_prompt="p", output_response="r", latency_ms=ms, prompt_tokens=10,
                                     completion_tokens=5, cost_usd=0.5, created_at=datetime.utcnow()))
            db.add(ToolInteractionLog(run_id=run_id, company_id=company_id, tool_id=model, tool_name=model,
                                      success=ms < 300, latency_ms=ms, created_at=datetime.utcnow()))
        await db.commit()


async def _clean(company_id, agent_id, run_ids):
    from src.common.tenancy.session import tenant_session

    async with tenant_session(company_id) as db:
        for table in ("llm_interaction_logs", "tool_interaction_logs"):
            await db.execute(text(f"DELETE FROM {table} WHERE run_id = ANY(:r)"), {"r": run_ids})
        await db.commit()
        await _drop_entity(db, agent_id)


async def test_a_global_view_adds_up_every_tenant_database(tenants):  # noqa: F811
    from src.ai.reports_service import ReportsService
    from src.common.tenancy.session import control_session

    acme, beta = tenants
    scopes = [acme.company_id, beta.company_id]
    tag = uuid.uuid4().hex[:8]
    model = f"fanout-model-{tag}"

    async with control_session() as db:
        before = (await ReportsService(db, scopes=scopes).get_execution_health())["status_breakdown"]
    made = []
    try:
        made.append((acme.company_id, *await _runs(acme.company_id, f"fanout-a-{tag}",
                                                   [("COMPLETED", 100, 1.0), ("COMPLETED", 300, 3.0),
                                                    ("FAILED", 50, 0.5)])))
        made.append((beta.company_id, *await _runs(beta.company_id, f"fanout-b-{tag}",
                                                   [("COMPLETED", 200, 2.0)])))
        await _llm_calls(acme.company_id, made[0][2][0], model, [100, 200])
        await _llm_calls(beta.company_id, made[1][2][0], model, [600])

        async with control_session() as db:
            svc = ReportsService(db, scopes=scopes)
            health = await svc.get_execution_health()
            llm = await svc.get_llm_performance()
            tools = await svc.get_tool_efficacy()

        count = lambda rows, s: next((r["count"] for r in rows if r["status"] == s), 0)  # noqa: E731
        after = health["status_breakdown"]
        assert count(after, "COMPLETED") - count(before, "COMPLETED") == 3  # two from Acme, one from Beta
        assert count(after, "FAILED") - count(before, "FAILED") == 1

        [row] = [m for m in llm["model_breakdown"] if m["model"] == model]
        assert row["calls"] == 3 and row["avg_latency_ms"] == 300.0  # (100 + 200 + 600) / 3, not an average of averages
        assert row["total_prompt_tokens"] == 30 and row["total_cost_usd"] == 1.5
        [tool] = [t for t in tools["tools"] if t["tool_name"] == model]
        assert (tool["total_calls"], tool["success_count"], tool["avg_latency_ms"]) == (3, 2, 300.0)
        assert "tenants_unavailable" not in health
    finally:
        for company_id, agent_id, run_ids in made:
            await _clean(company_id, agent_id, run_ids)


async def test_a_tenant_that_cannot_be_read_is_listed_not_fatal(tenants):  # noqa: F811
    from src.ai.reports_service import ReportsService
    from src.common.tenancy.session import control_session

    acme, _beta = tenants
    nobody = uuid.uuid4()  # no database
    async with control_session() as db:
        report = await ReportsService(db, scopes=[acme.company_id, nobody]).get_execution_health()
    assert report["tenants_unavailable"] == [str(nobody)]
    assert "summary" in report


async def test_a_partner_sees_each_tenant_runs_from_its_own_database(tenants):  # noqa: F811
    from sqlalchemy import func, select

    from src.ai.orm.execution import ExecutionRun
    from src.ai.reports_service import ReportsService
    from src.auth.models import Company
    from src.common.tenancy.session import control_session, tenant_session

    acme, beta = tenants
    tag = uuid.uuid4().hex[:8]
    async with control_session() as db:
        partner = Company(name=f"fanout-partner-{tag}", type="PARTNER", status="active")
        db.add(partner)
        await db.flush()
        partner_id = partner.id
        old_parents = {}
        for t in (acme, beta):
            company = await db.get(Company, t.company_id)
            old_parents[t.company_id] = company.parent_id
            company.parent_id = partner_id
        await db.commit()
    made = []
    try:
        made.append((acme.company_id, *await _runs(acme.company_id, f"fanout-pa-{tag}", [("FAILED", 1, 0.1)])))
        made.append((beta.company_id, *await _runs(beta.company_id, f"fanout-pb-{tag}",
                                                   [("COMPLETED", 1, 0.1), ("COMPLETED", 1, 0.1)])))
        async with control_session() as db:
            scores = {s["company_id"]: s for s in
                      (await ReportsService(db).get_tenant_health_scores(partner_company_id=partner_id))["tenants"]}
        for t in (acme, beta):  # what each tenant's own database holds for the last 30 days
            async with tenant_session(t.company_id) as db:
                expected = (await db.execute(select(func.count(ExecutionRun.id)).where(
                    ExecutionRun.company_id == t.company_id,
                    ExecutionRun.created_at >= datetime.utcnow() - timedelta(days=30)))).scalar()
            assert scores[str(t.company_id)]["total_runs_30d"] == expected >= 1
        assert scores[str(beta.company_id)]["completed_runs"] >= 2
        assert scores[str(acme.company_id)]["failed_runs"] >= 1
    finally:
        for company_id, agent_id, run_ids in made:
            await _clean(company_id, agent_id, run_ids)
        async with control_session() as db:
            for company_id, parent in old_parents.items():
                (await db.get(Company, company_id)).parent_id = parent
            await db.flush()  # before the partner goes: they still point at it
            await db.execute(text("DELETE FROM companies WHERE id = :p"), {"p": partner_id})
            await db.commit()


async def test_the_kpi_dashboard_adds_up_every_tenant_database(tenants, monkeypatch):  # noqa: F811
    from types import SimpleNamespace

    from src.ai.api import admin
    from src.common.tenancy.session import control_session, tenant_session

    acme, beta = tenants
    monkeypatch.setattr(admin, "tenant_scopes", _scopes([acme.company_id, beta.company_id]))
    tag = uuid.uuid4().hex[:8]
    made = []
    try:
        made.append((acme.company_id, *await _runs(acme.company_id, f"kpi-a-{tag}", [("COMPLETED", 1, 0.1)])))
        made.append((beta.company_id, *await _runs(beta.company_id, f"kpi-b-{tag}",
                                                   [("COMPLETED", 1, 0.1), ("FAILED", 1, 0.1)])))
        for t in tenants:
            async with tenant_session(t.company_id) as db:
                await db.execute(text("REFRESH MATERIALIZED VIEW kpi_daily_rollup"))
                await db.commit()
        staff = SimpleNamespace(role="app_admin", company_id=acme.company_id)
        async with control_session() as db:
            every = await admin.kpi_runs(since="7d", company_id=None, db=db, user=staff)
            each = [await admin.kpi_runs(since="7d", company_id=t.company_id, db=db, user=staff) for t in tenants]
        totals = lambda days: {k: sum(d[k] for d in days) for k in ("runs_total", "runs_completed", "runs_failed")}  # noqa: E731
        both = totals(each[0] + each[1])
        assert totals(every) == both and both["runs_total"] >= 3
    finally:
        for company_id, agent_id, run_ids in made:
            await _clean(company_id, agent_id, run_ids)


def _scopes(ids):
    async def scopes():
        return list(ids)
    return scopes
