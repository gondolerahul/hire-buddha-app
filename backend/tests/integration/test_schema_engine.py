"""The schema engine in a business's own database (WS4 4.1–4.4; tech spec §8):
base pack v1 on first use, a business's additions applied with their DDL,
checks that refuse and leave the blueprint as it was, an agent's change
waiting for a person, previews with their impact, and the
``schema.version.activated`` event.

Each test has a throwaway tenant database (``tests.harness.tenant_db``).
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import select, text

from src.automation import store
from src.schema_engine import engine as schema
from src.schema_engine.planner import PlanError

pytestmark = pytest.mark.needs_db


@pytest_asyncio.fixture
async def control(monkeypatch):
    """The control database through a per-test engine (no pooled connection from another test's loop)."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    import src.common.orm_models  # noqa: F401
    from src.common import database
    from src.common.config import settings

    engine = create_async_engine(settings.CONTROL_DATABASE_URL, poolclass=NullPool,
                                 json_serializer=database.json_serializer)
    monkeypatch.setattr(database, "AsyncSessionLocal", async_sessionmaker(engine, expire_on_commit=False))
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def tenant(control, monkeypatch):
    from tests.harness.tenant_db import scratch_tenant

    nudged = []

    async def _nudge(company_id, event_id, *, attempt=""):
        nudged.append(event_id)

    monkeypatch.setattr(store, "nudge", _nudge)
    async with scratch_tenant() as t:
        engine, _ = await schema.business_engine(t.company_id)
        t.engine, t.nudged = engine, nudged
        yield t


async def _tables(t):
    async with t.engine.connect() as conn:
        return {f"{s}.{n}" for s, n in (await conn.execute(text(
            "SELECT table_schema, table_name FROM information_schema.tables "
            "WHERE table_schema IN ('business', 'custom')"))).all()}


async def test_records_need_the_business_on_its_own_database(control):
    import uuid

    with pytest.raises(schema.RecordsUnavailable):
        await schema.business_engine(uuid.uuid4())


async def test_the_base_pack_is_applied_on_first_use(tenant):
    blueprint = await schema.active_blueprint(tenant.engine, tenant.company_id)
    assert blueprint["version"] == 1 and blueprint["base_pack"] == "1.0"
    assert await _tables(tenant) == {"business.account", "business.contact", "business.activity", "business.consent"}
    again = await schema.active_blueprint(tenant.engine, tenant.company_id)
    assert again["version"] == 1                                    # once
    async with schema.session(tenant.engine) as db:
        from src.automation.models import Event

        event = (await db.execute(select(Event).where(Event.type == "schema.version.activated"))).scalar_one()
    assert event.data["version"] == 1 and tenant.nudged == [event.id]


async def test_a_business_adds_an_object_and_a_field_and_they_exist(tenant):
    await schema.active_blueprint(tenant.engine, tenant.company_id)
    change = await schema.propose(tenant.engine, tenant.company_id, [
        {"op": "add_object", "object": "order", "definition": {"fields": {
            "number": {"type": "text", "max_length": 40, "required": True},
            "contact": {"type": "ref", "to": "contact"},
            "status": {"type": "enum", "values": ["new", "paid"], "default": "new"}}}},
        {"op": "add_field", "object": "contact", "field": "x_tier", "definition": {"type": "text"}},
    ], actor_kind="user", actor_id="user:owner")
    assert change["status"] == "applied" and change["result_version"] == 2
    assert "custom.order" in await _tables(tenant)
    async with tenant.engine.begin() as conn:
        contact_id = (await conn.execute(text(
            "INSERT INTO business.contact (first_name, x_tier) VALUES ('Priya', 'gold') RETURNING id"))).scalar()
        await conn.execute(text("INSERT INTO custom.\"order\" (number, contact) VALUES ('A-1', :c)"), {"c": contact_id})
        with pytest.raises(Exception):  # the enum's CHECK
            async with conn.begin_nested():
                await conn.execute(text("INSERT INTO custom.\"order\" (number, status) VALUES ('A-2', 'lost')"))


async def test_a_check_that_fails_leaves_everything_as_it_was(tenant):
    await schema.active_blueprint(tenant.engine, tenant.company_id)
    async with tenant.engine.begin() as conn:
        await conn.execute(text("INSERT INTO business.contact (first_name) VALUES ('No source')"))
    with pytest.raises(schema.ApplyError, match="fill them first"):
        await schema.propose(tenant.engine, tenant.company_id,
                             [{"op": "make_required", "object": "contact", "field": "source"}],
                             actor_kind="platform")
    assert (await schema.active_blueprint(tenant.engine, tenant.company_id))["version"] == 1
    with pytest.raises(PlanError, match="cannot be changed in place"):
        await schema.propose(tenant.engine, tenant.company_id,
                             [{"op": "change_type", "object": "contact", "field": "source"}], actor_kind="user")


async def test_an_agents_change_waits_for_a_person(tenant):
    await schema.active_blueprint(tenant.engine, tenant.company_id)
    ops = [{"op": "add_object", "object": "shipment", "definition": {"fields": {"carrier": {"type": "text"}}}}]
    waiting = await schema.propose(tenant.engine, tenant.company_id, ops, actor_kind="agent", actor_id="run:1")
    assert waiting["status"] == "awaiting_approval" and "custom.shipment" not in await _tables(tenant)
    applied = await schema.decide(tenant.engine, tenant.company_id, waiting["id"], approve=True,
                                  decided_by="user:owner")
    assert applied["status"] == "applied" and "custom.shipment" in await _tables(tenant)

    other = await schema.propose(tenant.engine, tenant.company_id,
                                 [{"op": "add_index", "object": "shipment", "columns": ["carrier"]}],
                                 actor_kind="agent", actor_id="run:2")
    rejected = await schema.decide(tenant.engine, tenant.company_id, other["id"], approve=False,
                                   decided_by="user:owner")
    assert rejected["status"] == "rejected"
    auto = await schema.propose(tenant.engine, tenant.company_id,
                                [{"op": "add_index", "object": "shipment", "columns": ["carrier"]}],
                                actor_kind="agent", actor_id="run:3", agents_auto_additive=True)
    assert auto["status"] == "applied"


async def test_a_preview_shows_the_plan_and_what_it_touches(tenant):
    from src.automation.models import Trigger

    await schema.active_blueprint(tenant.engine, tenant.company_id)
    async with schema.session(tenant.engine) as db:
        import uuid

        from src.ai.orm import HierarchicalEntity

        agent = HierarchicalEntity(company_id=tenant.company_id, type="AGENT", status="ACTIVE", name="Invoicer")
        db.add(agent)
        await db.flush()
        db.add(Trigger(id=uuid.uuid4(), company_id=tenant.company_id, name="on contact change", kind="data",
                       entity_id=agent.id, event_type="record.contact.*", created_by_kind="user"))
        await db.commit()
    preview = await schema.propose(tenant.engine, tenant.company_id,
                                   [{"op": "add_field", "object": "contact", "field": "x_score",
                                     "definition": {"type": "integer"}}], actor_kind="user", dry_run=True)
    assert preview["status"] == "preview" and preview["result_version"] == 2
    assert 'ADD COLUMN "x_score" bigint' in preview["plan"]["statements"][0]["sql"]
    assert [t["name"] for t in preview["impact"]["triggers"]] == ["on contact change"]
    assert (await schema.active_blueprint(tenant.engine, tenant.company_id))["version"] == 1
