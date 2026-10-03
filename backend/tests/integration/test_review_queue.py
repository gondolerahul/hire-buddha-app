"""What waits for a person is counted (P10.7 — MI-17).

Four things need a human — prompt candidates, skill candidates, DRAFT entities
and DRAFT synthesized tools — and nothing said any of them was waiting, so the
queues were seen only by someone who happened to open the right tab.
Real Postgres, rolled back.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from src.ai.api.admin import router
from src.ai.meta.meta_intelligence_tree import MetaIntelligenceTree
from src.ai.models import HierarchicalEntity
from src.ai.orm.tools import ToolRegistryEntry

pytestmark = pytest.mark.needs_db


@pytest.mark.asyncio
async def test_the_queue_counts_everything_that_waits(db, test_company_id):
    from src.auth.dependencies import get_current_user
    from src.common.database import get_db

    tree = MetaIntelligenceTree(db, test_company_id)
    await tree.add_prompt_update_candidate(prompt_diff="+ be terse", rationale="too long")
    approved = await tree.add_prompt_update_candidate(prompt_diff="+ cite", rationale="no sources")
    await tree.approve_prompt_candidate(approved)
    await tree.add_skill_candidate(source_entity_id=uuid.uuid4(), chain=["web_search", "scraper_tool"], frequency=4)
    db.add(HierarchicalEntity(company_id=test_company_id, type="SKILL", status="DRAFT", name=f"d-{uuid.uuid4().hex[:6]}"))
    db.add(ToolRegistryEntry(company_id=test_company_id, name=f"synth_{uuid.uuid4().hex[:6]}",
                             tool_type="SYNTHESIZED", configuration={"status": "DRAFT"}))
    await db.flush()

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")

    async def _user():
        return SimpleNamespace(id=uuid.uuid4(), role="tenant_admin", company_id=test_company_id)

    async def _db():
        yield db

    app.dependency_overrides[get_current_user] = _user
    app.dependency_overrides[get_db] = _db
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        body = (await c.get("/api/v1/ai/admin/meta/review_queue")).json()

    assert body["prompt_candidates"] == 1          # the approved one is not waiting
    assert body["skill_candidates"] == 1
    assert body["draft_entities"] >= 1 and body["draft_tools"] >= 1
    assert body["total"] == sum(v for k, v in body.items() if k != "total")
