"""SA-18: a suspended company is refused once per request, by the auth dependency.

CompanySuspensionMiddleware decoded the bearer token itself, opened its own
database session and loaded the company on every request with a token —
before routing, so even a 404 paid for it — and then get_current_user loaded
the same company again and refused a suspended one with the same 403. The
middleware is deleted; the dependency is the check. On the local stack one
authenticated GET /api/v1/users went from 4 SQL statements to 3.
"""
import importlib.util
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from src.auth.dependencies import _authenticate_user
from src.common.security import create_access_token
from src.main import app


class _FakeResult:
    def __init__(self, user):
        self._user = user

    def scalars(self):
        return self

    def first(self):
        return self._user


class _FakeSession:
    def __init__(self, user):
        self.user = user
        self.queries = 0

    async def execute(self, _statement):
        self.queries += 1
        return _FakeResult(self.user)


def _user(status: str):
    return SimpleNamespace(email="rep@acme.test", is_active=True, token_version=0, company=SimpleNamespace(status=status))


def test_the_middleware_is_gone():
    assert importlib.util.find_spec("src.common.middleware") is None
    assert "CompanySuspensionMiddleware" not in {m.cls.__name__ for m in app.user_middleware}


async def test_a_suspended_company_is_refused_by_the_dependency():
    token = create_access_token(data={"sub": "rep@acme.test", "company_id": "c1", "type": "access", "tv": 0})
    db = _FakeSession(_user("suspended"))
    with pytest.raises(HTTPException) as exc:
        await _authenticate_user(token, db)
    assert exc.value.status_code == 403
    assert "suspended" in exc.value.detail
    assert db.queries == 1          # the user, with its company eager-loaded


async def test_an_active_company_passes():
    token = create_access_token(data={"sub": "rep@acme.test", "company_id": "c1", "type": "access", "tv": 0})
    user = _user("active")
    assert await _authenticate_user(token, _FakeSession(user)) is user
