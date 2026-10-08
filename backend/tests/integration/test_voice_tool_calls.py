"""A voice call's tool calls are run, logged and charged like a step's (P3.7, TL-20).

Before: the voice handler gave tools a context of company and user only — no
run, no ``tool_interaction_logs`` row, no charge — so a voice agent could send
WhatsApp messages or write CRM records that no run, report or bill ever saw.
Real Postgres, rolled back per test.
"""
from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from src.ai.orm import ExecutionRun, HierarchicalEntity, ToolInteractionLog
from src.ai.orm.usage import UsageLog
from src.ai.tools.base import Tool, ToolRegistry
from src.config.models import IntegrationRegistry
from src.voice.tool_calls import VoiceToolCalls

pytestmark = pytest.mark.needs_db


class _Booker(Tool):
    name = "p37_book_meeting"
    description = "books a meeting"

    def __init__(self):
        self.contexts: list[dict] = []

    async def run(self, input_data):  # noqa: ARG002
        return "unused"

    async def run_with_context(self, input_data, context=None):
        self.contexts.append(dict(context or {}))
        return "booked"


@pytest.fixture
def booker():
    tool = _Booker()
    ToolRegistry.register(tool)
    yield tool
    ToolRegistry._tools.pop(tool.name, None)


async def _voice_call(db):
    from src.auth.models import Company
    c = Company(name=f"voice-{uuid.uuid4().hex[:6]}", type="TENANT", status="active")
    db.add(c)
    await db.flush()
    agent = HierarchicalEntity(company_id=c.id, type="AGENT", status="ACTIVE", name="receptionist",
                               capabilities={"tools": [{"tool_id": "p37_book_meeting"}]})
    db.add(agent)
    db.add(IntegrationRegistry(company_id=c.id, provider_name="test", service_sku="p37_book_meeting",
                               component_type="tool", internal_cost=Decimal("0.03"),
                               cost_unit="per_request", status="active", service_category="API_TOOL"))
    await db.flush()
    session = SimpleNamespace(id=uuid.uuid4(), company_id=c.id, agent_id=agent.id,
                              customer_id=uuid.uuid4(), session_metadata={"campaign_id": None})
    return session


@pytest.mark.asyncio
async def test_a_voice_tool_call_has_a_run_a_log_and_a_charge(db, booker):
    session = await _voice_call(db)
    calls = VoiceToolCalls(db, session)
    [tr] = await calls.run_calls([{"name": "p37_book_meeting", "args": {"when": "tomorrow"}}])

    assert tr.success and calls.run is not None
    run = (await db.execute(select(ExecutionRun).where(ExecutionRun.id == calls.run.id))).scalar_one()
    assert run.entity_id == session.agent_id and run.input_data["voice_session_id"] == str(session.id)
    [ctx] = booker.contexts
    assert ctx["run_id"] == str(run.id) and ctx["company_id"] == str(session.company_id)

    [log] = (await db.execute(select(ToolInteractionLog).where(
        ToolInteractionLog.run_id == run.id))).scalars().all()
    assert log.tool_id == "p37_book_meeting" and log.success
    [usage] = (await db.execute(select(UsageLog).where(UsageLog.run_id == run.id))).scalars().all()
    assert Decimal(str(usage.calculated_cost)) == Decimal("0.03")
    assert calls.cost == Decimal("0.03")


@pytest.mark.asyncio
async def test_a_refused_voice_tool_call_is_logged_and_not_charged(db, booker):
    session = await _voice_call(db)
    calls = VoiceToolCalls(db, session)
    [tr] = await calls.run_calls([{"name": "whatsapp_send_tenant", "args": {"to": "+1"}}])

    assert tr.skipped and "not granted" in tr.output
    [log] = (await db.execute(select(ToolInteractionLog).where(
        ToolInteractionLog.run_id == calls.run.id))).scalars().all()
    assert log.log_metadata == {"refused": "not_granted"}
    assert (await db.execute(select(UsageLog).where(UsageLog.run_id == calls.run.id))).scalars().all() == []
    assert calls.cost == 0


@pytest.mark.asyncio
async def test_the_calls_run_closes_with_its_tool_cost(db, booker):
    session = await _voice_call(db)
    calls = VoiceToolCalls(db, session)
    await calls.run_calls([{"name": "p37_book_meeting", "args": {}}])
    await calls.run_calls([{"name": "p37_book_meeting", "args": {}}])
    assert await calls.finish(db) == Decimal("0.06")

    run = (await db.execute(select(ExecutionRun).where(ExecutionRun.id == calls.run.id))).scalar_one()
    await db.refresh(run)
    assert run.status == "COMPLETED" and Decimal(str(run.total_cost_usd)) == Decimal("0.06")
    assert run.completed_at is not None


@pytest.mark.asyncio
async def test_the_tool_cost_is_in_the_calls_charged_total(db):
    from src.voice.usage_logger import VoiceUsageLogger
    session = await _voice_call(db)
    usage = await VoiceUsageLogger(db).log_voice_session_usage(
        session_id=session.id, company_id=session.company_id, provider="none",
        duration_seconds=0, tool_cost=Decimal("0.06"))
    assert usage.total_cost == Decimal("0.06")


@pytest.mark.asyncio
async def test_a_call_that_never_connected_has_no_run_to_close(db):
    """No `start()` (refused at admission, or the live session failed) and no tool call: no run (VT-21)."""
    session = await _voice_call(db)
    calls = VoiceToolCalls(db, session)
    assert await calls.finish(db) == 0 and calls.run is None
