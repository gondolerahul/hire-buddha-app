"""Run logs carry their run's company, and it cannot drift (DM-09).

``llm_interaction_logs``, ``tool_interaction_logs`` and ``human_approvals`` had
no tenant column, so a query that forgot to join ``execution_runs`` returned
every company's rows. Each now has ``company_id``, filled from the run when a
writer does not give it, and a ``(run_id, company_id)`` key keeps it equal to
the run's. ``execution_trace_events.company_id`` gets the same key.

Real Postgres, rolled back.
"""
from __future__ import annotations

import uuid
from datetime import datetime

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

pytestmark = pytest.mark.needs_db


async def _company(db):
    from src.auth.models import Company
    c = Company(name=f"dm09-{uuid.uuid4().hex[:6]}", type="TENANT", status="active")
    db.add(c)
    await db.flush()
    return c.id


async def _run(db, company_id):
    from src.ai.orm.entity import HierarchicalEntity
    from src.ai.orm.execution import ExecutionRun

    agent = HierarchicalEntity(company_id=company_id, type="AGENT", status="ACTIVE", name="dm09")
    db.add(agent)
    await db.flush()
    run = ExecutionRun(entity_id=agent.id, company_id=company_id, status="RUNNING", created_at=datetime.utcnow())
    db.add(run)
    await db.flush()
    return run


def _logs(run_id, **kw):
    from src.ai.orm.execution import HumanApproval, LLMInteractionLog, ToolInteractionLog
    return [
        LLMInteractionLog(run_id=run_id, model_provider="p", model_name="m", input_prompt="i",
                          output_response="o", latency_ms=5, **kw),
        ToolInteractionLog(run_id=run_id, tool_id="t", tool_name="t", **kw),
        HumanApproval(run_id=run_id, checkpoint_trigger="x", status="PENDING", **kw),
    ]


@pytest.mark.asyncio
async def test_a_log_written_with_only_run_id_gets_the_runs_company(db):
    company = await _company(db)
    run = await _run(db, company)
    rows = _logs(run.id)
    db.add_all(rows)
    await db.flush()
    assert [r.company_id for r in rows] == [company] * 3


@pytest.mark.asyncio
@pytest.mark.parametrize("which", [0, 1, 2])
async def test_a_log_cannot_name_another_company(db, which):
    mine, theirs = await _company(db), await _company(db)
    run = await _run(db, mine)
    db.add(_logs(run.id, company_id=theirs)[which])
    with pytest.raises(IntegrityError):
        await db.flush()


@pytest.mark.asyncio
async def test_a_trace_event_cannot_name_another_company(db):
    from src.ai.orm.trace import ExecutionTraceEvent

    mine, theirs = await _company(db), await _company(db)
    run = await _run(db, mine)
    ok = ExecutionTraceEvent(run_id=run.id, company_id=mine, span_id=uuid.uuid4(), kind="tool", status="success")
    db.add(ok)
    await db.flush()
    db.add(ExecutionTraceEvent(run_id=run.id, company_id=theirs, span_id=uuid.uuid4(), kind="tool", status="success"))
    with pytest.raises(IntegrityError):
        await db.flush()


@pytest.mark.asyncio
async def test_unjoined_reads_are_scoped(db):
    from src.ai.orm.execution import ExecutionRun, LLMInteractionLog
    from src.ai.reports_service import ReportsService
    from src.ai.service import AIService

    mine, theirs = await _company(db), await _company(db)
    my_run, their_run = await _run(db, mine), await _run(db, theirs)
    db.add_all(_logs(my_run.id) + _logs(their_run.id))
    await db.flush()

    approvals = await AIService(db).get_pending_approvals(mine)
    assert [a.run_id for a in approvals] == [my_run.id]
    llm = await ReportsService(db).get_llm_performance(company_id=mine)
    assert llm["total_calls"] == 1
    tools = await ReportsService(db).get_tool_efficacy(company_id=mine)
    assert sum(t["total_calls"] for t in tools["tools"]) == 1

    db.expunge_all()
    run = (await db.execute(select(ExecutionRun).options(selectinload(ExecutionRun.llm_logs))
                            .where(ExecutionRun.id == my_run.id))).scalar_one()
    assert [log.company_id for log in run.llm_logs] == [mine]
    assert (await db.execute(select(LLMInteractionLog.run_id).where(LLMInteractionLog.company_id == theirs))
            ).scalars().all() == [their_run.id]
