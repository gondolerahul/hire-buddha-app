"""A cancelled run stays cancelled, and a finished run stays finished (DM-17).

Real Postgres, rolled back. Two writers race for a run's status: the user's
cancel and the loop's final write. Both now respect the state machine against
the stored status — the loop re-reads the row (locked) before its final write,
and cancel is a single ``UPDATE … WHERE status NOT IN (terminal)``.
"""
from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import select, update

pytestmark = pytest.mark.needs_db


async def _run(db, company_id, status):
    from src.ai.orm.entity import HierarchicalEntity
    from src.ai.orm.execution import ExecutionRun

    agent = HierarchicalEntity(company_id=company_id, type="AGENT", status="ACTIVE", name="dm17")
    db.add(agent)
    await db.flush()
    run = ExecutionRun(entity_id=agent.id, company_id=company_id, status=status, created_at=datetime.utcnow())
    db.add(run)
    await db.flush()
    return run


async def _stored_status(db, run_id):
    from src.ai.orm.execution import ExecutionRun
    return (await db.execute(select(ExecutionRun.status).where(ExecutionRun.id == run_id))).scalar_one()


@pytest.mark.asyncio
async def test_the_loops_final_write_sees_a_cancel_made_behind_its_back(db, test_company_id):
    from src.ai.core.agent_loop import AgentLoop
    from src.ai.orm.execution import ExecutionRun

    run = await _run(db, test_company_id, "RUNNING")
    # The cancel lands in the database; the loop's instance still says RUNNING.
    await db.execute(update(ExecutionRun).where(ExecutionRun.id == run.id).values(status="CANCELLED")
                     .execution_options(synchronize_session=False))
    assert run.status == "RUNNING"

    fresh = await AgentLoop._reload_run(SimpleNamespace(db=db), run.id, for_update=True)
    assert fresh is run and fresh.status == "CANCELLED"
    fresh.status = "COMPLETED"
    fresh.total_cost_usd = 1
    await db.flush()
    assert await _stored_status(db, run.id) == "CANCELLED"
    assert fresh.total_cost_usd == 1  # the rest of the final write still lands


@pytest.mark.asyncio
async def test_cancel_leaves_a_finished_run_alone(db, test_company_id):
    from src.ai.service import AIService

    run = await _run(db, test_company_id, "COMPLETED")
    out = await AIService(db).cancel_execution(run.id, test_company_id)
    assert out.status == "COMPLETED" and await _stored_status(db, run.id) == "COMPLETED"


@pytest.mark.asyncio
async def test_cancel_stops_a_running_run(db, test_company_id):
    from src.ai.service import AIService

    run = await _run(db, test_company_id, "RUNNING")
    out = await AIService(db).cancel_execution(run.id, test_company_id)
    assert out.status == "CANCELLED" and out.completed_at is not None
    assert await _stored_status(db, run.id) == "CANCELLED"


@pytest.mark.asyncio
async def test_cancel_does_not_overwrite_a_finish_it_did_not_see(db, test_company_id):
    """The run finished in the database after cancel loaded it as RUNNING."""
    from src.ai.orm.execution import ExecutionRun
    from src.ai.service import AIService

    run = await _run(db, test_company_id, "RUNNING")
    await db.execute(update(ExecutionRun).where(ExecutionRun.id == run.id).values(status="COMPLETED")
                     .execution_options(synchronize_session=False))
    out = await AIService(db).cancel_execution(run.id, test_company_id)
    assert out.status == "COMPLETED" and await _stored_status(db, run.id) == "COMPLETED"
