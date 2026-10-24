"""The commission arithmetic (Phase 15 T8-7, tech design §11.6): ``commission.compute``.

The §11.6 worked example, the pool cap (levels ≥ 1 scaled first), no
compression (an ineligible level's share stays with the platform), held shares,
and — for any rates, eligibility and cap — the payout never exceeds the cap and
the shares and the platform add up to the base.
"""
from __future__ import annotations

import random
from decimal import Decimal

from src.partners.commission import LevelIn, compute

D = Decimal


def test_the_worked_example():
    """Gold P0 20 %, Gold P1 3 %, Silver P2 (no revenue this month) 2 %: ₹1,00,000 top-up, cap 25 %."""
    result = compute(D("100000"), [LevelIn(0, "P0", D(20)), LevelIn(1, "P1", D(3)),
                                   LevelIn(2, "P2", D(2), eligible=False, why="no own paid revenue this month")],
                     cap_pct=D(25))
    assert [(s.partner_id, s.amount, s.status) for s in result.shares] == [
        ("P0", D(20000), "accrued"), ("P1", D(3000), "accrued"), ("P2", D(0), "platform")]
    assert result.platform == D(77000) and result.capped is False and result.pool_cap == D(25000)


def test_over_the_cap_the_uplines_are_scaled_first():
    result = compute(D(1000), [LevelIn(0, "P0", D(20)), LevelIn(1, "P1", D(6)), LevelIn(2, "P2", D(4))],
                     cap_pct=D(25))
    amounts = [s.amount for s in result.shares]
    assert result.capped and sum(amounts) == D(250)
    assert amounts[0] == D(200)                                  # level 0 untouched
    assert amounts[1] == D(30) and amounts[2] == D(20)           # 50 shared 6 : 4


def test_level_zero_alone_over_the_cap_is_cut_to_it():
    result = compute(D(1000), [LevelIn(0, "P0", D(40)), LevelIn(1, "P1", D(3))], cap_pct=D(25))
    assert [s.amount for s in result.shares] == [D(250), D(0)]


def test_a_held_share_counts_but_is_not_payable():
    result = compute(D(500), [LevelIn(0, "P0", D(10), hold="lapsed")], cap_pct=D(15))
    assert (result.shares[0].amount, result.shares[0].status, result.shares[0].why) == (D(50), "held", "lapsed")


def test_fees_split_without_a_cap():
    result = compute(D(10000), [LevelIn(0, "G", D(75)), LevelIn(1, "U1", D(3)), LevelIn(2, "U2", D(2))], cap_pct=None)
    assert [s.amount for s in result.shares] == [D(7500), D(300), D(200)] and result.platform == D(2000)


def test_payouts_never_exceed_the_cap():
    rng = random.Random(15)
    for _ in range(500):
        base = D(rng.randint(1, 10_000_000)) / 100
        cap = D(rng.randint(0, 100))
        levels = [LevelIn(k, f"P{k}", D(rng.randint(0, 6000)) / 100, eligible=rng.random() > 0.2,
                          hold="kyc" if rng.random() < 0.2 else None) for k in range(rng.randint(1, 3))]
        result = compute(base, levels, cap_pct=cap)
        paid = sum((s.amount for s in result.shares), D(0))
        assert paid <= base * cap / 100 + D("1e-20")
        assert paid + result.platform == base
        assert all(s.amount == 0 for s in result.shares if s.status == "platform")
        assert all(s.amount >= 0 for s in result.shares)
