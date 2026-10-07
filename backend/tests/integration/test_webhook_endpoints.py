"""GW-01 against Postgres: registering, using and revoking a webhook endpoint.

Real database, rolled back; the app is the two webhook routers with the caller
and the session overridden, and the queue captured. What is checked: the secret
is stored encrypted and shown once, the endpoint's company is the event's, a
foreign agent cannot be bound, roles are enforced, and a revoked endpoint or a
suspended company takes no more events.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import select

from src.gateway import envelope as envelope_module
from src.gateway import webhook_endpoints_router, webhook_inbound
from src.gateway.models import WebhookEndpoint

pytestmark = pytest.mark.needs_db


@pytest_asyncio.fixture
async def world(db, monkeypatch):
    from src.ai.orm import HierarchicalEntity
    from src.auth.models import Company

    queued: list[dict] = []

    async def fake_enqueue(function, *args, **kwargs):
        queued.append(args[0])
        return object()

    monkeypatch.setattr(envelope_module, "enqueue_job", fake_enqueue)
    mine = Company(name=f"gw01-{uuid.uuid4().hex[:6]}", type="TENANT", status="active")
    other = Company(name=f"gw01o-{uuid.uuid4().hex[:6]}", type="TENANT", status="active")
    db.add_all([mine, other])
    await db.flush()
    agent = HierarchicalEntity(company_id=mine.id, type="AGENT", status="ACTIVE", name="inbox")
    foreign = HierarchicalEntity(company_id=other.id, type="AGENT", status="ACTIVE", name="theirs")
    db.add_all([agent, foreign])
    await db.flush()
    return SimpleNamespace(mine=mine, other=other, agent=agent, foreign=foreign, queued=queued)


def _client(db, role: str, company) -> httpx.AsyncClient:
    from src.auth.dependencies import get_current_user
    from src.common.database import get_db

    app = FastAPI()
    app.include_router(webhook_endpoints_router.router)
    app.include_router(webhook_inbound.router)
    actor = SimpleNamespace(id=None, role=role, company_id=company.id)

    async def _user():
        return actor

    async def _db():
        yield db

    app.dependency_overrides[get_current_user] = _user
    app.dependency_overrides[get_db] = _db
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


def _signed(secret: str, payload: dict) -> tuple[bytes, dict]:
    body = json.dumps(payload).encode()
    sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return body, {"X-HB-Signature": sig, "Content-Type": "application/json"}


@pytest.mark.asyncio
async def test_register_use_and_revoke(db, world):
    async with _client(db, "tenant_admin", world.mine) as c:
        r = await c.post("/api/v1/webhook-endpoints",
                         json={"source": "crm", "name": "HubSpot leads", "entity_id": str(world.agent.id)})
        assert r.status_code == 201, r.text
        created = r.json()
        secret = created["secret"]
        assert created["url"].endswith(f"/webhook/inbound/{created['id']}")

        row = (await db.execute(select(WebhookEndpoint).where(WebhookEndpoint.id == uuid.UUID(created["id"])))).scalar_one()
        assert row.company_id == world.mine.id
        assert secret not in row.secret_encrypted          # stored encrypted

        listed = (await c.get("/api/v1/webhook-endpoints")).json()
        assert [e["id"] for e in listed] == [created["id"]]
        assert "secret" not in listed[0]                    # shown once

        body, headers = _signed(secret, {"crm_event": "lead.created"})
        r = await c.post(f"/webhook/inbound/{created['id']}?client_id={world.other.id}",
                         content=body, headers=headers)
        assert r.status_code == 202, r.text
        [envelope] = world.queued
        assert envelope["client_id"] == str(world.mine.id)   # the endpoint's company, not the query's
        assert envelope["metadata"]["entity_id"] == str(world.agent.id)
        await db.refresh(row)
        assert row.last_received_at is not None

        body, headers = _signed("not-the-secret-0000000000", {"crm_event": "lead.created"})
        r = await c.post(f"/webhook/inbound/{created['id']}", content=body, headers=headers)
        assert r.status_code == 401
        assert len(world.queued) == 1

        assert (await c.delete(f"/api/v1/webhook-endpoints/{created['id']}")).status_code == 204
        body, headers = _signed(secret, {"crm_event": "lead.created"})
        r = await c.post(f"/webhook/inbound/{created['id']}", content=body, headers=headers)
        assert r.status_code == 404
        assert len(world.queued) == 1


@pytest.mark.asyncio
async def test_a_provider_issued_secret_is_kept(db, world):
    async with _client(db, "tenant_admin", world.mine) as c:
        r = await c.post("/api/v1/webhook-endpoints",
                         json={"source": "github", "name": "repo", "secret": "my-github-webhook-secret"})
        assert r.status_code == 201
        assert r.json()["secret"] == "my-github-webhook-secret"


@pytest.mark.asyncio
async def test_a_foreign_agent_cannot_be_bound(db, world):
    async with _client(db, "tenant_admin", world.mine) as c:
        r = await c.post("/api/v1/webhook-endpoints",
                         json={"source": "generic", "name": "x", "entity_id": str(world.foreign.id)})
        assert r.status_code == 404


@pytest.mark.asyncio
async def test_only_company_admins_manage_endpoints(db, world):
    async with _client(db, "tenant_user", world.mine) as c:
        assert (await c.post("/api/v1/webhook-endpoints",
                             json={"source": "generic", "name": "x"})).status_code == 403
        assert (await c.get("/api/v1/webhook-endpoints")).status_code == 403


@pytest.mark.asyncio
async def test_another_companys_endpoint_is_invisible(db, world):
    async with _client(db, "tenant_admin", world.mine) as c:
        created = (await c.post("/api/v1/webhook-endpoints",
                                json={"source": "generic", "name": "mine"})).json()
    async with _client(db, "tenant_admin", world.other) as c:
        assert (await c.get("/api/v1/webhook-endpoints")).json() == []
        assert (await c.delete(f"/api/v1/webhook-endpoints/{created['id']}")).status_code == 404


@pytest.mark.asyncio
async def test_a_suspended_company_takes_no_events(db, world):
    async with _client(db, "tenant_admin", world.mine) as c:
        created = (await c.post("/api/v1/webhook-endpoints",
                                json={"source": "generic", "name": "mine"})).json()
        world.mine.status = "suspended"
        await db.flush()
        body, headers = _signed(created["secret"], {"type": "x"})
        r = await c.post(f"/webhook/inbound/{created['id']}", content=body, headers=headers)
        assert r.status_code == 404
        assert world.queued == []


@pytest.mark.asyncio
async def test_an_unknown_source_is_422(db, world):
    async with _client(db, "tenant_admin", world.mine) as c:
        r = await c.post("/api/v1/webhook-endpoints", json={"source": "carrier-pigeon", "name": "x"})
        assert r.status_code == 422
