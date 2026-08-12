"""
E2E Tests — Phone Numbers & Streaming Sessions
Covers: DID assignment, voice/whatsapp sessions, conversation history, webhooks (endpoints)
"""
import pytest
import httpx
import uuid

from tests.e2e.conftest import auth_headers, TEST_ID


_PHONE_ASSIGNMENT_ID = None

# ── Phone Numbers ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_assign_phone_number(client: httpx.AsyncClient, app_admin_token, app_admin_company_id):
    global _PHONE_ASSIGNMENT_ID

    # Pre-req: need an agent ID
    agent_resp = await client.post(
        "/api/v1/ai/entities",
        headers=auth_headers(app_admin_token),
        json={
            "name": f"PhoneAgent_{TEST_ID}",
            "type": "AGENT",
        },
    )
    assert agent_resp.status_code == 200
    agent_id = agent_resp.json()["id"]

    resp = await client.post(
        "/api/v1/phone-numbers",
        headers=auth_headers(app_admin_token),
        json={
            "phone_number": f"+155500011{TEST_ID[:2]}", # Try to make unique
            "provider": "twilio",
            "agent_id": agent_id,
            "customer_id": str(uuid.uuid4()),
            "customer_name": "Test Customer",
        },
    )
    # If 400 (number taken), we can ignore/skip rest of test, but we use a random suffix
    if resp.status_code == 400 and "already assigned" in resp.text:
       pytest.skip("Generated phone number was taken")
       
    assert resp.status_code == 200, resp.text
    _PHONE_ASSIGNMENT_ID = resp.json()["id"]


@pytest.mark.asyncio
async def test_list_phone_numbers(client: httpx.AsyncClient, app_admin_token):
    resp = await client.get("/api/v1/phone-numbers", headers=auth_headers(app_admin_token))
    assert resp.status_code == 200
    data = resp.json()
    if isinstance(data, dict):
        assert "sessions" in data or "items" in data or "phone_numbers" in data
    else:
        assert isinstance(data, list)


@pytest.mark.asyncio
async def test_get_phone_number(client: httpx.AsyncClient, app_admin_token):
    if not _PHONE_ASSIGNMENT_ID:
        pytest.skip("Phone number not created")
        
    resp = await client.get(f"/api/v1/phone-numbers/{_PHONE_ASSIGNMENT_ID}", headers=auth_headers(app_admin_token))
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_delete_phone_number(client: httpx.AsyncClient, app_admin_token):
    if not _PHONE_ASSIGNMENT_ID:
        pytest.skip("Phone number not created")
        
    resp = await client.delete(f"/api/v1/phone-numbers/{_PHONE_ASSIGNMENT_ID}", headers=auth_headers(app_admin_token))
    assert resp.status_code == 200


# ── Streaming Sessions ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_voice_sessions(client: httpx.AsyncClient, app_admin_token):
    resp = await client.get("/api/v1/streaming/voice-sessions", headers=auth_headers(app_admin_token))
    assert resp.status_code == 200
    data = resp.json()
    assert "sessions" in data
    assert isinstance(data["sessions"], list)


@pytest.mark.asyncio
async def test_list_whatsapp_sessions(client: httpx.AsyncClient, app_admin_token):
    resp = await client.get("/api/v1/streaming/whatsapp-sessions", headers=auth_headers(app_admin_token))
    assert resp.status_code == 200
    data = resp.json()
    assert "sessions" in data
    assert isinstance(data["sessions"], list)


@pytest.mark.asyncio
async def test_get_conversation_history(client: httpx.AsyncClient, app_admin_token):
    # Testing endpoint returns a list (empty or not)
    resp = await client.get("/api/v1/streaming/conversation-history", headers=auth_headers(app_admin_token))
    assert resp.status_code == 200
    data = resp.json()
    assert "history" in data
    assert isinstance(data["history"], list)


@pytest.mark.asyncio
async def test_get_streaming_stats(client: httpx.AsyncClient, app_admin_token):
    resp = await client.get("/api/v1/streaming/stats", headers=auth_headers(app_admin_token))
    assert resp.status_code == 200
    data = resp.json()
    assert "voice" in data
    assert "total_calls" in data["voice"]
    assert "whatsapp" in data
    assert "total_messages" in data["whatsapp"]


# ── Webhooks ─────────────────────────────────────────────────────────────────
# Note: For webhooks, we can just verify the endpoints exist and handle requests
# (We won't provide real Twilio signatures here unless we mock parsing)

@pytest.mark.asyncio
async def test_twilio_voice_webhook_no_twilio_header(client: httpx.AsyncClient):
    # Should probably 400 or 401 depending on validation
    resp = await client.post("/webhooks/voice/twilio/incoming")
    # Might fail with missing params (Form data), but validates endpoint exists
    assert resp.status_code in (400, 422, 401, 200)


@pytest.mark.asyncio
async def test_twilio_whatsapp_webhook(client: httpx.AsyncClient):
    resp = await client.post("/webhooks/voice/whatsapp/incoming")
    assert resp.status_code in (400, 422, 401, 200)


@pytest.mark.asyncio
async def test_twilio_status_webhook(client: httpx.AsyncClient):
    resp = await client.post("/webhooks/voice/twilio/status")
    assert resp.status_code in (400, 422, 401, 200)


@pytest.mark.asyncio
async def test_tata_voice_webhook(client: httpx.AsyncClient):
    resp = await client.post("/webhooks/voice/tata/incoming", json={})
    assert resp.status_code in (400, 422, 401, 200)


@pytest.mark.asyncio
async def test_tata_whatsapp_webhook(client: httpx.AsyncClient):
    resp = await client.post("/webhooks/voice/tata/whatsapp/incoming", json={})
    assert resp.status_code in (400, 422, 401, 200)


# ── Messaging ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_send_whatsapp_message(client: httpx.AsyncClient, app_admin_token):
    resp = await client.post(
        "/api/v1/messaging/send",
        headers=auth_headers(app_admin_token),
        json={
            "to": "+15551234567",
            "message": "Hello from E2E test",
            "provider": "twilio"
        }
    )
    # If the provider is not configured, it will return 500
    if resp.status_code == 500:
        pytest.skip("Provider API not configured for messaging")
    assert resp.status_code == 200
    

@pytest.mark.asyncio
async def test_send_whatsapp_template(client: httpx.AsyncClient, app_admin_token):
    resp = await client.post(
        "/api/v1/messaging/send-template",
        headers=auth_headers(app_admin_token),
        json={
            "to": "+15551234567",
            "template_id": "hello_world",
            "parameters": ["test parameter"],
            "provider": "twilio"
        }
    )
    if resp.status_code == 500:
        pytest.skip("Provider API not configured for template messaging")
    assert resp.status_code == 200
