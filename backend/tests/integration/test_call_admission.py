"""One admission rule for every call (VT-01, VT-08, HD9).

The inbound webhooks compared ``total_available`` — ignoring credit other
runs hold — and let the call through on any error; the media socket let
every inbound call through. Now a call, inbound or outbound, is admitted only
on free credit at the ``AGENT`` floor and under the spend cap, and a balance
that cannot be read refuses it. Real Postgres, rolled back.
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select

from src.ai.core.events import capture_test_events
from src.billing.billing_models import CreditHold
from src.voice.call_admission import UNCHECKED, call_refusal

from tests.integration.test_run_credit_guard import _company, _run

pytestmark = pytest.mark.needs_db


async def _refusal(db, company):
    with capture_test_events() as events:
        refusal = await call_refusal(db, company, direction="inbound", checkpoint="twilio_webhook")
    return refusal, [e for e in events if e.name.startswith(("voice.call.", "gate.failed"))]


@pytest.mark.asyncio
async def test_a_company_with_credit_takes_the_call(db):
    company = await _company(db, "5")
    refusal, events = await _refusal(db, company)
    assert refusal is None
    assert [e.name for e in events] == ["voice.call.admitted"]
    assert events[0].payload["direction"] == "inbound"


@pytest.mark.asyncio
async def test_credit_held_by_running_runs_is_not_free(db):
    from src.billing.credit_service import minimum_threshold

    floor = minimum_threshold("AGENT")
    company = await _company(db, str(floor * 2))          # total_available is twice the floor…
    run, _ = await _run(db, company)                       # …but a RUNNING run holds 1.5 floors
    db.add(CreditHold(company_id=company, run_id=run.id, amount=floor * Decimal("1.5")))
    await db.flush()
    assert (await db.execute(select(CreditHold).where(CreditHold.run_id == run.id))).scalar_one()

    refusal, events = await _refusal(db, company)
    assert refusal and "Cannot start execution" in refusal
    assert [e.name for e in events] == ["voice.call.refused"]


@pytest.mark.asyncio
async def test_an_empty_wallet_refuses_an_inbound_call(db):
    refusal, _ = await _refusal(db, await _company(db, "0"))
    assert refusal


@pytest.mark.asyncio
async def test_a_balance_that_cannot_be_read_refuses(db):
    class _Broken:
        async def execute(self, *_a, **_k):
            raise ConnectionError("database unreachable")

        async def commit(self):
            pass

        async def rollback(self):
            pass

    refusal, events = await _refusal(_Broken(), await _company(db, "5"))
    assert refusal == UNCHECKED
    failed = [e for e in events if e.name == "gate.failed"]
    assert failed and failed[0].payload["gate"] == "voice_call_credit" and failed[0].payload["decision"] == "closed"
