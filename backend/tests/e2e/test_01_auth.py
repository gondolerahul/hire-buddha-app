"""
E2E Tests — Authentication & Authorization
Covers: register, login, refresh, me, admin-only, invalid tokens
"""
import uuid
import pytest
import httpx

from tests.e2e.conftest import auth_headers, register_and_login, TEST_ID


# ── Registration ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_register_new_user(client: httpx.AsyncClient):
    email = f"e2e_register_{TEST_ID}@test.hirebuddha.com"
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "StrongPwd1!", "full_name": "Reg Test"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["email"] == email
    assert "id" in data


@pytest.mark.asyncio
async def test_register_duplicate_email(client: httpx.AsyncClient):
    email = f"e2e_dup_{TEST_ID}@test.hirebuddha.com"
    # First registration
    await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "StrongPwd1!", "full_name": "Dup Test"},
    )
    # Second registration with same email
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "StrongPwd1!", "full_name": "Dup Test"},
    )
    assert resp.status_code in (400, 409, 422), f"Expected conflict, got {resp.status_code}: {resp.text}"


# ── Login ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_login_valid_credentials(client: httpx.AsyncClient):
    email = f"e2e_login_{TEST_ID}@test.hirebuddha.com"
    password = "LoginPwd1!"
    await register_and_login(client, email, password, "Login Test")
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert "refresh_token" in data


@pytest.mark.asyncio
async def test_login_wrong_password(client: httpx.AsyncClient):
    email = f"e2e_login_{TEST_ID}@test.hirebuddha.com"
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "WrongPassword!"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_login_nonexistent_email(client: httpx.AsyncClient):
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "noone@nowhere.com", "password": "Anything1!"},
    )
    assert resp.status_code == 401


# ── /auth/me ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_me_authenticated(client: httpx.AsyncClient, app_admin_token):
    resp = await client.get("/api/v1/auth/me", headers=auth_headers(app_admin_token))
    assert resp.status_code == 200
    data = resp.json()
    assert "email" in data
    assert "company_id" in data
    assert "role" in data


@pytest.mark.asyncio
async def test_get_me_no_token(client: httpx.AsyncClient):
    resp = await client.get("/api/v1/auth/me")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_get_me_invalid_token(client: httpx.AsyncClient):
    resp = await client.get(
        "/api/v1/auth/me",
        headers=auth_headers("this.is.not.a.valid.jwt"),
    )
    assert resp.status_code == 401


# ── Token Refresh ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_refresh_token(client: httpx.AsyncClient):
    email = f"e2e_refresh_{TEST_ID}@test.hirebuddha.com"
    password = "RefreshPwd1!"
    _, refresh = await register_and_login(client, email, password, "Refresh Test")
    assert refresh, "Did not get refresh token from login"

    resp = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": refresh},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "access_token" in data
    assert "refresh_token" in data


@pytest.mark.asyncio
async def test_refresh_invalid_token(client: httpx.AsyncClient):
    resp = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": "invalid-token-string"},
    )
    assert resp.status_code in (401, 404), resp.text


# ── Admin-Only Endpoint ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_admin_only_as_admin(client: httpx.AsyncClient, app_admin_token):
    resp = await client.get(
        "/api/v1/auth/admin-only",
        headers=auth_headers(app_admin_token),
    )
    assert resp.status_code == 200
    assert resp.json()["message"] == "Admin access granted"


@pytest.mark.asyncio
async def test_admin_only_as_user(client: httpx.AsyncClient, user_token):
    resp = await client.get(
        "/api/v1/auth/admin-only",
        headers=auth_headers(user_token),
    )
    assert resp.status_code == 403
