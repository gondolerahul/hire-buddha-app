"""Concurrent settlements add up in one billing line (DM-04, kept for billing lines in Phase 15 T3-8).

``billing_events`` once selected the month's row and inserted one when none was
found, then added to it in Python: two settlements at once made two rows or
lost an increment (DM-04). Billing lines replaced billing events (T3-8) and
keep the fix — one ``INSERT ... ON CONFLICT DO UPDATE`` on
``uq_billing_lines_key``, NULL groupings equal.

Runs against the real Postgres with real commits — concurrency needs separate
connections, which the suite's rolled-back transaction cannot give — and deletes
what it wrote.
"""
from __future__ import annotations

import asyncio
import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

pytestmark = pytest.mark.needs_db

SETTLEMENTS = 12
COST = Decimal("0.125")
BILLED = Decimal("0.15")


@pytest_asyncio.fixture
async def sessions():
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from src.auth.models import Company
    from src.billing.billing_models import BillingLine
    from src.common.config import settings

    engine = create_async_engine(settings.DATABASE_URL, pool_size=SETTLEMENTS, max_overflow=0)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    company_id = uuid.uuid4()
    async with maker() as db:
        db.add(Company(id=company_id, name=f"dm04-{company_id.hex[:8]}", type="TENANT", status="active",
                       country_code="IN", billing_currency="INR"))
        await db.commit()
    try:
        yield maker, company_id
    finally:
        async with maker() as db:
            await db.execute(delete(BillingLine).where(BillingLine.company_id == company_id))
            await db.execute(delete(Company).where(Company.id == company_id))
            await db.commit()
        await engine.dispose()


def _row(category: str = "ai_models", quantity: str = "1") -> SimpleNamespace:
    return SimpleNamespace(category=category, calculated_cost=COST, billed_usd=BILLED, raw_quantity=Decimal(quantity))


async def _record(maker, company_id, rows, grouping_type=None, grouping_id=None):
    from src.billing.lines import record_lines

    async with maker() as db:
        added = await record_lines(db, company_id=company_id, rows=rows, grouping_type=grouping_type,
                                   grouping_id=grouping_id)
        await db.commit()
        return added


async def _lines(maker, company_id):
    from src.billing.billing_models import BillingLine

    async with maker() as db:
        return (await db.execute(select(BillingLine).where(BillingLine.company_id == company_id))).scalars().all()


@pytest.mark.asyncio
async def test_concurrent_settlements_make_one_line_with_every_amount(sessions):
    maker, company_id = sessions
    agent = uuid.uuid4()
    await asyncio.gather(*[_record(maker, company_id, [_row()], "entity", agent) for _ in range(SETTLEMENTS)])
    [line] = await _lines(maker, company_id)
    assert line.cost_usd == COST * SETTLEMENTS
    assert line.billed_usd == BILLED * SETTLEMENTS
    assert line.rows == SETTLEMENTS and line.currency == "INR"
    assert line.billed_ccy == BILLED * SETTLEMENTS * 100        # INR 100 to the dollar (seeded rate)


@pytest.mark.asyncio
async def test_ungrouped_settlements_share_one_line(sessions):
    maker, company_id = sessions
    await asyncio.gather(*[_record(maker, company_id, [_row()]) for _ in range(4)])
    [line] = await _lines(maker, company_id)
    assert line.grouping_type is None and line.grouping_id is None
    assert line.cost_usd == COST * 4


@pytest.mark.asyncio
async def test_each_grouping_and_category_is_kept_apart(sessions):
    maker, company_id = sessions
    a, b = uuid.uuid4(), uuid.uuid4()
    await _record(maker, company_id, [_row("media", "2")], "agent", a)
    await _record(maker, company_id, [_row("video")], "agent", b)
    added = await _record(maker, company_id, [_row("voice", "90"), _row("voice", "30")], "agent", a)
    assert [(x["category"], x["billed_usd"]) for x in added] == [("voice", BILLED * 2)]
    lines = {(line.grouping_id, line.category): line for line in await _lines(maker, company_id)}
    assert set(lines) == {(a, "media"), (b, "video"), (a, "voice")}
    assert lines[(a, "media")].quantity == 2
    assert lines[(a, "voice")].quantity == 120 and lines[(a, "voice")].rows == 2
