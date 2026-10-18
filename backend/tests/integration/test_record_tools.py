"""Agents' record tools (WS4 4.8, M4) in a throwaway business database: the
tools a run is offered are declared from the business's blueprint and the
agent's ``capabilities.records``; calls go through the Data API as the run; a
new object an agent proposed and a person approved appears in the next run's
tools without a restart.
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio

from src.automation import store
from src.schema_engine import engine as schema

pytestmark = pytest.mark.needs_db

GRANTED = ["describe_schema", "find_records", "get_record", "create_record", "update_record", "link_records",
           "archive_record", "run_report", "propose_schema_change"]


@pytest_asyncio.fixture
async def biz(monkeypatch):
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    import src.common.orm_models  # noqa: F401
    from src.ai.orm import HierarchicalEntity
    from src.common import database
    from src.common.config import settings
    from src.common.tenancy.session import tenant_session
    from tests.harness.tenant_db import scratch_tenant

    control = create_async_engine(settings.CONTROL_DATABASE_URL, poolclass=NullPool,
                                  json_serializer=database.json_serializer)
    monkeypatch.setattr(database, "AsyncSessionLocal", async_sessionmaker(control, expire_on_commit=False))
    monkeypatch.setattr(database, "engine", control)  # a split tenant session's control tables
    monkeypatch.setattr(settings, "TENANCY_MODE", "split")

    async def _nudge(company_id, event_id, *, attempt=""):
        return None

    monkeypatch.setattr(store, "nudge", _nudge)
    async with scratch_tenant("rectools") as t:
        def agent(name, records):
            return HierarchicalEntity(company_id=t.company_id, type="AGENT", status="ACTIVE", name=name,
                                      capabilities={"tools": [{"tool_id": n} for n in GRANTED],
                                                    "records": records})
        async with tenant_session(t.company_id) as db:
            t.clerk = agent("Clerk", {"objects": {"contact": ["read", "create"]}, "schema_changes": "propose"})
            t.reader = agent("Reader", {"objects": {"*": ["read"]}, "reports": True})
            t.plain = agent("Plain", None)
            t.linker = agent("Linker", {"objects": {"contact": "*", "account": ["read", "create"]}})
            db.add_all([t.clerk, t.reader, t.plain, t.linker])
            await db.commit()
        t.engine, _ = await schema.business_engine(t.company_id)
        yield t
    await control.dispose()


async def _offered(biz, entity):
    from src.ai.governance.tool_access import ToolAccess
    from src.common.tenancy.session import tenant_session

    async with tenant_session(biz.company_id) as db:
        access = await ToolAccess.load(db, biz.company_id, entity, meta_tools=False)
    return {s["name"]: s for s in access.schemas()}


async def _call(biz, entity, name, args, run_id=None):
    from src.ai.tools.base import ToolRegistry

    ctx = {"company_id": str(biz.company_id), "run_id": str(run_id or uuid.uuid4()), "entity_id": str(entity.id)}
    return await ToolRegistry.get_tool(name).invoke(args, ctx)


async def test_a_run_is_offered_the_records_its_agent_may_use(biz):
    clerk = await _offered(biz, biz.clerk)
    assert set(clerk) == {"find_records", "get_record", "describe_schema", "create_record",
                          "propose_schema_change"}                      # no update, archive or reports
    assert clerk["create_record"]["parameters"]["properties"]["object"]["enum"] == ["contact"]
    assert "lifecycle_stage (one of subscriber|lead|" in clerk["find_records"]["description"]
    assert "email (email; personal)" in clerk["create_record"]["description"]
    reader = await _offered(biz, biz.reader)
    assert set(reader) == {"find_records", "get_record", "describe_schema", "run_report"}
    assert set(reader["run_report"]["parameters"]["properties"]["object"]["enum"]) == \
        {"account", "contact", "activity", "consent"}
    assert await _offered(biz, biz.plain) == {}                       # granted, but no records to reach


async def test_an_agent_creates_and_finds_records_within_its_capability(biz):
    run = uuid.uuid4()
    made = await _call(biz, biz.clerk, "create_record", {"object": "contact", "values": {
        "first_name": "Asha", "email": "asha@example.com"}}, run)
    assert made.success, made.error
    again = await _call(biz, biz.clerk, "create_record", {"object": "contact", "values": {
        "first_name": "Asha", "email": "asha@example.com"}}, run)
    assert again.output["id"] == made.output["id"]                    # the same create in one run: one record
    assert made.output["created_by"] == f"run:{run}"

    found = await _call(biz, biz.clerk, "find_records", {"object": "contact", "filters": [
        {"field": "email", "op": "eq", "value": "asha@example.com"}, {"field": "created_at", "op": "gt",
                                                                       "value": "now-1h"}]})
    assert [r["first_name"] for r in found.output["items"]] == ["Asha"]

    refused = await _call(biz, biz.clerk, "update_record", {"object": "contact", "id": made.output["id"],
                                                            "values": {"first_name": "A"}})
    assert not refused.success and refused.error_code == "forbidden"
    other = await _call(biz, biz.clerk, "find_records", {"object": "account"})
    assert not other.success and other.error_code == "forbidden"
    described = await _call(biz, biz.clerk, "describe_schema", {})
    assert described.output["objects"]["contact"]["you_may"] == ["create", "read"]


async def test_an_approved_object_appears_in_the_next_runs_tools(biz):
    proposed = await _call(biz, biz.clerk, "propose_schema_change", {
        "reason": "track deliveries", "operations": [{"op": "add_object", "object": "shipment", "definition": {
            "label": "Shipment", "fields": {"carrier": {"type": "text"}, "contact": {"type": "ref",
                                                                                      "to": "contact"}}}}]})
    assert proposed.success and proposed.output["status"] == "awaiting_approval"
    assert "shipment" not in (await _offered(biz, biz.reader))["find_records"]["parameters"]["properties"][
        "object"]["enum"]
    await schema.decide(biz.engine, biz.company_id, proposed.output["id"], approve=True, decided_by="user:owner")
    offered = await _offered(biz, biz.reader)
    assert "shipment" in offered["find_records"]["parameters"]["properties"]["object"]["enum"]
    assert "contact (id of a contact)" in offered["find_records"]["description"]


async def test_an_agent_links_a_contact_to_its_account(biz):
    assert "link_records" in await _offered(biz, biz.linker)
    account = (await _call(biz, biz.linker, "create_record", {"object": "account", "values": {"name": "Acme"}})).output
    contact = (await _call(biz, biz.linker, "create_record", {"object": "contact",
                                                              "values": {"first_name": "Ravi"}})).output
    linked = await _call(biz, biz.linker, "link_records", {"object": "contact", "id": contact["id"],
                                                           "relation": "account", "to": account["id"]})
    assert linked.success and linked.output["changed"][0]["account"] == account["id"]
    read = await _call(biz, biz.linker, "link_records", {"object": "account", "id": account["id"],
                                                         "relation": "contact", "read": True})
    assert [r["first_name"] for r in read.output["items"]] == ["Ravi"]
