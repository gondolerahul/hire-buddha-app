"""FE-28 through the real app and the real auth, on Postgres.

A missing artifact or run answers 404 only once the caller is authenticated, so
a 404 here means the token was accepted and a 401 that it was refused.
"""
from __future__ import annotations

import uuid

import httpx
import pytest
import pytest_asyncio

from src.auth import service
from src.common.database import get_db
from src.main import app

pytestmark = pytest.mark.needs_db


@pytest_asyncio.fixture
async def user(db):
    from src.auth.models import Company, User

    company = Company(name=f"fe28-{uuid.uuid4().hex[:6]}", type="TENANT", status="active")
    db.add(company)
    await db.flush()
    u = User(email=f"fe28-{uuid.uuid4().hex[:8]}@example.com", hashed_password="x", full_name="FE-28",
             role="tenant_admin", company_id=company.id, is_active=True, is_verified=True)
    db.add(u)
    await db.flush()
    return u


@pytest_asyncio.fixture
async def client(db):
    async def _db():
        yield db

    app.dependency_overrides[get_db] = _db
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
            yield c
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_minting_needs_a_login_and_a_known_scope(client, user):
    login = {"Authorization": f"Bearer {service.issue_access_token(user)}"}
    r = await client.post("/api/v1/auth/url-token", json={"scope": "/api/v1/artifacts/"}, headers=login)
    assert r.status_code == 200, r.text
    assert r.json()["expires_in"] == 600
    assert (await client.post("/api/v1/auth/url-token", json={"scope": "/"}, headers=login)).status_code == 422
    assert (await client.post("/api/v1/auth/url-token", json={"scope": "/api/v1/artifacts/"})).status_code == 401


@pytest.mark.asyncio
async def test_artifact_downloads_take_a_url_token_not_a_login(client, user):
    path = f"/api/v1/artifacts/{uuid.uuid4()}/download"
    url_token = service.issue_url_token(user, "/api/v1/artifacts/")
    assert (await client.get(f"{path}?token={url_token}")).status_code == 404       # accepted
    login = service.issue_access_token(user)
    assert (await client.get(f"{path}?token={login}")).status_code == 401           # refused in a URL
    assert (await client.get(path, headers={"Authorization": f"Bearer {login}"})).status_code == 404
    other = service.issue_url_token(user, "/api/v1/ai/executions/")
    assert (await client.get(f"{path}?token={other}")).status_code == 401           # another scope


@pytest.mark.asyncio
async def test_the_run_stream_takes_a_url_token_not_a_login(client, user):
    path = f"/api/v1/ai/executions/{uuid.uuid4()}/stream"
    url_token = service.issue_url_token(user, "/api/v1/ai/executions/")
    assert (await client.get(f"{path}?token={url_token}")).status_code == 404
    assert (await client.get(f"{path}?token={service.issue_access_token(user)}")).status_code == 401
