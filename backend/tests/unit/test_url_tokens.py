"""FE-28: a URL the browser loads itself carries a short-lived, path-bound token.

Artifact previews, recordings and the run page's EventSource put the login
access token in ``?token=``; it then sat in server logs, the browser history and
Referer headers for the token's whole life. Query strings now take only a URL
token (``POST /auth/url-token``): minutes long, good under one path prefix.
"""
from __future__ import annotations

import uuid
from datetime import timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from src.auth import service
from src.auth.dependencies import _authenticate_user
from src.common.security import (URL_TOKEN_SCOPES, URL_TOKEN_TYPE, create_access_token,
                                 decode_access_token)

ARTIFACT = f"/api/v1/artifacts/{uuid.uuid4()}/download"
STREAM = f"/api/v1/ai/executions/{uuid.uuid4()}/stream"


class _Result:
    def __init__(self, value):
        self._value = value

    def scalars(self):
        return self

    def first(self):
        return self._value


class _DB:
    def __init__(self, user):
        self.user = user

    async def execute(self, _stmt):
        return _Result(self.user)


def _user(tv: int = 0):
    return SimpleNamespace(id=uuid.uuid4(), email="rep@example.com", company_id=uuid.uuid4(),
                           is_active=True, is_verified=True, token_version=tv,
                           company=SimpleNamespace(status="active"))


async def _url_auth(token: str, path: str, user):
    return await _authenticate_user(token, _DB(user), token_type=URL_TOKEN_TYPE, path=path)


def test_a_url_token_is_short_lived_and_scoped() -> None:
    claims = decode_access_token(service.issue_url_token(_user(), "/api/v1/artifacts/"))
    assert claims["type"] == URL_TOKEN_TYPE
    assert claims["scope"] == "/api/v1/artifacts/"
    import time
    assert 0 < claims["exp"] - time.time() <= 600 + 5


@pytest.mark.asyncio
async def test_a_url_token_opens_its_own_paths() -> None:
    user = _user()
    assert await _url_auth(service.issue_url_token(user, "/api/v1/artifacts/"), ARTIFACT, user) is user
    assert await _url_auth(service.issue_url_token(user, "/api/v1/ai/executions/"), STREAM, user) is user


@pytest.mark.asyncio
async def test_a_url_token_does_not_open_another_path() -> None:
    user = _user()
    with pytest.raises(HTTPException) as exc:
        await _url_auth(service.issue_url_token(user, "/api/v1/artifacts/"), STREAM, user)
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_a_login_token_is_refused_in_a_url() -> None:
    user = _user()
    with pytest.raises(HTTPException) as exc:
        await _url_auth(service.issue_access_token(user), ARTIFACT, user)
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_a_url_token_is_not_a_login() -> None:
    user = _user()
    with pytest.raises(HTTPException) as exc:
        await _authenticate_user(service.issue_url_token(user, "/api/v1/artifacts/"), _DB(user))
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_a_forged_scope_is_refused() -> None:
    user = _user()
    token = create_access_token({"sub": user.email, "type": URL_TOKEN_TYPE, "tv": 0, "scope": "/"})
    with pytest.raises(HTTPException):
        await _url_auth(token, ARTIFACT, user)


@pytest.mark.asyncio
async def test_an_expired_url_token_is_refused() -> None:
    user = _user()
    token = create_access_token({"sub": user.email, "type": URL_TOKEN_TYPE, "tv": 0,
                                 "scope": "/api/v1/artifacts/"}, expires_delta=timedelta(seconds=-1))
    with pytest.raises(HTTPException):
        await _url_auth(token, ARTIFACT, user)


@pytest.mark.asyncio
async def test_ending_sessions_ends_url_tokens() -> None:
    token = service.issue_url_token(_user(tv=0), "/api/v1/artifacts/")
    with pytest.raises(HTTPException):
        await _url_auth(token, ARTIFACT, _user(tv=1))


def test_the_scopes_are_the_routes_that_read_a_query_token() -> None:
    assert set(URL_TOKEN_SCOPES) == {"/api/v1/artifacts/", "/api/v1/ai/executions/"}
