"""
Shared fixtures for E2E tests.
Uses httpx.AsyncClient against the real FastAPI app + live PostgreSQL.
"""
import os
import sys
import uuid
import pytest
import pytest_asyncio
import httpx

# Ensure backend src is on path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from src.main import app  # noqa: E402

# ---------------------------------------------------------------------------
# Unique per-session suffix to isolate test data
# ---------------------------------------------------------------------------
TEST_ID = uuid.uuid4().hex[:8]


def _email(role: str) -> str:
    return f"e2e_{role}_{TEST_ID}@test.hirebuddha.com"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture(scope="session")
async def client():
    """Async HTTP client bound to the FastAPI app."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as c:
        yield c


# -- helper: register + login -------------------------------------------------

async def register_and_login(client: httpx.AsyncClient, email: str, password: str, full_name: str):
    """Register a user (ignore duplicate) then login and return token."""
    await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "full_name": full_name},
    )
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    data = resp.json()
    return data.get("access_token"), data.get("refresh_token")


def auth_headers(token: str) -> dict:
    """Return headers dict with Bearer token."""
    return {"Authorization": f"Bearer {token}"}


# -- bootstrap an app_admin user -----------------------------------------------
# The very first user registered through /register gets a default company.
# We then need to patch them to app_admin via DB.  For simplicity, if an
# app_admin already exists we just login.

@pytest_asyncio.fixture(scope="session")
async def app_admin_token(client: httpx.AsyncClient):
    """Register (or login) the app_admin user and return the access_token."""
    email = _email("appadmin")
    password = "Test1234!"
    token, _ = await register_and_login(client, email, password, "E2E App Admin")
    if not token:
        pytest.skip("Could not create app_admin user – check if DB is reachable")

    # Patch role to app_admin directly through internal import
    from src.common.database import AsyncSessionLocal
    from src.auth.models import User
    from sqlalchemy import select, update

    async with AsyncSessionLocal() as db:
        await db.execute(
            update(User).where(User.email == email).values(role="app_admin")
        )
        await db.commit()

    # Re-login to get a token that carries the new role
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    return resp.json()["access_token"]


@pytest_asyncio.fixture(scope="session")
async def app_admin_company_id(app_admin_token, client: httpx.AsyncClient):
    """Return the company_id of the app_admin user."""
    resp = await client.get("/api/v1/auth/me", headers=auth_headers(app_admin_token))
    return resp.json()["company_id"]


# -- partner setup ------------------------------------------------------------

@pytest_asyncio.fixture(scope="session")
async def test_partner(app_admin_token, client: httpx.AsyncClient):
    """Create a PARTNER company. Returns dict with id."""
    resp = await client.post(
        "/api/v1/companies",
        headers=auth_headers(app_admin_token),
        json={"name": f"E2E Partner {TEST_ID}", "type": "PARTNER", "status": "active"},
    )
    assert resp.status_code == 200, f"Failed to create partner: {resp.text}"
    return resp.json()


@pytest_asyncio.fixture(scope="session")
async def partner_admin_token(test_partner, app_admin_token, client: httpx.AsyncClient):
    """Register a partner_admin user and return access_token."""
    email = _email("partneradmin")
    password = "Test1234!"
    # Register
    await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "full_name": "E2E Partner Admin"},
    )
    # Patch company + role
    from src.common.database import AsyncSessionLocal
    from src.auth.models import User
    from sqlalchemy import update

    async with AsyncSessionLocal() as db:
        await db.execute(
            update(User)
            .where(User.email == email)
            .values(role="partner_admin", company_id=test_partner["id"])
        )
        await db.commit()

    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    return resp.json()["access_token"]


# -- tenant setup ------------------------------------------------------------

@pytest_asyncio.fixture(scope="session")
async def test_tenant(app_admin_token, test_partner, client: httpx.AsyncClient):
    """Create a TENANT company under the partner. Returns dict."""
    resp = await client.post(
        "/api/v1/companies",
        headers=auth_headers(app_admin_token),
        json={
            "name": f"E2E Tenant {TEST_ID}",
            "type": "TENANT",
            "status": "active",
            "parent_id": test_partner["id"],
        },
    )
    assert resp.status_code == 200, f"Failed to create tenant: {resp.text}"
    return resp.json()


@pytest_asyncio.fixture(scope="session")
async def tenant_admin_token(test_tenant, client: httpx.AsyncClient):
    """Register a tenant_admin user and return access_token."""
    email = _email("tenantadmin")
    password = "Test1234!"
    await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "full_name": "E2E Tenant Admin"},
    )
    from src.common.database import AsyncSessionLocal
    from src.auth.models import User
    from sqlalchemy import update

    async with AsyncSessionLocal() as db:
        await db.execute(
            update(User)
            .where(User.email == email)
            .values(role="tenant_admin", company_id=test_tenant["id"])
        )
        await db.commit()

    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    return resp.json()["access_token"]


@pytest_asyncio.fixture(scope="session")
async def tenant_admin_company_id(test_tenant):
    return test_tenant["id"]


# -- regular user token -------------------------------------------------------

@pytest_asyncio.fixture(scope="session")
async def user_token(test_tenant, client: httpx.AsyncClient):
    """Register a regular user (role=user) and return access_token."""
    email = _email("regularuser")
    password = "Test1234!"
    await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "full_name": "E2E Regular User"},
    )
    from src.common.database import AsyncSessionLocal
    from src.auth.models import User
    from sqlalchemy import update

    async with AsyncSessionLocal() as db:
        await db.execute(
            update(User)
            .where(User.email == email)
            .values(role="user", company_id=test_tenant["id"])
        )
        await db.commit()

    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    return resp.json()["access_token"]
