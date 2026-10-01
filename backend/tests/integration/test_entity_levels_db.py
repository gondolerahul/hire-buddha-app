"""The database holds entity types to the six levels (R1).

``r1_entity_levels`` adds ``ck_hierarchical_entities_type`` and validates it on
a clean table. Real Postgres, rolled back.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

pytestmark = pytest.mark.needs_db


@pytest.mark.asyncio
@pytest.mark.parametrize("value", ["LOOP", "GRAPH"])
async def test_loop_and_graph_rows_are_stored(db, test_company_id, value):
    from src.ai.orm.entity import HierarchicalEntity

    entity = HierarchicalEntity(company_id=test_company_id, type=value, name=f"r1-{uuid.uuid4().hex[:8]}")
    db.add(entity)
    await db.flush()
    stored = (await db.execute(
        text("SELECT type FROM hierarchical_entities WHERE id = :id"), {"id": entity.id},
    )).scalar_one()
    assert stored == value


@pytest.mark.asyncio
async def test_the_database_refuses_a_type_outside_the_six(db, test_company_id):
    from src.ai.orm.entity import HierarchicalEntity

    db.add(HierarchicalEntity(company_id=test_company_id, type="WORKFLOW", name=f"r1-{uuid.uuid4().hex[:8]}"))
    with pytest.raises(IntegrityError):
        await db.flush()
