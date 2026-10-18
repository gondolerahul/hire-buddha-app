"""
Artifact Router — REST API for artifact management (list, upload, download, delete).
All routes are at /api/v1/artifacts.
"""
import logging
import mimetypes
from datetime import datetime
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

from src.common.tenancy.session import get_control_db, get_tenant_db, is_split, tenant_db_for
from src.common.pagination import CursorParam, LimitParam, keyset, page_of
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
    run_id: Optional[UUID] = Query(None, description="A run's files, its child runs' included"),
    limit: int = LimitParam(),
    cursor: Optional[str] = CursorParam(),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_tenant_db),
):
    """One page of the company's files, newest first: ``items``,
    ``next_cursor``, ``limit`` (API-16; it was ``limit`` / ``offset`` and
    ``{"artifacts", "count"}``)."""
    from src.ai.artifact_models import Artifact

    query = ArtifactService(db).artifacts_query(
        run_id=run_id,
        company_id=current_user.company_id,
        origin=origin,
        file_category=file_category,
        agent_id=agent_id,
        campaign_id=campaign_id,
        date_from=date_from,
        date_to=date_to,
    )
    rows = (await db.execute(keyset(query, Artifact.created_at, Artifact.id, cursor, limit))).scalars().all()
    return page_of(rows, limit, items=[_to_response(a) for a in rows])


async def _require_own_links(db: AsyncSession, company_id: UUID, campaign_id: Optional[UUID],
                             agent_id: Optional[UUID]) -> None:
    """404 unless the campaign and agent an upload names belong to the uploader's company.

    The foreign keys only prove the rows exist; without this, a file could be
    attached to another company's campaign or agent (DM-18).
    """
    from sqlalchemy import select

    from src.ai.campaign_models import Campaign
    from src.ai.orm.entity import HierarchicalEntity

    if campaign_id is not None:
        owner = (await db.execute(select(Campaign.company_id).where(Campaign.id == campaign_id))).scalar_one_or_none()
        if owner != company_id:
            raise HTTPException(status_code=404, detail="Campaign not found")
    if agent_id is not None:
        owner = (await db.execute(
            select(HierarchicalEntity.company_id).where(HierarchicalEntity.id == agent_id)
        )).scalar_one_or_none()
        if owner != company_id:
            raise HTTPException(status_code=404, detail="Agent not found")


@router.post("/upload", summary="Upload a new artifact file")
async def upload_artifact(
    file: UploadFile = File(...),
    file_category: str = Form(..., description="recordings | images | videos | documents | text"),
    campaign_id: Optional[UUID] = Form(None),
    agent_id: Optional[UUID] = Form(None),
    purpose: Optional[str] = Form(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_tenant_db),
):
    valid_categories = ("recordings", "images", "videos", "documents", "text")
    if file_category not in valid_categories:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"file_category must be one of: {', '.join(valid_categories)}",
        )

    await _require_own_links(db, current_user.company_id, campaign_id, agent_id)
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
    db: AsyncSession = Depends(get_tenant_db),
):
    svc = ArtifactService(db)
    artifact = await svc.get_artifact(artifact_id, current_user.company_id)
    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return _to_response(artifact)


_TOKEN_QUERY = Query(None, description="A URL token from POST /api/v1/auth/url-token, for media the browser loads itself (FE-28)")
_HEADER_TOKEN = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token", auto_error=False)


async def _file_reader(request: Request, token: Optional[str], header_token: Optional[str],
                       db: AsyncSession) -> User:
    """A login token in the Authorization header; else a URL token for this
    path in ?token= — never a login token in the URL (FE-28)."""
    from src.auth.dependencies import _authenticate_user
    from src.common.security import URL_TOKEN_TYPE
    if header_token:
        return await _authenticate_user(header_token, db)
    if token:
        return await _authenticate_user(token, db, token_type=URL_TOKEN_TYPE, path=request.url.path)
    raise HTTPException(status_code=401, detail="Could not validate credentials")


def _media_type(artifact) -> str:
    return artifact.mime_type or mimetypes.guess_type(artifact.file_name)[0] or "application/octet-stream"


async def _file_response(artifact, request: Request, *, inline: bool = False):
    """The artifact's bytes from this API: the file itself on local disk, a
    stream from storage otherwise, or a proxied provider URL."""
    from src.ai.artifact_service import _legacy_local_file
    from src.common.platform.storage import StorageObjectNotFound, get_storage

    media_type = _media_type(artifact)
    disposition = "inline" if inline else "attachment"

    # Some artifacts (e.g. call recordings) are stored as remote provider-hosted
    # URLs (Tata Tele / Twilio) rather than local files. Detect and proxy-stream
    # those so the client downloads through us without exposing the upstream URL.
    if not artifact.storage_key and _is_remote_url(artifact.file_path):
        return await _proxy_remote_file(
            url=artifact.file_path,
            filename=artifact.file_name,
            fallback_media_type=media_type,
            range_header=request.headers.get("range"),
        )

    storage = get_storage()
    local = storage.local_path(artifact.storage_key) if artifact.storage_key else _legacy_local_file(artifact)
    if local is not None:
        if not local.is_file():
            raise HTTPException(status_code=404, detail="Artifact file not found in storage")
        return FileResponse(path=str(local), filename=artifact.file_name, media_type=media_type,
                            content_disposition_type=disposition)
    if not artifact.storage_key:
        raise HTTPException(status_code=404, detail="Artifact file not found in storage")

    size = await storage.size(artifact.storage_key)
    if size is None:
        raise HTTPException(status_code=404, detail="Artifact file not found in storage")
    stream = storage.open_stream(artifact.storage_key)
    try:
        first = await stream.__anext__()
    except StopAsyncIteration:
        first = b""
    except StorageObjectNotFound:
        raise HTTPException(status_code=404, detail="Artifact file not found in storage")

    async def _body():
        if first:
            yield first
        async for chunk in stream:
            yield chunk

    headers = {"Content-Disposition": f"{disposition}; filename*=UTF-8''{quote(artifact.file_name)}",
               "Content-Length": str(size)}
    return StreamingResponse(_body(), media_type=media_type, headers=headers)


@router.get("/{artifact_id}/download", summary="Download/stream artifact file")
async def download_artifact(
    artifact_id: UUID,
    request: Request,
    token: Optional[str] = _TOKEN_QUERY,
    db: AsyncSession = Depends(get_control_db),
    header_token: Optional[str] = Depends(_HEADER_TOKEN),
):
    """The bytes through the API whatever the storage — what the app's
    authenticated XHR downloads use (no cross-origin redirect)."""
    current_user = await _file_reader(request, token, header_token, db)
    async with tenant_db_for(db, current_user.company_id) as tenant_db:
        artifact = await ArtifactService(tenant_db).get_artifact(artifact_id, current_user.company_id)
        if not artifact:
            raise HTTPException(status_code=404, detail="Artifact not found")
        return await _file_response(artifact, request)


# ─── Signed file links (Phase 14 WS1 1.3) ───────────────────────────────────────
# GET /api/v1/files/{id}: the caller is authorised for the artifact, then sent to
# a short-lived signed URL at the storage (Blob SAS), so the bytes never pass
# through the API; on local disk the API serves them. It replaces the static
# /artifact, /uploads and /reports mounts for anything the browser loads itself.

files_router = APIRouter(prefix="/api/v1/files", tags=["Files"])


@files_router.get("/{artifact_id}", summary="Open an artifact's file: a signed link, or the bytes")
async def open_file(
    artifact_id: UUID,
    request: Request,
    inline: bool = Query(False, description="Display in the browser instead of downloading"),
    token: Optional[str] = _TOKEN_QUERY,
    db: AsyncSession = Depends(get_control_db),
    header_token: Optional[str] = Depends(_HEADER_TOKEN),
):
    current_user = await _file_reader(request, token, header_token, db)
    async with tenant_db_for(db, current_user.company_id) as tenant_db:
        artifact = await ArtifactService(tenant_db).get_artifact(artifact_id, current_user.company_id)
        if not artifact:
            raise HTTPException(status_code=404, detail="Artifact not found")
        return await _signed_or_served(artifact, request, inline=inline)


@files_router.get("/{artifact_id}/public", summary="A public image (an agent avatar)")
async def open_public_file(artifact_id: UUID, request: Request,
                           company: Optional[UUID] = Query(None, description=(
                               "The company that owns the file; with split tenancy the URL "
                               "names it (public_file_url)")),
                           db: AsyncSession = Depends(get_control_db)):
    """Files marked public when saved — avatars shown wherever an agent is.
    Anything else is 404, as if it did not exist."""
    from sqlalchemy import select

    from src.ai.artifact_models import Artifact
    from src.common.tenancy.directory import TenantNotFound, TenantNotReady

    if is_split() and company is None:
        raise HTTPException(status_code=404, detail="Not found")
    try:
        async with tenant_db_for(db, company) as tenant_db:
            artifact = (await tenant_db.execute(
                select(Artifact).where(Artifact.id == artifact_id))).scalar_one_or_none()
    except (TenantNotFound, TenantNotReady):
        artifact = None
    if artifact is None or not (artifact.artifact_metadata or {}).get("public"):
        raise HTTPException(status_code=404, detail="Not found")
    response = await _signed_or_served(artifact, request, inline=True)
    # Served from the API's own origin (local disk): an SVG avatar must not run script there.
    response.headers["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'; sandbox"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


def public_file_url(artifact_id: UUID, company_id: UUID) -> str:
    """Where a public file is served. With split tenancy the URL names the
    company, whose database holds the file's row."""
    url = f"/api/v1/files/{artifact_id}/public"
    return f"{url}?company={company_id}" if is_split() else url


async def _signed_or_served(artifact, request: Request, *, inline: bool):
    from fastapi.responses import RedirectResponse

    from src.common.config import settings
    from src.common.platform.storage import get_storage

    if artifact.storage_key:
        url = await get_storage().signed_url(
            artifact.storage_key, ttl_seconds=settings.STORAGE_SIGNED_URL_TTL_SECONDS,
            file_name=None if inline else artifact.file_name, content_type=_media_type(artifact))
        if url:
            return RedirectResponse(url, status_code=302, headers={"Cache-Control": "private, no-store"})
    return await _file_response(artifact, request, inline=inline)


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
    db: AsyncSession = Depends(get_tenant_db),
):
    svc = ArtifactService(db)
    deleted = await svc.delete_artifact(artifact_id, current_user.company_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return {"message": "Artifact deleted successfully"}
