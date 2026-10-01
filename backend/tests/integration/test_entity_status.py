"""Entity status is a state machine the runtime honours (EP-09).

Any status could be set to any other, and a DRAFT or ARCHIVED entity executed
happily — a half-built DRAFT agent referenced by a published PROCESS ran.
Real Postgres, rolled back.
"""
from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

pytestmark = pytest.mark.needs_db


async def _row(db, company_id, type_, status="ACTIVE", **fields):
    from src.ai.orm.entity import HierarchicalEntity

    entity = HierarchicalEntity(company_id=company_id, type=type_, status=status,
                                name=f"ep09-{uuid.uuid4().hex[:6]}", **fields)
    db.add(entity)
    await db.flush()
    return entity


def _children(*entities):
    return {"children": [{"child_id": str(e.id)} for e in entities]}


async def _trigger(db, company_id, entity):
    from src.ai.schemas.execution import ExecutionRunCreate
    from src.ai.service import AIService

    return await AIService(db).trigger_execution(
        ExecutionRunCreate(entity_id=entity.id, input_data={"input": "go"}), company_id,
    )


@pytest.mark.asyncio
async def test_status_moves_only_along_the_allowed_transitions(db, test_company_id):
    from src.ai.schemas.entity import HierarchicalEntityUpdate
    from src.ai.service import AIService

    service = AIService(db)
    entity = await _row(db, test_company_id, "AGENT", status="DRAFT")
    for target in ("ACTIVE", "DEPRECATED", "ARCHIVED", "ACTIVE"):
        updated = await service.update_entity(entity.id, HierarchicalEntityUpdate(status=target), test_company_id)
        assert updated.status == target

    with pytest.raises(HTTPException) as deleted:
        await service.update_entity(entity.id, HierarchicalEntityUpdate(status="DELETED"), test_company_id)
    assert deleted.value.status_code == 422 and "DELETE" in deleted.value.detail

    draft = await _row(db, test_company_id, "AGENT", status="DRAFT")
    with pytest.raises(HTTPException) as skipped:
        await service.update_entity(draft.id, HierarchicalEntityUpdate(status="DEPRECATED"), test_company_id)
    assert skipped.value.status_code == 422


@pytest.mark.asyncio
async def test_an_archived_entity_does_not_run(db, test_company_id):
    archived = await _row(db, test_company_id, "AGENT", status="ARCHIVED")
    with pytest.raises(HTTPException) as exc:
        await _trigger(db, test_company_id, archived)
    assert exc.value.status_code == 400 and "ARCHIVED" in exc.value.detail


@pytest.mark.asyncio
async def test_a_draft_runs_inside_a_draft_tree_but_not_under_a_published_parent(db, test_company_id):
    from src.ai.governance.composition import dispatch_violations

    draft_child = await _row(db, test_company_id, "AGENT", status="DRAFT")
    published = await _row(db, test_company_id, "PROCESS", hierarchy=_children(draft_child))
    with pytest.raises(HTTPException) as exc:
        await _trigger(db, test_company_id, published)
    assert exc.value.status_code == 400 and "DRAFT" in exc.value.detail

    draft_tree = await _row(db, test_company_id, "PROCESS", status="DRAFT", hierarchy=_children(draft_child))
    assert await dispatch_violations(db, draft_tree) == []

    archived_child = await _row(db, test_company_id, "SKILL", status="ARCHIVED")
    holder = await _row(db, test_company_id, "AGENT", hierarchy=_children(archived_child))
    assert any("ARCHIVED" in p for p in await dispatch_violations(db, holder))


@pytest.mark.asyncio
async def test_a_child_run_of_an_archived_entity_is_refused(db, test_company_id):
    from src.ai.core.exceptions import CompositionError
    from src.ai.orm.execution import ExecutionRun
    from src.ai.schemas.planning import PlanStep
    from src.ai.step_executor import StepExecutorService
    from src.ai.usage_service import UsageService

    parent = await _row(db, test_company_id, "PROCESS")
    archived = await _row(db, test_company_id, "AGENT", status="ARCHIVED")
    run = ExecutionRun(company_id=test_company_id, entity_id=parent.id, input_data={}, status="RUNNING")
    db.add(run)
    await db.flush()
    step = PlanStep.model_validate({"step_id": "s1", "name": "Delegate", "type": "CHILD_ENTITY_INVOCATION",
                                    "target": {"entity_id": str(archived.id)}})
    with pytest.raises(CompositionError, match="ARCHIVED"):
        await StepExecutorService(db, None, test_company_id, UsageService(db)).create_child_run(run, parent, step, {})


@pytest.mark.asyncio
async def test_a_deprecated_entity_runs_and_says_so(db, test_company_id):
    from src.ai.core.events import capture_test_events

    deprecated = await _row(db, test_company_id, "AGENT", status="DEPRECATED")
    with capture_test_events() as events:
        try:
            await _trigger(db, test_company_id, deprecated)
        except HTTPException as exc:          # the test company has no credit
            assert exc.status_code == 402
    assert "agent.entity.deprecated_run" in [e.name for e in events]
