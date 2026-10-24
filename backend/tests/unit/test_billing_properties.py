"""Billing properties (Phase 15 T10-2; plan 08 §5): seeded random cases, exact Decimals.

* Linearity: the formula bills the sum of costs as the sum of the bills
  (Σ TB(cᵢ) = TB(Σ cᵢ)), so rating each usage row at write and billing the
  run's total agree to the last digit.
* Per-second calls: a call's price is additive over any split of its seconds,
  and a per-minute price is the per-second price × 60 / 60.
* FX: converting is linear and a round trip returns the amount; a rate change
  never alters what an earlier conversion locked.
* No rounding: nothing in rating or conversion quantises.
"""
from __future__ import annotations

import random
from decimal import Decimal

import pytest

from src.billing.currency import Rate, to_ccy, to_usd
from src.billing.formulas import Formula
from src.billing.units import price_usd

SEEDS = range(40)


def _d(rng: random.Random, digits: int = 10, scale: int = 6) -> Decimal:
    return Decimal(rng.randrange(0, 10 ** digits)) / Decimal(10 ** scale)


def _formula(rng: random.Random) -> Formula:
    return Formula(mf=Decimal(rng.randrange(100, 400)) / 100, pf=Decimal(rng.randrange(0, 50)) / 100,
                   d=Decimal(rng.randrange(0, 20)) / 100)


@pytest.mark.parametrize("seed", SEEDS)
def test_the_formula_is_linear(seed):
    rng = random.Random(seed)
    formula = _formula(rng)
    costs = [_d(rng) for _ in range(rng.randrange(1, 60))]
    assert sum((formula.rate(c) for c in costs), Decimal(0)) == formula.rate(sum(costs, Decimal(0)))


@pytest.mark.parametrize("seed", SEEDS)
def test_a_formula_bills_zero_for_nothing_and_scales(seed):
    rng = random.Random(seed)
    formula, cost, k = _formula(rng), _d(rng), rng.randrange(1, 1000)
    assert formula.rate(0) == 0
    assert formula.rate(cost * k) == formula.rate(cost) * k


@pytest.mark.parametrize("seed", SEEDS)
def test_a_call_is_priced_per_second_over_any_split(seed):
    rng = random.Random(seed)
    per_second = _d(rng, 8, 8)
    seconds = rng.randrange(1, 7200)
    cuts = sorted(rng.sample(range(1, seconds + 1), min(5, seconds)))
    parts = [b - a for a, b in zip([0] + cuts, cuts + [seconds]) if b > a]
    whole = price_usd(Decimal(seconds), per_second, "PER_SECOND")
    assert sum((price_usd(Decimal(p), per_second, "PER_SECOND") for p in parts), Decimal(0)) == whole
    assert price_usd(Decimal(seconds), per_second * 60, "PER_MINUTE") == whole


@pytest.mark.parametrize("seed", SEEDS)
def test_conversion_is_linear_and_round_trips(seed):
    rng = random.Random(seed)
    rate = Rate("INR", Decimal(rng.randrange(5000, 12000)) / 100)
    amounts = [_d(rng) for _ in range(rng.randrange(1, 30))]
    assert sum((to_ccy(a, rate) for a in amounts), Decimal(0)) == to_ccy(sum(amounts, Decimal(0)), rate)
    for a in amounts:
        back = to_usd(to_ccy(a, rate), rate)
        assert abs(back - a) <= Decimal("1e-20")


@pytest.mark.parametrize("seed", SEEDS)
def test_a_rate_change_does_not_move_a_locked_amount(seed):
    rng = random.Random(seed)
    usd = _d(rng)
    before, after = Rate("INR", Decimal("83.10")), Rate("INR", Decimal(rng.randrange(7000, 9900)) / 100)
    locked = to_ccy(usd, before)
    assert to_ccy(usd, after) != locked or after.units_per_usd == before.units_per_usd
    assert locked == usd * Decimal("83.10")          # the amount kept is the one converted at the locked rate


def test_nothing_quantises():
    tiny = Decimal("0.0000000001")
    assert Formula(Decimal("1.5"), Decimal("0.1"), Decimal(0)).rate(tiny) == tiny * Decimal("1.5") * Decimal("1.1")
    assert price_usd(Decimal(1), tiny, "PER_SECOND") == tiny
    assert to_ccy(tiny, Rate("INR", Decimal("83.1"))) == tiny * Decimal("83.1")
