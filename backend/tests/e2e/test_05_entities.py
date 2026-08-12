"""
E2E Tests — Hierarchical Entities (Actions, Skills, Agents, Processes)
Covers: CRUD operations, filtering by type, entity DAG structure constraints
"""
import pytest
import httpx

from tests.e2e.conftest import auth_headers, TEST_ID

_ENTITIES: dict[str, str] = {}


# ── Create Entities ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_action(client: httpx.AsyncClient, app_admin_token):
    resp = await client.post(
        "/api/v1/ai/entities",
        headers=auth_headers(app_admin_token),
        json={
            "name": f"E2E_Action_{TEST_ID}",
            "description": "A leaf action returning stock price",
            "type": "ACTION",
            "status": "ACTIVE",
            "io_contract": {
                "input_schema": {"type": "object", "properties": {"ticker": {"type": "string"}}},
                "output_schema": {"type": "object", "properties": {"price": {"type": "number"}}}
            }
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["type"] == "ACTION"
    _ENTITIES["action"] = data["id"]


@pytest.mark.asyncio
async def test_create_skill(client: httpx.AsyncClient, app_admin_token):
    resp = await client.post(
        "/api/v1/ai/entities",
        headers=auth_headers(app_admin_token),
        json={
            "name": f"E2E_Skill_{TEST_ID}",
            "type": "SKILL",
            "status": "ACTIVE",
            "capabilities": {
                "tools": [{"tool_id": "web_search"}, {"tool_id": "calculator"}]
            }
        },
    )
    assert resp.status_code == 200, resp.text
    _ENTITIES["skill"] = resp.json()["id"]


@pytest.mark.asyncio
async def test_create_agent(client: httpx.AsyncClient, app_admin_token):
    resp = await client.post(
        "/api/v1/ai/entities",
        headers=auth_headers(app_admin_token),
        json={
            "name": f"E2E_Agent_{TEST_ID}",
            "type": "AGENT",
            "identity": {
                "system_prompt": "You are a helpful E2E testing agent.",
                "examples": []
            },
            "logic_gate": {
                "reasoning_config": {
                    "model_provider": "openai",
                    "model_name": "gpt-4",
                    "reasoning_mode": "REACT"
                }
            }
        },
    )
    assert resp.status_code == 200, resp.text
    _ENTITIES["agent"] = resp.json()["id"]


@pytest.mark.asyncio
async def test_create_process(client: httpx.AsyncClient, app_admin_token):
    # Process relies on children
    if "agent" not in _ENTITIES:
        pytest.skip("Agent not created")

    resp = await client.post(
        "/api/v1/ai/entities",
        headers=auth_headers(app_admin_token),
        json={
            "name": f"E2E_Process_{TEST_ID}",
            "type": "PROCESS",
            "hierarchy": {
                "children": [
                    {"child_id": _ENTITIES["agent"], "child_type": "AGENT", "relationship": "SEQUENTIAL"}
                ],
                "is_atomic": False
            }
        },
    )
    assert resp.status_code == 200, resp.text
    _ENTITIES["process"] = resp.json()["id"]


# ── List / Get Entities ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_all_entities(client: httpx.AsyncClient, app_admin_token):
    resp = await client.get("/api/v1/ai/entities", headers=auth_headers(app_admin_token))
    assert resp.status_code == 200
    entities = resp.json()
    assert isinstance(entities, list)
    assert len(entities) >= len(_ENTITIES)


@pytest.mark.asyncio
async def test_filter_entities_by_type(client: httpx.AsyncClient, app_admin_token):
    resp = await client.get("/api/v1/ai/entities?type=AGENT", headers=auth_headers(app_admin_token))
    assert resp.status_code == 200
    agents = resp.json()
    for ag in agents:
        assert ag["type"] == "AGENT"


@pytest.mark.asyncio
async def test_get_single_entity(client: httpx.AsyncClient, app_admin_token):
    if "agent" not in _ENTITIES:
        pytest.skip("Agent not created")
    
    resp = await client.get(
        f"/api/v1/ai/entities/{_ENTITIES['agent']}",
        headers=auth_headers(app_admin_token),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == _ENTITIES["agent"]
    assert data["identity"]["system_prompt"] == "You are a helpful E2E testing agent."


# ── Update / Delete ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_update_entity(client: httpx.AsyncClient, app_admin_token):
    if "action" not in _ENTITIES:
        pytest.skip("Action not created")

    resp = await client.put(
        f"/api/v1/ai/entities/{_ENTITIES['action']}",
        headers=auth_headers(app_admin_token),
        json={"name": "Updated_Action", "display_name": "Stock Price Fetcher", "type": "ACTION"}
    )
    assert resp.status_code == 200
    assert resp.json()["display_name"] == "Stock Price Fetcher"


@pytest.mark.asyncio
async def test_entity_not_found(client: httpx.AsyncClient, app_admin_token):
    import uuid
    resp = await client.get(f"/api/v1/ai/entities/{uuid.uuid4()}", headers=auth_headers(app_admin_token))
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_entity(client: httpx.AsyncClient, app_admin_token):
    # Delete the process first to avoid FK constraints if any
    if "process" in _ENTITIES:
        resp = await client.delete(
            f"/api/v1/ai/entities/{_ENTITIES['process']}",
            headers=auth_headers(app_admin_token),
        )
        assert resp.status_code == 200
