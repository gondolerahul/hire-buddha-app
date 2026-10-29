"""Security headers on every API response (SH-E5, GOOG-E9; CASA's baseline).

* ``Strict-Transport-Security`` — browsers keep to HTTPS for a year
  (``SECURITY_HSTS_SECONDS``; the gateway's routes send it too).
* ``X-Content-Type-Options: nosniff``, ``Referrer-Policy``, ``X-Frame-Options: DENY``.
* ``Content-Security-Policy`` — a JSON answer may load nothing and be framed
  by nobody; the API's few HTML pages (Meta's deletion status page) may use
  their own inline styles and nothing else. A route that sets its own policy
  keeps it (shared files are sandboxed, ``ai/artifact_router.py``); the API's
  own documentation pages load Swagger from a CDN and are left alone.

Pure ASGI, so streams (server-sent run traces) pass through untouched;
WebSockets are not HTTP responses and get nothing.
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

JSON_POLICY = "default-src 'none'; frame-ancestors 'none'"
HTML_POLICY = ("default-src 'none'; style-src 'unsafe-inline'; img-src 'self' data:; form-action 'self'; "
               "frame-ancestors 'none'; base-uri 'none'")
DOC_PATHS = ("/docs", "/redoc")


def headers_for(path: str, existing: List[Tuple[bytes, bytes]], hsts_seconds: int) -> List[Tuple[bytes, bytes]]:
    """The headers to add to a response of ``path`` that already has ``existing``."""
    have = {name.lower() for name, _ in existing}
    content_type = next((value for name, value in existing if name.lower() == b"content-type"), b"")
    added: Dict[bytes, bytes] = {
        b"x-content-type-options": b"nosniff",
        b"referrer-policy": b"strict-origin-when-cross-origin",
        b"x-frame-options": b"DENY",
    }
    if hsts_seconds > 0:
        added[b"strict-transport-security"] = f"max-age={hsts_seconds}; includeSubDomains".encode()
    if not path.startswith(DOC_PATHS):
        added[b"content-security-policy"] = (HTML_POLICY if content_type.startswith(b"text/html")
                                             else JSON_POLICY).encode()
    return [(name, value) for name, value in added.items() if name not in have]


class SecurityHeadersMiddleware:
    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        from src.common.config import settings

        if scope["type"] != "http" or not settings.SECURITY_HEADERS_ENABLED:
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")

        async def send_wrapper(message: Dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                existing = list(message.get("headers") or [])
                message["headers"] = existing + headers_for(path, existing, settings.SECURITY_HSTS_SECONDS)
            await send(message)

        await self.app(scope, receive, send_wrapper)
