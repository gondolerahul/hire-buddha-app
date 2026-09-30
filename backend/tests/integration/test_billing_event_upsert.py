"""Concurrent settlements add up in one billing_events row (DM-04).

``record_billing_event`` selected the month's row and inserted one when none was
found, then added to it in Python. Two settlements at once could both insert
(two rows, so every report over-counted) or both read the same row and write
back their own sum (one increment lost). It is now one ``INSERT ... ON CONFLICT
DO UPDATE`` on ``uq_billing_events_period_grouping``.

Runs against the real Postgres with real commits — concurrency needs separate
connections, which the suite's rolled-back transaction cannot give — and deletes
what it wrote.
"""
from __future__ import annotations

import asyncio
import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

pytestmark = pytest.mark.needs_db

SETTLEMENTS = 12
BASE = Decimal("0.125000")


@pytest_asyncio.fixture
async def sessions():
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from src.auth.models import Company
    from src.billing.billing_models import BillingEvent
    from src.common.config import settings

    engine = create_async_engine(settings.DATABASE_URL, pool_size=SETTLEMENTS, max_overflow=0)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    company_id = uuid.uuid4()
    async with maker() as db:
        db.add(Company(id=company_id, name=f"dm04-{company_id.hex[:8]}", type="TENANT", status="active"))
        await db.commit()
    try:
        yield maker, company_id
    finally:
        async with maker() as db:
            await db.execute(delete(BillingEvent).where(BillingEvent.company_id == company_id))
            await db.execute(delete(Company).where(Company.id == company_id))
            await db.commit()
        await engine.dispose()


async def _record(maker, company_id, **kwargs):
    from src.billing.billing_service import BillingService

    async with maker() as db:
        return await BillingService(db).record_billing_event(company_id=company_id, base_cost=BASE, **kwargs)


async def _rows(maker, company_id):
    from src.billing.billing_models import BillingEvent

    async with maker() as db:
        return (await db.execute(select(BillingEvent).where(BillingEvent.company_id == company_id))).scalars().all()


async def _one_settlement_total(maker, company_id) -> Decimal:
    from src.billing.billing_service import BillingService, compute_billed_amount

    async with maker() as db:
        config = await BillingService(db).get_billing_config(company_id)
    return compute_billed_amount(BASE, config)


@pytest.mark.asyncio
async def test_concurrent_settlements_make_one_row_with_every_amount(sessions):
    maker, company_id = sessions
    await asyncio.gather(*[
        _record(maker, company_id, grouping_type="process", grouping_value="Research Director",
                other_ai_cost=BASE, event_category="llm")
        for _ in range(SETTLEMENTS)
    ])
    rows = await _rows(maker, company_id)
    assert len(rows) == 1
    row = rows[0]
    one = await _one_settlement_total(maker, company_id)
    assert row.base_cost == BASE * SETTLEMENTS
    assert row.other_ai_cost == BASE * SETTLEMENTS
    assert row.total_billing == one * SETTLEMENTS
    assert row.llm_charge == one * SETTLEMENTS
    assert row.api_charge == 0


@pytest.mark.asyncio
async def test_ungrouped_events_share_one_row(sessions):
    maker, company_id = sessions
    await asyncio.gather(*[_record(maker, company_id) for _ in range(4)])
    rows = await _rows(maker, company_id)
    assert len(rows) == 1 and rows[0].grouping_type is None
    assert rows[0].base_cost == BASE * 4


@pytest.mark.asyncio
async def test_each_grouping_and_category_is_kept_apart(sessions):
    maker, company_id = sessions
    first = await _record(maker, company_id, grouping_type="agent", grouping_value="a", event_category="image",
                          image_gen_count=2)
    await _record(maker, company_id, grouping_type="agent", grouping_value="b", event_category="video")
    again = await _record(maker, company_id, grouping_type="agent", grouping_value="a", event_category="telephony",
                          telephony_in_minutes=Decimal("1.5"))
    rows = {r.grouping_value: r for r in await _rows(maker, company_id)}
    assert set(rows) == {"a", "b"}
    assert again.id == first.id  # the returned row is the accumulated one
    one = await _one_settlement_total(maker, company_id)
    assert rows["a"].image_charge == one and rows["a"].telephony_charge > 0
    assert rows["a"].image_gen_count == 2 and rows["a"].telephony_in_minutes == Decimal("1.5")
    assert rows["b"].video_charge == one and rows["b"].image_charge == 0
