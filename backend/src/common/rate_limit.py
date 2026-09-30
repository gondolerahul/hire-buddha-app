"""The API's per-client rate limit.

``RATE_LIMIT`` (default 200/minute) per client IP, counted in Redis, applied by
``SlowAPIMiddleware`` in ``main.py`` to every route. It is what the gateway on
:8001 applied to everything it proxied; the gateway is now merged into the API.
The inbound webhook and internal-event endpoints are ``@limiter.exempt`` — the
gateway never limited them. WebSockets and static mounts are not limited.

If Redis is unreachable the count falls back to process memory instead of
failing the request (the gateway's limiter returned a 500 on every request).
"""
from slowapi import Limiter
from slowapi.util import get_remote_address

from src.common.config import settings

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[settings.RATE_LIMIT],
    storage_uri=settings.REDIS_URL,
    in_memory_fallback_enabled=True,
)
