"""Refresh tokens are stored only as SHA-256 hashes (AU-10).

``refresh_tokens.token`` held each 7-day session credential in plaintext: a read
of the table was a set of working sessions. Runs against the real Postgres in
the suite's rolled-back transaction.
"""
from __future__ import annotations

import hashlib
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import select, text

pytestmark = pytest.mark.needs_db


async def _user(db, test_company_id):
    from src.auth.models import User
    user = User(email=f"au10-{uuid.uuid4().hex[:8]}@example.com", full_name="AU10", hashed_password="x",
                company_id=test_company_id, role="tenant_user")
    db.add(user)
    await db.flush()
    return user


@pytest.mark.asyncio
async def test_the_table_holds_a_hash_not_the_token(db, test_company_id):
    from src.auth import service
    from src.auth.models import RefreshToken

    user = await _user(db, test_company_id)
    token = await service.create_refresh_token(db, user.id)
    row = (await db.execute(select(RefreshToken).where(RefreshToken.user_id == user.id))).scalar_one()
    assert row.token_hash == hashlib.sha256(token.encode()).hexdigest()
    columns = (await db.execute(text(
        "SELECT column_name FROM information_schema.columns WHERE table_name = 'refresh_tokens'"
    ))).scalars().all()
    assert "token" not in columns
    stored = (await db.execute(text("SELECT token_hash FROM refresh_tokens WHERE user_id = :u"),
                               {"u": user.id})).scalar_one()
    assert token not in stored


@pytest.mark.asyncio
async def test_the_token_works_and_its_stored_hash_does_not(db, test_company_id):
    from src.auth import service
    from src.auth.models import RefreshToken

    user = await _user(db, test_company_id)
    token = await service.create_refresh_token(db, user.id)
    assert (await service.verify_refresh_token(db, token)).id == user.id
    leaked = (await db.execute(select(RefreshToken.token_hash).where(RefreshToken.user_id == user.id))).scalar_one()
    with pytest.raises(HTTPException) as exc:
        await service.verify_refresh_token(db, leaked)
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_rotation_finds_the_token_by_its_hash(db, test_company_id):
    from src.auth import service

    user = await _user(db, test_company_id)
    first = await service.create_refresh_token(db, user.id)
    second = await service.rotate_refresh_token(db, first)
    assert second != first
    assert (await service.verify_refresh_token(db, second)).id == user.id
    with pytest.raises(HTTPException):
        await service.rotate_refresh_token(db, first)
