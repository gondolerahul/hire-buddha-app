"""
E2E Tests — Profile (Avatar/Logo)
Covers: avatar upload, company logo upload
"""
import pytest
import httpx

from tests.e2e.conftest import auth_headers


@pytest.mark.asyncio
async def test_upload_user_avatar(client: httpx.AsyncClient, app_admin_token):
    img_content = b"fake image"
    files = {"file": ("avatar.png", img_content, "image/png")}
    
    resp = await client.post(
        "/api/v1/profile/avatar",
        headers=auth_headers(app_admin_token),
        files=files,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "profile_picture_url" in data
    assert data["profile_picture_url"].startswith("/uploads/")


@pytest.mark.asyncio
async def test_upload_company_logo(client: httpx.AsyncClient, app_admin_token):
    img_content = b"fake logo"
    files = {"file": ("logo.png", img_content, "image/png")}
    
    resp = await client.post(
        "/api/v1/profile/company-logo",
        headers=auth_headers(app_admin_token),
        files=files,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "logo_url" in data
    assert data["logo_url"].startswith("/uploads/")


@pytest.mark.asyncio
async def test_non_admin_cannot_upload_logo(client: httpx.AsyncClient, user_token):
    img_content = b"fake logo"
    files = {"file": ("logo.png", img_content, "image/png")}
    
    resp = await client.post(
        "/api/v1/profile/company-logo",
        headers=auth_headers(user_token),
        files=files,
    )
    assert resp.status_code == 403
