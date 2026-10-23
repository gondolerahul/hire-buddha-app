"""A voice call is a run from connect to hang-up (VT-21, HD14).

A call left a ``VoiceSession`` and nothing else: no run, so it was in no run
report and the trace viewer had nothing to show; only its tool use opened a
run (TL-20). Now the call opens its run when it connects, its usage rows are
written on it, and it closes with the call's whole cost and a span in the
trace. Real Postgres, rolled back.
"""
from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import select

import src.common.database  # noqa: F401  (its UTC codec, before the test engine connects)
from src.ai.orm import ExecutionRun
from src.ai.orm.trace import ExecutionTraceEvent
from src.ai.orm.usage import UsageLog
from src.config.models import IntegrationRegistry
from src.voice.live_usage import LiveUsage
from src.voice.tool_calls import VoiceToolCalls
from tests.integration.test_voice_tool_calls import _voice_call, booker  # noqa: F401

pytestmark = pytest.mark.needs_db


@pytest.fixture
def one_session(db, monkeypatch):
    """Trace spans are written on their own session; here, on the test's."""
    @asynccontextmanager
    async def _session():
        yield db
    monkeypatch.setattr("src.common.database.AsyncSessionLocal", _session)
    return db


async def _call(db):
    session = await _voice_call(db)
    session.direction, session.provider = "inbound", "twilio"
    session.phone_number = "+15550000000"
    db.add(IntegrationRegistry(company_id=session.company_id, provider_name="twilio",
                               service_sku="in-out", component_type="telephony",
                               internal_cost=Decimal("0.02"), cost_unit_code="PER_MINUTE",
                               status="active", service_category="COMMUNICATION"))
    await db.flush()
    return session


@pytest.mark.asyncio
async def test_a_call_opens_its_run_when_it_connects(db, one_session):
    session = await _call(db)
    calls = VoiceToolCalls(db, session)
    await calls.start()

    run = (await db.execute(select(ExecutionRun).where(ExecutionRun.id == calls.run_id))).scalar_one()
    assert run.status == "RUNNING" and run.entity_id == session.agent_id
    assert run.input_data["channel"] == "voice" and run.input_data["direction"] == "inbound"
    await calls.start()                                   # once per call
    assert (await db.execute(select(ExecutionRun).where(
        ExecutionRun.input_data["voice_session_id"].astext == str(session.id)))).scalars().all() == [run]


@pytest.mark.asyncio
async def test_the_calls_run_closes_with_the_whole_call_and_a_trace(db, one_session, booker):  # noqa: F811
    from src.voice.usage_logger import VoiceUsageLogger

    session = await _call(db)
    calls = VoiceToolCalls(db, session)
    await calls.start()
    await calls.run_calls([{"name": "p37_book_meeting", "args": {"when": "tomorrow"}}])

    usage = await VoiceUsageLogger(db).log_voice_session_usage(
        session_id=session.id, company_id=session.company_id, provider="twilio",
        duration_seconds=90, audio_input_seconds=0, audio_output_seconds=0,
        tool_cost=calls.cost, run_id=calls.run_id)
    cost = await calls.finish(db, billed_amount=Decimal("0.5"), tokens=1200,
                              result={"duration_seconds": 90, "turns": 4})

    # 90 s at $0.02/min is 1.5 minutes, billed per second (T1-4; was 2 started minutes) + the tool
    assert cost == usage.total_cost and cost == Decimal("0.03") + calls.cost
    run = (await db.execute(select(ExecutionRun).where(ExecutionRun.id == calls.run_id))).scalar_one()
    await db.refresh(run)
    assert run.status == "COMPLETED" and Decimal(str(run.total_cost_usd)) == cost
    assert Decimal(str(run.billed_amount)) == Decimal("0.5") and run.total_tokens == 1200
    assert run.result_data == {"duration_seconds": 90, "turns": 4}
    telephony = (await db.execute(select(UsageLog).where(
        UsageLog.run_id == run.id, UsageLog.attribution == "voice_call"))).scalars().all()
    assert telephony and all(u.company_id == session.company_id for u in telephony)

    spans = (await db.execute(select(ExecutionTraceEvent).where(
        ExecutionTraceEvent.run_id == run.id).order_by(ExecutionTraceEvent.seq))).scalars().all()
    by_kind = {s.kind: s for s in spans}
    assert set(by_kind) == {"step", "tool"}
    assert by_kind["step"].name == "voice call" and Decimal(str(by_kind["step"].cost_usd)) == cost
    assert by_kind["tool"].name == "p37_book_meeting"
    assert by_kind["tool"].parent_span_id == by_kind["step"].span_id


@pytest.mark.asyncio
async def test_hang_up_closes_the_run_after_the_call_is_charged(db, one_session, monkeypatch):
    """The handler's call-end path: usage on the run, then the run closed."""
    from src.billing.billing_models import CreditWallet
    from src.voice import websocket_handler as wh

    session = await _call(db)
    later = datetime.utcnow() + timedelta(days=1)
    db.add(CreditWallet(company_id=session.company_id, daily_credits=Decimal("0"),
                        daily_expires_at=later, wallet_balance=Decimal("100"),
                        wallet_expires_at=later))
    await db.flush()

    class _Sessions:
        def __init__(self, _db):
            pass

        async def end_voice_session(self, *_a, **_k):
            return None

    async def _nothing(*_a, **_k):
        return None

    class _Socket:
        async def close(self, *_a, **_k):
            return None

    monkeypatch.setattr(wh, "SessionManager", _Sessions)
    handler = object.__new__(wh.TwilioStreamHandler)
    handler.session_id = session.id
    handler.voice_session = session
    handler.started_at = datetime.utcnow() - timedelta(seconds=61)
    handler.call_ended_at = None
    handler.turn_number = 3
    handler.mobile = None
    handler.websocket = _Socket()
    handler._ringback_task = None
    handler._live_usage = LiveUsage()
    handler.db = db
    for name in ("_save_recording_artifact", "_generate_call_summary",
                 "_update_campaign_call_post_cleanup"):
        monkeypatch.setattr(handler, name, _nothing)
    calls = handler._tool_calls()
    await calls.start()

    await wh.BaseStreamHandler._cleanup(handler)

    run = (await db.execute(select(ExecutionRun).where(ExecutionRun.id == calls.run_id))).scalar_one()
    await db.refresh(run)
    # At least 61 s at $0.02/min, per second (T1-4; the started-minute rule made it 2 minutes, $0.04)
    assert run.status == "COMPLETED" and Decimal(str(run.total_cost_usd)) >= Decimal("0.02") * 61 / 60
    assert run.billed_amount is not None and run.result_data["turns"] == 3
