"""Promoting a DRAFT entity passes the publication checks (P10.1 — MI-20, D27).

``POST /ai/admin/meta/entities/{id}/promote`` was "the admin override of the
Board pipeline"; with no Board it flipped any DRAFT to ACTIVE unchecked.
Real Postgres, rolled back.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from src.ai.api.admin import router
from src.ai.orm import HierarchicalEntity

pytestmark = pytest.mark.needs_db


def _client(db, company_id) -> httpx.AsyncClient:
    from src.auth.dependencies import get_current_user
    from src.common.database import get_db

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    actor = SimpleNamespace(id=uuid.uuid4(), role="tenant_admin", company_id=company_id)

    async def _user():
        return actor

    async def _db():
        yield db

    app.dependency_overrides[get_current_user] = _user
    app.dependency_overrides[get_db] = _db
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


async def _draft(db, company_id, **fields):
    ent = HierarchicalEntity(company_id=company_id, type="SKILL", status="DRAFT",
                             name=f"p10-{uuid.uuid4().hex[:6]}", goal="Summarise a page", **fields)
    db.add(ent)
    await db.flush()
    return ent


@pytest.mark.asyncio
async def test_a_draft_that_fails_the_checks_stays_a_draft(db, test_company_id, monkeypatch):
    monkeypatch.setattr(db, "commit", db.flush)
    ent = await _draft(db, test_company_id, capabilities={"tools": [{"tool_id": "not_a_tool"}]})
    async with _client(db, test_company_id) as c:
        r = await c.post(f"/api/v1/ai/admin/meta/entities/{ent.id}/promote")
    assert r.status_code == 422, r.text
    assert {c["name"] for c in r.json()["detail"]["failed_checks"]} == {"governance_caps_set", "granted_tools_exist"}
    assert ent.status == "DRAFT"


@pytest.mark.asyncio
async def test_a_draft_that_passes_is_promoted(db, test_company_id, monkeypatch):
    monkeypatch.setattr(db, "commit", db.flush)
    ent = await _draft(db, test_company_id, governance={"max_cost_usd": 0.5},
                       capabilities={"tools": [{"tool_id": "calculator"}]})
    async with _client(db, test_company_id) as c:
        r = await c.post(f"/api/v1/ai/admin/meta/entities/{ent.id}/promote")
    assert r.status_code == 200, r.text
    assert ent.status == "ACTIVE"
