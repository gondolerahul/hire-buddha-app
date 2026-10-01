"""An OAuth login into an existing account finds it by address and verifies it (AU-23).

The provider has proved the address, so an account that never clicked its
verification link is verified rather than left unable to use the API. The
lookup ignores case. Real Postgres, rolled back.
"""
from __future__ import annotations

import uuid

import pytest

pytestmark = pytest.mark.needs_db


@pytest.mark.asyncio
async def test_an_existing_unverified_account_is_found_and_verified(db, test_company_id):
    from src.auth.models import User
    from src.auth.service import get_or_create_oauth_user

    local = f"au23-{uuid.uuid4().hex[:8]}"
    user = User(email=f"{local}@Example.com", full_name="x", hashed_password="x", company_id=test_company_id,
                role="tenant_admin", is_verified=False)
    db.add(user)
    await db.flush()

    found = await get_or_create_oauth_user(db, f"{local}@example.com", "x")
    assert found.id == user.id and found.is_verified is True
