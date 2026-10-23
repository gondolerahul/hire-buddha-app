"""Phase 15 T1-1: the ``cost_units`` table is the enum (tech design §2.1).

A registry row will name its unit by code with a foreign key (T1-2). If the
table and ``src.billing.units.UNITS`` drifted — a unit added to the code with
no migration, or a row edited in the database — prices would be computed with
one divisor and checked against another. Real Postgres at the control head.
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import text

from src.billing.units import UNITS

pytestmark = pytest.mark.needs_db


@pytest.mark.asyncio
async def test_the_table_is_the_enum(db):
    rows = (await db.execute(text(
        "SELECT code, dimension, per_quantity, label, active FROM cost_units"))).all()
    table = {r.code: (r.dimension, Decimal(r.per_quantity), r.label, r.active) for r in rows}
    enum = {str(code): (str(s.dimension), s.per_quantity, s.label, True) for code, s in UNITS.items()}
    assert table == enum


@pytest.mark.asyncio
async def test_a_unit_must_price_something(db):
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            await db.execute(text(
                "INSERT INTO cost_units (code, dimension, per_quantity, label) VALUES ('PER_NOTHING', 'unit', 0, 'x')"))
