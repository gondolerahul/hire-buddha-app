"""PO-23 on Postgres: templates can be created, and only app_admin changes them.

``create_entity`` gave a template ``company_id = None`` against a NOT NULL
column, so ``POST /ai/templates`` always failed; and ``PUT``/``DELETE
/ai/entities/{id}`` loaded through ``get_entity``, which returns templates to
every caller, with no template check — any signed-in user could edit or delete a
template every tenant clones. An ordinary update could also turn a tenant's
entity into a template every tenant sees.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import select

from src.ai.orm import HierarchicalEntity
from src.ai.router import router

pytestmark = pytest.mark.needs_db


@pytest_asyncio.fixture
async def world(db, monkeypatch):
    from src.auth.models import Company
    from src.auth.platform import platform_company_id

    platform = await platform_company_id(db)
    if platform is None:
        app_co = Company(name=f"po23-app-{uuid.uuid4().hex[:6]}", type="APP", status="active")
        db.add(app_co)
        await db.flush()
        platform = app_co.id
    tenant = Company(name=f"po23-{uuid.uuid4().hex[:6]}", type="TENANT", status="active")
    db.add(tenant)
    await db.flush()
    own = HierarchicalEntity(company_id=tenant.id, type="AGENT", status="ACTIVE", name="mine")
    db.add(own)
    await db.flush()
    return SimpleNamespace(platform=platform, tenant=tenant, own=own)


def _client(db, role: str, company_id) -> httpx.AsyncClient:
    from src.auth.dependencies import get_current_user
    from src.common.database import get_db

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    actor = SimpleNamespace(id=None, role=role, company_id=company_id)

    async def _user():
        return actor

    async def _db():
        yield db

    app.dependency_overrides[get_current_user] = _user
    app.dependency_overrides[get_db] = _db
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


TEMPLATE = {"type": "AGENT", "name": "Lead qualifier", "goal": "Qualify inbound leads"}


async def _template(db, world) -> uuid.UUID:
    async with _client(db, "app_admin", world.platform) as c:
        r = await c.post("/api/v1/ai/templates", json=TEMPLATE)
        assert r.status_code == 200, r.text
        return uuid.UUID(r.json()["id"])


@pytest.mark.asyncio
async def test_app_admin_creates_a_template_owned_by_the_platform(db, world):
    template_id = await _template(db, world)
    row = (await db.execute(select(HierarchicalEntity).where(HierarchicalEntity.id == template_id))).scalar_one()
    assert row.is_template and row.company_id == world.platform


@pytest.mark.asyncio
async def test_tenants_read_and_clone_but_cannot_change_a_template(db, world):
    template_id = await _template(db, world)
    async with _client(db, "tenant_admin", world.tenant.id) as c:
        listed = (await c.get("/api/v1/ai/templates")).json()
        assert str(template_id) in [t["id"] for t in listed]
        assert (await c.put(f"/api/v1/ai/entities/{template_id}", json={"goal": "hijacked"})).status_code == 403
        assert (await c.delete(f"/api/v1/ai/entities/{template_id}")).status_code == 403
        clone = await c.post(f"/api/v1/ai/templates/{template_id}/clone")
        assert clone.status_code == 200, clone.text
    copy = (await db.execute(select(HierarchicalEntity).where(
        HierarchicalEntity.id == uuid.UUID(clone.json()["id"])))).scalar_one()
    assert copy.company_id == world.tenant.id and not copy.is_template
    template = (await db.execute(select(HierarchicalEntity).where(HierarchicalEntity.id == template_id))).scalar_one()
    assert template.goal == "Qualify inbound leads" and template.status != "DELETED"


@pytest.mark.asyncio
async def test_a_tenant_cannot_make_a_template(db, world):
    async with _client(db, "tenant_admin", world.tenant.id) as c:
        r = await c.post("/api/v1/ai/entities", json={**TEMPLATE, "is_template": True})
        assert r.status_code == 403
        r = await c.put(f"/api/v1/ai/entities/{world.own.id}", json={"is_template": True})
        assert r.status_code == 422
    await db.refresh(world.own)
    assert not world.own.is_template


@pytest.mark.asyncio
async def test_app_admin_changes_a_template(db, world):
    template_id = await _template(db, world)
    async with _client(db, "app_admin", world.platform) as c:
        r = await c.put(f"/api/v1/ai/templates/{template_id}", json={"goal": "Qualify and book"})
        assert r.status_code == 200, r.text
        assert (await c.delete(f"/api/v1/ai/templates/{template_id}")).status_code == 200
