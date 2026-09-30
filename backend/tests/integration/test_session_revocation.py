"""Sessions can be ended: logout, logout everywhere, refresh-token reuse (AU-05, AU-09, AU-12).

Before: no logout endpoint (sign-out only cleared the browser), access tokens
could not be revoked at all, and a revoked refresh token presented again — the
sign that it was copied — was refused and nothing else. ``users.token_version``
is carried in each access token as ``tv``; bumping it ends every session.

Runs against the real Postgres in the suite's rolled-back transaction.
"""
from __future__ import annotations

import uuid

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from sqlalchemy import select

pytestmark = pytest.mark.needs_db


async def _user(db, company_id):
    from src.auth.models import User
    user = User(email=f"au05-{uuid.uuid4().hex[:8]}@example.com", full_name="AU05", hashed_password="x",
                company_id=company_id, role="tenant_user", is_active=True, is_verified=True)
    db.add(user)
    await db.flush()
    await db.refresh(user)
    return user


async def _authenticates(db, token) -> bool:
    from src.auth.dependencies import _authenticate_user
    db.expire_all()
    try:
        await _authenticate_user(token, db)
        return True
    except HTTPException as exc:
        assert exc.status_code == 401
        return False


async def _refresh_works(db, token) -> bool:
    from src.auth import service
    try:
        await service.verify_refresh_token(db, token)
        return True
    except HTTPException:
        return False


@pytest.mark.asyncio
async def test_ending_all_sessions_ends_existing_access_tokens(db, test_company_id):
    from src.auth import service

    user = await _user(db, test_company_id)
    before = service.issue_access_token(user)
    assert await _authenticates(db, before)
    await service.revoke_all_sessions(db, user.id)
    await db.flush()
    assert not await _authenticates(db, before)
    await db.refresh(user)
    assert await _authenticates(db, service.issue_access_token(user))  # a new login works


@pytest.mark.asyncio
async def test_an_access_token_without_a_version_is_refused(db, test_company_id):
    from src.common.security import create_access_token

    user = await _user(db, test_company_id)
    assert not await _authenticates(db, create_access_token({"sub": user.email, "type": "access"}))


@pytest.mark.asyncio
async def test_reusing_a_rotated_refresh_token_ends_every_session(db, test_company_id):
    from src.auth import service

    user = await _user(db, test_company_id)
    access = service.issue_access_token(user)
    stolen = await service.create_refresh_token(db, user.id)
    _, current = await service.rotate_refresh_token(db, stolen)  # the real client rotates first
    with pytest.raises(HTTPException) as exc:
        await service.rotate_refresh_token(db, stolen)  # the copy is presented again
    assert exc.value.status_code == 401
    assert not await _refresh_works(db, current)
    assert not await _authenticates(db, access)


@pytest.mark.asyncio
async def test_logout_ends_this_session_only(db, test_company_id):
    from src.auth import service

    user = await _user(db, test_company_id)
    here = await service.create_refresh_token(db, user.id)
    elsewhere = await service.create_refresh_token(db, user.id)
    await service.logout(db, here)
    assert not await _refresh_works(db, here)
    assert await _refresh_works(db, elsewhere)
    assert await _authenticates(db, service.issue_access_token(user))


@pytest.mark.asyncio
async def test_logout_everywhere_ends_every_session(db, test_company_id):
    from src.auth import service

    user = await _user(db, test_company_id)
    access = service.issue_access_token(user)
    here = await service.create_refresh_token(db, user.id)
    elsewhere = await service.create_refresh_token(db, user.id)
    await service.logout(db, here, all_sessions=True)
    assert not await _refresh_works(db, here)
    assert not await _refresh_works(db, elsewhere)
    assert not await _authenticates(db, access)


@pytest.mark.asyncio
async def test_logging_out_twice_is_not_treated_as_reuse(db, test_company_id):
    from src.auth import service
    from src.auth.models import User

    user = await _user(db, test_company_id)
    token = await service.create_refresh_token(db, user.id)
    elsewhere = await service.create_refresh_token(db, user.id)
    await service.logout(db, token)
    await service.logout(db, token)
    assert await _refresh_works(db, elsewhere)
    version = (await db.execute(select(User.token_version).where(User.id == user.id))).scalar_one()
    assert version == 0


@pytest.mark.asyncio
async def test_the_logout_route(db, test_company_id):
    from src.auth import router as auth_router
    from src.auth import service
    from src.common.database import get_db

    user = await _user(db, test_company_id)
    token = await service.create_refresh_token(db, user.id)
    app = FastAPI()
    app.include_router(auth_router.router)

    async def _db():
        yield db

    app.dependency_overrides[get_db] = _db
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client:
        res = await client.post("/auth/logout", json={"refresh_token": token})
        unknown = await client.post("/auth/logout", json={"refresh_token": "never-issued"})
    assert res.status_code == 204 and unknown.status_code == 204
    assert not await _refresh_works(db, token)
