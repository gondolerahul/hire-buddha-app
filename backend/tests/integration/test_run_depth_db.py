"""A child run past max_recursion_depth is refused (EP-06, EP-28).

The setting was a sentence in a prompt and nothing counted depth. Real
Postgres, rolled back.
"""
from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.needs_db

MIGRATION = Path(__file__).resolve().parents[2] / "migrations" / "versions" / "ep06_run_depth.py"


async def _entity(db, company_id, type_, limit=None):
    from src.ai.orm.entity import HierarchicalEntity

    entity = HierarchicalEntity(company_id=company_id, type=type_, name=f"ep06-{uuid.uuid4().hex[:6]}",
                                governance=None if limit is None else {"max_recursion_depth": limit})
    db.add(entity)
    await db.flush()
    return entity


def _step(child):
    from src.ai.schemas.planning import PlanStep

    return PlanStep.model_validate({"step_id": "s1", "name": "Delegate", "type": "CHILD_ENTITY_INVOCATION",
                                    "target": {"entity_id": str(child.id), "prompt_template": "{{input}}"}})


async def _children_of(db, run_id):
    return (await db.execute(
        text("SELECT count(*) FROM execution_runs WHERE parent_run_id = :id"), {"id": run_id},
    )).scalar_one()


@pytest.mark.asyncio
async def test_children_count_depth_and_stop_at_the_limit(db, test_company_id):
    from src.ai.core.exceptions import CompositionError
    from src.ai.orm.execution import ExecutionRun
    from src.ai.step_executor import StepExecutorService
    from src.ai.usage_service import UsageService

    root_entity = await _entity(db, test_company_id, "PROCESS", limit=1)
    agent = await _entity(db, test_company_id, "AGENT")
    skill = await _entity(db, test_company_id, "SKILL")
    root = ExecutionRun(company_id=test_company_id, entity_id=root_entity.id, input_data={"input": "x"},
                        status="RUNNING")
    db.add(root)
    await db.flush()
    service = StepExecutorService(db, None, test_company_id, UsageService(db))

    child = await service.create_child_run(root, root_entity, _step(agent), {"input": "x"})
    assert (child.depth, child.max_depth) == (1, 1)

    with pytest.raises(CompositionError, match="max_recursion_depth"):
        await service.create_child_run(child, agent, _step(skill), {"input": "x"})
    assert await _children_of(db, child.id) == 0


@pytest.mark.asyncio
async def test_a_recurse_child_counts_against_the_limit(db, test_company_id):
    from src.ai.core.exceptions import CompositionError
    from src.ai.memory.cortex_service import _host_child_run_factory
    from src.ai.orm.execution import ExecutionRun

    entity = await _entity(db, test_company_id, "AGENT", limit=1)
    run = ExecutionRun(company_id=test_company_id, entity_id=entity.id, input_data={}, status="RUNNING",
                       depth=1, max_depth=1)
    db.add(run)
    await db.flush()
    tree = SimpleNamespace(id=uuid.uuid4(), entity_id=entity.id, user_id=None)
    with pytest.raises(CompositionError):
        await _host_child_run_factory(db, test_company_id, tree=tree, node_id=uuid.uuid4(), task="t",
                                      task_node_id=uuid.uuid4(), result_slot="r", execution_run_id=run.id)
    assert await _children_of(db, run.id) == 0


@pytest.mark.asyncio
async def test_the_migration_counts_depth_and_folds_the_builders_setting(db, test_company_id):
    spec = importlib.util.spec_from_file_location("ep06_migration", MIGRATION)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    from src.ai.orm.entity import HierarchicalEntity
    from src.ai.orm.execution import ExecutionRun

    entity = await _entity(db, test_company_id, "PROCESS")
    root = ExecutionRun(company_id=test_company_id, entity_id=entity.id, status="COMPLETED")
    db.add(root)
    await db.flush()
    child = ExecutionRun(company_id=test_company_id, entity_id=entity.id, status="COMPLETED", parent_run_id=root.id)
    db.add(child)
    await db.flush()
    grandchild = ExecutionRun(company_id=test_company_id, entity_id=entity.id, status="COMPLETED",
                              parent_run_id=child.id)
    built = HierarchicalEntity(company_id=test_company_id, type="AGENT", name=f"ep28-{uuid.uuid4().hex[:6]}",
                               governance={"max_recursion_depth": 5,
                                           "execution_limits": {"max_recursion_depth": 2, "max_tool_calls": 9}})
    db.add_all([grandchild, built])
    await db.flush()
    await db.execute(text("UPDATE execution_runs SET depth = 0 WHERE id = ANY(:ids)"),
                     {"ids": [root.id, child.id, grandchild.id]})

    for sql in (migration.DEPTH_BACKFILL_SQL, migration.FOLD_SQL, migration.DROP_LEFTOVER_SQL):
        await db.execute(text(sql))
    depths = dict((await db.execute(text("SELECT id, depth FROM execution_runs WHERE id = ANY(:ids)"),
                                    {"ids": [root.id, child.id, grandchild.id]})).all())
    assert [depths[root.id], depths[child.id], depths[grandchild.id]] == [0, 1, 2]
    governance = (await db.execute(text("SELECT governance FROM hierarchical_entities WHERE id = :id"),
                                   {"id": built.id})).scalar_one()
    assert governance == {"max_recursion_depth": 2, "execution_limits": {"max_tool_calls": 9}}
