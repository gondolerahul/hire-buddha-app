"""An OAuth login signs in only as an address the provider has verified (AU-23).

The login links to the existing account with the provider's email. Microsoft's
``mail`` attribute is set by the user's own tenant admin, so an attacker's
Entra tenant could name any victim's address and sign in as them; Google's
``email`` was used without ``email_verified``.
"""
from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

_RealClient = httpx.AsyncClient  # the test's own client; the router's is replaced


class _FakeResponse:
    def __init__(self, status_code: int, body: dict):
        self.status_code, self._body = status_code, body

    def json(self) -> dict:
        return self._body


def _fake_client(user_info: dict):
    class FakeClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, data=None):
            return _FakeResponse(200, {"access_token": "provider-token"})

        async def get(self, url, headers=None):
            return _FakeResponse(200, user_info)

    return FakeClient


@pytest.fixture
def login(monkeypatch):
    from src.auth import router as auth_router
    from src.common.database import get_db

    linked: list[str] = []

    async def fake_get_or_create(db, email, name):
        linked.append(email)
        return SimpleNamespace(id="u1", is_active=True, is_verified=True, company_id="c1",
                               email=email, token_version=0, role="tenant_admin")

    async def fake_refresh(db, user_id):
        return "refresh"

    monkeypatch.setattr(auth_router.service, "get_or_create_oauth_user", fake_get_or_create)
    monkeypatch.setattr(auth_router.service, "create_refresh_token", fake_refresh)
    monkeypatch.setattr(auth_router.service, "issue_access_token", lambda user: "access")

    app = FastAPI()
    app.include_router(auth_router.router, prefix="/api/v1")

    async def _db():
        yield None

    app.dependency_overrides[get_db] = _db

    async def call(provider: str, user_info: dict):
        monkeypatch.setattr(auth_router.httpx, "AsyncClient", _fake_client(user_info))
        async with _RealClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
            res = await c.post(f"/api/v1/auth/oauth/{provider}", json={"code": "x", "redirect_uri": "http://r"})
        return res, list(linked)

    return call


@pytest.mark.asyncio
async def test_microsoft_identity_is_the_upn_not_the_tenant_set_mail(login):
    res, linked = await login("microsoft", {
        "mail": "victim@customer.com",  # any tenant admin can type this
        "userPrincipalName": "Attacker@evil.onmicrosoft.com",
        "displayName": "a",
    })
    assert res.status_code == 200
    assert linked == ["attacker@evil.onmicrosoft.com"]


@pytest.mark.asyncio
async def test_google_requires_a_verified_email(login):
    res, linked = await login("google", {"email": "victim@customer.com", "email_verified": False, "name": "a"})
    assert res.status_code == 400 and linked == []
    res, linked = await login("google", {"email": "Owner@customer.com", "email_verified": True, "name": "o"})
    assert res.status_code == 200 and linked == ["owner@customer.com"]
