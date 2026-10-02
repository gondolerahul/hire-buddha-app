"""Entity versions — what a run executes (EP-10, R2).

The ``hierarchical_entities`` row is the head: the API, the Board, the meta
tools and the clone helpers all edit it in place. A run must not see an edit
made after it started, so every run pins a version — an immutable snapshot of
the row's definition — when it is created (the ``before_insert`` listener on
``ExecutionRun``). The same content is the same version: a run of an unchanged
entity reuses the version the last one pinned, and an edit back to an earlier
content reuses that earlier version.

``capture_head_sync`` is the one implementation. It works on a synchronous
``Connection`` so the listener can call it inside the flush; async callers go
through ``capture_head``.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any, Iterable, Mapping, Optional, cast
from uuid import UUID

from sqlalchemy import Table, func, insert, select, update

if TYPE_CHECKING:
    from sqlalchemy.engine import Connection
    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "SNAPSHOT_FIELDS",
    "capture_head",
    "capture_head_sync",
    "content_hash",
    "note_head",
    "snapshot_of",
]

# A version's definition: what a run reads. Identity and lifecycle (``id``,
# ``company_id``, ``parent_id``, ``status``) stay on the live row.
SNAPSHOT_FIELDS: tuple[str, ...] = (
    "name", "display_name", "description", "goal", "type", "version",
    "identity", "hierarchy", "logic_gate", "planning", "capabilities",
    "governance", "io_contract", "observability", "metadata_extensions",
)
# Kept in its own key order when hashed: the order is meaning (DM-13). The
# other blocks are JSONB, which orders keys itself.
_ORDERED_FIELDS = frozenset({"io_contract"})


def snapshot_of(row: Any) -> dict[str, Any]:
    """The definition fields of an entity row (a mapping or an ORM object)."""
    if isinstance(row, Mapping):
        return {f: row.get(f) for f in SNAPSHOT_FIELDS}
    return {f: getattr(row, f, None) for f in SNAPSHOT_FIELDS}


def content_hash(snapshot: Mapping[str, Any], assets: Iterable[tuple[str, str]] = ()) -> str:
    """SHA-256 of a definition and its asset manifest (``(path, content_hash)``)."""
    h = hashlib.sha256()
    for field in SNAPSHOT_FIELDS:
        body = json.dumps(snapshot.get(field), sort_keys=field not in _ORDERED_FIELDS,
                          separators=(",", ":"), default=str)
        h.update(f"{field}\0{body}\0".encode())
    for path, digest in sorted(assets):
        h.update(f"asset\0{path}\0{digest}\0".encode())
    return h.hexdigest()


def capture_head_sync(conn: "Connection", entity_id: UUID, *, created_by: Optional[UUID] = None) -> Optional[UUID]:
    """The version matching the entity row now; appended if there is none.

    Locks the entity row, so two captures of one entity cannot both append a
    version. A new version is published at once (it is the head) and carries
    the previous head's assets. Returns ``None`` when the entity does not exist.
    """
    from src.ai.orm.entity import HierarchicalEntity
    from src.ai.orm.versions import EntityAsset, EntityVersion

    ents = cast(Table, HierarchicalEntity.__table__)
    vers = cast(Table, EntityVersion.__table__)
    assets = cast(Table, EntityAsset.__table__)

    row = conn.execute(select(ents).where(ents.c.id == entity_id).with_for_update()).mappings().first()
    if row is None:
        return None
    snapshot = snapshot_of(row)
    head = row["active_version_id"]
    head_assets = (
        conn.execute(select(assets).where(assets.c.entity_version_id == head)).mappings().all()
        if head else []
    )
    digest = content_hash(snapshot, ((a["path"], a["content_hash"]) for a in head_assets))
    now = datetime.utcnow()

    found = conn.execute(
        select(vers.c.id, vers.c.published).where(vers.c.entity_id == entity_id, vers.c.content_hash == digest)
    ).first()
    version_id: UUID
    if found is not None:
        version_id = found.id
        if not found.published:  # the row was given a draft's content: it is published now
            conn.execute(update(vers).where(vers.c.id == version_id).values(published=True, published_at=now))
    else:
        version_id = uuid.uuid4()
        number = (conn.execute(
            select(func.max(vers.c.version_number)).where(vers.c.entity_id == entity_id)
        ).scalar() or 0) + 1
        conn.execute(insert(vers).values(
            id=version_id, entity_id=entity_id, company_id=row["company_id"], version_number=number,
            label=row["version"], snapshot=snapshot, content_hash=digest, published=True,
            published_at=now, created_by=created_by, created_at=now,
        ))
        if head_assets:
            conn.execute(insert(assets), [
                {**{k: a[k] for k in ("path", "content_hash", "language", "body", "size_bytes")},
                 "id": uuid.uuid4(), "entity_version_id": version_id, "created_at": now}
                for a in head_assets
            ])
    if head != version_id:
        # ``updated_at`` is kept: pinning a run is not an edit of the entity.
        conn.execute(update(ents).where(ents.c.id == entity_id).values(
            active_version_id=version_id, updated_at=row["updated_at"],
        ))
    return version_id


async def capture_head(db: "AsyncSession", entity_id: UUID, *, created_by: Optional[UUID] = None) -> Optional[UUID]:
    """``capture_head_sync`` on the session's connection (its transaction)."""
    conn = await db.connection()
    version_id = await conn.run_sync(lambda sync_conn: capture_head_sync(sync_conn, entity_id, created_by=created_by))
    note_head(db.sync_session, entity_id, version_id)
    return version_id


def note_head(session: Any, entity_id: UUID, version_id: Optional[UUID]) -> None:
    """Show a loaded entity its new head without marking it changed.

    The capture writes ``active_version_id`` with Core; sessions do not expire
    on commit, so an entity object already in the session would keep the old
    value (and lazy-loading a refresh is not possible under asyncio).
    """
    from sqlalchemy.orm.attributes import set_committed_value
    from src.ai.orm.entity import HierarchicalEntity

    if session is None or version_id is None:
        return
    for obj in list(session.identity_map.values()):
        if isinstance(obj, HierarchicalEntity) and obj.id == entity_id:
            set_committed_value(obj, "active_version_id", version_id)
