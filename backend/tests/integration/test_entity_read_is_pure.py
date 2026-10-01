"""Reading an entity never writes to it (EP-27).

``get_entity`` gave an ACTION or SKILL with no static steps a "virtual" plan by
assigning it to the persistent row, so any update that went through it — a
rename, a status change — saved a plan nobody authored. The default step is now
computed for the response only, at every level. Real Postgres, rolled back.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.needs_db


async def _stored_planning(db, entity_id):
    return (await db.execute(
        text("SELECT planning FROM hierarchical_entities WHERE id = :id"), {"id": entity_id},
    )).scalar_one()


async def _entity(db, company_id, type_):
    from src.ai.orm.entity import HierarchicalEntity

    entity = HierarchicalEntity(company_id=company_id, type=type_, name=f"ep27-{uuid.uuid4().hex[:6]}",
                                description="Answers questions.", planning={"dynamic_planning": {"enabled": False}})
    db.add(entity)
    await db.flush()
    return entity


@pytest.mark.asyncio
@pytest.mark.parametrize("type_", ["ACTION", "SKILL", "PROCESS"])
async def test_a_rename_does_not_save_a_plan_nobody_authored(db, test_company_id, type_):
    from src.ai.schemas.entity import HierarchicalEntityUpdate
    from src.ai.service import AIService

    entity = await _entity(db, test_company_id, type_)
    service = AIService(db)
    read = await service.get_entity(entity.id, test_company_id)
    assert read.planning == {"dynamic_planning": {"enabled": False}}
    assert not db.dirty

    await service.update_entity(entity.id, HierarchicalEntityUpdate(name="renamed"), test_company_id)
    assert await _stored_planning(db, entity.id) == {"dynamic_planning": {"enabled": False}}


@pytest.mark.asyncio
@pytest.mark.parametrize("type_", ["ACTION", "AGENT", "LOOP", "GRAPH"])
async def test_the_read_route_shows_the_default_step_at_every_level(db, test_company_id, type_):
    from src.ai import router

    entity = await _entity(db, test_company_id, type_)
    user = SimpleNamespace(company_id=test_company_id, role="tenant_admin", id=None)
    shown = await router.get_entity(entity.id, db=db, current_user=user)

    steps = shown.planning.static_plan.steps
    assert [s.step_id for s in steps] == ["auto_generated"]
    assert steps[0].target.prompt_template == "{{input}}"
    assert shown.planning.dynamic_planning.enabled is False
    assert await _stored_planning(db, entity.id) == {"dynamic_planning": {"enabled": False}}
