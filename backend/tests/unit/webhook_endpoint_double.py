"""A registered webhook endpoint without a database, for the ingress unit tests.

``bind_endpoint`` makes ``load_endpoint`` return one endpoint for one id and
gives the delivery check an in-memory Redis; ``relay_headers`` signs a body the
way a relay does (``X-HB-Signature``).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from typing import Any

from src.gateway import webhook_inbound

SECRET = "unit-test-webhook-secret-0123456789"


def bind_endpoint(monkeypatch, *, source: str = "crm", company_id: uuid.UUID | None = None,
                  entity_id: uuid.UUID | None = None) -> webhook_inbound.BoundEndpoint:
    endpoint = webhook_inbound.BoundEndpoint(
        id=uuid.uuid4(), company_id=company_id or uuid.uuid4(), source=source,
        secret=SECRET, entity_id=entity_id,
    )

    async def load(db: Any, endpoint_id: str):
        return endpoint if endpoint_id == str(endpoint.id) else None

    async def mark(db: Any, endpoint_id: uuid.UUID) -> None:
        return None

    monkeypatch.setattr(webhook_inbound, "load_endpoint", load)
    monkeypatch.setattr(webhook_inbound, "_mark_received", mark)
    redis = MemoryRedis()
    monkeypatch.setattr(webhook_inbound, "shared_redis", lambda: redis)
    return endpoint


class MemoryRedis:
    """``SET NX EX`` and ``DELETE`` — what the delivery check uses."""

    def __init__(self) -> None:
        self.keys: dict[str, str] = {}

    async def set(self, key: str, value: str, nx: bool = False, ex: int | None = None):
        if nx and key in self.keys:
            return None
        self.keys[key] = value
        return True

    async def delete(self, key: str) -> int:
        return 1 if self.keys.pop(key, None) is not None else 0


def relay_headers(body: bytes, secret: str = SECRET) -> dict[str, str]:
    sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return {"X-HB-Signature": sig, "Content-Type": "application/json"}


def signed_json(payload: dict, secret: str = SECRET) -> tuple[bytes, dict[str, str]]:
    body = json.dumps(payload).encode()
    return body, relay_headers(body, secret)
