"""
Social Connections API Router.

Provides CRUD endpoints for managing social media platform connections
(OAuth token storage) for AI agent integrations.
"""
import logging
from datetime import datetime
from typing import Optional, List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.auth.dependencies import get_current_user_and_company
from src.common.database import AsyncSessionLocal
from src.common.security import encrypt_api_key, decrypt_api_key
from src.ai.social_models import SocialConnection
from src.ai import social_connection_service

from sqlalchemy import select, delete

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/social-connections", tags=["Social Connections"])


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


VALID_PLATFORMS = {"linkedin", "twitter", "facebook", "instagram", "google_ads",
                   "youtube", "tiktok", "reddit", "quora"}


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("", response_model=SocialConnectionResponse, status_code=201)
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

    async with AsyncSessionLocal() as db:
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
            oauth_metadata=body.oauth_metadata,
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


@router.get("", response_model=SocialConnectionListResponse)
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


@router.delete("/{connection_id}", status_code=204)
async def delete_social_connection(
    connection_id: UUID,
    auth=Depends(get_current_user_and_company),
):
    """Delete a social media connection."""
    user, company = auth

    async with AsyncSessionLocal() as db:
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


@router.post("/{connection_id}/refresh", response_model=dict)
async def refresh_social_connection(
    connection_id: UUID,
    auth=Depends(get_current_user_and_company),
):
    """Manually trigger an OAuth token refresh for a connection."""
    user, company = auth

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(SocialConnection).where(
                SocialConnection.id == connection_id,
                SocialConnection.company_id == company.id,
            )
        )
        conn = result.scalars().first()
        if not conn:
            raise HTTPException(status_code=404, detail="Connection not found")

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
