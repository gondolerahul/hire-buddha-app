"""
E2E Tests — User Management
Covers: list users (role-scoped), create user (admin), update user, cross-company block
"""
import pytest
import httpx

from tests.e2e.conftest import auth_headers, TEST_ID


# ── List Users ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_app_admin_lists_all_users(client: httpx.AsyncClient, app_admin_token):
    resp = await client.get("/api/v1/users", headers=auth_headers(app_admin_token))
    assert resp.status_code == 200
    users = resp.json()
    assert isinstance(users, list)
    assert len(users) >= 1


@pytest.mark.asyncio
async def test_partner_admin_lists_scoped_users(
    client: httpx.AsyncClient, partner_admin_token, test_partner
):
    resp = await client.get("/api/v1/users", headers=auth_headers(partner_admin_token))
    assert resp.status_code == 200
    users = resp.json()
    assert isinstance(users, list)


@pytest.mark.asyncio
async def test_tenant_admin_lists_own_users(
    client: httpx.AsyncClient, tenant_admin_token, test_tenant
):
    resp = await client.get("/api/v1/users", headers=auth_headers(tenant_admin_token))
    assert resp.status_code == 200
    users = resp.json()
    for u in users:
        assert u["company_id"] == test_tenant["id"]


@pytest.mark.asyncio
async def test_regular_user_cannot_list_users(client: httpx.AsyncClient, user_token):
    resp = await client.get("/api/v1/users", headers=auth_headers(user_token))
    assert resp.status_code == 403


# ── Create User (Admin) ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_admin_creates_user(
    client: httpx.AsyncClient, app_admin_token, test_tenant
):
    resp = await client.post(
        "/api/v1/users",
        headers=auth_headers(app_admin_token),
        json={
            "email": f"e2e_created_{TEST_ID}@test.hirebuddha.com",
            "password": "Created1!",
            "full_name": "Created User",
            "company_id": test_tenant["id"],
            "role": "user",
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["email"] == f"e2e_created_{TEST_ID}@test.hirebuddha.com"
    assert data["role"] == "user"


# ── Update User ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_admin_updates_user(
    client: httpx.AsyncClient, app_admin_token
):
    # First get a user to update
    resp = await client.get("/api/v1/users", headers=auth_headers(app_admin_token))
    users = resp.json()
    assert len(users) > 0
    target_user = users[0]

    resp = await client.patch(
        f"/api/v1/users/{target_user['id']}",
        headers=auth_headers(app_admin_token),
        json={"full_name": "Updated Name E2E"},
    )
    assert resp.status_code == 200
    assert resp.json()["full_name"] == "Updated Name E2E"


@pytest.mark.asyncio
async def test_cross_company_user_update_blocked(
    client: httpx.AsyncClient, tenant_admin_token, app_admin_token
):
    """Tenant admin cannot update a user from a different company."""
    # Get the app_admin user
    resp = await client.get("/api/v1/auth/me", headers=auth_headers(app_admin_token))
    admin_user = resp.json()

    resp = await client.patch(
        f"/api/v1/users/{admin_user['id']}",
        headers=auth_headers(tenant_admin_token),
        json={"full_name": "Hacked"},
    )
    assert resp.status_code == 403
