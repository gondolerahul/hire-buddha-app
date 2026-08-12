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
    ) -> List[Artifact]:
        """Return filtered artifact list for a company."""
        conditions = [Artifact.company_id == company_id]

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
