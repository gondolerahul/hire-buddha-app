"""Wave 3's data rules end to end (docs/phase15/14_connector_approvals/10 §3.1–§3.5).

Real Postgres; the rows this module commits are purged with its company.

* SH-E2, LI-E2: a run that read LinkedIn comments is marked; once LinkedIn's
  limit is up the hourly pass removes them from its tool log, trace, prompts,
  memory and result; a Page's statistics stay their year; a disconnect brings
  the removal forward.
* LI-E3: a run that read LinkedIn member data saves no records and no episode.
* SH-E6: staff working in the business see that run with its content withheld
  until the business gives support access; every view is recorded.
* META-E4, META-E5: a customer who asks for a person is handed off and back;
  the assistant says it is an AI; WhatsApp's window, templates and opt-ins.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import select, text

import src.main  # noqa: F401  (every model mapped)

pytestmark = [pytest.mark.needs_db]

COMMENTS = {"platform": "linkedin", "operation": "manage_comments", "payload": {"action": "list", "post_id": "p"}}
COMMENT = "Great post! I am Asha and I would love a demo."


@pytest_asyncio.fixture
async def world(monkeypatch):
    """A business with an owner; this test's own control engine."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    from src.auth.models import Company, User
    from src.common import database
    from src.common.config import settings
    from src.common.tenancy.session import control_session
    from tests.harness.infra import infra_unavailable

    engine = create_async_engine(settings.CONTROL_DATABASE_URL, poolclass=NullPool,
                                 json_serializer=database.json_serializer)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        await engine.dispose()
        infra_unavailable(f"Postgres unreachable ({exc})")
    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(database, "AsyncSessionLocal", async_sessionmaker(engine, expire_on_commit=False))
    monkeypatch.setattr(settings, "TENANCY_MODE", "single")
    told = []

    async def _notify(company_id, **kw):
        told.append(kw)
        return 1

    monkeypatch.setattr("src.notifications.service.notify", _notify)
    async with control_session() as db:
        company = Company(id=uuid.uuid4(), name=f"wave3-{uuid.uuid4().hex[:6]}", type="TENANT", status="active")
        db.add(company)
        await db.flush()
        owner = User(id=uuid.uuid4(), email=f"wave3-{uuid.uuid4().hex[:8]}@test.local", full_name="Owner",
                     hashed_password="x", company_id=company.id, role="tenant_admin", is_active=True, is_verified=True)
        db.add(owner)
        await db.commit()
        company_id, owner_id = company.id, owner.id
    staff = SimpleNamespace(id=uuid.uuid4(), company_id=uuid.uuid4(), role="app_admin")
    try:
        yield SimpleNamespace(company=company_id, owner=SimpleNamespace(id=owner_id, company_id=company_id,
                                                                        role="tenant_admin"),
                              staff=staff, told=told)
    finally:
        from tests.harness.purge import purge_companies

        async with control_session() as db:
            for table in ("support_access_views", "support_access_grants"):
                await db.execute(text(f"DELETE FROM {table} WHERE company_id = :c"), {"c": company_id})
            await purge_companies(await db.connection(), [company_id])
            await db.commit()
        await engine.dispose()


async def _run_that_read_linkedin(company):
    """A finished run with a LinkedIn comment in its tool log, trace, prompt, memory and result."""
    from cortex_memory.enums import CortexNodeType
    from cortex_memory.models import CortexNode, CortexTree
    from src.ai.orm import ExecutionRun
    from src.ai.orm.entity import HierarchicalEntity
    from src.ai.orm.execution import LLMInteractionLog, ToolInteractionLog
    from src.ai.orm.trace import ExecutionTraceEvent
    from src.common.tenancy.session import tenant_session
    from src.connections.models import Connection

    async with tenant_session(company) as db:
        agent = HierarchicalEntity(company_id=company, type="AGENT", status="ACTIVE", name="Page agent")
        db.add(agent)
        await db.flush()
        run = ExecutionRun(entity_id=agent.id, company_id=company, status="COMPLETED",
                           input_data={"input": "Summarise the comments"}, result_data={"output": f"Asha: {COMMENT}"})
        connection = Connection(company_id=company, connector_id="linkedin_org", display_name="Acme Page",
                                external_account_id="123", settings={"organization_urn": "urn:li:organization:123"})
        db.add_all([run, connection])
        await db.flush()
        tree = CortexTree(company_id=company, entity_id=agent.id, task_description="comments")
        db.add(tree)
        await db.flush()
        db.add_all([
            ToolInteractionLog(run_id=run.id, company_id=company, tool_id="social_api", tool_name="social_api",
                               input_parameters=COMMENTS, output_result={"comments": [{"text": COMMENT}]}, success=True),
            ExecutionTraceEvent(run_id=run.id, company_id=company, span_id=uuid.uuid4(), kind="tool",
                                name="social_api", status="success", seq=1, payload={"output": COMMENT}),
            LLMInteractionLog(run_id=run.id, company_id=company, model_provider="google", model_name="gemini",
                              input_prompt=f"Comments: {COMMENT}", output_response="Asha wants a demo"),
            CortexNode(tree_id=tree.id, node_type=CortexNodeType.FINDING, title="comments", content=COMMENT,
                       execution_run_id=run.id),
        ])
        await db.commit()
        return run.id, connection.id, agent.id


async def test_a_linkedin_comment_is_gone_from_the_run_after_linkedins_limit(world):
    """SH-E2's test: a LinkedIn comment in a trace, gone once LinkedIn's limit is up."""
    from cortex_memory.models import CortexNode
    from src.ai.orm import ExecutionRun
    from src.ai.orm.execution import LLMInteractionLog, ToolInteractionLog
    from src.ai.orm.trace import ExecutionTraceEvent
    from src.common.tenancy.session import tenant_session
    from src.connections import source_data
    from src.connections.models import ConnectorDataMark

    company = world.company
    run_id, connection_id, agent_id = await _run_that_read_linkedin(company)
    read_at = datetime.utcnow() - timedelta(hours=1)
    ctx = {"company_id": str(company), "run_id": str(run_id)}
    used = [{"connection_id": str(connection_id), "connector_id": "linkedin_org"}]
    assert await source_data.mark(ctx, "social_api", COMMENTS, used, now=read_at) == 1
    stats = {"platform": "linkedin", "operation": "get_analytics", "payload": {}}
    assert await source_data.mark(ctx, "social_api", {**stats}, used, now=read_at) == 1  # the Page's own: a year
    post = {"platform": "linkedin", "operation": "create_post", "payload": {"text": "Hiring"}}
    assert await source_data.mark(ctx, "social_api", post, used, now=read_at) == 0       # a write is not a read

    async with tenant_session(company) as db:
        assert (await source_data.redact_due(db, now=read_at + timedelta(hours=22)))["runs"] == 0  # not yet
        done = await source_data.redact_due(db, now=read_at + timedelta(hours=23, minutes=1))
        assert done["runs"] == 1 and done["tool_logs"] == 1 and done["spans"] == 1 and done["llm_logs"] == 1
        assert done["memory_nodes"] == 1 and done["results"] == 1
    async with tenant_session(company) as db:
        log = (await db.execute(select(ToolInteractionLog).where(ToolInteractionLog.run_id == run_id))).scalar_one()
        span = (await db.execute(select(ExecutionTraceEvent).where(ExecutionTraceEvent.run_id == run_id))).scalar_one()
        llm = (await db.execute(select(LLMInteractionLog).where(LLMInteractionLog.run_id == run_id))).scalar_one()
        node = (await db.execute(select(CortexNode).where(CortexNode.execution_run_id == run_id))).scalar_one()
        run = await db.get(ExecutionRun, run_id)
        stored = [str(log.output_result), str(span.payload), llm.input_prompt, llm.output_response, node.content,
                  str(run.result_data)]
        assert not any("Asha" in s or "Great post" in s for s in stored), stored
        assert "LinkedIn" in node.content and span.kind == "tool" and span.name == "social_api"  # what it was stays
        marks = {m.operation: m for m in (await db.execute(select(ConnectorDataMark).where(
            ConnectorDataMark.run_id == run_id))).scalars().all()}
        assert marks["manage_comments"].redacted_at is not None and marks["manage_comments"].records is False
        statistics = marks["get_analytics"]
        assert statistics.redacted_at is None and statistics.records is True
        assert statistics.expires_at - read_at > timedelta(days=364)
        # Disconnected: the statistics go too, on the next pass (SH-E2, YT-E5's 7 days).
        assert await source_data.expire_connection(db, connection_id) == 1
        await db.commit()
        assert (await source_data.redact_due(db))["runs"] == 1


async def test_a_run_that_read_linkedin_saves_no_records_and_no_memory(world):
    """LI-E3: an agent asked to save a commenter as a lead is refused; no episode is kept."""
    from src.common.tenancy.session import tenant_session
    from src.connections import source_data
    from src.data_api.records import RecordError, _source_allows

    company = world.company
    run_id, connection_id, _ = await _run_that_read_linkedin(company)
    async with tenant_session(company) as db:
        await _source_allows(db, f"run:{run_id}")                  # nothing read yet: allowed
        assert not await source_data.keeps_no_memory(db, run_id)
    await source_data.mark({"company_id": str(company), "run_id": str(run_id)}, "social_api", COMMENTS,
                           [{"connection_id": str(connection_id), "connector_id": "linkedin_org"}])
    async with tenant_session(company) as db:
        with pytest.raises(RecordError) as refused:
            await _source_allows(db, f"run:{run_id}")
        assert refused.value.status == 403 and "LinkedIn" in refused.value.detail
        await _source_allows(db, f"user:{world.owner.id}")          # a person may still save what they choose
        assert await source_data.keeps_no_memory(db, run_id)


async def test_staff_see_the_content_only_under_the_business_grant(world):
    """SH-E6: withheld for staff until the business gives access; each view recorded."""
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from src.auth import support_access
    from src.auth.dependencies import get_current_user
    from src.auth.models import SupportAccessView
    from src.common.tenancy.session import control_session, tenant_session
    from src.connections import source_data

    company = world.company
    run_id, connection_id, _ = await _run_that_read_linkedin(company)
    await source_data.mark({"company_id": str(company), "run_id": str(run_id)}, "social_api", COMMENTS,
                           [{"connection_id": str(connection_id), "connector_id": "linkedin_org"}])
    async with tenant_session(company) as db:
        owner_sees = await support_access.run_access(db, world.owner, company, [run_id], path="/run")
        staff_sees = await support_access.run_access(db, world.staff, company, [run_id], path="/run")
    assert not owner_sees.withheld                                   # the business's own people
    assert staff_sees.withheld == {str(run_id): ["linkedin_org"]}
    assert "LinkedIn" in staff_sees.note(run_id) and "support access" in staff_sees.note(run_id)

    app = FastAPI()
    app.include_router(support_access.router)
    viewer = {"user": world.owner}
    app.dependency_overrides[get_current_user] = lambda: viewer["user"]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        given = await client.post("/api/v1/support-access", json={"hours": 4, "reason": "Ticket 1042"})
        assert given.status_code == 201, given.text
        async with tenant_session(company) as db:
            assert not (await support_access.run_access(db, world.staff, company, [run_id], path="/run")).withheld
        listing = (await client.get("/api/v1/support-access")).json()
        assert listing["active"]["reason"] == "Ticket 1042"
        assert [v["withheld"] for v in listing["views"]] == [False, True]   # newest first
        ended = await client.delete(f"/api/v1/support-access/{given.json()['id']}")
        assert ended.status_code == 200 and not ended.json()["active"]
        viewer["user"] = SimpleNamespace(id=uuid.uuid4(), company_id=company, role="tenant_user")
        assert (await client.post("/api/v1/support-access", json={"hours": 4, "reason": "x y z"})).status_code == 403
    async with tenant_session(company) as db:
        assert (await support_access.run_access(db, world.staff, company, [run_id], path="/run")).withheld
    async with control_session() as db:
        views = (await db.execute(select(SupportAccessView).where(SupportAccessView.company_id == company))
                 ).scalars().all()
    assert sorted(v.withheld for v in views) == [False, True, True]


async def test_a_customer_who_asks_for_a_person_is_handed_off_and_back(world):
    """META-E4: the assistant stops; the team is told; after the hand-back it says it is an AI again."""
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from src.auth.dependencies import get_current_user
    from src.messaging import api, rules

    company = world.company
    first = await rules.before_reply(company, "messenger", "page1", "psid1", "Hello!")
    assert first.disclosed and first.text.startswith("You're chatting with") and first.text.endswith("Hello!")
    await rules.replied(company, "messenger", "page1", "psid1", disclosed=True)
    again = await rules.before_reply(company, "messenger", "page1", "psid1", "Anything else?")
    assert not again.disclosed and again.text == "Anything else?"                 # once per conversation

    seen = await rules.inbound(company, "messenger", "page1", "psid1", "Can I talk to a person please?")
    assert seen.with_person and "asked someone" in seen.reply
    assert [t["kind"] for t in world.told] == ["conversation_handoff"]
    refused = await rules.before_reply(company, "messenger", "page1", "psid1", "I can help!")
    assert refused.refusal and "person from the team" in refused.refusal
    later = await rules.inbound(company, "messenger", "page1", "psid1", "hello?")
    assert later.with_person and later.reply is None and len(world.told) == 1    # told once

    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[get_current_user] = lambda: world.owner
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        waiting = (await client.get("/api/v1/conversations", params={"with_person": True})).json()["conversations"]
        assert [c["contact_id"] for c in waiting] == ["psid1"]
        back = await client.post(f"/api/v1/conversations/{waiting[0]['id']}/hand-back")
        assert back.status_code == 200 and not back.json()["with_person"]
    after = await rules.before_reply(company, "messenger", "page1", "psid1", "I'm back.")
    assert after.disclosed and not after.refusal                                  # says it again after a hand-back


async def test_whatsapp_messages_the_business_starts_follow_the_window_and_opt_ins(world):
    """META-E5: free text in the 24 hours; then only a template, only to a contact who opted in; STOP stops."""
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from src.auth.dependencies import get_current_user
    from src.messaging import api, rules

    company = world.company
    number = "+91 98450 00001"
    assert "only an approved message template" in await rules.business_initiated_refusal(company, number,
                                                                                        template=None)
    assert "not opted in" in await rules.business_initiated_refusal(company, number, template="order_update")
    await rules.inbound(company, "whatsapp", "whatsapp:+918000000000", "whatsapp:+919845000001", "Hi, is it open?")
    assert await rules.business_initiated_refusal(company, number, template=None) is None   # inside the window
    later = datetime.utcnow() + timedelta(hours=25)
    assert await rules.business_initiated_refusal(company, number, template=None, now=later)

    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[get_current_user] = lambda: world.owner
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        recorded = await client.post("/api/v1/whatsapp/opt-ins", json={
            "contact": number, "status": "in", "source": "website form", "evidence": "form 77"})
        assert recorded.status_code == 201 and recorded.json()["contact"] == "919845000001"
        assert (await client.get("/api/v1/whatsapp/opt-ins")).json()["opt_ins"][0]["source"] == "website form"
    assert await rules.business_initiated_refusal(company, number, template="order_update", now=later) is None
    stop = await rules.inbound(company, "whatsapp", "918000000000", "919845000001", "STOP")
    assert stop.opted == "out" and "START" in stop.reply
    assert "replied STOP" in await rules.business_initiated_refusal(company, number, template="order_update")
    agent = SimpleNamespace(tags=["meta_agent", "system"], description="Builds agents")
    assert "builder assistant" in rules.whatsapp_agent_problem(agent)
    assert rules.whatsapp_agent_problem(SimpleNamespace(tags=[], description="Answers Acme's customers about "
                                                                              "orders and deliveries")) is None
