"""API-16, API-I3: every list pages the same way — items, next_cursor, limit.

``/ai/entities``, ``/ai/executions`` and ``/config/integrations`` answered every
row at once (``app_admin``: every company's integrations), and ``/artifacts``
took ``limit`` / ``offset`` and answered ``{"artifacts", "count"}``. Each now
takes ``?limit=`` (≤ 200) and ``?cursor=`` and answers one keyset page, newest
first. Real Postgres (rolled back).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

pytestmark = pytest.mark.needs_db


def _client(db, actor, *mounts) -> httpx.AsyncClient:
    from src.auth.dependencies import get_current_user
    from src.common.database import get_db

    app = FastAPI()
    for router, prefix in mounts:
        app.include_router(router, prefix=prefix)

    async def _user():
        return actor

    async def _db():
        yield db

    app.dependency_overrides[get_current_user] = _user
    app.dependency_overrides[get_db] = _db
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


async def _all_pages(client, path, limit, **params):
    pages, cursor = [], None
    while True:
        query = {"limit": limit, **params, **({"cursor": cursor} if cursor else {})}
        res = await client.get(path, params=query)
        assert res.status_code == 200, res.text
        body = res.json()
        assert set(body) == {"items", "next_cursor", "limit"} and body["limit"] == limit
        pages.append(body["items"])
        cursor = body["next_cursor"]
        if not cursor:
            return pages


@pytest.mark.asyncio
async def test_entities_page_through_newest_first(db, test_company_id):
    from src.ai.orm.entity import HierarchicalEntity
    from src.ai.router import router as ai_router

    base = datetime.utcnow()
    made = []
    for n in range(5):
        e = HierarchicalEntity(company_id=test_company_id, type="AGENT", status="ACTIVE",
                               name=f"api16-{n}-{uuid.uuid4().hex[:6]}", created_at=base + timedelta(seconds=n))
        db.add(e)
        made.append(e)
    await db.flush()
    actor = SimpleNamespace(id=uuid.uuid4(), role="tenant_admin", company_id=test_company_id)
    async with _client(db, actor, (ai_router, "/api/v1")) as client:
        pages = await _all_pages(client, "/api/v1/ai/entities", 2)
    ids = [e["id"] for page in pages for e in page]
    assert [len(p) for p in pages][:2] == [2, 2]
    assert len(ids) == len(set(ids))                              # no row twice
    ours = [i for i in ids if i in {str(e.id) for e in made}]
    assert ours == [str(e.id) for e in reversed(made)]            # newest first, none lost


@pytest.mark.asyncio
async def test_voice_agents_are_filtered_in_sql(db, test_company_id):
    from src.ai.orm.entity import HierarchicalEntity
    from src.ai.router import router as ai_router

    voiced = HierarchicalEntity(company_id=test_company_id, type="AGENT", status="ACTIVE", name="api16-voice",
                                identity={"persona": {"voice": {"voice_name": "Puck"}}})
    silent = HierarchicalEntity(company_id=test_company_id, type="AGENT", status="ACTIVE", name="api16-silent",
                                identity={"voice": {}})
    db.add_all([voiced, silent])
    await db.flush()
    actor = SimpleNamespace(id=uuid.uuid4(), role="tenant_admin", company_id=test_company_id)
    async with _client(db, actor, (ai_router, "/api/v1")) as client:
        res = await client.get("/api/v1/ai/entities", params={"voice_enabled": "true", "limit": 1})
    assert [e["id"] for e in res.json()["items"]] == [str(voiced.id)]   # a full page, not a filtered one


@pytest.mark.asyncio
async def test_executions_and_artifacts_page_the_same_way(db, test_company_id):
    from src.ai.artifact_models import Artifact
    from src.ai.artifact_router import router as artifact_router
    from src.ai.orm.entity import HierarchicalEntity
    from src.ai.orm.execution import ExecutionRun
    from src.ai.router import router as ai_router

    agent = HierarchicalEntity(company_id=test_company_id, type="AGENT", status="ACTIVE", name="api16-runs")
    db.add(agent)
    await db.flush()
    base = datetime.utcnow()
    for n in range(3):
        db.add(ExecutionRun(entity_id=agent.id, company_id=test_company_id, status="COMPLETED",
                            input_data={}, created_at=base + timedelta(seconds=n)))
        db.add(Artifact(company_id=test_company_id, origin="system-generated", file_category="text",
                        file_name=f"api16-{n}.txt", file_path=f"/tmp/api16-{n}.txt"))
    await db.flush()
    actor = SimpleNamespace(id=uuid.uuid4(), role="tenant_admin", company_id=test_company_id)
    async with _client(db, actor, (ai_router, "/api/v1"), (artifact_router, "")) as client:
        runs = await _all_pages(client, "/api/v1/ai/executions", 2)
        files = await _all_pages(client, "/api/v1/artifacts", 2)
        refused = await client.get("/api/v1/ai/executions", params={"cursor": "not-a-cursor"})
        too_big = await client.get("/api/v1/artifacts", params={"limit": 500})
    assert sum(len(p) for p in runs) == 3 and len(runs) == 2
    assert sorted(f["file_name"] for p in files for f in p) == ["api16-0.txt", "api16-1.txt", "api16-2.txt"]
    assert refused.status_code == 400
    assert too_big.status_code == 422


@pytest.mark.asyncio
async def test_integrations_are_one_companys_even_for_app_admin(db, test_company_id):
    from src.auth.models import Company
    from src.config.models import IntegrationRegistry
    from src.config.router import router as config_router

    other = Company(name=f"api16-{uuid.uuid4().hex[:6]}", type="TENANT", status="active")
    db.add(other)
    await db.flush()
    for company in (test_company_id, other.id):
        db.add(IntegrationRegistry(company_id=company, provider_name="test", service_sku=f"api16-{uuid.uuid4().hex[:6]}",
                                   model_name="m", component_type="input_token", cost_unit="per_1M_tokens",
                                   internal_cost=1, status="active", service_category="LLM"))
    await db.flush()
    admin = SimpleNamespace(id=uuid.uuid4(), role="app_admin", company_id=test_company_id)
    tenant = SimpleNamespace(id=uuid.uuid4(), role="tenant_admin", company_id=test_company_id)
    async with _client(db, admin, (config_router, "/api/v1")) as client:
        own = (await client.get("/api/v1/config/integrations")).json()["items"]
        theirs = (await client.get("/api/v1/config/integrations", params={"company_id": str(other.id)})).json()["items"]
    async with _client(db, tenant, (config_router, "/api/v1")) as client:
        refused = await client.get("/api/v1/config/integrations", params={"company_id": str(other.id)})
    assert {i["company_id"] for i in own} == {str(test_company_id)}
    assert {i["company_id"] for i in theirs} == {str(other.id)}
    assert refused.status_code == 403
