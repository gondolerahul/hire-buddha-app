"""One account per address, whatever case it is typed in (AU-26).

``EmailStr`` lower-cases only the domain and the unique index compares the text
as typed, so "Owner@x.com" and "owner@x.com" were two accounts, and a login
had to repeat the sign-up's case. Real Postgres, rolled back.
"""
from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

pytestmark = pytest.mark.needs_db


def test_inputs_are_lower_cased():
    from src.auth.schemas import EmailRequest, UserCreate, UserLogin

    assert UserCreate(email="Owner@Example.COM", password="x", full_name="o").email == "owner@example.com"
    assert UserLogin(email="OWNER@example.com", password="x").email == "owner@example.com"
    assert EmailRequest(email="Owner@example.com").email == "owner@example.com"


@pytest.mark.asyncio
async def test_signing_up_again_in_another_case_is_refused_and_login_ignores_case(db):
    from src.auth import service
    from src.auth.schemas import UserCreate, UserLogin

    local = f"au26-{uuid.uuid4().hex[:8]}"
    password = "a-long-enough-password"
    user = await service.create_user(db, UserCreate(email=f"{local}@example.com", password=password, full_name="o"))
    user.is_verified = True
    await db.flush()

    with pytest.raises(HTTPException) as exc:
        await service.create_user(db, UserCreate(email=f"{local.upper()}@Example.com", password=password,
                                                 full_name="o"))
    assert exc.value.status_code == 400

    signed_in = await service.authenticate_user(db, UserLogin(email=f"{local.upper()}@EXAMPLE.COM", password=password))
    assert signed_in and signed_in.id == user.id


@pytest.mark.asyncio
async def test_the_database_refuses_a_mixed_case_address(db, test_company_id):
    from src.auth.models import User

    db.add(User(email=f"AU26-{uuid.uuid4().hex[:8]}@example.com", full_name="x", hashed_password="x",
                company_id=test_company_id, role="tenant_user"))
    with pytest.raises(IntegrityError):
        await db.flush()
