"""Who may open a live audio or video socket (GW-04).

``/stream/audio`` and ``/stream/video`` start a live AI session billed to a
company. Their handshake used to name the company in ``client_id`` and carry a
``token`` that nothing checked, so a company's UUID was enough to open one. The
handshake's ``token`` must now be a URL token minted for ``/stream/``
(``POST /api/v1/auth/url-token``); the company is the token's, and a
``client_id`` naming another company is refused.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

from fastapi import HTTPException, WebSocket

logger = logging.getLogger(__name__)

# Application close codes (4000–4999): the HTTP status they stand for, plus 4000.
UNAUTHORIZED = 4401
FORBIDDEN = 4403


async def _refuse(websocket: WebSocket, code: int, error: str, message: str) -> None:
    try:
        await websocket.send_text(json.dumps({"event": "error", "code": error, "message": message}))
    finally:
        await websocket.close(code=code, reason=message[:120])


async def stream_company(websocket: WebSocket, handshake: dict[str, Any]) -> Optional[str]:
    """The company the handshake's token belongs to; None once the socket is refused."""
    from src.auth.dependencies import authenticate_stream_token

    try:
        user = await authenticate_stream_token(handshake.get("token"), websocket.url.path)
    except HTTPException:
        logger.warning("[StreamAuth] Refused %s: no valid stream token", websocket.url.path)
        await _refuse(websocket, UNAUTHORIZED, "unauthorized",
                      "A stream token is required: POST /api/v1/auth/url-token with scope /stream/")
        return None
    company = str(user.company_id)
    claimed = handshake.get("client_id")
    if claimed and claimed != company:
        logger.warning("[StreamAuth] Refused %s: client_id %s is not the token's company",
                       websocket.url.path, claimed)
        await _refuse(websocket, FORBIDDEN, "forbidden", "client_id is not the token's company")
        return None
    return company
