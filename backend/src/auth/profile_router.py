from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
from pathlib import Path
import shutil

from src.common.database import get_db
from src.auth.dependencies import get_current_user
from src.auth.models import User, Company
from src.auth.schemas import UserResponse, CompanyResponse
from src.common.config import settings

router = APIRouter(prefix="/profile", tags=["profile"])

# ── Artifact base dir (user-uploads) ─────────────────────────────────────────
_BACKEND_DIR = Path(__file__).resolve().parents[2]
_USER_UPLOADS_ROOT = _BACKEND_DIR / "artifact" / "user-uploads"


def _get_upload_dir(company_id) -> Path:
    d = _USER_UPLOADS_ROOT / str(company_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


@router.post("/avatar", response_model=UserResponse)
async def upload_avatar(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Upload user profile picture — saved in artifact/user-uploads/{company_id}/"""
    from src.ai.artifact_service import ArtifactService, ORIGIN_USER

    svc = ArtifactService(db)
    content = await file.read()
    file_ext = (file.filename or "avatar").rsplit(".", 1)[-1]
    avatar_filename = f"avatar_{current_user.id}.{file_ext}"

    artifact = await svc.save_artifact(
        file_bytes=content,
        file_name=avatar_filename,
        mime_type=file.content_type or "image/jpeg",
        file_category="images",
        origin=ORIGIN_USER,
        company_id=current_user.company_id,
        purpose="User profile picture",
        generated_by="user-upload:avatar",
    )

    # Update user profile picture URL to the artifact download endpoint
    current_user.profile_picture_url = f"/api/v1/artifacts/{artifact.id}/download"
    await db.commit()
    await db.refresh(current_user)

    return current_user


@router.post("/company-logo", response_model=CompanyResponse)
async def upload_logo(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Upload company logo — saved in artifact/user-uploads/{company_id}/. Admin only."""
    if current_user.role not in ["app_admin", "partner_admin", "tenant_admin"]:
        raise HTTPException(status_code=403, detail="Only admins can upload company logos")

    from src.ai.artifact_service import ArtifactService, ORIGIN_USER

    svc = ArtifactService(db)
    content = await file.read()
    file_ext = (file.filename or "logo").rsplit(".", 1)[-1]
    logo_filename = f"logo_{current_user.company_id}.{file_ext}"

    artifact = await svc.save_artifact(
        file_bytes=content,
        file_name=logo_filename,
        mime_type=file.content_type or "image/png",
        file_category="images",
        origin=ORIGIN_USER,
        company_id=current_user.company_id,
        purpose="Company logo",
        generated_by="user-upload:company-logo",
    )

    # Update company logo URL to the artifact download endpoint
    from sqlalchemy import select
    result = await db.execute(select(Company).where(Company.id == current_user.company_id))
    company = result.scalar_one_or_none()

    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    company.logo_url = f"/api/v1/artifacts/{artifact.id}/download"
    await db.commit()
    await db.refresh(company)

    return company
