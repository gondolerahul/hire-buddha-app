"""What every provider adapter does (Phase 14 WS5 5.4, tech spec §10.5).

A provider turns HireBuddha's app (``ProviderApp``) and the business's consent
into **accounts** — the Pages, numbers, organisations, installations or
mailboxes that become connections — and later keeps their tokens usable.

``secret`` is the sealed part of a connection (tokens, passwords, keys);
``settings`` the non-secret part (page id, WABA id, installation id, host).
Nothing here touches a database: the service (``connections/service.py``)
stores what an adapter returns.
"""
from __future__ import annotations

import base64
import hashlib
import secrets as pysecrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import httpx

__all__ = ["Account", "AccessToken", "Provider", "ProviderError", "http", "pkce_pair", "set_transport"]


class ProviderError(RuntimeError):
    """The provider refused or failed; the message is safe to show (no secrets)."""


@dataclass
class Account:
    external_id: str
    name: str
    secret: Dict[str, Any] = field(default_factory=dict)
    settings: Dict[str, Any] = field(default_factory=dict)
    scopes: List[str] = field(default_factory=list)
    expires_at: Optional[datetime] = None

    def public(self) -> Dict[str, Any]:
        """What the "choose accounts" step may show."""
        return {"external_id": self.external_id, "name": self.name, "settings": self.settings}


@dataclass
class AccessToken:
    """What a tool or app is handed for one use (never logged)."""
    access_token: Optional[str]
    expires_at: Optional[datetime] = None
    extra: Dict[str, Any] = field(default_factory=dict)


# Tests replace the transport (httpx.MockTransport) to play the provider.
_transport: Optional[httpx.AsyncBaseTransport] = None


def set_transport(transport: Optional[httpx.AsyncBaseTransport]) -> None:
    global _transport
    _transport = transport


def http(timeout: float = 30.0) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=_transport, timeout=timeout)


def pkce_pair() -> tuple[str, str]:
    """``(verifier, S256 challenge)`` (RFC 7636)."""
    verifier = pysecrets.token_urlsafe(64)[:96]
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def expires_in(seconds: Any) -> Optional[datetime]:
    try:
        return datetime.utcnow() + timedelta(seconds=int(seconds)) if seconds else None
    except (TypeError, ValueError):
        return None


def raise_for(response: httpx.Response, what: str) -> Dict[str, Any]:
    """The JSON body, or a :class:`ProviderError` that names the step and the provider's message."""
    try:
        body = response.json()
    except ValueError:
        body = {}
    if response.status_code >= 400:
        detail = ""
        if isinstance(body, dict):
            error = body.get("error")
            detail = (error.get("message") if isinstance(error, dict) else None) or body.get("error_description") \
                or body.get("message") or (error if isinstance(error, str) else "")
        raise ProviderError(f"{what} failed ({response.status_code}){': ' + str(detail)[:300] if detail else ''}")
    return body if isinstance(body, dict) else {"data": body}


class Provider:
    """Defaults for a provider; each adapter overrides what it supports."""

    name = "base"
    uses_pkce = False

    async def authorize_url(self, app: Any, connector: Any, *, state: str, redirect_uri: str,
                            code_challenge: Optional[str]) -> str:
        raise ProviderError(f"{self.name} has no browser sign-in")

    async def exchange(self, app: Any, connector: Any, params: Dict[str, Any], *, redirect_uri: str,
                       code_verifier: Optional[str]) -> List[Account]:
        raise ProviderError(f"{self.name} has no browser sign-in")

    async def from_form(self, connector: Any, fields: Dict[str, Any]) -> Account:
        raise ProviderError(f"{self.name} is not connected with a form")

    async def refresh(self, app: Any, connector: Any, settings: Dict[str, Any],
                      secret: Dict[str, Any]) -> Optional[tuple[Dict[str, Any], Optional[datetime]]]:
        """``(new secret, expires at)``; ``None`` when there is nothing to refresh."""
        return None

    async def access(self, app: Any, connector: Any, settings: Dict[str, Any],
                     secret: Dict[str, Any]) -> AccessToken:
        return AccessToken(access_token=secret.get("access_token"), extra={})

    async def test(self, app: Any, connector: Any, settings: Dict[str, Any],
                   secret: Dict[str, Any]) -> Dict[str, Any]:
        return {"ok": True, "detail": "nothing to check"}

    async def after_connect(self, app: Any, connector: Any, settings: Dict[str, Any],
                            secret: Dict[str, Any]) -> Dict[str, Any]:
        """Provider-side set-up once connected (webhook subscriptions); returns settings to keep."""
        return {}

    async def revoke(self, app: Any, connector: Any, settings: Dict[str, Any], secret: Dict[str, Any]) -> None:
        return None
