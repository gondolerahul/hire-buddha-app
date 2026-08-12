"""
Auth Middleware — Multi-channel tenant identity extraction.

Extracts tenant context from:
  REST:      Authorization: Bearer <JWT> | X-API-Key: <key>
  Webhook:   ?client_id=<uuid> query param + signature validation
  Internal:  X-Internal-Token: <shared_secret>   (bypasses tenant DB lookup)
  Audio/Video: WebSocket handshake query params ?client_id=&token=

Attaches TenantContext to request.state.tenant on success.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional
from uuid import UUID

from fastapi import Request, HTTPException, status
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# TenantContext — attached to request.state.tenant by middleware
# ---------------------------------------------------------------------------

@dataclass
class TenantContext:
    company_id: Optional[str] = None
    user_id: Optional[str] = None
    is_internal: bool = False       # True for internal service calls
    is_webhook: bool = False        # True for external webhook calls
    source_channel: str = "rest"    # "rest" | "webhook" | "internal" | "audio" | "video"
    raw_token: Optional[str] = None # For downstream logging only


# ---------------------------------------------------------------------------
# JWT decode helper (best-effort — does NOT raise if lib missing)
# ---------------------------------------------------------------------------

def _decode_jwt(token: str, secret: str, algorithm: str) -> Optional[dict]:
    try:
        from jose import jwt, JWTError
        return jwt.decode(token, secret, algorithms=[algorithm])
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------

class GatewayAuthMiddleware(BaseHTTPMiddleware):
    """
    Lightweight auth middleware for the unified gateway.

    ① Internal paths (/internal/event):  verified via X-Internal-Token header
    ② Webhook paths (/webhook/inbound):  extracted from ?client_id= query param
    ③ Audio/Video WebSocket paths:       extracted from ?client_id= query param
    ④ REST API paths (/api/v1/*):        JWT bearer or X-API-Key (passed through
                                         to backend; we only extract tenant_id here
                                         for routing/logging — auth enforced by backend)

    In all cases we attach request.state.tenant (a TenantContext).
    Missing / invalid credentials are NOT blocked here for REST / Webhook paths —
    the internal handlers enforce auth. Only /internal/event is blocked at middleware.
    """

    async def dispatch(self, request: Request, call_next):
        from src.gateway.gateway_config import settings

        path = request.url.path
        tenant = TenantContext()

        # ── ① Internal service calls ─────────────────────────────────────────
        if path.startswith("/internal/event"):
            token = request.headers.get("X-Internal-Token", "")
            if token != settings.INTERNAL_TOKEN:
                return _unauthorized("Invalid or missing X-Internal-Token")
            tenant.is_internal = True
            tenant.source_channel = "internal"

        # ── ② Webhook calls ──────────────────────────────────────────────────
        elif path.startswith("/webhook/inbound"):
            client_id = request.query_params.get("client_id", "")
            tenant.company_id = client_id or None
            tenant.is_webhook = True
            tenant.source_channel = "webhook"

        # ── ③ Audio/Video WebSocket ──────────────────────────────────────────
        elif path.startswith("/stream/audio") or path.startswith("/stream/video"):
            client_id = request.query_params.get("client_id", "")
            tenant.company_id = client_id or None
            tenant.source_channel = "audio" if "audio" in path else "video"

        # ── ④ REST API passthrough ───────────────────────────────────────────
        else:
            # Try to extract company_id for gateway-level logging / rate limiting
            auth_header = request.headers.get("Authorization", "")
            api_key = request.headers.get("X-API-Key", "")

            if auth_header.startswith("Bearer "):
                raw_token = auth_header[7:]
                tenant.raw_token = raw_token
                payload = _decode_jwt(
                    raw_token, settings.JWT_SECRET, settings.JWT_ALGORITHM
                )
                if payload:
                    tenant.user_id = payload.get("sub")
                    tenant.company_id = payload.get("company_id")
            elif api_key:
                # API keys are validated by the backend; we just log
                tenant.raw_token = api_key
            tenant.source_channel = "rest"

        request.state.tenant = tenant
        response = await call_next(request)
        return response


def _unauthorized(detail: str):
    from fastapi.responses import JSONResponse
    return JSONResponse(
        status_code=status.HTTP_401_UNAUTHORIZED,
        content={"error": "Unauthorized", "detail": detail},
    )


# ---------------------------------------------------------------------------
# Standalone FastAPI dependency (for use inside router endpoints)
# ---------------------------------------------------------------------------

def require_internal(request: Request) -> TenantContext:
    """Dependency: ensure request came through the internal channel."""
    tenant: TenantContext = getattr(request.state, "tenant", None)
    if not tenant or not tenant.is_internal:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="X-Internal-Token required",
        )
    return tenant


def get_tenant(request: Request) -> TenantContext:
    """Dependency: return tenant context (may be anonymous)."""
    return getattr(request.state, "tenant", TenantContext())
