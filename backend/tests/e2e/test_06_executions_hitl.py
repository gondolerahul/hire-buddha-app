"""
E2E Tests — Executions, HITL Approvals, Tools, Documents
"""
import pytest
import httpx

from tests.e2e.conftest import auth_headers, TEST_ID


# ── Fixtures for Execution Tests ──────────────────────────────────────────────

@pytest.fixture(scope="module")
def execution_context():
    return {"agent_id": None, "run_id": None}


# ── Tools & Documents ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_tools(client: httpx.AsyncClient, app_admin_token):
    resp = await client.get("/api/v1/ai/tools", headers=auth_headers(app_admin_token))
    assert resp.status_code == 200
    tools = resp.json()
    assert isinstance(tools, list)
    # Ensure some built-in tools are present
    tool_ids = [t["name"] for t in tools]
    assert "calculator" in tool_ids or "web_search" in tool_ids or len(tools) > 0


@pytest.mark.asyncio
async def test_list_documents(client: httpx.AsyncClient, app_admin_token):
    resp = await client.get("/api/v1/ai/documents", headers=auth_headers(app_admin_token))
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_search_documents(client: httpx.AsyncClient, app_admin_token):
    resp = await client.post(
        "/api/v1/ai/documents/search",
        headers=auth_headers(app_admin_token),
        params={"query": "test query", "top_k": 3}
    )
    if resp.status_code == 500 and "Gemini API Key" in resp.text:
        pytest.skip("Gemini API not configured")
        
    # Could be 200 with empty results or mocked, verifying endpoint exists + schema matches
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


# ── Executions ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_trigger_execution(client: httpx.AsyncClient, app_admin_token, execution_context):
    # Create simple agent to execute
    agent_resp = await client.post(
        "/api/v1/ai/entities",
        headers=auth_headers(app_admin_token),
        json={
            "name": f"DummyExecuteAgent_{TEST_ID}",
            "type": "AGENT",
            "identity": {"system_prompt": "You echo back inputs."}
        },
    )
    assert agent_resp.status_code == 200
    execution_context["agent_id"] = agent_resp.json()["id"]

    # Trigger run
    resp = await client.post(
        "/api/v1/ai/execute",
        headers=auth_headers(app_admin_token),
        json={
            "entity_id": execution_context["agent_id"],
            "input_data": {"message": "Hello"}
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "id" in data
    assert data["status"] in ("PENDING", "RUNNING", "COMPLETED")
    execution_context["run_id"] = data["id"]


@pytest.mark.asyncio
async def test_list_executions(client: httpx.AsyncClient, app_admin_token):
    resp = await client.get("/api/v1/ai/executions", headers=auth_headers(app_admin_token))
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data or isinstance(data, list)
    
    lst = data["items"] if "items" in data else data
    assert len(lst) >= 1


@pytest.mark.asyncio
async def test_get_execution_detail(client: httpx.AsyncClient, app_admin_token, execution_context):
    if not execution_context["run_id"]:
        pytest.skip("No execution triggered")
    
    resp = await client.get(
        f"/api/v1/ai/executions/{execution_context['run_id']}",
        headers=auth_headers(app_admin_token),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == execution_context["run_id"]


# ── HITL Approvals ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_pending_approvals(client: httpx.AsyncClient, app_admin_token):
    resp = await client.get(
        "/api/v1/ai/approvals/pending",
        headers=auth_headers(app_admin_token),
    )
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_respond_to_approval_not_found(client: httpx.AsyncClient, app_admin_token):
    import uuid
    resp = await client.post(
        f"/api/v1/ai/approvals/{uuid.uuid4()}/respond",
        headers=auth_headers(app_admin_token),
        json={"action": "approve", "notes": "LGTM"},
    )
    # Assuming 404 for non-existent approval
    assert resp.status_code in (404, 400, 422)
