"""
Artifact Service — manages file storage and metadata for all platform files.

The bytes go through the storage adapter (``src/common/platform/storage``,
Phase 14 WS1 1.2) under a neutral key:

  c-<company>/<area>/<YYYY-MM-DD>/<uuid>_<file_name>

  area:
    • uploads     — files manually uploaded by humans (origin user-uploads)
    • artifacts   — files created by AI agents / tools (origin system-generated)
    • recordings  — call recordings

Read an artifact's bytes with :func:`read_artifact_bytes` or
:func:`artifact_local_file`, never by opening ``file_path``.
"""
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator, Optional, List
from uuid import UUID

from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from src.ai.artifact_models import Artifact
from src.common.platform.storage import (
    StorageObjectNotFound,
    company_namespace,
    get_storage,
    materialized,
)

# ── Local-disk storage root ─────────────────────────────────────────────────────
# Where local_disk storage keeps files by default, and where every file lived
# before storage keys (src/common/platform/storage.default_local_root).
_BACKEND_DIR = Path(__file__).resolve().parents[2]   # …/backend
ARTIFACT_BASE_DIR = _BACKEND_DIR / "artifact"

ORIGIN_USER = "user-uploads"
ORIGIN_SYSTEM = "system-generated"


def storage_area(origin: str, file_category: str) -> str:
    if file_category == "recordings":
        return "recordings"
    return "uploads" if origin == ORIGIN_USER else "artifacts"


def _key_safe_name(file_name: str) -> str:
    """The file name as one key segment: no directories, NUL or dot-only names."""
    name = (file_name or "").replace("\\", "/").split("/")[-1].replace("\x00", "").strip()
    return name if name.strip(".") else "file"


def new_storage_key(origin: str, file_category: str, company_id: UUID, file_name: str) -> str:
    """A fresh key for a file of the company: ``c-<company>/<area>/<date>/<uuid>_<name>``."""
    date_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    return (f"{company_namespace(company_id)}/{storage_area(origin, file_category)}/{date_str}/"
            f"{uuid.uuid4().hex}_{_key_safe_name(file_name)}")


def company_storage_dirs(company_id: Any) -> List[Path]:
    """The company's directories on local-disk storage (for path confinement):
    its namespace, and its folders from before storage keys."""
    from src.common.platform.storage import company_namespaces

    roots = []
    try:
        namespace_dirs = [get_storage().local_path(f"{name}/x") for name in company_namespaces(company_id)]
    except ValueError:  # not a company id: it has no namespace
        namespace_dirs = []
    roots += [d.parent for d in namespace_dirs if d is not None]
    cid = str(company_id)
    roots += [ARTIFACT_BASE_DIR / ORIGIN_SYSTEM / cid, ARTIFACT_BASE_DIR / ORIGIN_USER / cid]
    return roots


# ── Reading an artifact's bytes ─────────────────────────────────────────────────

def _legacy_local_file(artifact: Artifact) -> Optional[Path]:
    """A row with no key whose ``file_path`` is a file on this machine."""
    path = artifact.file_path or ""
    if artifact.storage_key or not path or path.startswith(("http://", "https://")):
        return None
    candidate = Path(path)
    return candidate if candidate.is_file() else None


async def artifact_exists(artifact: Artifact) -> bool:
    if artifact.storage_key:
        return await get_storage().exists(artifact.storage_key)
    return _legacy_local_file(artifact) is not None


async def artifact_size(artifact: Artifact) -> Optional[int]:
    """Bytes stored for the artifact, or ``None`` when its file is missing."""
    if artifact.storage_key:
        return await get_storage().size(artifact.storage_key)
    legacy = _legacy_local_file(artifact)
    return legacy.stat().st_size if legacy else None


async def read_artifact_bytes(artifact: Artifact) -> bytes:
    """The artifact's bytes, or :class:`StorageObjectNotFound`."""
    if artifact.storage_key:
        return await get_storage().get(artifact.storage_key)
    legacy = _legacy_local_file(artifact)
    if legacy is None:
        raise StorageObjectNotFound(artifact.file_path or str(artifact.id))
    return legacy.read_bytes()


@asynccontextmanager
async def artifact_local_file(artifact: Artifact) -> AsyncIterator[Path]:
    """A local file with the artifact's bytes, for code that needs a path.

    Read it, never change it: on local disk it is the stored file itself.
    """
    if artifact.storage_key:
        async with materialized(artifact.storage_key, suffix=Path(artifact.file_name or "").suffix) as path:
            yield path
        return
    legacy = _legacy_local_file(artifact)
    if legacy is None:
        raise StorageObjectNotFound(artifact.file_path or str(artifact.id))
    yield legacy


class ArtifactService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def save_artifact(
        self,
        file_bytes: bytes,
        file_name: str,
        mime_type: str,
        file_category: str,            # recordings | images | videos | documents | text
        origin: str,                   # user-uploads | system-generated
        company_id: UUID,
        purpose: Optional[str] = None,
        generated_by: Optional[str] = None,
        campaign_id: Optional[UUID] = None,
        agent_id: Optional[UUID] = None,
        run_id: Optional[UUID] = None,
        duration_seconds: Optional[int] = None,
        extra_metadata: Optional[dict] = None,
    ) -> Artifact:
        """
        Store the bytes under a new key (``new_storage_key``) and create the DB
        record. Returns the created Artifact ORM object.
        """
        storage = get_storage()
        key = new_storage_key(origin, file_category, company_id, file_name)
        await storage.put(key, file_bytes, content_type=mime_type)
        local = storage.local_path(key)

        artifact = Artifact(
            company_id=company_id,
            campaign_id=campaign_id,
            agent_id=agent_id,
            run_id=run_id,
            origin=origin,
            file_category=file_category,
            file_name=file_name,
            file_path=str(local) if local is not None else key,
            storage_key=key,
            file_size=len(file_bytes),
            mime_type=mime_type,
            duration_seconds=duration_seconds,
            purpose=purpose,
            generated_by=generated_by,
            artifact_metadata=extra_metadata or {},
        )
        self.db.add(artifact)
        try:
            await self.db.commit()
        except Exception:
            # No row, so no stored object either: nothing could ever find it.
            await storage.delete(key)
            raise
        await self.db.refresh(artifact)
        return artifact

    async def save_upload(
        self,
        upload: UploadFile,
        file_category: str,
        company_id: UUID,
        campaign_id: Optional[UUID] = None,
        agent_id: Optional[UUID] = None,
        purpose: Optional[str] = None,
    ) -> Artifact:
        """Save a FastAPI UploadFile as a user-upload artifact."""
        content = await upload.read()
        return await self.save_artifact(
            file_bytes=content,
            file_name=upload.filename or "upload",
            mime_type=upload.content_type or "application/octet-stream",
            file_category=file_category,
            origin=ORIGIN_USER,
            company_id=company_id,
            campaign_id=campaign_id,
            agent_id=agent_id,
            purpose=purpose or f"User-uploaded {file_category} file",
            generated_by="user-upload",
        )

    async def list_artifacts(
        self,
        company_id: UUID,
        origin: Optional[str] = None,
        file_category: Optional[str] = None,
        agent_id: Optional[UUID] = None,
        campaign_id: Optional[UUID] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        limit: int = 100,
        run_id: Optional[UUID] = None,
    ) -> List[Artifact]:
        """Return filtered artifact list for a company, newest first.

        ``run_id``: the files of that run and of every run beneath it — what a
        run produced, child runs included (EP-21: the run page searched step
        outputs with regular expressions instead).
        """
        stmt = self.artifacts_query(company_id, origin=origin, file_category=file_category,
                                    agent_id=agent_id, campaign_id=campaign_id, date_from=date_from,
                                    date_to=date_to, run_id=run_id)
        result = await self.db.execute(stmt.order_by(Artifact.created_at.desc()).limit(limit))
        return result.scalars().all()

    def artifacts_query(
        self,
        company_id: UUID,
        origin: Optional[str] = None,
        file_category: Optional[str] = None,
        agent_id: Optional[UUID] = None,
        campaign_id: Optional[UUID] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        run_id: Optional[UUID] = None,
    ) -> Any:
        """The SELECT behind :meth:`list_artifacts`, unordered — for a caller that pages it (API-16)."""
        conditions = [Artifact.company_id == company_id]
        if run_id:
            from src.ai.orm.execution import ExecutionRun
            tree = select(ExecutionRun.id).where(ExecutionRun.id == run_id).cte("run_tree", recursive=True)
            tree = tree.union_all(select(ExecutionRun.id).where(ExecutionRun.parent_run_id == tree.c.id))
            conditions.append(Artifact.run_id.in_(select(tree.c.id)))

        if origin:
            conditions.append(Artifact.origin == origin)
        if file_category:
            conditions.append(Artifact.file_category == file_category)
        if agent_id:
            conditions.append(Artifact.agent_id == agent_id)
        if campaign_id:
            conditions.append(Artifact.campaign_id == campaign_id)
        if date_from:
            conditions.append(Artifact.created_at >= date_from)
        if date_to:
            conditions.append(Artifact.created_at <= date_to)

        return select(Artifact).where(and_(*conditions))

    async def get_artifact(self, artifact_id: UUID, company_id: UUID) -> Optional[Artifact]:
        """Fetch a single artifact by ID, scoped to company."""
        stmt = select(Artifact).where(
            Artifact.id == artifact_id,
            Artifact.company_id == company_id,
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def delete_artifact(self, artifact_id: UUID, company_id: UUID) -> bool:
        """Delete artifact record, then its stored file (a left-over file is
        harmless; a row pointing at nothing is not)."""
        artifact = await self.get_artifact(artifact_id, company_id)
        if not artifact:
            return False
        key, legacy = artifact.storage_key, _legacy_local_file(artifact)
        await self.db.delete(artifact)
        await self.db.commit()
        try:
            if key:
                await get_storage().delete(key)
            elif legacy is not None:
                legacy.unlink(missing_ok=True)
        except Exception:
            pass
        return True


def _as_uuid(value: object) -> Optional[UUID]:
    try:
        return UUID(str(value)) if value else None
    except (TypeError, ValueError):
        return None


async def save_tool_output(
    context: Optional[dict],
    *,
    file_name: str,
    file_bytes: bytes,
    mime_type: str,
    file_category: str,
    generated_by: str,
    purpose: Optional[str] = None,
    extra_metadata: Optional[dict] = None,
) -> Artifact:
    """The one way a tool keeps a file it made (TL-59, EP-21).

    Bytes in; the registered artifact out — its ``file_path`` is what the tool
    returns to the model, and its run, agent and campaign come from the call's
    context, so the file appears under its run. Tools used to write a first
    copy under ``backend/src/artifact`` and register a second one here, often
    with no run, returning the unregistered path.
    """
    from src.common.tenancy.session import tenant_session

    ctx = context or {}
    company_id = _as_uuid(ctx.get("company_id"))
    if company_id is None:
        raise ValueError("a tool output needs the call's company (no execution context)")
    async with tenant_session(company_id) as db:
        return await ArtifactService(db).save_artifact(
            file_bytes=file_bytes,
            file_name=file_name,
            mime_type=mime_type,
            file_category=file_category,
            origin=ORIGIN_SYSTEM,
            company_id=company_id,
            purpose=purpose,
            generated_by=generated_by,
            campaign_id=_as_uuid(ctx.get("campaign_id")),
            agent_id=_as_uuid(ctx.get("agent_id")),
            run_id=_as_uuid(ctx.get("run_id")),
            extra_metadata=extra_metadata,
        )
