"""
E2E Tests — Authentication & Authorization
Covers: register, email verification, login, refresh rotation, logout, me,
admin-only, invalid tokens
"""
import pytest
import httpx

from src.auth.dependencies import EMAIL_NOT_VERIFIED
from tests.e2e.conftest import PASSWORD, auth_headers, link_token, register_and_login, TEST_ID


# ── Registration ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_register_new_user(client: httpx.AsyncClient, sent_account_emails):
    email = f"e2e_register_{TEST_ID}@test.hirebuddha.com"
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": PASSWORD, "full_name": "Reg Test"},
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["email"] == email
    assert data["message"]
    # No tokens: the account cannot sign in until the address is verified (AU-08)
    assert "access_token" not in data
    assert "refresh_token" not in data
    assert "refresh_token" not in resp.cookies
    assert [m["subject"] for m in sent_account_emails if m["to"] == email] == ["Verify your HireBuddha account"]


@pytest.mark.asyncio
async def test_register_duplicate_email(client: httpx.AsyncClient):
    email = f"e2e_dup_{TEST_ID}@test.hirebuddha.com"
    # First registration
    first = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": PASSWORD, "full_name": "Dup Test"},
    )
    assert first.status_code == 201, first.text
    # Second registration with same email
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": PASSWORD, "full_name": "Dup Test"},
    )
    assert resp.status_code == 400, f"Expected conflict, got {resp.status_code}: {resp.text}"


@pytest.mark.asyncio
async def test_register_short_password_rejected(client: httpx.AsyncClient):
    resp = await client.post(
        "/api/v1/auth/register",
        json={
            "email": f"e2e_shortpwd_{TEST_ID}@test.hirebuddha.com",
            "password": "Short1!xyz",  # 10 characters; the minimum is 12 (AU-07)
            "full_name": "Short Password",
        },
    )
    assert resp.status_code == 422, resp.text
    assert "12 characters" in resp.json()["detail"]


# ── Email verification ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_login_unverified_user_refused(client: httpx.AsyncClient):
    email = f"e2e_unverified_{TEST_ID}@test.hirebuddha.com"
    reg = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": PASSWORD, "full_name": "Unverified Test"},
    )
    assert reg.status_code == 201, reg.text

    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": PASSWORD},
    )
    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"] == EMAIL_NOT_VERIFIED


@pytest.mark.asyncio
async def test_login_after_email_verification(client: httpx.AsyncClient, sent_account_emails):
    email = f"e2e_verified_{TEST_ID}@test.hirebuddha.com"
    reg = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": PASSWORD, "full_name": "Verified Test"},
    )
    assert reg.status_code == 201, reg.text
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert login.status_code == 403, login.text

    # Follow the link from the verification email, as the user would
    (link,) = [m["link"] for m in sent_account_emails if m["to"] == email]
    verify = await client.get("/api/v1/auth/verify-email", params={"token": link_token(link)})
    assert verify.status_code == 200, verify.text
    assert verify.json()["message"] == "Email verified successfully"

    resp = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["access_token"]
    assert data["refresh_token"]


# ── Login ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_login_valid_credentials(client: httpx.AsyncClient):
    email = f"e2e_login_{TEST_ID}@test.hirebuddha.com"
    await register_and_login(client, email, PASSWORD, "Login Test")
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": PASSWORD},
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
    # A per-run address: failed sign-ins are counted per email in Redis (AU-07),
    # so a fixed one would hit the 10-per-15-minutes limit on repeated runs.
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": f"e2e_nobody_{TEST_ID}@test.hirebuddha.com", "password": "Anything1!"},
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
    _, refresh = await register_and_login(client, email, PASSWORD, "Refresh Test")
    assert refresh, "Did not get refresh token from login"

    resp = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": refresh},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "access_token" in data
    # Refresh tokens rotate: each one works once (AU-09)
    assert data["refresh_token"] and data["refresh_token"] != refresh


@pytest.mark.asyncio
async def test_refresh_token_reuse_ends_every_session(client: httpx.AsyncClient):
    email = f"e2e_reuse_{TEST_ID}@test.hirebuddha.com"
    _, first = await register_and_login(client, email, PASSWORD, "Reuse Test")
    rotated = await client.post("/api/v1/auth/refresh", json={"refresh_token": first})
    assert rotated.status_code == 200, rotated.text
    access, second = rotated.json()["access_token"], rotated.json()["refresh_token"]

    # The rotated-out token presented again is treated as stolen...
    reuse = await client.post("/api/v1/auth/refresh", json={"refresh_token": first})
    assert reuse.status_code == 401, reuse.text
    # ...and every session of the user ends, the legitimate one included
    resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": second})
    assert resp.status_code == 401, resp.text
    resp = await client.get("/api/v1/auth/me", headers=auth_headers(access))
    assert resp.status_code == 401, resp.text


@pytest.mark.asyncio
async def test_refresh_invalid_token(client: httpx.AsyncClient):
    resp = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": "invalid-token-string"},
    )
    assert resp.status_code in (401, 404), resp.text


# ── Logout ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_logout_ends_refresh_token(client: httpx.AsyncClient):
    email = f"e2e_logout_{TEST_ID}@test.hirebuddha.com"
    _, refresh = await register_and_login(client, email, PASSWORD, "Logout Test")

    resp = await client.post("/api/v1/auth/logout", json={"refresh_token": refresh})
    assert resp.status_code == 204, resp.text

    resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
    assert resp.status_code == 401, resp.text


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
