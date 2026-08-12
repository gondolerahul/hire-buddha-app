"""
E2E Tests — Integrations Registry (Config)
Covers: CRUD, cross-company access control, models listing
"""
import pytest
import httpx
from decimal import Decimal

from tests.e2e.conftest import auth_headers, TEST_ID

_CREATED_IDS: list[str] = []


# ── Create Integration ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_admin_creates_integration(
    client: httpx.AsyncClient, app_admin_token, app_admin_company_id
):
    resp = await client.post(
        "/api/v1/config/integrations",
        headers=auth_headers(app_admin_token),
        json={
            "provider_name": "openai",
            "model_name": f"gpt-4-e2e-{TEST_ID}",
            "service_sku": f"openai-gpt4-{TEST_ID}",
            "service_category": "LLM",
            "component_type": "text_generation",
            "internal_cost": "0.03",
            "cost_unit": "1k_tokens",
            "company_id": app_admin_company_id,
            "api_key": "sk-test-key-12345",
            "status": "active",
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["provider_name"] == "openai"
    _CREATED_IDS.append(str(data["id"]))


@pytest.mark.asyncio
async def test_tenant_admin_creates_integration(
    client: httpx.AsyncClient, tenant_admin_token, tenant_admin_company_id
):
    resp = await client.post(
        "/api/v1/config/integrations",
        headers=auth_headers(tenant_admin_token),
        json={
            "provider_name": "gemini",
            "model_name": f"gemini-pro-e2e-{TEST_ID}",
            "service_sku": f"gemini-pro-{TEST_ID}",
            "service_category": "LLM",
            "component_type": "text_generation",
            "internal_cost": "0.01",
            "cost_unit": "1k_tokens",
            "company_id": tenant_admin_company_id,
            "api_key": "gemini-test-key",
            "status": "active",
        },
    )
    assert resp.status_code == 200, resp.text
    _CREATED_IDS.append(str(resp.json()["id"]))


@pytest.mark.asyncio
async def test_regular_user_cannot_create_integration(
    client: httpx.AsyncClient, user_token, tenant_admin_company_id
):
    resp = await client.post(
        "/api/v1/config/integrations",
        headers=auth_headers(user_token),
        json={
            "provider_name": "openai",
            "model_name": "forbidden",
            "service_sku": "forbidden",
            "service_category": "LLM",
            "component_type": "text_generation",
            "internal_cost": "0.01",
            "cost_unit": "1k_tokens",
            "company_id": tenant_admin_company_id,
            "api_key": "sk-nope",
            "status": "active",
        },
    )
    assert resp.status_code == 403


# ── Non-app_admin cannot create for other company ─────────────────────────────

@pytest.mark.asyncio
async def test_tenant_admin_cannot_create_for_other_company(
    client: httpx.AsyncClient, tenant_admin_token, app_admin_company_id
):
    resp = await client.post(
        "/api/v1/config/integrations",
        headers=auth_headers(tenant_admin_token),
        json={
            "provider_name": "openai",
            "model_name": "hack",
            "service_sku": "hack",
            "service_category": "LLM",
            "component_type": "text_generation",
            "internal_cost": "0.01",
            "cost_unit": "1k_tokens",
            "company_id": app_admin_company_id,  # NOT their company
            "api_key": "sk-hack",
            "status": "active",
        },
    )
    assert resp.status_code == 403


# ── List Integrations ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_integrations(client: httpx.AsyncClient, app_admin_token):
    resp = await client.get(
        "/api/v1/config/integrations",
        headers=auth_headers(app_admin_token),
    )
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


# ── Get Single Integration ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_integration(client: httpx.AsyncClient, app_admin_token):
    if not _CREATED_IDS:
        pytest.skip("No integration created")
    resp = await client.get(
        f"/api/v1/config/integrations/{_CREATED_IDS[0]}",
        headers=auth_headers(app_admin_token),
    )
    assert resp.status_code == 200
    assert resp.json()["id"] == _CREATED_IDS[0]


@pytest.mark.asyncio
async def test_get_cross_company_integration_blocked(
    client: httpx.AsyncClient, tenant_admin_token
):
    """Tenant admin accessing an integration belonging to app_admin's company."""
    if not _CREATED_IDS:
        pytest.skip("No integration created")
    resp = await client.get(
        f"/api/v1/config/integrations/{_CREATED_IDS[0]}",
        headers=auth_headers(tenant_admin_token),
    )
    assert resp.status_code == 403


# ── Update Integration ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_update_integration(client: httpx.AsyncClient, app_admin_token):
    if not _CREATED_IDS:
        pytest.skip("No integration created")
    resp = await client.patch(
        f"/api/v1/config/integrations/{_CREATED_IDS[0]}",
        headers=auth_headers(app_admin_token),
        json={"status": "inactive"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "inactive"


# ── List LLM Models ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_models(client: httpx.AsyncClient, app_admin_token):
    resp = await client.get(
        "/api/v1/config/models",
        headers=auth_headers(app_admin_token),
    )
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


# ── Delete Integration ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_delete_integration(client: httpx.AsyncClient, app_admin_token):
    if not _CREATED_IDS:
        pytest.skip("No integration created")
    resp = await client.delete(
        f"/api/v1/config/integrations/{_CREATED_IDS[0]}",
        headers=auth_headers(app_admin_token),
    )
    assert resp.status_code == 204
