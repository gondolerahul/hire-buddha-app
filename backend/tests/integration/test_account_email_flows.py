"""Registration verifies the address; a forgotten password can be reset (AU-06, AU-07, AU-08).

Before: ``/auth/forgot-password`` and ``/auth/reset-password`` did not exist,
no verification email was ever sent, ``is_verified`` gated nothing, and
registration returned working tokens. Product decision (2026-09-30): an
unverified account cannot sign in.

Drives the real auth router against Postgres in the suite's rolled-back
transaction, with the SMTP send captured and Redis replaced by a fake.
"""
from __future__ import annotations

import re
import uuid
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI

from tests.unit.test_login_throttle_and_policy import FakeRedis

pytestmark = pytest.mark.needs_db
PASSWORD = "correct horse battery staple"


@pytest.fixture
def outbox(monkeypatch):
    from src.auth import account_emails, throttle

    FakeRedis.store, FakeRedis.ttls = {}, {}
    monkeypatch.setattr(throttle, "client_factory", FakeRedis)
    sent: list[dict] = []

    async def capture(to_email, subject, body):
        link = re.search(r'href="([^"]+)"', body).group(1)
        sent.append({"to": to_email, "subject": subject, "token": parse_qs(urlparse(link).query)["token"][0],
                     "path": urlparse(link).path})
        return True

    monkeypatch.setattr(account_emails.email_service, "async_send_email", capture)
    return sent


@pytest_asyncio.fixture
async def client(db):
    from src.auth import router as auth_router
    from src.common.database import get_db

    app = FastAPI()
    app.include_router(auth_router.router)

    async def _db():
        yield db

    app.dependency_overrides[get_db] = _db
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        yield c


def _email() -> str:
    return f"au08-{uuid.uuid4().hex[:8]}@example.com"


async def _register(client, email, password=PASSWORD):
    return await client.post("/auth/register", json={"email": email, "password": password, "full_name": "Probe"})


async def _login(client, email, password=PASSWORD):
    return await client.post("/auth/login", json={"email": email, "password": password})


@pytest.mark.asyncio
async def test_registration_sends_a_link_and_signs_nobody_in(client, outbox):
    email = _email()
    res = await _register(client, email)
    assert res.status_code == 201
    assert "access_token" not in res.json() and "refresh_token" not in res.json()
    assert [(m["to"], m["path"]) for m in outbox] == [(email, "/verify-email")]


@pytest.mark.asyncio
async def test_an_unverified_account_cannot_sign_in_until_verified(client, outbox):
    email = _email()
    await _register(client, email)
    res = await _login(client, email)
    assert res.status_code == 403 and "verify" in res.json()["detail"]
    assert (await client.get("/auth/verify-email", params={"token": outbox[0]["token"]})).status_code == 200
    assert (await _login(client, email)).status_code == 200


@pytest.mark.asyncio
async def test_a_weak_password_is_refused_with_a_readable_message(client, outbox):
    res = await _register(client, _email(), password="short")
    assert res.status_code == 422 and "12 characters" in res.json()["detail"]
    assert outbox == []


@pytest.mark.asyncio
async def test_resend_answers_the_same_for_unknown_addresses(client, outbox):
    email = _email()
    await _register(client, email)
    unknown = await client.post("/auth/resend-verification", json={"email": _email()})
    known = await client.post("/auth/resend-verification", json={"email": email})
    assert unknown.status_code == known.status_code == 202 and unknown.json() == known.json()
    assert [m["to"] for m in outbox] == [email, email]


@pytest.mark.asyncio
async def test_password_reset_end_to_end(client, outbox):
    email = _email()
    await _register(client, email)
    await client.get("/auth/verify-email", params={"token": outbox[0]["token"]})
    session = (await _login(client, email)).json()

    unknown = await client.post("/auth/forgot-password", json={"email": _email()})
    known = await client.post("/auth/forgot-password", json={"email": email})
    assert unknown.status_code == known.status_code == 202 and unknown.json() == known.json()
    reset = outbox[-1]
    assert reset["path"] == "/reset-password"

    new_password = "an entirely new passphrase"
    res = await client.post("/auth/reset-password", json={"token": reset["token"], "new_password": new_password})
    assert res.status_code == 200
    assert (await _login(client, email)).status_code == 401  # old password
    assert (await _login(client, email, new_password)).status_code == 200
    # Every earlier session ended.
    assert (await client.post("/auth/refresh", json={"refresh_token": session["refresh_token"]})).status_code == 401
    # The link works once.
    again = await client.post("/auth/reset-password", json={"token": reset["token"], "new_password": "yet another passphrase"})
    assert again.status_code == 400


@pytest.mark.asyncio
async def test_a_verification_token_cannot_reset_a_password(client, outbox):
    email = _email()
    await _register(client, email)
    res = await client.post("/auth/reset-password",
                            json={"token": outbox[0]["token"], "new_password": "an entirely new passphrase"})
    assert res.status_code == 400


@pytest.mark.asyncio
async def test_ten_wrong_passwords_lock_sign_in_even_with_the_right_one(client, outbox):
    email = _email()
    await _register(client, email)
    await client.get("/auth/verify-email", params={"token": outbox[0]["token"]})
    for _ in range(10):
        assert (await _login(client, email, "wrong password guess")).status_code == 401
    res = await _login(client, email)
    assert res.status_code == 429 and "Retry-After" in res.headers
