"""Only an active user's login token authenticates a request (AU-04, AU-14).

``_authenticate_user`` read only the ``sub`` claim: any token signed with
``SECRET_KEY`` — an email-verification token included — worked as a login
token, and ``users.is_active`` was never read, so a deactivated user kept
logging in and calling every API.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from src.auth import service
from src.auth.dependencies import _authenticate_user
from src.auth.schemas import UserLogin
from src.common.security import create_access_token, get_password_hash


class _Result:
    def __init__(self, value):
        self._value = value

    def scalars(self):
        return self

    def first(self):
        return self._value


class _DB:
    def __init__(self, *values):
        self.values = list(values)

    async def execute(self, _stmt):
        return _Result(self.values.pop(0))

    async def commit(self):
        pass


def _user(active=True):
    return SimpleNamespace(id=uuid.uuid4(), email="rep@example.com", company_id=uuid.uuid4(),
                           is_active=active, is_verified=True, token_version=0, company=SimpleNamespace(status="active"),
                           hashed_password=get_password_hash("correct horse battery"))


@pytest.mark.asyncio
async def test_a_login_token_authenticates():
    user = _user()
    assert await _authenticate_user(service.issue_access_token(user), _DB(user)) is user


@pytest.mark.asyncio
@pytest.mark.parametrize("claims", [
    {"sub": "rep@example.com", "type": "email_verification"},
    {"sub": "rep@example.com"},  # untyped: minted by nothing that should sign in
    {"sub": "rep@example.com", "type": "password_reset"},
])
async def test_a_token_that_is_not_a_login_token_is_refused(claims):
    with pytest.raises(HTTPException) as exc:
        await _authenticate_user(create_access_token(claims), _DB(_user()))
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_a_deactivated_users_token_stops_working():
    user = _user(active=False)
    with pytest.raises(HTTPException) as exc:
        await _authenticate_user(service.issue_access_token(user), _DB(user))
    assert exc.value.status_code == 401
    assert "deactivated" in exc.value.detail


@pytest.mark.asyncio
async def test_a_deactivated_user_cannot_log_in_with_the_right_password():
    user = _user(active=False)
    with pytest.raises(HTTPException) as exc:
        await service.authenticate_user(_DB(user), UserLogin(email=user.email, password="correct horse battery"))
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_a_wrong_password_is_still_just_a_failed_login_for_a_deactivated_user():
    user = _user(active=False)
    # No 403 — that would confirm the account exists without the password.
    assert await service.authenticate_user(_DB(user), UserLogin(email=user.email, password="wrong")) is None


@pytest.mark.asyncio
async def test_a_deactivated_user_cannot_refresh():
    from datetime import datetime, timedelta
    user = _user(active=False)
    row = SimpleNamespace(revoked=False, expires_at=datetime.utcnow() + timedelta(days=1), user_id=user.id)
    with pytest.raises(HTTPException) as exc:
        await service.verify_refresh_token(_DB(row, user), "opaque")
    assert exc.value.status_code == 401


def test_oauth_login_refuses_a_deactivated_user():
    with pytest.raises(HTTPException) as exc:
        service.require_active(_user(active=False))
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_an_unverified_users_token_stops_working():
    user = _user()
    user.is_verified = False
    with pytest.raises(HTTPException) as exc:
        await _authenticate_user(service.issue_access_token(user), _DB(user))
    assert exc.value.status_code == 401 and "verify" in exc.value.detail
