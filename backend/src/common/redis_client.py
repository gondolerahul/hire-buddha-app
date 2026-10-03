"""One short-timeout Redis client per event loop, for small reads and writes.

A redis-py asyncio client is bound to the loop it first ran on, so a
module-level client breaks when a second loop (a test, a worker) uses it.
Callers that must not hang on Redis — caches, gates — use this one: half a
second to connect or answer, then an error the caller decides about.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict

_clients: Dict[int, Any] = {}


def shared_redis() -> Any:
    import redis.asyncio as redis

    from src.common.config import settings

    loop_id = id(asyncio.get_running_loop())
    client = _clients.get(loop_id)
    if client is None:
        client = redis.from_url(settings.REDIS_URL, socket_connect_timeout=0.5, socket_timeout=0.5)
        _clients[loop_id] = client
    return client
