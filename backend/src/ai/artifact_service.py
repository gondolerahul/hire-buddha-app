"""
Artifact Service — manages file storage and metadata for all platform files.

Storage path convention:
  artifact/{origin}/{company_id}/{YYYY-MM-DD}/{file_name}

  origin:
    • user-uploads      — files manually uploaded by humans
    • system-generated  — files created by AI agents / tools
"""
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List
from uuid import UUID

from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from src.ai.artifact_models import Artifact

# ── Storage root ────────────────────────────────────────────────────────────────
# Absolute path so every caller gets a consistent root regardless of CWD.
_BACKEND_DIR = Path(__file__).resolve().parents[2]   # …/backend
ARTIFACT_BASE_DIR = _BACKEND_DIR / "artifact"

ORIGIN_USER = "user-uploads"
ORIGIN_SYSTEM = "system-generated"


def get_storage_path(
    origin: str,
    company_id: UUID,
) -> Path:
    """
    Build the daily storage directory for an artifact.
    Format: artifact/{origin}/{company_id}/{YYYY-MM-DD}/
    """
    date_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    return ARTIFACT_BASE_DIR / origin / str(company_id) / date_str


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
        Write file to disk under artifact/{origin}/{company_id}/{date}/ and create DB record.
        Returns the created Artifact ORM object.
        """
        # Build and ensure directory
        storage_dir = get_storage_path(origin, company_id)
        storage_dir.mkdir(parents=True, exist_ok=True)

        # Ensure unique filename
        unique_name = f"{uuid.uuid4().hex}_{file_name}"
        file_path = storage_dir / unique_name

        # Write to disk
        with open(file_path, "wb") as f:
            f.write(file_bytes)

        # Create DB record
        artifact = Artifact(
            company_id=company_id,
            campaign_id=campaign_id,
            agent_id=agent_id,
            run_id=run_id,
            origin=origin,
            file_category=file_category,
            file_name=file_name,
            file_path=str(file_path),
            file_size=len(file_bytes),
            mime_type=mime_type,
            duration_seconds=duration_seconds,
            purpose=purpose,
            generated_by=generated_by,
            artifact_metadata=extra_metadata or {},
        )
        self.db.add(artifact)
        await self.db.commit()
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
        offset: int = 0,
        run_id: Optional[UUID] = None,
    ) -> List[Artifact]:
        """Return filtered artifact list for a company.

        ``run_id``: the files of that run and of every run beneath it — what a
        run produced, child runs included (EP-21: the run page searched step
        outputs with regular expressions instead).
        """
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

        stmt = (
            select(Artifact)
            .where(and_(*conditions))
            .order_by(Artifact.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def get_artifact(self, artifact_id: UUID, company_id: UUID) -> Optional[Artifact]:
        """Fetch a single artifact by ID, scoped to company."""
        stmt = select(Artifact).where(
            Artifact.id == artifact_id,
            Artifact.company_id == company_id,
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def delete_artifact(self, artifact_id: UUID, company_id: UUID) -> bool:
        """Delete artifact record and its physical file."""
        artifact = await self.get_artifact(artifact_id, company_id)
        if not artifact:
            return False
        # Remove file from disk
        try:
            Path(artifact.file_path).unlink(missing_ok=True)
        except Exception:
            pass
        await self.db.delete(artifact)
        await self.db.commit()
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
    from src.common.database import AsyncSessionLocal

    ctx = context or {}
    company_id = _as_uuid(ctx.get("company_id"))
    if company_id is None:
        raise ValueError("a tool output needs the call's company (no execution context)")
    async with AsyncSessionLocal() as db:
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
