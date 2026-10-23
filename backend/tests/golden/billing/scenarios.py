"""The fixed billing scenarios of the golden suite (Phase 15 T3-1).

Each is a formula (``mf``, ``pf``, ``spf``, ``d`` — today's ``billing_config``
fields) and the costs of the usage rows of one run or call. ``golden.json``
holds what today's code billed for each (``record.py``, run before WS15-3
changed anything); the new pipeline — per-row rating with ``spf`` folded into
``pf`` (K-10) — must bill the same. Calls carry what per-second billing
changes on purpose (REQ-CO-1).
"""
from __future__ import annotations

from decimal import Decimal as D

IDENTITY = {"mf": D("1"), "pf": D("0"), "spf": D("0"), "d": D("0")}
DOC_EXAMPLE = {"mf": D("1.5"), "pf": D("0.20"), "spf": D("0.10"), "d": D("0.05")}    # 02 §4 worked example
DISCOUNTED = {"mf": D("2"), "pf": D("0"), "spf": D("0"), "d": D("0.10")}
PARTNER_HEAVY = {"mf": D("1.25"), "pf": D("0.15"), "spf": D("0.30"), "d": D("0")}
FREE = {"mf": D("1"), "pf": D("0"), "spf": D("0"), "d": D("1")}

RUNS = {
    "identity_one_row": (IDENTITY, [D("0.4512345")]),
    "doc_example": (DOC_EXAMPLE, [D("0.40")]),
    "doc_example_many_rows": (DOC_EXAMPLE, [D("0.12"), D("0.08"), D("0.15"), D("0.05")]),
    "discounted_small_rows": (DISCOUNTED, [D("0.000045"), D("0.0000375"), D("1.234567")]),
    "partner_fee_folded": (PARTNER_HEAVY, [D("0.333333"), D("0.666667"), D("2.5")]),
    "fully_discounted": (FREE, [D("3.21")]),
    "zero_cost": (DOC_EXAMPLE, []),
}

# A call: (formula, seconds, telephony $/min, model audio cost, tool cost).
CALLS = {
    "short_call_doc_formula": (DOC_EXAMPLE, D("125"), D("0.60"), D("0.0123"), D("0")),
    "exact_minutes_identity": (IDENTITY, D("120"), D("0.60"), D("0"), D("0.04")),
    "one_second_discounted": (DISCOUNTED, D("1"), D("0.45"), D("0"), D("0")),
}

# Payments: (kind, amount, bonus_pct) → credits granted.
PAYMENTS = {
    "topup_10": ("topup", D("10.00"), None),
    "topup_cents": ("topup", D("12.34"), None),
    "subscription_growth": ("subscription", D("500"), D("20")),
    "subscription_scale": ("subscription", D("1000"), D("30")),
}
