"""Phase 11 Track 2 — Budget unit tests."""
from __future__ import annotations

from decimal import Decimal

import pytest

from src.ai.core.budget import Budget


def test_budget_default_pressure_is_zero() -> None:
    b = Budget()
    assert b.pressure == 0.0
    assert not b.exhausted()
    assert b.which_exhausted() is None


def test_from_governance_applies_defaults() -> None:
    b = Budget.from_governance(max_cost_usd=1.50, timeout_ms=60_000)
    assert b.usd_max == Decimal("1.50")
    assert b.wall_max_s == 60
    assert b.iters_max == 100
    assert b.tokens_max > 0


def test_from_governance_handles_none_cost() -> None:
    b = Budget.from_governance(max_cost_usd=None, timeout_ms=None)
    assert b.usd_max > 0
    assert b.wall_max_s > 0


def test_consume_advances_axes() -> None:
    b = Budget.from_governance(max_cost_usd=1.0, timeout_ms=60_000)
    b.consume(tokens=100, usd=0.25, wall_s=10, iter_step=True)
    assert b.tokens_used == 100
    assert b.usd_used == Decimal("0.25")
    assert b.wall_used_s == 10
    assert b.iters == 1


def test_pressure_returns_max_axis() -> None:
    b = Budget(usd_max=Decimal("1.0"), usd_used=Decimal("0.9"),
               wall_max_s=100, wall_used_s=10)
    # usd axis dominates: 90%
    assert b.pressure == pytest.approx(0.9, rel=1e-3)


def test_exhausted_triggers_on_any_axis() -> None:
    b = Budget(usd_max=Decimal("1.0"), usd_used=Decimal("1.0"))
    assert b.exhausted()
    assert b.which_exhausted() == "usd"


def test_can_afford_respects_caps() -> None:
    b = Budget(usd_max=Decimal("1.0"), usd_used=Decimal("0.8"))
    assert b.can_afford(expected_usd=Decimal("0.1"))
    assert not b.can_afford(expected_usd=Decimal("0.3"))


def test_snapshot_restore_roundtrip() -> None:
    b = Budget(
        tokens_max=10_000, tokens_used=1234,
        usd_max=Decimal("2.5"), usd_used=Decimal("0.75"),
        wall_max_s=600, wall_used_s=120,
        iters_max=20, iters=4,
    )
    snap = b.snapshot()
    b2 = Budget.restore(snap)
    assert b2.tokens_used == 1234
    assert b2.usd_used == Decimal("0.75")
    assert b2.wall_used_s == 120
    assert b2.iters == 4


def test_which_exhausted_priority_usd_first() -> None:
    b = Budget(
        usd_max=Decimal("1.0"), usd_used=Decimal("1.0"),
        tokens_max=10, tokens_used=10,
    )
    assert b.which_exhausted() == "usd"


def test_disabled_axis_does_not_block() -> None:
    """tokens_max=0 means 'no cap on this axis'."""
    b = Budget(tokens_max=0, tokens_used=999_999)
    assert "tokens" not in b._axis_pressure()
    assert not b.exhausted()
