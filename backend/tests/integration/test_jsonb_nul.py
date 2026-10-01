"""A NUL character in JSON no longer fails the write (DM-13).

``jsonb`` rejects the ``\\u0000`` escape that ``json`` accepted, so with the
columns converted, a tool output containing a NUL would have failed the whole
flush. The app engine drops NULs from the JSON it writes. This runs on that
engine (the suite's fixture builds its own) in a transaction that is rolled
back.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.needs_db


@pytest.mark.asyncio
async def test_a_nul_in_a_jsonb_value_is_dropped_not_fatal():
    from src.ai.orm.feature_flags import FeatureFlag
    from src.common.database import engine

    key = f"dm13-{uuid.uuid4().hex[:8]}"
    async with engine.connect() as conn:
        trans = await conn.begin()
        try:
            session = AsyncSession(bind=conn)
            session.add(FeatureFlag(flag_key=key, value_json={"output": "a\x00b", "items": ["\x00"]}))
            await session.flush()
            stored = (await session.execute(
                select(FeatureFlag.value_json).where(FeatureFlag.flag_key == key)
            )).scalar_one()
            assert stored == {"output": "ab", "items": [""]}
        finally:
            await trans.rollback()
