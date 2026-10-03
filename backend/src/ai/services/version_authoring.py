"""Authoring entity versions: drafts, their files, test runs and publishing (R2 §6.3).

A draft is an unpublished version: a base version's definition plus changes,
with the base's files, edited through ``entity_assets`` and test-run pinned to
itself. Publishing copies its definition onto the entity row and makes it the
head, so new runs execute it; runs in flight keep theirs. Publishing an older
version is a rollback. A published version never changes.
"""
from __future__ import annotations

import copy
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any, Optional
from uuid import UUID

from sqlalchemy import func, select

from src.ai.governance.entity_assets import VersionConflict, rehash_version
from src.ai.governance.entity_versions import SNAPSHOT_FIELDS, capture_head

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from src.ai.orm.entity import HierarchicalEntity
    from src.ai.orm.versions import EntityAsset, EntityVersion

__all__ = [
    "NotAVersionField",
    "create_draft",
    "get_asset",
    "get_version",
    "list_assets",
    "list_versions",
    "publish",
]


class NotAVersionField(ValueError):
    """A change to a field that belongs to the entity, not to a version. Maps to 422."""


async def list_versions(db: "AsyncSession", entity_id: UUID) -> list[tuple["EntityVersion", int]]:
    """Every version of the entity, newest first, with its asset count."""
    from src.ai.orm.versions import EntityAsset, EntityVersion
    counts = (
        select(EntityAsset.entity_version_id, func.count(EntityAsset.id).label("n"))
        .group_by(EntityAsset.entity_version_id).subquery()
    )
    rows = (await db.execute(
        select(EntityVersion, func.coalesce(counts.c.n, 0))
        .outerjoin(counts, counts.c.entity_version_id == EntityVersion.id)
        .where(EntityVersion.entity_id == entity_id)
        .order_by(EntityVersion.version_number.desc())
    )).all()
    return [(v, int(n)) for v, n in rows]


async def get_version(db: "AsyncSession", entity_id: UUID, version_id: UUID) -> "EntityVersion":
    """The entity's version, or ``LookupError`` (also for another entity's version)."""
    from src.ai.orm.versions import EntityVersion
    version = (await db.execute(select(EntityVersion).where(
        EntityVersion.id == version_id, EntityVersion.entity_id == entity_id,
    ))).scalar_one_or_none()
    if version is None:
        raise LookupError(f"version {version_id} of entity {entity_id} not found")
    return version


async def list_assets(db: "AsyncSession", version_id: UUID) -> list["EntityAsset"]:
    from src.ai.orm.versions import EntityAsset
    return list((await db.execute(
        select(EntityAsset).where(EntityAsset.entity_version_id == version_id).order_by(EntityAsset.path)
    )).scalars())


async def get_asset(db: "AsyncSession", version_id: UUID, path: str) -> "EntityAsset":
    from src.ai.orm.versions import EntityAsset
    asset = (await db.execute(select(EntityAsset).where(
        EntityAsset.entity_version_id == version_id, EntityAsset.path == path,
    ))).scalar_one_or_none()
    if asset is None:
        raise LookupError(f"no asset {path!r} in version {version_id}")
    return asset


async def _require_composition(db: "AsyncSession", entity: "HierarchicalEntity", changes: dict[str, Any]) -> None:
    """The entity as the version would make it must keep the composition rule."""
    from src.ai.governance.composition import EntityShape, authoring_violations
    problems = await authoring_violations(db, EntityShape.of(entity).with_changes(changes))
    if problems:
        raise NotAVersionField("Composition rule: " + "; ".join(problems))


async def create_draft(
    db: "AsyncSession",
    entity: "HierarchicalEntity",
    changes: dict[str, Any],
    *,
    base_version_id: Optional[UUID] = None,
    user_id: Optional[UUID] = None,
) -> "EntityVersion":
    """A new unpublished version: the base's definition and files plus ``changes``.

    ``changes`` are definition fields only (``SNAPSHOT_FIELDS``); status, tags
    and placement belong to the entity. A draft may start as a copy of its
    base — to add files, say; it cannot be *published* while it matches a
    published version.
    """
    from src.ai.orm.entity import HierarchicalEntity
    from src.ai.orm.versions import EntityAsset, EntityVersion

    if "version" in changes and not changes["version"]:
        changes = {k: v for k, v in changes.items() if k != "version"}   # the label is NOT NULL
    outside = sorted(set(changes) - set(SNAPSHOT_FIELDS))
    if outside:
        raise NotAVersionField(
            f"{', '.join(outside)} belong to the entity, not a version; change them on the entity"
        )
    await _require_composition(db, entity, changes)
    if base_version_id is None:
        base_version_id = entity.active_version_id or await capture_head(db, entity.id, created_by=user_id)
    if base_version_id is None:
        raise LookupError(f"entity {entity.id} not found")
    base = await get_version(db, entity.id, base_version_id)

    # The entity row's lock numbers drafts and captures one at a time.
    await db.execute(select(HierarchicalEntity.id).where(HierarchicalEntity.id == entity.id).with_for_update())
    number = (await db.execute(
        select(func.max(EntityVersion.version_number)).where(EntityVersion.entity_id == entity.id)
    )).scalar() or 0
    snapshot = {**copy.deepcopy(base.snapshot), **copy.deepcopy(changes)}
    draft = EntityVersion(
        entity_id=entity.id, company_id=entity.company_id, version_number=number + 1,
        label=snapshot.get("version"), snapshot=snapshot, content_hash=f"pending-{uuid.uuid4().hex}",
        published=False, created_by=user_id, created_at=datetime.utcnow(),
    )
    db.add(draft)
    await db.flush()
    for a in await list_assets(db, base.id):
        db.add(EntityAsset(entity_version_id=draft.id, path=a.path, content_hash=a.content_hash,
                           language=a.language, body=a.body, size_bytes=a.size_bytes))
    await db.flush()
    await rehash_version(db, draft)
    return draft


async def publish(
    db: "AsyncSession", entity: "HierarchicalEntity", version_id: UUID, *, user_id: Optional[UUID] = None,
) -> "EntityVersion":
    """Make a version the head: its definition goes onto the row; new runs execute it.

    A draft becomes published; an older published version is a rollback. A
    draft that matches a published version is refused (:class:`VersionConflict`):
    publish that version instead.
    """
    version = await get_version(db, entity.id, version_id)
    definition = {f: copy.deepcopy(version.snapshot.get(f)) for f in SNAPSHOT_FIELDS}
    await _require_composition(db, entity, definition)
    if not version.published:
        # A draft passes the publication checks (D27); a rollback to a version
        # already published does not re-run them.
        from src.ai.governance.publication import require_publishable
        await require_publishable(definition, entity.company_id)
    for field, value in definition.items():
        setattr(entity, field, value)
    # The head's files are the version's, so the capture below hashes to it.
    entity.active_version_id = version.id
    await db.flush()
    head_id = await capture_head(db, entity.id, created_by=user_id)
    head = await get_version(db, entity.id, head_id) if head_id else version
    if head.id != version.id:  # the capture found a published version with this content
        raise VersionConflict(
            f"version {version.version_number} is identical to version {head.version_number}; publish that"
        )
    head.published = True
    head.published_at = datetime.utcnow()
    head.published_by = user_id
    await db.flush()
    return head
