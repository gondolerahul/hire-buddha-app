"""Entity assets — the scripts and small text files of a version (R2 §7).

An asset is a row, not a file: the API process stores its body and never
imports or runs it; the worker writes it into the tenant workspace for the
sandbox (``ai.tools.sandbox.skill_files``). Assets are added to and removed
from **drafts** only — a published version is immutable — and every change
re-hashes the draft, because a version is its content.
"""
from __future__ import annotations

import hashlib
import re
from typing import TYPE_CHECKING, Any, Optional
from uuid import UUID

from sqlalchemy import delete, func, select

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from src.ai.orm.versions import EntityAsset, EntityVersion

__all__ = [
    "AssetRejected",
    "MAX_ASSETS_PER_VERSION",
    "MAX_ASSET_BYTES",
    "MAX_VERSION_BYTES",
    "VersionConflict",
    "delete_asset",
    "language_for",
    "put_asset",
    "rehash_version",
    "valid_asset_path",
]

MAX_ASSET_BYTES = 512 * 1024
MAX_VERSION_BYTES = 8 * 1024 * 1024
MAX_ASSETS_PER_VERSION = 500
_MAX_DEPTH = 12
_MAX_PATH = 255
# A segment: letters, digits, ``_`` and ``-``, then dots allowed — never a
# leading dot (no ``..``, no hidden files; ``.content-hash`` is the marker the
# worker writes next to the files).
_SEGMENT = re.compile(r"^[A-Za-z0-9_-][A-Za-z0-9._-]*$")

_LANGUAGES = {
    ".py": "python", ".js": "javascript", ".mjs": "javascript", ".ts": "typescript",
    ".sh": "shell", ".sql": "sql", ".json": "json", ".yaml": "yaml", ".yml": "yaml",
    ".xml": "xml", ".xsd": "xml", ".html": "html", ".css": "css", ".md": "markdown",
    ".txt": "text", ".csv": "csv",
}


class AssetRejected(ValueError):
    """The asset breaks a rule (path, size, count, encoding). Maps to 422."""


class VersionConflict(ValueError):
    """The version cannot take the change (it is published; or, publishing, it matches a published one). Maps to 409."""


def valid_asset_path(path: str) -> str:
    """``path`` if it is a safe relative POSIX path, else :class:`AssetRejected`."""
    if not isinstance(path, str) or not path or len(path) > _MAX_PATH:
        raise AssetRejected(f"an asset path is 1–{_MAX_PATH} characters")
    if "\\" in path or path.startswith("/"):
        raise AssetRejected(f"{path!r}: use a relative path with forward slashes")
    segments = path.split("/")
    if len(segments) > _MAX_DEPTH:
        raise AssetRejected(f"{path!r}: at most {_MAX_DEPTH} levels deep")
    for seg in segments:
        if not _SEGMENT.match(seg):
            raise AssetRejected(
                f"{path!r}: each part is letters, digits, '_', '-' and '.', and does not start with '.'"
            )
    return path


def language_for(path: str) -> Optional[str]:
    """A language label from the file extension (None when unknown)."""
    dot = path.rfind(".")
    return _LANGUAGES.get(path[dot:].lower()) if dot > path.rfind("/") else None


async def _draft(db: "AsyncSession", version_id: UUID) -> "EntityVersion":
    from src.ai.orm.versions import EntityVersion
    version = (await db.execute(
        select(EntityVersion).where(EntityVersion.id == version_id).with_for_update()
    )).scalar_one_or_none()
    if version is None:
        raise LookupError(f"version {version_id} not found")
    if version.published:
        raise VersionConflict(
            f"version {version.version_number} is published and cannot change; create a draft"
        )
    return version


async def rehash_version(db: "AsyncSession", version: "EntityVersion") -> str:
    """Recompute a draft's hash from its snapshot and assets.

    A draft may match another version while it is edited (a new draft starts
    as a copy of its base); publishing one that matches a published version is
    refused (``version_authoring.publish``).
    """
    from src.ai.governance.entity_versions import content_hash
    from src.ai.orm.versions import EntityAsset

    manifest = (await db.execute(
        select(EntityAsset.path, EntityAsset.content_hash).where(EntityAsset.entity_version_id == version.id)
    )).all()
    digest = content_hash(version.snapshot, [(p, h) for p, h in manifest])
    version.content_hash = digest
    await db.flush()
    return digest


async def put_asset(db: "AsyncSession", version_id: UUID, path: str, body: str) -> "EntityAsset":
    """Add or replace one asset of a draft, within the limits."""
    from src.ai.orm.versions import EntityAsset

    path = valid_asset_path(path)
    if not isinstance(body, str) or "\x00" in body:
        raise AssetRejected(f"{path!r}: an asset is UTF-8 text without NUL characters")
    data = body.encode("utf-8")
    if len(data) > MAX_ASSET_BYTES:
        raise AssetRejected(f"{path!r}: {len(data)} bytes; an asset is at most {MAX_ASSET_BYTES}")

    version = await _draft(db, version_id)
    existing = (await db.execute(select(EntityAsset).where(
        EntityAsset.entity_version_id == version_id, EntityAsset.path == path,
    ))).scalar_one_or_none()
    count, total = (await db.execute(select(
        func.count(EntityAsset.id), func.coalesce(func.sum(EntityAsset.size_bytes), 0),
    ).where(EntityAsset.entity_version_id == version_id))).one()
    if existing is None and count >= MAX_ASSETS_PER_VERSION:
        raise AssetRejected(f"a version holds at most {MAX_ASSETS_PER_VERSION} assets")
    new_total = int(total) - (existing.size_bytes if existing else 0) + len(data)
    if new_total > MAX_VERSION_BYTES:
        raise AssetRejected(f"the version's assets would be {new_total} bytes; at most {MAX_VERSION_BYTES}")

    fields: dict[str, Any] = dict(
        body=body, size_bytes=len(data), language=language_for(path),
        content_hash=hashlib.sha256(data).hexdigest(),
    )
    if existing is None:
        existing = EntityAsset(entity_version_id=version_id, path=path, **fields)
        db.add(existing)
    else:
        for k, v in fields.items():
            setattr(existing, k, v)
    await db.flush()
    await rehash_version(db, version)
    return existing


async def delete_asset(db: "AsyncSession", version_id: UUID, path: str) -> bool:
    """Remove one asset of a draft; False when it had no such asset."""
    from src.ai.orm.versions import EntityAsset

    version = await _draft(db, version_id)
    gone = await db.execute(delete(EntityAsset).where(
        EntityAsset.entity_version_id == version_id, EntityAsset.path == path,
    ))
    if not gone.rowcount:  # type: ignore[attr-defined]
        return False
    await rehash_version(db, version)
    return True
