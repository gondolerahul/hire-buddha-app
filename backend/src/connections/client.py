"""How tools get a credential (Phase 14 WS5 5.6, tech spec §10.5).

Tools no longer read credential tables. ``credentials_for(context, platform)``
finds the run's agent's usable connection of that platform — one it has been
granted — and asks the token broker for a credential, which refreshes it if
it is about to expire and audits the use. It answers in the shape the social
and e-mail tools already read (``access_token``, ``platform_page_id``, …).

Until WS7 has moved every business's old ``social_connections`` /
``email_connections`` rows, a business with no connection of that kind falls
back to them (``CONNECTIONS_LEGACY_FALLBACK``, on by default; WS9 removes it).
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# The old tools' platform names → the catalog connectors that serve them.
PLATFORM_CONNECTORS: Dict[str, List[str]] = {
    "facebook": ["facebook_pages"],
    "instagram": ["instagram_business"],
    "linkedin": ["linkedin_org"],
    "twitter": ["x_account"],
    "x": ["x_account"],
    "whatsapp": ["whatsapp_business"],
    "github": ["github"],
    "email": ["imap_mailbox", "gmail", "outlook_mail"],
    "google_drive": ["google_drive"],
}


def _principal(context: Optional[Dict[str, Any]]) -> tuple[Optional[str], Optional[str], Optional[str]]:
    ctx = context or {}
    return (str(ctx["company_id"]) if ctx.get("company_id") else None,
            str(ctx.get("entity_id") or ctx.get("agent_id") or "") or None,
            str(ctx["run_id"]) if ctx.get("run_id") else None)


def _social_shape(connection: Dict[str, Any], token: Any) -> Dict[str, Any]:
    settings = connection.get("settings") or {}
    extra = token.extra or {}
    return {
        "connection_id": connection["id"], "platform": connection["connector_id"],
        "access_token": token.access_token, "refresh_token": None,
        "token_expires_at": token.expires_at.isoformat() if token.expires_at else None,
        "platform_user_id": settings.get("user_id") or settings.get("instagram_account_id")
        or settings.get("organization_urn") or connection.get("external_account_id"),
        "platform_page_id": settings.get("page_id") or extra.get("page_id"),
        "scopes": connection.get("scopes") or [], "oauth_metadata": {**settings, **extra},
        "account_name": connection.get("external_account_name") or connection.get("display_name"),
        "source": "connections",
    }


async def credentials_for(context: Optional[Dict[str, Any]], platform: str, *, account: Optional[str] = None,
                          action: Optional[str] = None) -> Dict[str, Any]:
    """The run's agent's credential for ``platform`` (``{}`` when it has none)."""
    from src.common.config import settings
    from src.connections import service

    company_id, entity_id, run_id = _principal(context)
    if not company_id:
        return {}
    connectors = PLATFORM_CONNECTORS.get(platform, [])
    if connectors and entity_id:
        try:
            found = await service.connections_for(company_id, connectors, principal_kind="entity",
                                                  principal_id=entity_id, account=account)
        except Exception:  # noqa: BLE001 - a business without the tables yet (before its migration)
            logger.warning("connections not readable for company %s", company_id, exc_info=True)
            found = []
        for connection in found:
            try:
                token = await service.issue_token(company_id, connection["id"], principal_kind="entity",
                                                  principal_id=entity_id, action=action, run_id=run_id)
            except (service.NotGranted, service.ConnectionProblem) as error:
                logger.info("connection %s not usable for this run: %s", connection["id"], error)
                continue
            return _social_shape(connection, token)
    if not settings.CONNECTIONS_LEGACY_FALLBACK:
        return {}
    return await _legacy(company_id, platform, account)


async def _legacy(company_id: str, platform: str, account: Optional[str]) -> Dict[str, Any]:
    if platform == "email":
        from src.ai.tools.email.email_tool import _legacy_email_connection

        return await _legacy_email_connection(company_id, account)
    from src.ai.social_connection_service import resolve_connection

    return await resolve_connection(company_id=company_id, platform=platform, account_name=account)


async def email_credentials(context: Optional[Dict[str, Any]], email_address: Optional[str] = None) -> Dict[str, Any]:
    """A mailbox for the e-mail tools: IMAP/SMTP hosts and the password, or — for
    Gmail / Outlook connections — an OAuth access token (XOAUTH2)."""
    found = await credentials_for(context, "email", account=email_address)
    if not found or found.get("source") != "connections":
        return found
    meta = found.get("oauth_metadata") or {}
    if found["platform"] == "imap_mailbox":
        return {"email_address": meta.get("email_address"), "password": meta.get("password"),
                "imap_host": meta.get("imap_host"), "imap_port": meta.get("imap_port"),
                "smtp_host": meta.get("smtp_host"), "smtp_port": meta.get("smtp_port"),
                "connection_id": found["connection_id"]}
    hosts = {"gmail": ("imap.gmail.com", "smtp.gmail.com"), "outlook_mail": ("outlook.office365.com",
                                                                            "smtp.office365.com")}
    imap_host, smtp_host = hosts.get(found["platform"], (None, None))
    return {"email_address": meta.get("email"), "oauth_token": found["access_token"], "imap_host": imap_host,
            "imap_port": 993, "smtp_host": smtp_host, "smtp_port": 587, "connection_id": found["connection_id"]}
