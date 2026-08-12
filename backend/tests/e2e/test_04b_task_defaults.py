import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from src.config.models import ModelTaskDefault, IntegrationRegistry
from src.ai.models import HierarchicalEntity

@pytest.fixture
async def gemini_integration(db_session: AsyncSession, app_company):
    """Create a dummy integration for testing task defaults."""
    integration = IntegrationRegistry(
        company_id=app_company.id,
        service_category="llm",
        provider_name="google",
        model_name="gemini-2.0-flash-exp",
        credentials_enc=b"dummy",
        is_active=True
    )
    db_session.add(integration)
    await db_session.commit()
    await db_session.refresh(integration)
    return integration

@pytest.mark.asyncio
async def test_admin_creates_task_default(
    async_client: AsyncClient, 
    app_admin_token: str,
    gemini_integration
):
    headers = {"Authorization": f"Bearer {app_admin_token}"}
    payload = {
        "task_type": "text_generation",
        "integration_id": str(gemini_integration.id),
        "routing_mode": "single"
    }
    
    response = await async_client.post("/api/v1/config/task-defaults", headers=headers, json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["task_type"] == "text_generation"
    assert data["integration_id"] == str(gemini_integration.id)

@pytest.mark.asyncio
async def test_list_task_defaults(
    async_client: AsyncClient, 
    app_admin_token: str,
    gemini_integration,
    db_session: AsyncSession,
    app_company
):
    # Pre-seed
    td = ModelTaskDefault(
        company_id=app_company.id,
        task_type="thinking",
        integration_id=gemini_integration.id,
        routing_mode="single",
        is_default=True
    )
    db_session.add(td)
    await db_session.commit()

    headers = {"Authorization": f"Bearer {app_admin_token}"}
    response = await async_client.get("/api/v1/config/task-defaults", headers=headers)
    assert response.status_code == 200
    data = response.json()
    
    assert isinstance(data, list)
    assert len(data) >= 1
    found = False
    for item in data:
        if item["task_type"] == "thinking":
            assert item["integration"] is not None
            assert item["integration"]["model_name"] == "gemini-2.0-flash-exp"
            found = True
    assert found

@pytest.mark.asyncio
async def test_update_task_default_upsert(
    async_client: AsyncClient, 
    app_admin_token: str,
    gemini_integration
):
    headers = {"Authorization": f"Bearer {app_admin_token}"}
    # First create
    payload = {
        "task_type": "speech_to_speech",
        "integration_id": str(gemini_integration.id),
        "routing_mode": "single"
    }
    resp1 = await async_client.post("/api/v1/config/task-defaults", headers=headers, json=payload)
    assert resp1.status_code == 200
    
    # Then update (using POST as upsert)
    payload["routing_mode"] = "router"
    resp2 = await async_client.post("/api/v1/config/task-defaults", headers=headers, json=payload)
    assert resp2.status_code == 200
    assert resp2.json()["routing_mode"] == "router"

@pytest.mark.asyncio
async def test_delete_task_default(
    async_client: AsyncClient, 
    app_admin_token: str,
    gemini_integration
):
    headers = {"Authorization": f"Bearer {app_admin_token}"}
    # Create
    payload = {
        "task_type": "text_to_image",
        "integration_id": str(gemini_integration.id)
    }
    await async_client.post("/api/v1/config/task-defaults", headers=headers, json=payload)
    
    # Delete
    del_resp = await async_client.delete("/api/v1/config/task-defaults/text_to_image", headers=headers)
    assert del_resp.status_code == 200
    
    # Verify deletion
    list_resp = await async_client.get("/api/v1/config/task-defaults", headers=headers)
    data = list_resp.json()
    for item in data:
        assert item["task_type"] != "text_to_image"

@pytest.mark.asyncio
async def test_regular_user_cannot_set_task_default(
    async_client: AsyncClient, 
    regular_user_token: str,
    gemini_integration
):
    headers = {"Authorization": f"Bearer {regular_user_token}"}
    payload = {
        "task_type": "text_generation",
        "integration_id": str(gemini_integration.id)
    }
    
    response = await async_client.post("/api/v1/config/task-defaults", headers=headers, json=payload)
    assert response.status_code in (401, 403)
