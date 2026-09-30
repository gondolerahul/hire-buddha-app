"""Email connections are confined to the caller's company (AU-02).

Runs the router against the real Postgres inside the suite's rolled-back
transaction. Before the fix the routes took ``company_id`` from the query string
and looked connections up by id alone, so any caller could list, delete or
validate — decrypt and log in with — another company's mailbox credentials.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select

from src.ai import email_router
from src.ai.email_models import EmailConnection
from src.auth.dependencies import get_current_user_and_company
from src.common.database import get_db
from src.common.security import encrypt_api_key

pytestmark = pytest.mark.needs_db


async def _company(db) -> uuid.UUID:
    from src.auth.models import Company
    c = Company(name=f"email-scope-{uuid.uuid4().hex[:6]}", type="TENANT", status="active")
    db.add(c)
    await db.flush()
    return c.id


async def _connection(db, company_id, address) -> EmailConnection:
    conn = EmailConnection(company_id=company_id, email_address=address,
                           encrypted_app_password=encrypt_api_key("app-pass"),
                           imap_host="imap.example.com", imap_port=993,
                           smtp_host="smtp.example.com", smtp_port=587,
                           provider_type="custom", status="active")
    db.add(conn)
    await db.flush()
    return conn


def _client(db, company_id) -> httpx.AsyncClient:
    app = FastAPI()
    app.include_router(email_router.router)
    user = SimpleNamespace(id=uuid.uuid4(), role="tenant_admin", company_id=company_id)

    async def _auth():
        return user, SimpleNamespace(id=company_id)

    async def _db():
        yield db

    app.dependency_overrides[get_current_user_and_company] = _auth
    app.dependency_overrides[get_db] = _db
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


@pytest.fixture
def imap_logins(monkeypatch):
    calls: list = []

    class _IMAP:
        def __init__(self, host, port):
            calls.append((host, port))

        def login(self, user, password):
            calls.append((user, password))

        def noop(self):
            return "OK", []

        def logout(self):
            pass

    monkeypatch.setattr(email_router.imaplib, "IMAP4_SSL", _IMAP)
    return calls


@pytest.mark.asyncio
async def test_list_shows_only_the_callers_company(db):
    mine, theirs = await _company(db), await _company(db)
    await _connection(db, mine, "me@example.com")
    await _connection(db, theirs, "them@example.com")
    async with _client(db, mine) as c:
        # A company_id in the query string, as the old frontend sent, is ignored.
        res = await c.get(f"/email/connections?company_id={theirs}")
    assert res.status_code == 200
    assert [r["email_address"] for r in res.json()] == ["me@example.com"]


@pytest.mark.asyncio
async def test_create_lands_in_the_callers_company(db):
    mine, theirs = await _company(db), await _company(db)
    async with _client(db, mine) as c:
        res = await c.post(f"/email/connections?company_id={theirs}",
                           json={"email_address": "new@example.com", "app_password": "p"})
    assert res.status_code == 200
    assert res.json()["company_id"] == str(mine)


@pytest.mark.asyncio
async def test_another_companys_connection_cannot_be_deleted(db):
    mine, theirs = await _company(db), await _company(db)
    victim = await _connection(db, theirs, "them@example.com")
    async with _client(db, mine) as c:
        res = await c.delete(f"/email/connections/{victim.id}")
    assert res.status_code == 404
    still = await db.execute(select(EmailConnection.id).where(EmailConnection.id == victim.id))
    assert still.scalar_one_or_none() == victim.id


@pytest.mark.asyncio
async def test_another_companys_connection_is_never_decrypted_or_logged_into(db, imap_logins):
    mine, theirs = await _company(db), await _company(db)
    victim = await _connection(db, theirs, "them@example.com")
    async with _client(db, mine) as c:
        res = await c.post(f"/email/connections/{victim.id}/validate")
    assert res.status_code == 404
    assert imap_logins == []


@pytest.mark.asyncio
async def test_own_connection_validates_and_deletes(db, imap_logins):
    mine = await _company(db)
    own = await _connection(db, mine, "me@example.com")
    async with _client(db, mine) as c:
        res = await c.post(f"/email/connections/{own.id}/validate")
        assert res.status_code == 200 and res.json()["valid"] is True
        assert ("me@example.com", "app-pass") in imap_logins
        res = await c.delete(f"/email/connections/{own.id}")
    assert res.status_code == 200
