"""A version's scripts and small files (P5.3, R2 §7).

Assets are text rows on a draft version: safe relative paths, bounded sizes,
never changed once the version is published, and part of the version's hash
— a version is its content. Real Postgres, rolled back.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from src.ai.governance import entity_assets as ea
from src.ai.governance.entity_assets import (
    AssetRejected,
    VersionConflict,
    delete_asset,
    put_asset,
    valid_asset_path,
)
from src.ai.governance.entity_versions import capture_head, content_hash
from src.ai.models import HierarchicalEntity
from src.ai.orm.versions import EntityAsset, EntityVersion

pytestmark = pytest.mark.needs_db


@pytest.mark.parametrize("path", [
    "run.py", "office/schemas/ISO-IEC29500-4_2016/dml-chart.xsd", "a/b.c.d", "_x/-y",
])
def test_good_paths(path):
    assert valid_asset_path(path) == path


@pytest.mark.parametrize("path", [
    "", "/etc/passwd", "../up.py", "a/../b", "a//b", "./a", ".hidden", "a/.content-hash",
    "a\\b.py", "C:/x.py", "sp ace.py", "x" * 256, "/".join(["d"] * 13),
])
def test_bad_paths(path):
    with pytest.raises(AssetRejected):
        valid_asset_path(path)


async def _draft(db):
    from src.auth.models import Company
    c = Company(name=f"p53-{uuid.uuid4().hex[:6]}", type="TENANT", status="active")
    db.add(c)
    await db.flush()
    ent = HierarchicalEntity(company_id=c.id, type="SKILL", status="ACTIVE", name="with-files", goal="g")
    db.add(ent)
    await db.flush()
    head = await capture_head(db, ent.id)
    snap = (await db.execute(select(EntityVersion.snapshot).where(EntityVersion.id == head))).scalar_one()
    draft = EntityVersion(entity_id=ent.id, company_id=c.id, version_number=2, snapshot={**snap, "goal": "g2"},
                          content_hash="pending", published=False)
    db.add(draft)
    await db.flush()
    return ent, head, draft


@pytest.mark.asyncio
async def test_an_asset_is_stored_and_the_draft_rehashed(db):
    _ent, _head, draft = await _draft(db)
    asset = await put_asset(db, draft.id, "office/validate.py", "print('ok')\n")
    assert (asset.language, asset.size_bytes) == ("python", 12)
    assert draft.content_hash == content_hash(draft.snapshot, [("office/validate.py", asset.content_hash)])


@pytest.mark.asyncio
async def test_putting_the_same_path_replaces_it(db):
    _ent, _head, draft = await _draft(db)
    await put_asset(db, draft.id, "a.py", "one")
    await put_asset(db, draft.id, "a.py", "two")
    bodies = (await db.execute(select(EntityAsset.body).where(EntityAsset.entity_version_id == draft.id))).scalars().all()
    assert bodies == ["two"]


@pytest.mark.asyncio
async def test_a_published_version_is_immutable(db):
    _ent, head, _draft_row = await _draft(db)
    with pytest.raises(VersionConflict):
        await put_asset(db, head, "a.py", "x")
    with pytest.raises(VersionConflict):
        await delete_asset(db, head, "a.py")


@pytest.mark.asyncio
async def test_size_encoding_and_count_limits(db, monkeypatch):
    _ent, _head, draft = await _draft(db)
    with pytest.raises(AssetRejected):
        await put_asset(db, draft.id, "big.txt", "x" * (ea.MAX_ASSET_BYTES + 1))
    with pytest.raises(AssetRejected):
        await put_asset(db, draft.id, "nul.txt", "a\x00b")
    monkeypatch.setattr(ea, "MAX_ASSETS_PER_VERSION", 1)
    await put_asset(db, draft.id, "one.txt", "1")
    with pytest.raises(AssetRejected):
        await put_asset(db, draft.id, "two.txt", "2")
    await put_asset(db, draft.id, "one.txt", "replacing is not adding")
    monkeypatch.setattr(ea, "MAX_VERSION_BYTES", 30)
    with pytest.raises(AssetRejected):
        await put_asset(db, draft.id, "one.txt", "x" * 31)


@pytest.mark.asyncio
async def test_deleting_rehashes_and_a_missing_asset_is_false(db):
    _ent, _head, draft = await _draft(db)
    await put_asset(db, draft.id, "a.py", "x")
    assert await delete_asset(db, draft.id, "a.py") is True
    assert draft.content_hash == content_hash(draft.snapshot, [])
    assert await delete_asset(db, draft.id, "a.py") is False


@pytest.mark.asyncio
async def test_a_draft_may_match_a_published_version_while_it_is_edited(db):
    ent, head, draft = await _draft(db)
    head_row = (await db.execute(select(EntityVersion).where(EntityVersion.id == head))).scalar_one()
    draft.snapshot = dict(head_row.snapshot)            # back to the head's definition
    await db.flush()
    await put_asset(db, draft.id, "a.py", "x")
    assert await delete_asset(db, draft.id, "a.py") is True
    assert draft.content_hash == head_row.content_hash   # allowed; publishing it is refused (P5.6 API)
