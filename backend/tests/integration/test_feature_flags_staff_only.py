"""Phase 15 T0-1: feature flags are staff-only, declared and audited.

Before, a tenant or partner admin could set any flag for its own company —
``meta_agent.tool_synthesis_enabled`` and ``tools.video.people_of_all_ages``
among them — under any key, typos included, and nothing recorded who did it.
Real Postgres (rolled back): the routes run on the test's session.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import text

from src.ai.api import admin
from src.ai.core import flag_rows
from src.ai.core.feature_flags import flag_kind
from src.auth.dependencies import get_current_user
from src.common.database import get_db

pytestmark = pytest.mark.needs_db

FLAG = "/ai/admin/feature_flags"


def _client(db, role: str, company_id) -> httpx.AsyncClient:
    app = FastAPI()
    app.include_router(admin.router)
    user = SimpleNamespace(id=uuid.uuid4(), role=role, company_id=company_id)

    async def _user():
        return user

    async def _db():
        yield db

    app.dependency_overrides[get_current_user] = _user
    app.dependency_overrides[get_db] = _db
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


async def _audit(db, key: str) -> list:
    return (await db.execute(text(
        "SELECT action, actor_role, target_company_id, old_value, new_value, reason, scope "
        "FROM admin_audit_log WHERE object_type = 'feature_flag' AND object_key = :k ORDER BY at, id"
    ), {"k": key})).all()


async def _row(db, key: str, company_id):
    return (await db.execute(text(
        "SELECT enabled, value_json FROM feature_flags WHERE flag_key = :k AND company_id = :c AND entity_id IS NULL"
    ), {"k": key, "c": str(company_id)})).first()


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["tenant_admin", "partner_admin", "tenant_user", "app_user"])
async def test_only_app_admin_writes_a_flag(db, test_company_id, role):
    async with _client(db, role, test_company_id) as client:
        put = await client.put(f"{FLAG}/meta_agent.tool_synthesis_enabled",
                               json={"scope": "company", "enabled": True})
        delete = await client.delete(f"{FLAG}/meta_agent.tool_synthesis_enabled", params={"scope": "company"})
        experimental = await client.post("/ai/admin/admin/tools/web_search/experimental",
                                         params={"enabled": "true"})
    assert (put.status_code, delete.status_code, experimental.status_code) == (403, 403, 403)
    assert await _row(db, "meta_agent.tool_synthesis_enabled", test_company_id) is None
    assert await _audit(db, "meta_agent.tool_synthesis_enabled") == []


@pytest.mark.asyncio
async def test_an_unknown_key_is_refused(db, test_company_id):
    async with _client(db, "app_admin", test_company_id) as client:
        typo = await client.put(f"{FLAG}/bandit.enabeld", json={"scope": "company", "enabled": True,
                                                             "company_id": str(test_company_id)})
        bad_tool = await client.put(f"{FLAG}/tools.experimental.Not A Tool", json={"scope": "global", "enabled": True})
    assert typo.status_code == 422 and "unknown feature flag" in typo.json()["detail"]
    assert bad_tool.status_code == 422


@pytest.mark.asyncio
async def test_values_must_match_the_flag(db, test_company_id):
    body = {"scope": "company", "company_id": str(test_company_id)}
    async with _client(db, "app_admin", test_company_id) as client:
        not_bool = await client.put(f"{FLAG}/bandit.enabled", json={**body, "enabled": "yes"})
        not_number = await client.put(f"{FLAG}/bandit.epsilon", json={**body, "value_json": "0.2"})
        number = await client.put(f"{FLAG}/bandit.epsilon", json={**body, "value_json": 0.2})
    assert (not_bool.status_code, not_number.status_code, number.status_code) == (422, 422, 200)


@pytest.mark.asyncio
async def test_each_write_is_audited_with_the_value_it_replaced(db, test_company_id):
    key = "tools.video.people_of_all_ages"
    body = {"scope": "company", "company_id": str(test_company_id)}
    async with _client(db, "app_admin", test_company_id) as client:
        first = await client.put(f"{FLAG}/{key}", json={**body, "enabled": True, "reason": "customer asked, ticket 42"})
        second = await client.put(f"{FLAG}/{key}", json={**body, "enabled": False})
        gone = await client.delete(f"{FLAG}/{key}", params={"scope": "company", "company_id": str(test_company_id),
                                                            "reason": "back to the default"})
    assert first.status_code == second.status_code == gone.status_code == 200
    assert gone.json()["deleted"] is True
    assert await _row(db, key, test_company_id) is None

    audit = await _audit(db, key)
    assert [a.action for a in audit] == ["set", "set", "delete"]
    assert all(a.actor_role == "app_admin" and a.target_company_id == test_company_id for a in audit)
    assert audit[0].old_value is None and audit[0].new_value == {"enabled": True, "value_json": None}
    assert audit[0].reason == "customer asked, ticket 42" and audit[0].scope["scope"] == "company"
    assert audit[1].old_value == {"enabled": True, "value_json": None}
    assert audit[1].new_value == {"enabled": False, "value_json": None}
    assert audit[2].old_value == {"enabled": False, "value_json": None} and audit[2].new_value is None
    assert audit[2].reason == "back to the default"


@pytest.mark.asyncio
async def test_staff_opt_a_company_into_an_experimental_tool(db, test_company_id):
    async with _client(db, "app_admin", uuid.uuid4()) as client:
        response = await client.post("/ai/admin/admin/tools/web_search/experimental",
                                     params={"enabled": "true", "company_id": str(test_company_id)})
    assert response.status_code == 200 and response.json()["company_id"] == str(test_company_id)
    assert (await _row(db, "tools.experimental.web_search", test_company_id)).enabled is True
    assert [a.action for a in await _audit(db, "tools.experimental.web_search")] == ["set"]


def test_declared_keys():
    assert flag_kind("bandit.enabled") == "boolean"
    assert flag_kind("bandit.epsilon") == "numeric"
    assert flag_kind("tools.experimental.sandbox_code") == "boolean"
    assert flag_kind("tools.experimental.") is None
    assert flag_kind("bandit.enabeld") is None


@pytest.mark.asyncio
async def test_rows_customers_wrote_are_reported_and_can_be_reset(db, test_company_id):
    from src.ai.core.feature_flags import FeatureFlags

    flags = FeatureFlags(db)
    await flags.set("bandit.enabled", enabled=False, company_id=test_company_id)     # a customer's, before T0-1
    await flags.set("not.a.flag", enabled=True, company_id=test_company_id)          # a typo nothing reads
    report = await flag_rows.find_rows(db)
    mine = {k: [i["flag_key"] for i in items if i["company_id"] == test_company_id] for k, items in report.items()}
    assert mine == {"undeclared": ["not.a.flag"], "customer": ["bandit.enabled"]}

    # A row staff set (audited) is not a customer's.
    async with _client(db, "app_admin", test_company_id) as client:
        await client.put(f"{FLAG}/planner.v2_enabled",
                         json={"scope": "company", "company_id": str(test_company_id), "enabled": False})
    report = await flag_rows.find_rows(db)
    assert "planner.v2_enabled" not in [i["flag_key"] for i in report["customer"] if i["company_id"] == test_company_id]

    doomed = [i for i in report["undeclared"] + report["customer"] if i["company_id"] == test_company_id]
    assert await flag_rows.remove(db, doomed, "test") == 2
    assert await _row(db, "bandit.enabled", test_company_id) is None
    assert await _row(db, "planner.v2_enabled", test_company_id) is not None
    assert [a.action for a in await _audit(db, "not.a.flag")] == ["delete"]
