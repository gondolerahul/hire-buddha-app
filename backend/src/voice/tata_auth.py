"""Smartflo (Tata Tele) auth token resolution for account-level APIs.

The click-to-call ``api_key`` only authenticates the ``click_to_call*``
endpoints (it is sent inside the JSON payload). Account APIs such as
``/v1/call/hangup`` authenticate via the ``Authorization`` header and
require a Smartflo login JWT — sending the api_key there yields
``{"success": false, "message": "Deleted or blacklisted token provided"}``
(observed on all 42 hangup attempts in the Kanakia-Leads-01 run).

Resolution order:
  1. ``integration_registry.service_metadata["auth_token"]`` — a portal-issued
     long-lived token, if the tenant stored one.
  2. Login via ``service_metadata["login_email"]`` / ``["login_password"]``
     against ``POST /v1/auth/login`` (JWT cached in-process).
  3. Fall back to the click-to-call api_key (legacy behavior; known to fail
     on hangup but preserves the pre-existing request shape).
"""

import logging
from typing import Optional
from uuid import UUID

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from src.common.config import settings

logger = logging.getLogger(__name__)

SMARTFLO_BASE_URL = "https://api-smartflo.tatateleservices.com"

try:
    from cachetools import TTLCache
    _TOKEN_CACHE: TTLCache = TTLCache(
        maxsize=128, ttl=settings.TATA_AUTH_TOKEN_TTL_SECONDS
    )
    _CACHE_AVAILABLE = True
except ImportError:
    _TOKEN_CACHE = {}  # type: ignore[assignment]
    _CACHE_AVAILABLE = False


def bust_smartflo_token_cache(company_id: UUID) -> None:
    """Drop the cached login JWT for a company (e.g. after a 401)."""
    _TOKEN_CACHE.pop(str(company_id), None)


async def _login_for_token(email: str, password: str) -> Optional[str]:
    """Exchange portal credentials for a Smartflo login JWT."""
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{SMARTFLO_BASE_URL}/v1/auth/login",
                json={"email": email, "password": password},
                headers={"Content-Type": "application/json"},
                timeout=15.0,
            )
        data = resp.json()
        token = data.get("access_token") or data.get("token")
        if resp.status_code == 200 and token:
            logger.info("Smartflo login succeeded; JWT obtained")
            return token
        logger.error(
            f"Smartflo login failed: status={resp.status_code} "
            f"message={data.get('message', resp.text[:200])}"
        )
    except Exception as e:
        logger.error(f"Smartflo login request error: {e}")
    return None


async def get_smartflo_auth_token(
    db: AsyncSession, company_id: UUID, force_refresh: bool = False
) -> Optional[str]:
    """Resolve the Authorization-header token for Smartflo account APIs.

    Returns None only when no tata_tele integration exists at all.
    """
    cache_key = str(company_id)
    if force_refresh:
        bust_smartflo_token_cache(company_id)
    elif cache_key in _TOKEN_CACHE:
        return _TOKEN_CACHE[cache_key]

    from src.config.service import ConfigService

    config_service = ConfigService(db)
    entry = await config_service.get_integration_by_provider(
        company_id, "tata_tele"
    )
    if not entry:
        logger.warning(f"No tata_tele integration for company {company_id}")
        return None

    metadata = entry.service_metadata or {}

    token = metadata.get("auth_token")
    if token:
        _TOKEN_CACHE[cache_key] = token
        return token

    email = metadata.get("login_email")
    password = metadata.get("login_password")
    if email and password:
        token = await _login_for_token(email, password)
        if token:
            _TOKEN_CACHE[cache_key] = token
            return token

    logger.warning(
        "tata_tele integration has no auth_token or login credentials in "
        "service_metadata; falling back to api_key for the Authorization "
        "header — Smartflo account APIs (hangup) will likely reject it. "
        "Add service_metadata.auth_token (portal API token) or "
        "login_email/login_password to fix agent-initiated hangups."
    )
    api_key = await config_service.get_api_key_by_provider(
        company_id=company_id, provider_name="tata_tele"
    )
    return api_key
