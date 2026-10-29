"""
Social Connections API Router.

Provides CRUD endpoints for managing social media platform connections
(OAuth token storage) for AI agent integrations.

Served at ``/api/v1/social-connections`` (API-15): it was the one business
route without the version segment. The old ``/api/social-connections`` answers
for one more release as a deprecated alias — each call is logged and its
response carries ``Deprecation: true`` and a ``Link`` to the new path — and is
then removed.
"""
import logging
from datetime import datetime
from typing import Optional, List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from src.auth.dependencies import get_current_user_and_company
from src.common.tenancy.session import tenant_session
from src.common.security import encrypt_api_key, decrypt_api_key
from src.ai.social_models import SocialConnection
from src.ai.social_connection_service import PLATFORM_REFRESH_CONFIG, seal_oauth_metadata
from src.ai import social_connection_service

from sqlalchemy import select, delete

logger = logging.getLogger(__name__)

_routes = APIRouter(tags=["Social Connections"])


# ---------------------------------------------------------------------------
# Request / Response Schemas
# ---------------------------------------------------------------------------

class SocialConnectionCreate(BaseModel):
    platform: str = Field(..., description="Platform name: linkedin, twitter, facebook, instagram, google_ads")
    account_name: Optional[str] = Field(None, description="Human-readable label for this connection")
    access_token: str = Field(..., description="OAuth access token")
    refresh_token: Optional[str] = Field(None, description="OAuth refresh token")
    token_expires_at: Optional[datetime] = Field(None, description="Token expiry timestamp (UTC)")
    platform_user_id: Optional[str] = Field(None, description="Platform-specific user/account ID")
    platform_page_id: Optional[str] = Field(None, description="Platform page/org ID (for page-level tokens)")
    scopes: Optional[List[str]] = Field(default=[], description="Granted OAuth scopes")
    oauth_metadata: Optional[dict] = Field(None, description="Extra platform metadata (client_id, client_secret, etc.)")


class SocialConnectionResponse(BaseModel):
    id: str
    platform: str
    account_name: Optional[str]
    platform_user_id: Optional[str]
    platform_page_id: Optional[str]
    scopes: Optional[List[str]]
    is_active: bool
    status: str
    last_used_at: Optional[str]
    created_at: Optional[str]

    class Config:
        from_attributes = True


class SocialConnectionListResponse(BaseModel):
    connections: List[SocialConnectionResponse]
    count: int


# quora left with its tools (TL-23): Quora publishes no API they could call.
# One list (D17): a platform a connection can be made for can be refreshed,
# and ``social_api`` has operations for it.
VALID_PLATFORMS = set(PLATFORM_REFRESH_CONFIG)


def _connector_only(platform: str) -> None:
    """LinkedIn and X connect on the Connections screen only (LI-E5, X-E7)."""
    from src.connections.client import CONNECTOR_ONLY

    if platform in CONNECTOR_ONLY:
        raise HTTPException(status_code=410, detail=(
            f"{platform} is connected on the Connections screen now; HireBuddha reaches it only through "
            "that connection"))


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@_routes.post("", response_model=SocialConnectionResponse, status_code=201)
async def create_social_connection(
    body: SocialConnectionCreate,
    auth=Depends(get_current_user_and_company),
):
    """Create a new social media connection with encrypted OAuth tokens."""
    user, company = auth

    if body.platform not in VALID_PLATFORMS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid platform '{body.platform}'. Must be one of: {sorted(VALID_PLATFORMS)}"
        )
    _connector_only(body.platform)

    async with tenant_session(company.id) as db:
        # Check for existing connection
        existing = await db.execute(
            select(SocialConnection).where(
                SocialConnection.company_id == company.id,
                SocialConnection.platform == body.platform,
                SocialConnection.platform_user_id == body.platform_user_id,
            )
        )
        if existing.scalars().first():
            raise HTTPException(
                status_code=409,
                detail=f"Connection already exists for {body.platform} / {body.platform_user_id}"
            )

        conn = SocialConnection(
            company_id=company.id,
            platform=body.platform,
            account_name=body.account_name,
            encrypted_access_token=encrypt_api_key(body.access_token),
            encrypted_refresh_token=encrypt_api_key(body.refresh_token) if body.refresh_token else None,
            token_expires_at=body.token_expires_at,
            platform_user_id=body.platform_user_id,
            platform_page_id=body.platform_page_id,
            scopes=body.scopes or [],
            oauth_metadata=seal_oauth_metadata(body.oauth_metadata),   # secrets encrypted (AU-25)
        )
        db.add(conn)
        await db.commit()
        await db.refresh(conn)

        logger.info(
            f"[SocialRouter] Created {body.platform} connection for company {company.id}"
        )

        return SocialConnectionResponse(
            id=str(conn.id),
            platform=conn.platform,
            account_name=conn.account_name,
            platform_user_id=conn.platform_user_id,
            platform_page_id=conn.platform_page_id,
            scopes=conn.scopes,
            is_active=conn.is_active,
            status=conn.status,
            last_used_at=conn.last_used_at.isoformat() if conn.last_used_at else None,
            created_at=conn.created_at.isoformat() if conn.created_at else None,
        )


@_routes.get("", response_model=SocialConnectionListResponse)
async def list_social_connections(
    platform: Optional[str] = None,
    auth=Depends(get_current_user_and_company),
):
    """List all social connections for the authenticated company."""
    user, company = auth
    connections = await social_connection_service.list_connections(
        str(company.id), platform=platform
    )
    return SocialConnectionListResponse(
        connections=[SocialConnectionResponse(**c) for c in connections],
        count=len(connections),
    )


@_routes.delete("/{connection_id}", status_code=204)
async def delete_social_connection(
    connection_id: UUID,
    auth=Depends(get_current_user_and_company),
):
    """Delete a social media connection."""
    user, company = auth

    async with tenant_session(company.id) as db:
        result = await db.execute(
            select(SocialConnection).where(
                SocialConnection.id == connection_id,
                SocialConnection.company_id == company.id,
            )
        )
        conn = result.scalars().first()
        if not conn:
            raise HTTPException(status_code=404, detail="Connection not found")

        await db.execute(
            delete(SocialConnection).where(SocialConnection.id == connection_id)
        )
        await db.commit()

        logger.info(
            f"[SocialRouter] Deleted connection {connection_id} for company {company.id}"
        )


@_routes.post("/{connection_id}/refresh", response_model=dict)
async def refresh_social_connection(
    connection_id: UUID,
    auth=Depends(get_current_user_and_company),
):
    """Manually trigger an OAuth token refresh for a connection."""
    user, company = auth

    async with tenant_session(company.id) as db:
        result = await db.execute(
            select(SocialConnection).where(
                SocialConnection.id == connection_id,
                SocialConnection.company_id == company.id,
            )
        )
        conn = result.scalars().first()
        if not conn:
            raise HTTPException(status_code=404, detail="Connection not found")
        _connector_only(conn.platform)

        if not conn.encrypted_refresh_token:
            raise HTTPException(
                status_code=400,
                detail="No refresh token available for this connection"
            )

        credentials = {
            "access_token": decrypt_api_key(conn.encrypted_access_token),
            "refresh_token": decrypt_api_key(conn.encrypted_refresh_token),
        }

        refreshed = await social_connection_service._refresh_token(conn, credentials)
        if refreshed:
            return {"status": "refreshed", "token_expires_at": refreshed.get("token_expires_at")}
        else:
            raise HTTPException(
                status_code=502,
                detail="Token refresh failed. Check logs for details."
            )


# ---------------------------------------------------------------------------
# Mounting: the versioned path, and the old one for one more release (API-15)
# ---------------------------------------------------------------------------

PATH = "/api/v1/social-connections"
LEGACY_PATH = "/api/social-connections"


def _deprecated_path(request: Request, response: Response) -> None:
    logger.warning("Deprecated path %s %s called; use %s", request.method, request.url.path, PATH)
    response.headers["Deprecation"] = "true"
    response.headers["Link"] = f'<{PATH}>; rel="successor-version"'


router = APIRouter()
router.include_router(_routes, prefix=PATH)
router.include_router(_routes, prefix=LEGACY_PATH, dependencies=[Depends(_deprecated_path)],
                      deprecated=True, include_in_schema=False)
