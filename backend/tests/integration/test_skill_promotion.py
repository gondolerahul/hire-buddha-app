"""A skill candidate becomes a DRAFT SKILL through the creation service, and is
published through the Validator (P10.8 — R2 §11).

The promote route wrote the row directly with ``capabilities.tool_ids`` — a key
nothing reads, so the skill was granted no tools — and steps with no target, so
it could not run its own chain; no version was captured. Real Postgres, rolled back.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select

from src.ai.api.admin import router
from src.ai.meta.meta_intelligence_tree import MetaIntelligenceTree
from src.ai.models import HierarchicalEntity

pytestmark = pytest.mark.needs_db


@pytest.mark.asyncio
async def test_a_promoted_skill_can_run_its_chain_and_be_published(db, test_company_id, monkeypatch):
    from src.auth.dependencies import get_current_user
    from src.common.database import get_db

    monkeypatch.setattr(db, "commit", db.flush)
    node = await MetaIntelligenceTree(db, test_company_id).add_skill_candidate(
        source_entity_id=uuid.uuid4(), chain=["web_search", "scraper_tool"], frequency=5)

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")

    async def _user():
        return SimpleNamespace(id=None, role="tenant_admin", company_id=test_company_id)

    async def _db():
        yield db

    app.dependency_overrides[get_current_user] = _user
    app.dependency_overrides[get_db] = _db
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(f"/api/v1/ai/admin/meta/skill_candidates/{node}/promote")
        assert r.status_code == 200, r.text
        entity_id = r.json()["entity_id"]
        skill = (await db.execute(select(HierarchicalEntity).where(HierarchicalEntity.id == uuid.UUID(entity_id)))).scalar_one()

        assert (skill.type, skill.status) == ("SKILL", "DRAFT")
        assert [t["tool_id"] for t in skill.capabilities["tools"]] == ["web_search", "scraper_tool"]
        steps = skill.planning["static_plan"]["steps"]
        assert [(s["type"], s["target"]["tool_id"]) for s in steps] == [("TOOL_CALL", "web_search"),
                                                                         ("TOOL_CALL", "scraper_tool")]
        assert steps[1]["target"]["input_dependencies"] == ["step_1"]
        assert skill.active_version_id is not None        # version 1 captured

        r = await c.post(f"/api/v1/ai/admin/meta/entities/{entity_id}/promote")
        assert r.status_code == 200, r.text                 # passes the publication checks
        assert r.json()["status"] == "ACTIVE"
