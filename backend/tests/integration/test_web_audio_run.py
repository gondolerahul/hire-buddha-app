"""A browser audio session is a run, billed for its live audio (VT-22).

Real Postgres, rolled back: the adapter's end-of-session settlement opens the
session's run, writes the live model's usage rows on it and closes it.
"""
from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from src.ai.orm import ExecutionRun, HierarchicalEntity
from src.ai.orm.usage import UsageLog
from src.config.models import IntegrationRegistry
from src.gateway import web_audio_adapter
from src.voice.usage_logger import VoiceUsageLogger

pytestmark = pytest.mark.needs_db


async def _web_session(db):
    from src.auth.models import Company
    c = Company(name=f"vt22-{uuid.uuid4().hex[:6]}", type="TENANT", status="active")
    db.add(c)
    await db.flush()
    for sku, kind in ((VoiceUsageLogger.GEMINI_INPUT_SKU, "input_token"),
                      (VoiceUsageLogger.GEMINI_OUTPUT_SKU, "output_token")):
        db.add(IntegrationRegistry(company_id=c.id, provider_name="google", service_sku=sku,
                                   component_type=kind, internal_cost=Decimal("1.00"),
                                   cost_unit="per_1M_tokens", status="active", service_category="LLM"))
    agent = HierarchicalEntity(company_id=c.id, type="AGENT", status="ACTIVE", name="web receptionist")
    db.add(agent)
    await db.flush()
    return SimpleNamespace(id=uuid.uuid4(), company_id=c.id, agent_id=agent.id,
                           direction="inbound", customer_id=None)


@pytest.mark.asyncio
async def test_a_browser_session_settles_its_live_audio_on_one_run(db, monkeypatch):
    @asynccontextmanager
    async def _same_session():
        yield db

    class _Sessions:
        def __init__(self, _db):
            pass

        async def end_voice_session(self, _sid):
            return None

    settled = {}

    async def _settle(self, run, name):
        settled.update(run=run.id, status=run.status, name=name)
        return Decimal(str(run.total_cost_usd))

    from src.ai.governance.governance_service import GovernanceService
    monkeypatch.setattr(web_audio_adapter, "AsyncSessionLocal", _same_session)
    monkeypatch.setattr(web_audio_adapter, "SessionManager", _Sessions)
    monkeypatch.setattr(GovernanceService, "settle_billing", _settle)

    voice_session = await _web_session(db)
    adapter = web_audio_adapter.WebAudioAdapter(websocket=SimpleNamespace(close=_noop), voice_session=voice_session, db=db)
    adapter.usage.add(SimpleNamespace(prompt_token_count=600_000, response_token_count=400_000,
                                      prompt_tokens_details=[], response_tokens_details=[]))
    adapter.usage.sent(32_000 * 30)
    adapter.usage.received(48_000 * 20)
    await adapter._cleanup()

    run = (await db.execute(select(ExecutionRun).where(ExecutionRun.id == adapter.spend.run_id))).scalar_one()
    assert run.entity_id == voice_session.agent_id and run.status == "COMPLETED"
    assert run.input_data["channel"] == "web_audio"
    assert run.input_data["web_audio_session_id"] == str(voice_session.id)
    rows = (await db.execute(select(UsageLog).where(UsageLog.run_id == run.id))).scalars().all()
    skus = {(await db.get(IntegrationRegistry, r.sku_id)).service_sku for r in rows}
    assert skus == {VoiceUsageLogger.GEMINI_INPUT_SKU, VoiceUsageLogger.GEMINI_OUTPUT_SKU}
    assert sum(Decimal(str(r.calculated_cost)) for r in rows) == Decimal("1.00")   # 1M tokens at $1/1M
    assert settled == {"run": run.id, "status": "COMPLETED", "name": "web_audio call"}


async def _noop(*_a, **_k):
    return None
