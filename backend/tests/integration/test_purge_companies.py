"""TS-16: the purge the parity and e2e teardowns use deletes a session's
companies and everything under them — through the entity ↔ version cycle —
and nothing of another company. Rolled back like every integration test."""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select

from tests.harness.purge import purge_companies

pytestmark = pytest.mark.needs_db


async def _tenant_with_a_run(db):
    from src.ai.orm import ExecutionRun, HierarchicalEntity
    from src.ai.orm.versions import EntityVersion
    from src.auth.models import Company

    company = Company(name=f"parity-{uuid.uuid4().hex[:8]}", type="TENANT", status="active")
    db.add(company)
    await db.flush()
    entity = HierarchicalEntity(company_id=company.id, type="AGENT", status="ACTIVE", name="purge-probe")
    db.add(entity)
    await db.flush()
    version = EntityVersion(entity_id=entity.id, company_id=company.id, version_number=1,
                            snapshot={}, content_hash="0" * 64)
    db.add(version)
    await db.flush()
    entity.active_version_id = version.id          # the cycle the purge must break
    db.add(ExecutionRun(id=uuid.uuid4(), entity_id=entity.id, company_id=company.id,
                        status="COMPLETED", input_data={}))
    await db.flush()
    return company.id, entity.id


async def test_a_purge_deletes_the_companies_and_what_is_under_them(db) -> None:
    from src.ai.orm import ExecutionRun, HierarchicalEntity
    from src.auth.models import Company

    mine, my_entity = await _tenant_with_a_run(db)
    other, other_entity = await _tenant_with_a_run(db)

    await purge_companies(db, [mine])

    async def count(model, **where):
        return await db.scalar(select(func.count()).select_from(model).filter_by(**where))

    assert await count(Company, id=mine) == 0
    assert await count(HierarchicalEntity, id=my_entity) == 0
    assert await count(ExecutionRun, entity_id=my_entity) == 0
    assert await count(Company, id=other) == 1
    assert await count(ExecutionRun, entity_id=other_entity) == 1
    other_row = await db.get(HierarchicalEntity, other_entity)
    await db.refresh(other_row)
    assert other_row.active_version_id is not None


async def test_no_companies_is_a_no_op(db) -> None:
    await purge_companies(db, [])
