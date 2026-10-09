"""How often an address may open a live socket, and an endpoint take a webhook (GW-02).

The REST routes are limited per client IP by ``SlowAPIMiddleware``; nothing
limited the rest of the edge:

* **Live-socket handshakes** — ``/stream/audio``, ``/stream/video`` and
  ``/mobile/ws`` — are limited per client IP (``WS_HANDSHAKE_RATE_LIMIT``). An
  address over it is accepted and closed with ``4429``. The telephony media
  streams are not: they come from the provider's shared servers, and each is
  gated by its call (a session that exists and is fresh, GW-04; the call's
  admission, VT-01; the company's live-session cap, :mod:`src.voice.live_sessions`).
* **Webhook deliveries** are limited per endpoint — one company and one source —
  after the signature check (``WEBHOOK_RATE_LIMIT``), so unsigned requests
  cannot use up a tenant's allowance. Over it is a 429 with ``Retry-After``;
  the provider retries.

Counts live in the REST limiter's Redis. When Redis cannot be reached they are
kept in this process instead — still a limit (gate ``edge_rate_limit``).
"""
from __future__ import annotations

import logging
from typing import Any

from limits import parse
from limits.storage import MemoryStorage
from limits.strategies import FixedWindowRateLimiter

from src.common.config import settings
from src.common.rate_limit import limiter

logger = logging.getLogger(__name__)

__all__ = ["TOO_MANY", "handshake_allowed", "webhook_allowed", "client_address"]

# Application close code: HTTP 429's, as stream_auth uses 4401 / 4403.
TOO_MANY = 4429

_fallback = FixedWindowRateLimiter(MemoryStorage())


def _hit(limit_text: str, *identifiers: str) -> bool:
    """One more against ``limit_text`` for these identifiers; False when over it."""
    from src.common.gates import gate_failed

    item = parse(limit_text)
    try:
        return limiter.limiter.hit(item, *identifiers)
    except Exception as exc:                                                # noqa: BLE001
        gate_failed("edge_rate_limit", exc, decision="memory", limit=limit_text, key=identifiers[0])
        return _fallback.hit(item, *identifiers)


def client_address(websocket: Any) -> str:
    client = getattr(websocket, "client", None)
    return getattr(client, "host", None) or "unknown"


def handshake_allowed(websocket: Any) -> bool:
    """Whether this address may open another live socket now."""
    address = client_address(websocket)
    if _hit(settings.WS_HANDSHAKE_RATE_LIMIT, "ws-handshake", address):
        return True
    from src.ai.core.events import event
    event("gateway.socket.rate_limited", path=str(getattr(websocket, "url", "")), address=address)
    logger.warning("[SocketLimits] Handshake refused for %s: over %s", address, settings.WS_HANDSHAKE_RATE_LIMIT)
    return False


def webhook_allowed(endpoint_id: Any) -> bool:
    """Whether this webhook endpoint may take another signed delivery now."""
    return _hit(settings.WEBHOOK_RATE_LIMIT, "webhook-endpoint", str(endpoint_id))
