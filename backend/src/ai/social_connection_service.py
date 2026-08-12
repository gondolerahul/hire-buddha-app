"""
Social Connection Service — OAuth token resolution and auto-refresh.

Provides async methods for:
- Resolving decrypted credentials from the social_connections table
- Auto-refreshing expired OAuth tokens per platform
- Updating token status on failure
"""
import logging
import json
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional
from uuid import UUID as _UUID

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Platform-specific OAuth refresh configurations
# ---------------------------------------------------------------------------

PLATFORM_REFRESH_CONFIG: Dict[str, Dict[str, Any]] = {
    "linkedin": {
        "token_url": "https://www.linkedin.com/oauth/v2/accessToken",
        "grant_type": "refresh_token",
        "extra_params": {},
    },
    "twitter": {
        "token_url": "https://api.x.com/2/oauth2/token",
        "grant_type": "refresh_token",
        "extra_params": {},
    },
    "facebook": {
        "token_url": "https://graph.facebook.com/v22.0/oauth/access_token",
        "grant_type": "fb_exchange_token",
        "extra_params": {},
    },
    "instagram": {
        # Instagram uses the Facebook Graph API for token refresh
        "token_url": "https://graph.instagram.com/refresh_access_token",
        "grant_type": "ig_refresh_token",
        "extra_params": {},
    },
    "google_ads": {
        "token_url": "https://oauth2.googleapis.com/token",
        "grant_type": "refresh_token",
        "extra_params": {},
    },
    "youtube": {
        "token_url": "https://oauth2.googleapis.com/token",
        "grant_type": "refresh_token",
        "extra_params": {},
    },
    "tiktok": {
        "token_url": "https://open.tiktokapis.com/v2/oauth/token/",
        "grant_type": "refresh_token",
        "extra_params": {},
    },
    "reddit": {
        "token_url": "https://www.reddit.com/api/v1/access_token",
        "grant_type": "refresh_token",
        "extra_params": {},
    },
}

# Refresh tokens when less than this many minutes remain
TOKEN_REFRESH_THRESHOLD_MINUTES = 10


async def resolve_connection(
    company_id: Optional[str],
    platform: str,
    account_name: Optional[str] = None,
    platform_user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Look up social media credentials from the social_connections table.

    Returns a dict with decrypted access_token, refresh_token, and metadata.
    Returns empty dict if no matching connection is found.
    """
    if not company_id:
        return {}

    try:
        from src.common.database import AsyncSessionLocal
        from src.common.security import decrypt_api_key
        from sqlalchemy import select
        from src.ai.social_models import SocialConnection

        async with AsyncSessionLocal() as db:
            company_uuid = _UUID(str(company_id))
            query = (
                select(SocialConnection)
                .where(SocialConnection.company_id == company_uuid)
                .where(SocialConnection.platform == platform)
                .where(SocialConnection.is_active.is_(True))
            )

            if account_name:
                query = query.where(SocialConnection.account_name == account_name)
            if platform_user_id:
                query = query.where(SocialConnection.platform_user_id == platform_user_id)

            result = await db.execute(query)
            conn = result.scalars().first()

            if not conn:
                return {}

            # Check if token needs refresh
            credentials = {
                "connection_id": str(conn.id),
                "platform": conn.platform,
                "access_token": decrypt_api_key(conn.encrypted_access_token),
                "refresh_token": (
                    decrypt_api_key(conn.encrypted_refresh_token)
                    if conn.encrypted_refresh_token
                    else None
                ),
                "token_expires_at": conn.token_expires_at.isoformat() if conn.token_expires_at else None,
                "platform_user_id": conn.platform_user_id,
                "platform_page_id": conn.platform_page_id,
                "scopes": conn.scopes or [],
                "oauth_metadata": conn.oauth_metadata or {},
                "account_name": conn.account_name,
            }

            # Auto-refresh if token is expiring soon
            if conn.token_expires_at and conn.encrypted_refresh_token:
                threshold = datetime.now(timezone.utc) + timedelta(minutes=TOKEN_REFRESH_THRESHOLD_MINUTES)
                if conn.token_expires_at.replace(tzinfo=timezone.utc) < threshold:
                    logger.info(
                        f"[SocialConnSvc] Token for {platform}/{conn.account_name} "
                        f"expires at {conn.token_expires_at}, refreshing..."
                    )
                    refreshed = await _refresh_token(conn, credentials)
                    if refreshed:
                        credentials.update(refreshed)

            # Update last_used_at
            conn.last_used_at = datetime.utcnow()
            await db.commit()

            return credentials

    except Exception as e:
        logger.error(f"[SocialConnSvc] Failed to resolve connection: {e}")
        return {}


async def _refresh_token(conn, credentials: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Attempt to refresh the OAuth token using the platform's token endpoint.

    Returns updated credentials dict on success, None on failure.
    """
    platform = conn.platform
    config = PLATFORM_REFRESH_CONFIG.get(platform)
    if not config:
        logger.warning(f"[SocialConnSvc] No refresh config for platform: {platform}")
        return None

    refresh_token = credentials.get("refresh_token")
    if not refresh_token:
        logger.warning(f"[SocialConnSvc] No refresh token available for {platform}")
        return None

    try:
        # Get client credentials from oauth_metadata
        metadata = conn.oauth_metadata or {}
        client_id = metadata.get("client_id", "")
        client_secret = metadata.get("client_secret", "")

        if not client_id or not client_secret:
            logger.warning(
                f"[SocialConnSvc] Missing client_id/client_secret in oauth_metadata "
                f"for {platform}/{conn.account_name}"
            )
            return None

        payload = {
            "grant_type": config["grant_type"],
            "refresh_token": refresh_token,
            "client_id": client_id,
            "client_secret": client_secret,
            **config.get("extra_params", {}),
        }

        # Platform-specific adjustments
        if platform == "facebook":
            payload = {
                "grant_type": "fb_exchange_token",
                "client_id": client_id,
                "client_secret": client_secret,
                "fb_exchange_token": credentials.get("access_token", ""),
            }
        elif platform == "instagram":
            payload = {
                "grant_type": "ig_refresh_token",
                "access_token": credentials.get("access_token", ""),
            }

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(config["token_url"], data=payload)

        if resp.status_code != 200:
            logger.error(
                f"[SocialConnSvc] Token refresh failed for {platform}: "
                f"{resp.status_code} {resp.text}"
            )
            # Mark connection as token_expired
            await _update_connection_status(str(conn.id), "token_expired")
            return None

        data = resp.json()
        new_access_token = data.get("access_token")
        new_refresh_token = data.get("refresh_token", refresh_token)  # some platforms rotate
        expires_in = data.get("expires_in")  # seconds

        if not new_access_token:
            logger.error(f"[SocialConnSvc] No access_token in refresh response for {platform}")
            return None

        # Persist updated tokens
        new_expires_at = None
        if expires_in:
            new_expires_at = datetime.now(timezone.utc) + timedelta(seconds=int(expires_in))

        await _update_tokens(
            str(conn.id),
            new_access_token,
            new_refresh_token,
            new_expires_at,
        )

        logger.info(f"[SocialConnSvc] Successfully refreshed token for {platform}/{conn.account_name}")

        return {
            "access_token": new_access_token,
            "refresh_token": new_refresh_token,
            "token_expires_at": new_expires_at.isoformat() if new_expires_at else None,
        }

    except Exception as e:
        logger.error(f"[SocialConnSvc] Token refresh exception for {platform}: {e}")
        return None


async def _update_tokens(
    connection_id: str,
    access_token: str,
    refresh_token: Optional[str],
    expires_at: Optional[datetime],
) -> None:
    """Persist refreshed tokens to the database."""
    try:
        from src.common.database import AsyncSessionLocal
        from src.common.security import encrypt_api_key
        from sqlalchemy import update
        from src.ai.social_models import SocialConnection

        async with AsyncSessionLocal() as db:
            values = {
                "encrypted_access_token": encrypt_api_key(access_token),
                "token_expires_at": expires_at,
                "status": "active",
                "updated_at": datetime.utcnow(),
            }
            if refresh_token:
                values["encrypted_refresh_token"] = encrypt_api_key(refresh_token)

            await db.execute(
                update(SocialConnection)
                .where(SocialConnection.id == _UUID(connection_id))
                .values(**values)
            )
            await db.commit()
    except Exception as e:
        logger.error(f"[SocialConnSvc] Failed to update tokens: {e}")


async def _update_connection_status(connection_id: str, status: str) -> None:
    """Update the status of a social connection (e.g. on auth failure)."""
    try:
        from src.common.database import AsyncSessionLocal
        from sqlalchemy import update
        from src.ai.social_models import SocialConnection

        async with AsyncSessionLocal() as db:
            await db.execute(
                update(SocialConnection)
                .where(SocialConnection.id == _UUID(connection_id))
                .values(status=status, updated_at=datetime.utcnow())
            )
            await db.commit()
    except Exception as e:
        logger.error(f"[SocialConnSvc] Failed to update status: {e}")


async def list_connections(company_id: str, platform: Optional[str] = None) -> List[Dict[str, Any]]:
    """List all social connections for a company (without decrypting tokens)."""
    try:
        from src.common.database import AsyncSessionLocal
        from sqlalchemy import select
        from src.ai.social_models import SocialConnection

        async with AsyncSessionLocal() as db:
            query = (
                select(SocialConnection)
                .where(SocialConnection.company_id == _UUID(company_id))
            )
            if platform:
                query = query.where(SocialConnection.platform == platform)

            result = await db.execute(query)
            connections = result.scalars().all()

            return [
                {
                    "id": str(c.id),
                    "platform": c.platform,
                    "account_name": c.account_name,
                    "platform_user_id": c.platform_user_id,
                    "platform_page_id": c.platform_page_id,
                    "scopes": c.scopes or [],
                    "is_active": c.is_active,
                    "status": c.status,
                    "last_used_at": c.last_used_at.isoformat() if c.last_used_at else None,
                    "created_at": c.created_at.isoformat() if c.created_at else None,
                }
                for c in connections
            ]
    except Exception as e:
        logger.error(f"[SocialConnSvc] Failed to list connections: {e}")
        return []
