"""Stored timestamps are instants; Python still sees naive UTC (DM-12).

The UTC session and the codec are installed on every pool's connections, so a
plain engine built here gets them too (a pooled app connection may belong to
another test's event loop). Its transaction is rolled back.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.needs_db


@pytest.mark.asyncio
async def test_timestamps_are_stored_with_their_zone_and_read_back_as_naive_utc():
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool

    from src.ai.orm.feature_flags import FeatureFlag
    from src.common.config import settings

    engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    ist = timezone(timedelta(hours=5, minutes=30))
    async with engine.connect() as conn:
        trans = await conn.begin()
        try:
            assert (await conn.execute(text("SELECT current_setting('TimeZone')"))).scalar_one() == "UTC"
            column_type = (await conn.execute(text(
                "SELECT data_type FROM information_schema.columns "
                "WHERE table_name = 'execution_runs' AND column_name = 'created_at'"
            ))).scalar_one()
            assert column_type == "timestamp with time zone"

            session = AsyncSession(bind=conn)
            naive_utc = datetime(2026, 10, 1, 4, 30)
            a, b = f"dm12-{uuid.uuid4().hex[:8]}", f"dm12-{uuid.uuid4().hex[:8]}"
            session.add_all([
                FeatureFlag(flag_key=a, created_at=naive_utc, updated_at=naive_utc),
                # The same instant given with an offset is stored as the same instant.
                FeatureFlag(flag_key=b, created_at=datetime(2026, 10, 1, 10, 0, tzinfo=ist), updated_at=naive_utc),
            ])
            await session.flush()
            session.expunge_all()

            rows = (await session.execute(
                select(FeatureFlag.flag_key, FeatureFlag.created_at).where(FeatureFlag.flag_key.in_([a, b]))
            )).all()
            assert {r.created_at for r in rows} == {naive_utc}
            assert all(r.created_at.tzinfo is None for r in rows)

            # Raw SQL too: the value is an instant, and it reads back naive UTC.
            raw = (await conn.execute(text(
                "SELECT created_at, created_at = TIMESTAMPTZ '2026-10-01 10:00:00+05:30' AS same_instant "
                "FROM feature_flags WHERE flag_key = :k"
            ), {"k": a})).one()
            assert raw.created_at == naive_utc and raw.same_instant

            # A server default of now() is the current UTC time, not local time.
            server_now = (await conn.execute(text("SELECT now()"))).scalar_one()
            assert abs(server_now - datetime.utcnow()) < timedelta(minutes=5)
        finally:
            await trans.rollback()
    await engine.dispose()
