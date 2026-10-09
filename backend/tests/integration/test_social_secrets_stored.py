"""AU-25 through the real route and resolver, on Postgres (rolled back).

Both open their own sessions with ``AsyncSessionLocal``; it is pointed at the
test's session, as in ``test_write_idempotency.py``.
"""
from __future__ import annotations

import json
import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import text

from src.ai import social_router
from src.ai.social_connection_service import resolve_connection
from src.auth.dependencies import get_current_user_and_company
from src.common.orm_models import import_all_models

pytestmark = pytest.mark.needs_db

import_all_models()


@pytest.mark.asyncio
async def test_a_client_secret_is_stored_encrypted_and_resolves(db, monkeypatch):
    import src.common.database as database
    from src.auth.models import Company

    @asynccontextmanager
    async def _session():
        yield db

    monkeypatch.setattr(database, "AsyncSessionLocal", _session)
    monkeypatch.setattr(social_router, "AsyncSessionLocal", _session)

    company = Company(name=f"au25-{uuid.uuid4().hex[:6]}", type="TENANT", status="active")
    db.add(company)
    await db.flush()
    app = FastAPI()
    app.include_router(social_router.router)
    app.dependency_overrides[get_current_user_and_company] = lambda: (
        SimpleNamespace(id=None), SimpleNamespace(id=company.id))

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/api/v1/social-connections", json={
            "platform": "google_ads", "account_name": "ads", "access_token": "at-1",
            "oauth_metadata": {"client_id": "app-1", "client_secret": "cs-plain",
                               "developer_token": "dt-plain", "customer_id": "111"},
        })
        assert r.status_code == 201, r.text
        assert "cs-plain" not in r.text

    row = (await db.execute(text(
        "SELECT oauth_metadata::text FROM social_connections WHERE company_id = :c"),
        {"c": company.id})).scalar_one()
    assert "cs-plain" not in row and "dt-plain" not in row          # stored encrypted
    assert json.loads(row)["customer_id"] == "111"

    creds = await resolve_connection(str(company.id), "google_ads")
    assert creds["oauth_metadata"]["client_secret"] == "cs-plain"   # the resolver opens it
    assert creds["oauth_metadata"]["developer_token"] == "dt-plain"
