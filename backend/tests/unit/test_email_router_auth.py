"""Every /email route needs a signed-in user (AU-02).

The five routes that create, list, delete and validate SMTP/IMAP credentials
depended on ``get_db`` alone; ``validate`` decrypted any connection's app
password and logged into the mailbox for an anonymous caller. The company
scoping is covered against the real database in
``tests/integration/test_email_connection_scope.py``.
"""
from __future__ import annotations

import uuid

import httpx
import pytest
from fastapi import FastAPI

from src.ai import email_router
from src.common.database import get_db

CONN = uuid.uuid4()
ROUTES = [
    ("GET", "/email/provider-defaults"),
    ("GET", "/email/connections"),
    ("POST", "/email/connections"),
    ("DELETE", f"/email/connections/{CONN}"),
    ("POST", f"/email/connections/{CONN}/validate"),
]


class _NoDB:
    async def execute(self, *a, **k):
        raise AssertionError("an anonymous request reached the database")


@pytest.mark.asyncio
@pytest.mark.parametrize("method,path", ROUTES)
async def test_anonymous_request_is_401_before_any_query(method, path):
    app = FastAPI()
    app.include_router(email_router.router)

    async def _db():
        yield _NoDB()

    app.dependency_overrides[get_db] = _db
    body = {"email_address": "a@example.com", "app_password": "x"} if method == "POST" else None
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client:
        res = await client.request(method, path, json=body)
    assert res.status_code == 401
