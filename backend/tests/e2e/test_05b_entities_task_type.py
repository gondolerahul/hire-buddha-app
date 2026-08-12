import pytest
from httpx import AsyncClient
from uuid import uuid4

@pytest.mark.asyncio
async def test_create_entity_with_task_type(
    async_client: AsyncClient, 
    app_admin_token: str
):
    """Verify that we can create an entity with a specific task_type in logic_gate."""
    headers = {"Authorization": f"Bearer {app_admin_token}"}
    payload = {
        "name": "Test Speech Entity",
        "description": "An entity for speech tasks",
        "category": "agent",
        "is_agentic": True,
        "logic_gate": {
            "reasoning_config": {
                "task_type": "speech_to_speech",
                "temperature": 0.8,
                "max_tokens": 1000
            }
        }
    }
    
    response = await async_client.post("/api/v1/entities/", headers=headers, json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Test Speech Entity"
    
    # Verify task_type was saved
    assert "logic_gate" in data
    assert "reasoning_config" in data["logic_gate"]
    assert data["logic_gate"]["reasoning_config"].get("task_type") == "speech_to_speech"
    # Ensure legacy fields are omitted or handled gracefully
    assert "model_name" not in data["logic_gate"]["reasoning_config"]

@pytest.mark.asyncio
async def test_entity_task_type_persists(
    async_client: AsyncClient, 
    app_admin_token: str
):
    """Verify that fetching an existing entity returns its task_type."""
    headers = {"Authorization": f"Bearer {app_admin_token}"}
    
    # Create first
    payload = {
        "name": "Planar Entity Task",
        "category": "planar",
        "logic_gate": {
            "reasoning_config": {
                "task_type": "text_to_image",
                "temperature": 0.5
            }
        }
    }
    create_resp = await async_client.post("/api/v1/entities/", headers=headers, json=payload)
    assert create_resp.status_code == 200
    entity_id = create_resp.json()["id"]
    
    # Fetch
    fetch_resp = await async_client.get(f"/api/v1/entities/{entity_id}", headers=headers)
    assert fetch_resp.status_code == 200
    data = fetch_resp.json()
    
    assert data["logic_gate"]["reasoning_config"]["task_type"] == "text_to_image"
