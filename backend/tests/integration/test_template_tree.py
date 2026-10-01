"""A template carries every child of the entity it was made from (EP-19).

``convert_to_template`` walked ``parent_id`` and ``hierarchy.children`` but not
static-plan CHILD_ENTITY_INVOCATION targets, so a child named only by a plan
step — how several seeds wire them — was missing from the template and from
every clone of it. Real Postgres, rolled back.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select, text

pytestmark = pytest.mark.needs_db


async def _row(db, company_id, type_, **fields):
    from src.ai.orm.entity import HierarchicalEntity

    entity = HierarchicalEntity(company_id=company_id, type=type_, name=f"ep19-{uuid.uuid4().hex[:6]}", **fields)
    db.add(entity)
    await db.flush()
    return entity


@pytest.mark.asyncio
async def test_a_child_named_only_by_a_plan_step_reaches_the_template_and_its_clones(db, test_company_id):
    from src.ai.orm.entity import HierarchicalEntity
    from src.ai.service import AIService

    skill = await _row(db, test_company_id, "SKILL")
    agent = await _row(db, test_company_id, "AGENT", hierarchy={"children": [{"child_id": str(skill.id)}]})
    process = await _row(db, test_company_id, "PROCESS", planning={"static_plan": {"enabled": True, "steps": [
        {"step_id": "s1", "name": "Delegate", "type": "CHILD_ENTITY_INVOCATION",
         "target": {"entity_id": str(agent.id), "prompt_template": "{{input}}"}},
    ]}})

    service = AIService(db)
    template = await service.convert_to_template(process.id, test_company_id, None)

    copies = {
        row.template_source_id: row
        for row in (await db.execute(select(HierarchicalEntity).where(
            HierarchicalEntity.is_template.is_(True),
            HierarchicalEntity.template_source_id.in_([agent.id, skill.id]),
        ))).scalars().all()
    }
    assert set(copies) == {agent.id, skill.id}
    # Read what was stored, not the session's objects: the remap used to change
    # them in memory only.
    async def _stored(column, entity_id):
        return (await db.execute(text(f"SELECT {column} FROM hierarchical_entities WHERE id = :id"),
                                 {"id": entity_id})).scalar_one()

    stored_plan = await _stored("planning", template.id)
    assert stored_plan["static_plan"]["steps"][0]["target"]["entity_id"] == str(copies[agent.id].id)
    stored_children = await _stored("hierarchy", copies[agent.id].id)
    assert stored_children["children"][0]["child_id"] == str(copies[skill.id].id)

    clone = await service.clone_template(template.id, test_company_id, None)
    cloned = (await db.execute(select(HierarchicalEntity).where(
        HierarchicalEntity.is_template.is_(False),
        HierarchicalEntity.template_source_id.in_([copies[agent.id].id, copies[skill.id].id]),
    ))).scalars().all()
    assert len(cloned) == 2
    clone_plan = await _stored("planning", clone.id)
    assert clone_plan["static_plan"]["steps"][0]["target"]["entity_id"] in {str(c.id) for c in cloned}
