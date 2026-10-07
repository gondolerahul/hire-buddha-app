"""A run pins the entity version it executes (P5.1, EP-10).

``hierarchical_entities.version`` was a label nothing read, and a run read the
live row, so an edit reached runs already in flight. Now every run is pinned,
when it is created, to an immutable snapshot of the row — whichever of the
eight run creators made it, and whichever writer edited the row. Real
Postgres, rolled back.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from src.ai.governance.entity_versions import capture_head, content_hash, snapshot_of
from src.ai.orm import ExecutionRun, HierarchicalEntity
from src.ai.orm.versions import EntityAsset, EntityVersion
from src.ai.schemas.entity import HierarchicalEntityUpdate
from src.ai.service import AIService
from src.auth.models import User

pytestmark = pytest.mark.needs_db


async def _entity(db, **kw):
    from src.auth.models import Company
    c = Company(name=f"p51-{uuid.uuid4().hex[:6]}", type="TENANT", status="active")
    db.add(c)
    await db.flush()
    ent = HierarchicalEntity(company_id=c.id, type="ACTION", status="ACTIVE", name="versioned",
                             goal="first goal", io_contract={"b": 1, "a": 2}, **kw)
    db.add(ent)
    await db.flush()
    return ent


async def _run(db, ent, **kw):
    run = ExecutionRun(entity_id=ent.id, company_id=ent.company_id, status="PENDING", input_data={}, **kw)
    db.add(run)
    await db.flush()
    return run


async def _version(db, vid) -> EntityVersion:
    return (await db.execute(select(EntityVersion).where(EntityVersion.id == vid))).scalar_one()


@pytest.mark.asyncio
async def test_a_run_is_pinned_and_the_entity_points_at_its_head(db):
    ent = await _entity(db)
    run = await _run(db, ent)
    assert run.entity_version_id is not None
    assert ent.active_version_id == run.entity_version_id      # the loaded object sees it too
    v = await _version(db, run.entity_version_id)
    assert (v.version_number, v.published, v.snapshot["goal"]) == (1, True, "first goal")
    assert list(v.snapshot["io_contract"]) == ["b", "a"]      # JSON key order kept (DM-13)


@pytest.mark.asyncio
async def test_runs_of_an_unchanged_entity_share_its_version(db):
    ent = await _entity(db)
    first, second = await _run(db, ent), await _run(db, ent)
    assert first.entity_version_id == second.entity_version_id


@pytest.mark.asyncio
async def test_an_edit_by_any_writer_is_a_new_version_and_the_old_run_keeps_its_own(db):
    ent = await _entity(db)
    before = await _run(db, ent)
    ent.goal = "second goal"                       # a writer that bypasses the service
    await db.flush()
    after = await _run(db, ent)

    assert after.entity_version_id != before.entity_version_id
    old, new = await _version(db, before.entity_version_id), await _version(db, after.entity_version_id)
    assert (old.version_number, old.snapshot["goal"]) == (1, "first goal")
    assert (new.version_number, new.snapshot["goal"]) == (2, "second goal")


@pytest.mark.asyncio
async def test_editing_back_reuses_the_earlier_version(db):
    ent = await _entity(db)
    v1 = (await _run(db, ent)).entity_version_id
    ent.goal = "detour"
    await db.flush()
    await _run(db, ent)
    ent.goal = "first goal"
    await db.flush()
    assert (await _run(db, ent)).entity_version_id == v1


@pytest.mark.asyncio
async def test_a_run_given_a_version_keeps_it(db):
    ent = await _entity(db)
    v1 = (await _run(db, ent)).entity_version_id
    ent.goal = "second goal"
    await db.flush()
    pinned = await _run(db, ent, entity_version_id=v1)
    assert pinned.entity_version_id == v1


@pytest.mark.asyncio
async def test_the_service_versions_an_edit_and_records_who(db):
    ent = await _entity(db)
    user_id = (await db.execute(select(User.id).limit(1))).scalar()
    await AIService(db).update_entity(ent.id, HierarchicalEntityUpdate(goal="edited"), ent.company_id,
                                      user_role="app_admin", user_id=user_id)
    v = await _version(db, ent.active_version_id)
    assert v.snapshot["goal"] == "edited" and v.created_by == user_id


@pytest.mark.asyncio
async def test_a_new_head_carries_the_previous_heads_assets(db):
    ent = await _entity(db)
    v1 = await capture_head(db, ent.id)
    db.add(EntityAsset(entity_version_id=v1, path="run.py", content_hash="h1", language="python",
                       body="print(1)", size_bytes=8))
    await db.flush()
    ent.goal = "second goal"
    await db.flush()
    v2 = await capture_head(db, ent.id)
    paths = (await db.execute(select(EntityAsset.path).where(EntityAsset.entity_version_id == v2))).scalars().all()
    assert v2 != v1 and paths == ["run.py"]
    assert (await _version(db, v2)).content_hash == content_hash(snapshot_of(ent), [("run.py", "h1")])


@pytest.mark.asyncio
async def test_pinning_is_not_an_edit(db):
    ent = await _entity(db)
    stamp = (await db.execute(select(HierarchicalEntity.updated_at).where(HierarchicalEntity.id == ent.id))).scalar()
    await _run(db, ent)
    assert (await db.execute(
        select(HierarchicalEntity.updated_at).where(HierarchicalEntity.id == ent.id))).scalar() == stamp
