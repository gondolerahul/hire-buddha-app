"""Phase 15 T1-1: one enumerated list of cost units, and the one price formula.

The migrations' seed must equal ``UNITS`` (a unit added to the code needs a
migration that inserts it); the database side is ``tests/integration/test_cost_units.py``.
"""
from __future__ import annotations

import importlib.util
from decimal import Decimal
from pathlib import Path

import pytest

from src.billing.units import UNITS, CostUnit, Dimension, price_usd, unit_spec

VERSIONS = Path(__file__).resolve().parents[2] / "migrations" / "control" / "versions"


def _seeded_units() -> dict:
    """Every unit the control migrations insert (each revision's ``COST_UNITS``), in order."""
    seeded = {}
    for path in sorted(VERSIONS.glob("control_*.py")):
        spec = importlib.util.spec_from_file_location(path.stem, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        for code, dimension, per_quantity, label in getattr(module, "COST_UNITS", []):
            seeded[code] = (dimension, Decimal(per_quantity), label)
    return seeded


def test_every_code_has_one_spec():
    assert set(UNITS) == set(CostUnit)
    assert all(spec.per_quantity > 0 for spec in UNITS.values())


def test_the_migrations_seed_the_enum():
    assert _seeded_units() == {str(c): (str(s.dimension), s.per_quantity, s.label) for c, s in UNITS.items()}


def test_time_is_seconds():
    assert {c: UNITS[c].per_quantity for c in UNITS if UNITS[c].dimension == Dimension.SECOND} == {
        CostUnit.PER_SECOND: 1, CostUnit.PER_MINUTE: 60, CostUnit.PER_HOUR: 3600}


@pytest.mark.parametrize("quantity,rate,code,expected", [
    (Decimal("1500"), Decimal("0.30"), "PER_1M_TOKENS", Decimal("0.00045")),     # gemini-2.5-flash-in
    (Decimal("125"), Decimal("0.60"), CostUnit.PER_MINUTE, Decimal("1.25")),      # 125 s at $0.60/min (T1-4)
    (Decimal("2.5"), Decimal("0.00002"), "PER_SECOND", Decimal("0.00005")),      # sandbox
    (Decimal("3"), Decimal("0.04"), "PER_IMAGE", Decimal("0.12")),
])
def test_price_is_quantity_times_rate_over_per_quantity(quantity, rate, code, expected):
    assert price_usd(quantity, rate, code) == expected


def test_an_unknown_code_is_refused():
    with pytest.raises(ValueError, match="unknown cost unit 'per_million_tokens'"):
        unit_spec("per_million_tokens")
