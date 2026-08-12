"""
Artifact Router — REST API for artifact management (list, upload, download, delete).
All routes are at /api/v1/artifacts.
"""
import logging
import mimetypes
from datetime import datetime
from pathlib import Path
from typing import Optional, List
from urllib.parse import urlparse, quote
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, Form, Query, status
from fastapi.security import OAuth2PasswordBearer
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

from src.common.database import get_db
from src.auth.router import get_current_user
from src.auth.models import User
from src.ai.artifact_service import ArtifactService, ORIGIN_USER, ORIGIN_SYSTEM

router = APIRouter(prefix="/api/v1/artifacts", tags=["Artifacts"])


# ─── Response schemas ──────────────────────────────────────────────────────────

class ArtifactResponse(BaseModel):
    id: str
    company_id: str
    campaign_id: Optional[str]
    agent_id: Optional[str]
    run_id: Optional[str]
    origin: str
    file_category: str
    file_name: str
    file_path: str
    file_size: Optional[int]
    mime_type: Optional[str]
    duration_seconds: Optional[int]
    purpose: Optional[str]
    generated_by: Optional[str]
    artifact_metadata: Optional[dict]
    created_at: datetime
    download_url: str

    class Config:
        from_attributes = True


def _to_response(artifact) -> dict:
    return {
        "id": str(artifact.id),
        "company_id": str(artifact.company_id),
        "campaign_id": str(artifact.campaign_id) if artifact.campaign_id else None,
        "agent_id": str(artifact.agent_id) if artifact.agent_id else None,
        "run_id": str(artifact.run_id) if artifact.run_id else None,
        "origin": artifact.origin,
        "file_category": artifact.file_category,
        "file_name": artifact.file_name,
        "file_path": artifact.file_path,
        "file_size": artifact.file_size,
        "mime_type": artifact.mime_type,
        "duration_seconds": artifact.duration_seconds,
        "purpose": artifact.purpose,
        "generated_by": artifact.generated_by,
        "artifact_metadata": artifact.artifact_metadata,
        "created_at": artifact.created_at.isoformat(),
        "download_url": f"/api/v1/artifacts/{artifact.id}/download",
    }


# ─── Endpoints ──────────────────────────────────────────────────────────────────

@router.get("", summary="List artifacts with optional filters")
async def list_artifacts(
    origin: Optional[str] = Query(None, description="user-uploads | system-generated"),
    file_category: Optional[str] = Query(None, description="recordings | images | videos | documents | text"),
    agent_id: Optional[UUID] = Query(None),
    campaign_id: Optional[UUID] = Query(None),
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    svc = ArtifactService(db)
    artifacts = await svc.list_artifacts(
        company_id=current_user.company_id,
        origin=origin,
        file_category=file_category,
        agent_id=agent_id,
        campaign_id=campaign_id,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        offset=offset,
    )
    return {"artifacts": [_to_response(a) for a in artifacts], "count": len(artifacts)}


@router.post("/upload", summary="Upload a new artifact file")
async def upload_artifact(
    file: UploadFile = File(...),
    file_category: str = Form(..., description="recordings | images | videos | documents | text"),
    campaign_id: Optional[UUID] = Form(None),
    agent_id: Optional[UUID] = Form(None),
    purpose: Optional[str] = Form(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    valid_categories = ("recordings", "images", "videos", "documents", "text")
    if file_category not in valid_categories:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"file_category must be one of: {', '.join(valid_categories)}",
        )

    svc = ArtifactService(db)
    artifact = await svc.save_upload(
        upload=file,
        file_category=file_category,
        company_id=current_user.company_id,
        campaign_id=campaign_id,
        agent_id=agent_id,
        purpose=purpose,
    )
    return _to_response(artifact)


@router.get("/{artifact_id}", summary="Get single artifact metadata")
async def get_artifact(
    artifact_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    svc = ArtifactService(db)
    artifact = await svc.get_artifact(artifact_id, current_user.company_id)
    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return _to_response(artifact)


@router.get("/{artifact_id}/download", summary="Download/stream artifact file")
async def download_artifact(
    artifact_id: UUID,
    request: Request,
    token: Optional[str] = Query(None, description="JWT token for media preview (alternative to Authorization header)"),
    db: AsyncSession = Depends(get_db),
    header_token: Optional[str] = Depends(OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token", auto_error=False)),
):
    # Authenticate via header token first, fall back to query token
    from src.auth.dependencies import _authenticate_user
    effective_token = header_token or token
    if not effective_token:
        raise HTTPException(status_code=401, detail="Could not validate credentials")
    current_user = await _authenticate_user(effective_token, db)

    svc = ArtifactService(db)
    artifact = await svc.get_artifact(artifact_id, current_user.company_id)
    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found")

    media_type = artifact.mime_type or mimetypes.guess_type(artifact.file_name)[0] or "application/octet-stream"

    # Some artifacts (e.g. call recordings) are stored as remote provider-hosted
    # URLs (Tata Tele / Twilio) rather than local files. Detect and proxy-stream
    # those so the client downloads through us without exposing the upstream URL.
    if _is_remote_url(artifact.file_path):
        return await _proxy_remote_file(
            url=artifact.file_path,
            filename=artifact.file_name,
            fallback_media_type=media_type,
            range_header=request.headers.get("range"),
        )

    file_path = Path(artifact.file_path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Artifact file not found on disk")

    return FileResponse(
        path=str(file_path),
        filename=artifact.file_name,
        media_type=media_type,
    )


def _is_remote_url(path: Optional[str]) -> bool:
    """True when the stored file_path is an http(s) URL rather than a disk path."""
    if not path:
        return False
    return urlparse(path).scheme in ("http", "https")


async def _proxy_remote_file(
    url: str,
    filename: str,
    fallback_media_type: str,
    range_header: Optional[str] = None,
) -> StreamingResponse:
    """
    Stream a remote (provider-hosted) file through the backend to the client.

    A client Range header is forwarded upstream so the inline audio player can seek;
    the upstream status (200 or 206) and range headers are passed back through. The
    upstream connection stays open for the lifetime of the generator and is closed
    when streaming finishes or the client disconnects.
    """
    upstream_headers = {"Range": range_header} if range_header else {}
    client = httpx.AsyncClient(follow_redirects=True, timeout=httpx.Timeout(30.0, read=300.0))
    try:
        req = client.build_request("GET", url, headers=upstream_headers)
        upstream = await client.send(req, stream=True)
    except httpx.HTTPError as e:
        await client.aclose()
        logger.warning(f"Failed to reach upstream artifact URL {url}: {e}")
        raise HTTPException(status_code=502, detail="Could not fetch recording from provider")

    if upstream.status_code not in (200, 206):
        await upstream.aclose()
        await client.aclose()
        logger.warning(f"Upstream artifact URL {url} returned {upstream.status_code}")
        raise HTTPException(status_code=404, detail="Artifact file not found at provider")

    async def _stream():
        try:
            async for chunk in upstream.aiter_bytes():
                yield chunk
        finally:
            await upstream.aclose()
            await client.aclose()

    media_type = upstream.headers.get("content-type") or fallback_media_type
    headers = {"Content-Disposition": f'attachment; filename="{quote(filename)}"'}
    # Pass through size / range metadata so the browser can show progress and seek.
    for h in ("content-length", "content-range", "accept-ranges"):
        if h in upstream.headers:
            headers[h] = upstream.headers[h]

    return StreamingResponse(
        _stream(),
        status_code=upstream.status_code,
        media_type=media_type,
        headers=headers,
    )


@router.delete("/{artifact_id}", summary="Delete an artifact")
async def delete_artifact(
    artifact_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    svc = ArtifactService(db)
    deleted = await svc.delete_artifact(artifact_id, current_user.company_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return {"message": "Artifact deleted successfully"}
