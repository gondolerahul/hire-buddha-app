"""Phase 15 T3-1: the new billing path bills what the old one billed (``golden.json``).

The golden values were recorded with the code before WS15-3 (``record.py``).
The new path rates each usage row with the company's formula version
(``src.billing.formulas``, ``spf`` folded into ``pf``) and sums: by linearity it
must reproduce every run exactly. Calls change on purpose — per second, not per
started minute (REQ-CO-1) — so their new amounts are checked against the rule,
and against the old ones only where the two rules agree (whole minutes).
"""
from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from src.billing.formulas import Formula
from tests.golden.billing.scenarios import CALLS, PAYMENTS, RUNS

GOLDEN = json.loads(Path(__file__).with_name("golden.json").read_text(encoding="utf-8"))


def _v2(f: dict) -> Formula:
    return Formula(f["mf"], f["pf"] + f["spf"], f["d"])            # the migration's folding (K-10)


@pytest.mark.parametrize("name", sorted(RUNS))
def test_a_run_is_billed_as_before(name):
    formula, costs = RUNS[name]
    per_row = sum((_v2(formula).rate(c) for c in costs), Decimal("0"))
    assert per_row == Decimal(GOLDEN["runs"][name])


@pytest.mark.parametrize("name", sorted(CALLS))
def test_a_call_is_billed_per_second(name):
    formula, seconds, per_minute, audio, tools = CALLS[name]
    billed = _v2(formula).rate(seconds * per_minute / 60 + audio + tools)
    before = Decimal(GOLDEN["calls"][name]["billed_per_started_minute"])
    assert billed <= before                                         # never more than the started-minute rule
    if seconds % 60 == 0:
        assert billed == before                                     # whole minutes: the rules agree


def test_the_doc_example_short_call():
    """125 s at $0.60/min under the 02 §4 formula: $1.25 of telephony, not $1.80."""
    formula, seconds, per_minute, audio, tools = CALLS["short_call_doc_formula"]
    assert _v2(formula).rate(seconds * per_minute / 60 + audio + tools) == Decimal("2.3668125")  # (1.25 + 0.0123) × 1.5 × 1.25


@pytest.mark.parametrize("name", sorted(PAYMENTS))
def test_payments_grant_what_they_granted(name):
    kind, amount, bonus = PAYMENTS[name]
    credits = amount if kind == "topup" else amount + amount * bonus / 100
    assert credits == Decimal(GOLDEN["payments"][name])


def test_the_suite_covers_every_scenario():
    assert set(GOLDEN["runs"]) == set(RUNS) and set(GOLDEN["calls"]) == set(CALLS)
    assert set(GOLDEN["payments"]) == set(PAYMENTS)
