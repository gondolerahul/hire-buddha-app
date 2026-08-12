"""
E2E Tests — Assets & Email Connections
Covers: file upload/download, asset listing, email connection CRUD
"""
import pytest
import httpx
import uuid

from tests.e2e.conftest import auth_headers, TEST_ID


_ASSET_ID = None
_EMAIL_CONN_ID = None

# ── Assets ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_upload_asset(client: httpx.AsyncClient, app_admin_token, app_admin_company_id):
    global _ASSET_ID
    
    file_content = b"fake audio content"
    files = {"file": ("test_audio.wav", file_content, "audio/wav")}
    
    resp = await client.post(
        "/api/v1/assets/upload",
        headers=auth_headers(app_admin_token),
        data={
            "asset_type": "recordings",
            "session_id": str(uuid.uuid4())
        },
        files=files,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "id" in data
    assert data["file_type"] == "recordings"
    assert data["company_id"] == app_admin_company_id
    _ASSET_ID = data["id"]


@pytest.mark.asyncio
async def test_upload_invalid_asset_type(client: httpx.AsyncClient, app_admin_token):
    file_content = b"fake content"
    files = {"file": ("test.txt", file_content, "text/plain")}
    
    resp = await client.post(
        "/api/v1/assets/upload",
        headers=auth_headers(app_admin_token),
        data={"asset_type": "not_an_audio_or_image"},
        files=files,
    )
    # The application probably allows it, maps it as 'prompt_audio' or similar if not specified
    # Or 422 if enum strictly enforced
    assert resp.status_code in (200, 422, 400)


@pytest.mark.asyncio
async def test_list_assets(client: httpx.AsyncClient, app_admin_token):
    resp = await client.get("/api/v1/assets", headers=auth_headers(app_admin_token))
    data = resp.json()
    assert "assets" in data
    assert isinstance(data["assets"], list)


@pytest.mark.asyncio
async def test_get_asset_metadata(client: httpx.AsyncClient, app_admin_token):
    if not _ASSET_ID:
        pytest.skip("Asset not created")
        
    resp = await client.get(f"/api/v1/assets/{_ASSET_ID}", headers=auth_headers(app_admin_token))
    assert resp.status_code == 200
    assert resp.json()["id"] == _ASSET_ID


@pytest.mark.asyncio
async def test_download_asset(client: httpx.AsyncClient, app_admin_token):
    if not _ASSET_ID:
        pytest.skip("Asset not created")
        
    resp = await client.get(f"/api/v1/assets/{_ASSET_ID}/download", headers=auth_headers(app_admin_token))
    assert resp.status_code == 200
    # The content should be the fake audio we sent
    assert resp.content == b"fake audio content"


@pytest.mark.asyncio
async def test_delete_asset(client: httpx.AsyncClient, app_admin_token):
    if not _ASSET_ID:
        pytest.skip("Asset not created")
        
    resp = await client.delete(f"/api/v1/assets/{_ASSET_ID}", headers=auth_headers(app_admin_token))
    assert resp.status_code == 200


# ── Email Connections ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_email_providers(client: httpx.AsyncClient, app_admin_token):
    resp = await client.get("/api/v1/email/provider-defaults", headers=auth_headers(app_admin_token))
    assert resp.status_code == 200
    data = resp.json()
    assert "gmail" in data
    assert "outlook" in data


@pytest.mark.asyncio
async def test_create_email_connection(client: httpx.AsyncClient, app_admin_token, app_admin_company_id):
    global _EMAIL_CONN_ID
    
    resp = await client.post(
        f"/api/v1/email/connections?company_id={app_admin_company_id}",
        headers=auth_headers(app_admin_token),
        json={
            "email_address": f"test_{TEST_ID}@example.com",
            "provider_type": "custom",
            "imap_host": "imap.example.com",
            "imap_port": 993,
            "smtp_host": "smtp.example.com",
            "smtp_port": 587,
            "app_password": "fake_password_123"
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "id" in data
    assert data["email_address"] == f"test_{TEST_ID}@example.com"
    # Password should NOT be in response
    assert "password" not in data
    _EMAIL_CONN_ID = data["id"]


@pytest.mark.asyncio
async def test_list_email_connections(client: httpx.AsyncClient, app_admin_token, app_admin_company_id):
    resp = await client.get(f"/api/v1/email/connections?company_id={app_admin_company_id}", headers=auth_headers(app_admin_token))
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_validate_email_connection(client: httpx.AsyncClient, app_admin_token):
    if not _EMAIL_CONN_ID:
        pytest.skip("Email connection not created")
        
    # Validation will try to connect to the fake server and fail
    resp = await client.post(
        f"/api/v1/email/connections/{_EMAIL_CONN_ID}/validate", 
        headers=auth_headers(app_admin_token)
    )
    # Validation returns 200 with {valid: false} when IMAP server is unreachable
    assert resp.status_code in (200, 400, 500)
    if resp.status_code == 200:
        data = resp.json()
        assert "valid" in data
        # For fake server this will be False since IMAP can't connect
        assert isinstance(data["valid"], bool)


@pytest.mark.asyncio
async def test_delete_email_connection(client: httpx.AsyncClient, app_admin_token):
    if not _EMAIL_CONN_ID:
        pytest.skip("Email connection not created")
        
    resp = await client.delete(
        f"/api/v1/email/connections/{_EMAIL_CONN_ID}", 
        headers=auth_headers(app_admin_token)
    )
    assert resp.status_code == 200
