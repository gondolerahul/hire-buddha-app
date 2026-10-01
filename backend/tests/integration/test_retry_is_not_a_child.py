"""A retry or refinement is not a child of the run it repeats (EP-03).

Both wrote the previous run into ``parent_run_id``, the column that means
"dispatched as a child": the credit guard then skipped admission, the breaker
and settlement for them, and the run list hid them. They now point at it
through ``retry_of_run_id``. Real Postgres, rolled back.
"""
from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.needs_db

MIGRATION = Path(__file__).resolve().parents[2] / "migrations" / "versions" / "ep03_retry_of_run_id.py"


async def _entity(db, company_id, type_="AGENT"):
    from src.ai.orm.entity import HierarchicalEntity

    entity = HierarchicalEntity(company_id=company_id, type=type_, name=f"ep03-{uuid.uuid4().hex[:6]}")
    db.add(entity)
    await db.flush()
    return entity


async def _run(db, company_id, entity, status, **fields):
    from src.ai.orm.execution import ExecutionRun

    run = ExecutionRun(company_id=company_id, entity_id=entity.id, status=status,
                       input_data=fields.pop("input_data", {"input": "go"}), **fields)
    db.add(run)
    await db.flush()
    return run


@pytest.fixture
def no_enqueue(monkeypatch):
    queued: list = []

    async def _enqueue(name, *args, **kwargs):
        queued.append((name, args))

    monkeypatch.setattr("src.ai.service.enqueue_job", _enqueue)
    return queued


@pytest.mark.asyncio
async def test_a_retry_points_at_the_run_it_repeats_and_is_a_top_level_run(db, test_company_id, no_enqueue):
    from src.ai.core.credit_guard import CreditGuard
    from src.ai.service import AIService

    entity = await _entity(db, test_company_id)
    failed = await _run(db, test_company_id, entity, "FAILED")
    retry = await AIService(db).retry_execution(failed.id, test_company_id, None)

    assert retry.retry_of_run_id == failed.id
    assert retry.parent_run_id is None
    assert CreditGuard(db, None, retry, entity).top_level        # admitted, metered, settled
    listed = {r.id for r in await AIService(db).get_executions(test_company_id)}
    assert retry.id in listed and failed.id in listed


@pytest.mark.asyncio
async def test_a_refinement_points_at_the_run_it_refines(db, test_company_id, no_enqueue, monkeypatch):
    from src.ai.schemas.execution import ExecutionRefineRequest
    from src.ai.service import AIService

    async def _nothing_to_rerun(self, *args, **kwargs):
        return []

    monkeypatch.setattr(AIService, "_analyze_refinement_feedback", _nothing_to_rerun)
    entity = await _entity(db, test_company_id)
    done = await _run(db, test_company_id, entity, "COMPLETED", result_data={"output": "x", "steps": []})
    refined = await AIService(db).refine_execution(
        done.id, ExecutionRefineRequest(feedback="shorter please"), test_company_id, None,
    )
    assert refined.retry_of_run_id == done.id
    assert refined.parent_run_id is None


@pytest.mark.asyncio
async def test_the_backfill_moves_retries_and_refinements_and_keeps_children(db, test_company_id):
    spec = importlib.util.spec_from_file_location("ep03_migration", MIGRATION)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    entity = await _entity(db, test_company_id, "PROCESS")
    other = await _entity(db, test_company_id)
    root = await _run(db, test_company_id, entity, "FAILED")
    retry = await _run(db, test_company_id, entity, "COMPLETED", parent_run_id=root.id)
    refine = await _run(db, test_company_id, entity, "COMPLETED", parent_run_id=root.id,
                        input_data={"input": "go", "__refinement_feedback__": "shorter"})
    recurse = await _run(db, test_company_id, entity, "COMPLETED", parent_run_id=root.id,
                         input_data={"subtree_root_id": str(uuid.uuid4()), "task": "t"})
    child = await _run(db, test_company_id, other, "COMPLETED", parent_run_id=root.id)

    await db.execute(text(migration.BACKFILL_SQL))
    rows = {
        r.id: (r.parent_run_id, r.retry_of_run_id)
        for r in (await db.execute(text(
            "SELECT id, parent_run_id, retry_of_run_id FROM execution_runs WHERE id = ANY(:ids)"),
            {"ids": [retry.id, refine.id, recurse.id, child.id]})).all()
    }
    assert rows[retry.id] == (None, root.id)
    assert rows[refine.id] == (None, root.id)
    assert rows[recurse.id] == (root.id, None)
    assert rows[child.id] == (root.id, None)
