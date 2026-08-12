"""
E2E Tests — RBAC & Company Management
Covers: partner/tenant CRUD, role-based access fencing, suspension middleware
"""
import pytest
import httpx

from tests.e2e.conftest import auth_headers, TEST_ID


# ── List Partners ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_app_admin_can_list_partners(client: httpx.AsyncClient, app_admin_token):
    resp = await client.get(
        "/api/v1/companies/partners",
        headers=auth_headers(app_admin_token),
    )
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_partner_admin_cannot_list_partners(client: httpx.AsyncClient, partner_admin_token):
    resp = await client.get(
        "/api/v1/companies/partners",
        headers=auth_headers(partner_admin_token),
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_tenant_admin_cannot_list_partners(client: httpx.AsyncClient, tenant_admin_token):
    resp = await client.get(
        "/api/v1/companies/partners",
        headers=auth_headers(tenant_admin_token),
    )
    assert resp.status_code == 403


# ── List Tenants ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_app_admin_can_list_tenants(client: httpx.AsyncClient, app_admin_token):
    resp = await client.get(
        "/api/v1/companies/tenants",
        headers=auth_headers(app_admin_token),
    )
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_partner_admin_lists_own_tenants(client: httpx.AsyncClient, partner_admin_token, test_tenant):
    resp = await client.get(
        "/api/v1/companies/tenants",
        headers=auth_headers(partner_admin_token),
    )
    assert resp.status_code == 200
    tenants = resp.json()
    # Should only see tenants whose parent_id matches the partner's company_id
    for t in tenants:
        assert t["type"] == "TENANT"


# ── Create Companies ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_app_admin_creates_partner(client: httpx.AsyncClient, app_admin_token):
    resp = await client.post(
        "/api/v1/companies",
        headers=auth_headers(app_admin_token),
        json={"name": f"TestPartner2_{TEST_ID}", "type": "PARTNER", "status": "active"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["type"] == "PARTNER"
    assert data["status"] == "active"


@pytest.mark.asyncio
async def test_app_admin_creates_tenant(client: httpx.AsyncClient, app_admin_token, test_partner):
    resp = await client.post(
        "/api/v1/companies",
        headers=auth_headers(app_admin_token),
        json={
            "name": f"TestTenant2_{TEST_ID}",
            "type": "TENANT",
            "status": "active",
            "parent_id": test_partner["id"],
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["type"] == "TENANT"


@pytest.mark.asyncio
async def test_partner_admin_creates_tenant(client: httpx.AsyncClient, partner_admin_token):
    resp = await client.post(
        "/api/v1/companies",
        headers=auth_headers(partner_admin_token),
        json={"name": f"PACreatedTenant_{TEST_ID}", "type": "TENANT", "status": "active"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["type"] == "TENANT"


@pytest.mark.asyncio
async def test_partner_admin_cannot_create_partner(client: httpx.AsyncClient, partner_admin_token):
    resp = await client.post(
        "/api/v1/companies",
        headers=auth_headers(partner_admin_token),
        json={"name": "ForbiddenPartner", "type": "PARTNER", "status": "active"},
    )
    assert resp.status_code == 403


# ── Update Company ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_update_own_company(client: httpx.AsyncClient, app_admin_token, app_admin_company_id):
    resp = await client.patch(
        f"/api/v1/companies/{app_admin_company_id}",
        headers=auth_headers(app_admin_token),
        json={"name": f"UpdatedCompany_{TEST_ID}"},
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_update_company_cross_tenant_blocked(client: httpx.AsyncClient, tenant_admin_token, test_partner):
    """Tenant admin should not update a partner company they don't own."""
    resp = await client.patch(
        f"/api/v1/companies/{test_partner['id']}",
        headers=auth_headers(tenant_admin_token),
        json={"name": "Hacked"},
    )
    assert resp.status_code == 403


# ── Company Suspension ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_suspended_company_blocks_access(client: httpx.AsyncClient, app_admin_token, test_tenant, tenant_admin_token):
    """Suspend the tenant, verify tenant_admin is blocked, then reactivate."""
    # Suspend
    resp = await client.patch(
        f"/api/v1/companies/{test_tenant['id']}",
        headers=auth_headers(app_admin_token),
        json={"status": "suspended"},
    )
    assert resp.status_code == 200

    # Re-login to get a fresh token so middleware checks company status
    from tests.e2e.conftest import _email
    resp_login = await client.post(
        "/api/v1/auth/login",
        json={"email": _email("tenantadmin"), "password": "Test1234!"},
    )
    fresh_token = resp_login.json().get("access_token")

    # Try to access a protected endpoint — should be blocked
    if fresh_token:
        resp_me = await client.get("/api/v1/auth/me", headers=auth_headers(fresh_token))
        # Either middleware 403 or dependency 403
        assert resp_me.status_code == 403, f"Expected 403, got {resp_me.status_code}"

    # Reactivate
    resp = await client.patch(
        f"/api/v1/companies/{test_tenant['id']}",
        headers=auth_headers(app_admin_token),
        json={"status": "active"},
    )
    assert resp.status_code == 200
