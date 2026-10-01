"""A parent never runs another tenant's entity as its child (EP-01).

``resolve_child_entity_id`` Strategy 4 looked an ``entity_name_hint`` up by name
across every company, and ``create_child_run`` accepted a child UUID from any
company — so a plan naming a child another tenant owns ran that tenant's
entity. Real Postgres, rolled back.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.needs_db


async def _company(db) -> uuid.UUID:
    cid = uuid.uuid4()
    await db.execute(
        text("INSERT INTO companies (id, name, type, status, created_at, updated_at) "
             "VALUES (:id, :name, 'TENANT', 'active', now(), now())"),
        {"id": str(cid), "name": f"ep01-{cid.hex[:8]}"},
    )
    return cid


async def _entity(db, company_id, name, type_="AGENT", planning=None):
    from src.ai.orm.entity import HierarchicalEntity

    entity = HierarchicalEntity(company_id=company_id, type=type_, name=name, planning=planning)
    db.add(entity)
    await db.flush()
    return entity


def _invocation(name_hint=None, entity_id=None) -> dict:
    target = {"prompt_template": "{{input}}"}
    if name_hint:
        target["entity_name_hint"] = name_hint
    if entity_id:
        target["entity_id"] = str(entity_id)
    return {"step_id": "step_1", "name": "Delegate", "type": "CHILD_ENTITY_INVOCATION", "target": target}


@pytest.mark.asyncio
async def test_a_name_hint_resolves_only_inside_the_parents_company(db, test_company_id):
    from src.ai.planning.child_resolver import EntityNotFoundError, resolve_child_entity_id

    other = await _company(db)
    name = f"ep01-writer-{uuid.uuid4().hex[:6]}"
    await _entity(db, other, name)                      # only the other tenant has it
    parent = await _entity(db, test_company_id, "ep01-parent", "PROCESS")
    step = {**_invocation(name_hint=name), "name": "Unmatched step"}

    with pytest.raises(EntityNotFoundError):
        await resolve_child_entity_id(step, parent, db)

    own = await _entity(db, test_company_id, name)      # now the parent's company has one too
    assert await resolve_child_entity_id(step, parent, db) == own.id


@pytest.mark.asyncio
async def test_a_child_run_is_never_created_for_another_companys_entity(db, test_company_id):
    from src.ai.core.exceptions import EntityNotFoundError
    from src.ai.orm.execution import ExecutionRun
    from src.ai.schemas.planning import PlanStep
    from src.ai.step_executor import StepExecutorService
    from src.ai.usage_service import UsageService

    other = await _company(db)
    foreign = await _entity(db, other, f"ep01-foreign-{uuid.uuid4().hex[:6]}")
    parent = await _entity(db, test_company_id, "ep01-parent", "PROCESS")
    run = ExecutionRun(company_id=test_company_id, entity_id=parent.id, input_data={"input": "x"},
                       status="RUNNING")
    db.add(run)
    await db.flush()

    service = StepExecutorService(db, None, test_company_id, UsageService(db))
    step = PlanStep.model_validate(_invocation(entity_id=foreign.id))
    with pytest.raises(EntityNotFoundError):
        await service.create_child_run(run, parent, step, {"input": "x"})

    children = (await db.execute(
        text("SELECT count(*) FROM execution_runs WHERE parent_run_id = :id"), {"id": run.id},
    )).scalar_one()
    assert children == 0
