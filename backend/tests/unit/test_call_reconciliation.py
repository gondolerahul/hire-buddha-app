"""Phase 15 T1-6, K-2: the carrier's pulse is for reconciliation only.

A 125-second call at $0.60 a minute is billed $1.25 (per second); a carrier
that bills per started minute charges us for 180 seconds, $1.80 — the gap the
cost reconciliation report shows, and the admin covers with the rate or ``mf``.
"""
from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from src.billing.reconciliation import billing_increment, call_cost_gap, carrier_seconds


def _sku(**metadata):
    return SimpleNamespace(internal_cost=Decimal("0.60"), cost_unit_code="PER_MINUTE", service_metadata=metadata)


def test_the_carrier_bills_whole_pulses():
    assert carrier_seconds(Decimal("125"), 60) == 180
    assert carrier_seconds(Decimal("120"), 60) == 120
    assert carrier_seconds(Decimal("0.4"), 1) == 1
    assert carrier_seconds(Decimal("0"), 60) == 0


def test_the_gap_on_a_short_call():
    gap = call_cost_gap(Decimal("125"), _sku(provider_billing_increment_seconds=60))
    assert (gap["cost_per_second"], gap["carrier_cost"], gap["gap"]) == (Decimal("1.25"), Decimal("1.80"), Decimal("0.55"))


def test_the_increment_comes_from_the_sku():
    assert billing_increment(_sku()) == 60
    assert billing_increment(_sku(provider_billing_increment_seconds=1)) == 1
    assert call_cost_gap(Decimal("125"), _sku(provider_billing_increment_seconds=1))["gap"] == 0
