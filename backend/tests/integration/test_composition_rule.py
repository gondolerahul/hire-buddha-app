"""The composition rule (R1): a child sits at its parent's level or below, in
its parent's company, with no cycle — checked at authoring (422), at dispatch
over the whole tree (400, every level) and when a child run is created.

Real Postgres, rolled back.
"""
from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import text

pytestmark = pytest.mark.needs_db


async def _company(db) -> uuid.UUID:
    cid = uuid.uuid4()
    await db.execute(
        text("INSERT INTO companies (id, name, type, status, created_at, updated_at) "
             "VALUES (:id, :name, 'TENANT', 'active', now(), now())"),
        {"id": str(cid), "name": f"r1-{cid.hex[:8]}"},
    )
    return cid


async def _row(db, company_id, type_, name=None, **fields):
    """An entity written straight through the ORM — no authoring check."""
    from src.ai.orm.entity import HierarchicalEntity

    entity = HierarchicalEntity(company_id=company_id, type=type_,
                                name=name or f"r1-{type_.lower()}-{uuid.uuid4().hex[:6]}", **fields)
    db.add(entity)
    await db.flush()
    return entity


def _children(*entities) -> dict:
    return {"children": [{"child_id": str(e.id), "child_type": e.type} for e in entities]}


def _plan(*targets) -> dict:
    steps = []
    for i, target in enumerate(targets, start=1):
        key = "entity_id" if not isinstance(target, str) else "entity_name_hint"
        value = str(target.id) if not isinstance(target, str) else target
        steps.append({"step_id": f"step_{i}", "order": i, "name": f"Delegate {i}",
                      "type": "CHILD_ENTITY_INVOCATION",
                      "target": {key: value, "prompt_template": "{{input}}"}})
    return {"static_plan": {"enabled": True, "steps": steps}}


async def _create(db, company_id, type_, **fields):
    from src.ai.schemas.entity import HierarchicalEntityCreate
    from src.ai.service import AIService

    payload = {"name": f"r1-{type_.lower()}-{uuid.uuid4().hex[:6]}", "type": type_, **fields}
    return await AIService(db).create_entity(HierarchicalEntityCreate(**payload), company_id)


# ── Authoring ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_six_levels_compose_downwards(db, test_company_id):
    action = await _create(db, test_company_id, "ACTION")
    skill = await _create(db, test_company_id, "SKILL", hierarchy=_children(action))
    agent = await _create(db, test_company_id, "AGENT", hierarchy=_children(skill))
    process = await _create(db, test_company_id, "PROCESS", planning=_plan(agent))
    loop = await _create(db, test_company_id, "LOOP", hierarchy=_children(process))
    sub_loop = await _create(db, test_company_id, "LOOP", hierarchy=_children(process))
    graph = await _create(db, test_company_id, "GRAPH", hierarchy=_children(loop, sub_loop))
    assert graph.type == "GRAPH"


@pytest.mark.asyncio
@pytest.mark.parametrize("parent_type, child_type", [
    ("AGENT", "PROCESS"), ("SKILL", "AGENT"), ("ACTION", "SKILL"), ("LOOP", "GRAPH"), ("PROCESS", "LOOP"),
])
async def test_a_child_above_its_parents_level_is_refused(db, test_company_id, parent_type, child_type):
    child = await _row(db, test_company_id, child_type)
    with pytest.raises(HTTPException) as by_hierarchy:
        await _create(db, test_company_id, parent_type, hierarchy=_children(child))
    assert by_hierarchy.value.status_code == 422
    with pytest.raises(HTTPException) as by_plan:
        await _create(db, test_company_id, parent_type, planning=_plan(child))
    assert by_plan.value.status_code == 422
    assert child_type in by_plan.value.detail


@pytest.mark.asyncio
async def test_a_parent_below_the_child_is_refused(db, test_company_id):
    agent = await _row(db, test_company_id, "AGENT")
    with pytest.raises(HTTPException) as exc:
        await _create(db, test_company_id, "PROCESS", parent_id=str(agent.id))
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_a_child_from_another_company_is_refused(db, test_company_id):
    foreign = await _row(db, await _company(db), "SKILL")
    with pytest.raises(HTTPException) as exc:
        await _create(db, test_company_id, "AGENT", hierarchy=_children(foreign))
    assert exc.value.status_code == 422
    assert "does not exist in this company" in exc.value.detail


@pytest.mark.asyncio
async def test_a_placeholder_target_is_left_for_dispatch(db, test_company_id):
    """The seed scripts save `__PLACEHOLDER__` targets and patch them later."""
    process = await _create(db, test_company_id, "PROCESS", planning=_plan("__PLACEHOLDER__"))
    assert process.id


@pytest.mark.asyncio
async def test_an_edit_that_closes_a_cycle_is_refused(db, test_company_id):
    from src.ai.schemas.entity import HierarchicalEntityUpdate
    from src.ai.service import AIService

    b = await _create(db, test_company_id, "AGENT")
    a = await _create(db, test_company_id, "AGENT", hierarchy=_children(b))
    with pytest.raises(HTTPException) as by_child:
        await AIService(db).update_entity(b.id, HierarchicalEntityUpdate(hierarchy=_children(a)), test_company_id)
    assert by_child.value.status_code == 422
    assert "descendant of itself" in by_child.value.detail

    with pytest.raises(HTTPException) as by_parent:
        await AIService(db).update_entity(a.id, HierarchicalEntityUpdate(parent_id=b.id), test_company_id)
    assert by_parent.value.status_code == 422

    with pytest.raises(HTTPException) as by_self:
        await AIService(db).update_entity(a.id, HierarchicalEntityUpdate(planning=_plan(a)), test_company_id)
    assert by_self.value.status_code == 422


# ── Dispatch ────────────────────────────────────────────────────────────────

async def _trigger(db, company_id, entity):
    from src.ai.schemas.execution import ExecutionRunCreate
    from src.ai.service import AIService

    return await AIService(db).trigger_execution(
        ExecutionRunCreate(entity_id=entity.id, input_data={"input": "go"}), company_id,
    )


@pytest.mark.asyncio
async def test_dispatch_checks_every_level_not_only_process(db, test_company_id):
    """An AGENT naming a deleted child used to be dispatched: only PROCESS was checked."""
    gone = await _row(db, test_company_id, "SKILL", status="DELETED")
    agent = await _row(db, test_company_id, "AGENT", planning=_plan(gone))
    with pytest.raises(HTTPException) as exc:
        await _trigger(db, test_company_id, agent)
    assert exc.value.status_code == 400
    assert str(gone.id) in exc.value.detail


@pytest.mark.asyncio
async def test_dispatch_walks_the_whole_tree(db, test_company_id):
    """A grandchild above its parent's level, written around the authoring
    check, stops the run before anything is spent."""
    process = await _row(db, test_company_id, "PROCESS")
    skill = await _row(db, test_company_id, "SKILL", hierarchy=_children(process))
    agent = await _row(db, test_company_id, "AGENT", hierarchy=_children(skill))
    root = await _row(db, test_company_id, "PROCESS", planning=_plan(agent))
    with pytest.raises(HTTPException) as exc:
        await _trigger(db, test_company_id, root)
    assert exc.value.status_code == 400
    assert skill.name in exc.value.detail and "PROCESS" in exc.value.detail


@pytest.mark.asyncio
async def test_dispatch_refuses_an_unresolved_step_and_resolves_a_name(db, test_company_id):
    from src.ai.governance.composition import dispatch_violations

    placeholder = await _row(db, test_company_id, "PROCESS", planning=_plan("__PLACEHOLDER__"))
    with pytest.raises(HTTPException) as exc:
        await _trigger(db, test_company_id, placeholder)
    assert exc.value.status_code == 400
    assert "__PLACEHOLDER__" in exc.value.detail

    named = await _row(db, test_company_id, "AGENT", name=f"r1-named-{uuid.uuid4().hex[:6]}")
    by_name = await _row(db, test_company_id, "PROCESS", planning=_plan(named.name))
    assert await dispatch_violations(db, by_name) == []


@pytest.mark.asyncio
async def test_dispatch_finds_a_cycle(db, test_company_id):
    from src.ai.governance.composition import dispatch_violations

    a = await _row(db, test_company_id, "AGENT")
    b = await _row(db, test_company_id, "AGENT", hierarchy=_children(a))
    a.hierarchy = _children(b)
    await db.flush()
    problems = await dispatch_violations(db, a)
    assert any("cycle" in p for p in problems)


@pytest.mark.asyncio
async def test_a_shared_child_is_not_a_cycle(db, test_company_id):
    from src.ai.governance.composition import dispatch_violations

    shared = await _row(db, test_company_id, "SKILL")
    left = await _row(db, test_company_id, "AGENT", hierarchy=_children(shared))
    right = await _row(db, test_company_id, "AGENT", planning=_plan(shared))
    root = await _row(db, test_company_id, "PROCESS", hierarchy=_children(left, right))
    assert await dispatch_violations(db, root) == []


# ── Runtime ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_child_run_above_the_parents_level_is_refused(db, test_company_id):
    """A dynamic plan's children are first seen when the child run is created."""
    from src.ai.core.exceptions import CompositionError
    from src.ai.orm.execution import ExecutionRun
    from src.ai.schemas.planning import PlanStep
    from src.ai.step_executor import StepExecutorService
    from src.ai.usage_service import UsageService

    process = await _row(db, test_company_id, "PROCESS")
    agent = await _row(db, test_company_id, "AGENT")
    run = ExecutionRun(company_id=test_company_id, entity_id=agent.id, input_data={"input": "x"}, status="RUNNING")
    db.add(run)
    await db.flush()

    step = PlanStep.model_validate(_plan(process)["static_plan"]["steps"][0])
    with pytest.raises(CompositionError):
        await StepExecutorService(db, None, test_company_id, UsageService(db)).create_child_run(
            run, agent, step, {"input": "x"},
        )
    children = (await db.execute(
        text("SELECT count(*) FROM execution_runs WHERE parent_run_id = :id"), {"id": run.id},
    )).scalar_one()
    assert children == 0
