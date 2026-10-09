"""API-18: DELETE on an entity says it is a soft delete, and admins can list what it kept.

``DELETE /ai/entities/{id}`` answered ``{"status": "success"}`` while it kept the
rows (status ``DELETED``, ``deleted_at`` set, the descendants too) — nothing in
the API said so, and nothing could list them again. It now returns what it did
(``EntityDeleted``), documents it in OpenAPI, and ``GET /ai/entities`` takes
``include_deleted`` for admins. Real Postgres (rolled back).
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

pytestmark = pytest.mark.needs_db


async def _tree(db, company_id):
    from src.ai.orm.entity import HierarchicalEntity

    parent = HierarchicalEntity(company_id=company_id, type="PROCESS", status="ACTIVE",
                                name=f"api18-p-{uuid.uuid4().hex[:6]}")
    db.add(parent)
    await db.flush()
    child = HierarchicalEntity(company_id=company_id, type="AGENT", status="ACTIVE", parent_id=parent.id,
                               name=f"api18-c-{uuid.uuid4().hex[:6]}")
    db.add(child)
    await db.flush()
    return parent.id, child.id


@pytest.mark.asyncio
async def test_delete_returns_what_it_soft_deleted(db, test_company_id, monkeypatch):
    from src.ai import router as ai_router

    async def _quiet(*_a, **_k):
        return None

    monkeypatch.setattr("src.voice.agent_cache_bus.announce_agent_changed", _quiet)
    parent, child = await _tree(db, test_company_id)
    admin = SimpleNamespace(id=uuid.uuid4(), company_id=test_company_id, role="tenant_admin")
    body = await ai_router.delete_entity(parent, db=db, current_user=admin)
    assert body["status"] == "DELETED" and body["entity_id"] == parent
    assert set(body["deleted_ids"]) == {parent, child} and body["deleted_at"] is not None

    async def _ids(user, **kw):
        listed = await ai_router.list_entities(type=None, company_id=None, voice_enabled=None, status=None,
                                               db=db, current_user=user, **kw)
        return {e.id: e for e in listed}

    assert parent not in await _ids(admin, include_deleted=False)
    kept = await _ids(admin, include_deleted=True)
    assert {parent, child} <= set(kept)
    assert str(kept[child].status) in ("DELETED", "EntityStatus.DELETED") and kept[child].deleted_at is not None


@pytest.mark.asyncio
async def test_only_admins_may_list_deleted_entities(db, test_company_id):
    from src.ai import router as ai_router

    user = SimpleNamespace(id=uuid.uuid4(), company_id=test_company_id, role="tenant_user")
    with pytest.raises(HTTPException) as refused:
        await ai_router.list_entities(type=None, company_id=None, voice_enabled=None, status=None,
                                      include_deleted=True, db=db, current_user=user)
    assert refused.value.status_code == 403


def test_openapi_says_it_is_a_soft_delete():
    from src.main import app

    operation = app.openapi()["paths"]["/api/v1/ai/entities/{entity_id}"]["delete"]
    assert operation["summary"] == "Soft-delete an entity and its descendants"
    assert "soft delete" in operation["description"]
    schema = operation["responses"]["200"]["content"]["application/json"]["schema"]
    assert schema["$ref"].endswith("/EntityDeleted")
