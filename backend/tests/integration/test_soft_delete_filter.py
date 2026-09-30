"""Soft-deleted entities are hidden from every entity query by default (DM-16).

Deletion sets ``status = 'DELETED'`` and keeps the row. Every query had to add
``status != 'DELETED'`` itself, and about forty did not — a deleted agent still
answered calls and could be given a phone number. ``orm/entity.py`` now adds the
filter to every ORM SELECT of entities; relationship loads (a run's entity) and
queries that opt out with ``include_deleted`` still see the row.

Runs against the real Postgres in the suite's rolled-back transaction.
"""
from __future__ import annotations

import uuid
from datetime import datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import joinedload, selectinload

pytestmark = pytest.mark.needs_db


async def _entities(db, company_id):
    from src.ai.orm.entity import HierarchicalEntity
    from src.ai.orm.execution import ExecutionRun

    live = HierarchicalEntity(company_id=company_id, type="AGENT", status="ACTIVE", name=f"live-{uuid.uuid4().hex[:6]}")
    gone = HierarchicalEntity(company_id=company_id, type="AGENT", status="DELETED", name=f"gone-{uuid.uuid4().hex[:6]}")
    db.add_all([live, gone])
    await db.flush()
    run = ExecutionRun(entity_id=gone.id, company_id=company_id, status="COMPLETED", created_at=datetime.utcnow())
    db.add(run)
    await db.flush()
    ids = (live.id, gone.id, run.id)
    db.expunge_all()  # force real SELECTs, not identity-map hits
    return ids


@pytest.mark.asyncio
async def test_entity_queries_hide_deleted_rows(db, test_company_id):
    from src.ai.orm.entity import HierarchicalEntity

    live, gone, _ = await _entities(db, test_company_id)
    rows = (await db.execute(select(HierarchicalEntity).where(HierarchicalEntity.company_id == test_company_id))).scalars().all()
    assert [r.id for r in rows] == [live]
    by_id = await db.execute(select(HierarchicalEntity.id).where(HierarchicalEntity.id == gone))
    assert by_id.scalar_one_or_none() is None
    assert await db.get(HierarchicalEntity, gone) is None


@pytest.mark.asyncio
async def test_opting_out_sees_deleted_rows(db, test_company_id):
    from src.ai.orm.entity import INCLUDE_DELETED, HierarchicalEntity

    _, gone, _ = await _entities(db, test_company_id)
    stmt = select(HierarchicalEntity).where(HierarchicalEntity.id == gone).execution_options(**{INCLUDE_DELETED: True})
    assert (await db.execute(stmt)).scalar_one().status == "DELETED"


@pytest.mark.asyncio
@pytest.mark.parametrize("loader", [joinedload, selectinload])
async def test_a_runs_entity_still_loads_after_deletion(db, test_company_id, loader):
    from src.ai.orm.execution import ExecutionRun

    _, gone, run_id = await _entities(db, test_company_id)
    run = (await db.execute(
        select(ExecutionRun).options(loader(ExecutionRun.entity)).where(ExecutionRun.id == run_id)
    )).unique().scalar_one()
    assert run.entity is not None and run.entity.id == gone


@pytest.mark.asyncio
async def test_a_join_through_entities_is_not_filtered(db, test_company_id):
    from src.ai.orm.entity import HierarchicalEntity
    from src.ai.orm.execution import ExecutionRun

    await _entities(db, test_company_id)
    joined = (select(func.count(ExecutionRun.id))
              .join(HierarchicalEntity, ExecutionRun.entity_id == HierarchicalEntity.id)
              .where(ExecutionRun.company_id == test_company_id))
    assert (await db.execute(joined)).scalar_one() == 1


@pytest.mark.asyncio
async def test_selecting_entity_columns_is_filtered_unless_opted_out(db, test_company_id):
    from src.ai.orm.entity import INCLUDE_DELETED, HierarchicalEntity
    from src.ai.orm.execution import ExecutionRun

    await _entities(db, test_company_id)
    history = (select(ExecutionRun.id, HierarchicalEntity.name)
               .join(HierarchicalEntity, ExecutionRun.entity_id == HierarchicalEntity.id)
               .where(ExecutionRun.company_id == test_company_id))
    assert (await db.execute(history)).all() == []
    assert len((await db.execute(history.execution_options(**{INCLUDE_DELETED: True}))).all()) == 1


@pytest.mark.asyncio
async def test_run_history_reports_keep_deleted_agents(db, test_company_id):
    from src.ai.reports_service import ReportsService

    _, gone, _ = await _entities(db, test_company_id)
    rates = await ReportsService(db).get_agent_error_rates(test_company_id)
    assert [a["entity_id"] for a in rates["agents"]] == [str(gone)]
