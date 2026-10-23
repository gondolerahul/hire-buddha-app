"""Record ``golden.json``: what today's billing code bills for each scenario (Phase 15 T3-1).

    PYTHONPATH=. python tests/golden/billing/record.py

Run once, before WS15-3 changed the billing path (23 Oct 2026, at ``3ae2f9a``
plus WS15-1/2); the file is committed and not regenerated. It calls the code
as it was: ``calculate_tb`` on a run's summed cost with the four
``billing_config`` fields; calls priced per started minute (BC-12);
top-ups credited at the order's amount; a subscription cycle granting its fee
plus the bonus percentage.
"""
from __future__ import annotations

import json
import math
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from src.billing.billing_service import calculate_tb  # noqa: E402  (the formula as it was)
from tests.golden.billing.scenarios import CALLS, PAYMENTS, RUNS  # noqa: E402


def _tb(cost: Decimal, f: dict) -> Decimal:
    return calculate_tb(cost, f["mf"], f["pf"], f["spf"], f["d"])["total_billing"]


def record() -> dict:
    runs = {name: str(_tb(sum(costs, Decimal("0")), f)) for name, (f, costs) in RUNS.items()}
    calls = {}
    for name, (f, seconds, per_minute, audio, tools) in CALLS.items():
        minutes = Decimal(math.ceil(seconds / 60))           # the started-minute rule of today's code
        calls[name] = {"billed_per_started_minute": str(_tb(minutes * per_minute + audio + tools, f))}
    payments = {}
    for name, (kind, amount, bonus) in PAYMENTS.items():
        credits = amount if kind == "topup" else amount + amount * bonus / 100
        payments[name] = str(credits)
    return {"recorded_with": "calculate_tb + billing_config (mf, pf, spf, d); calls per started minute",
            "runs": runs, "calls": calls, "payments": payments}


if __name__ == "__main__":
    out = Path(__file__).with_name("golden.json")
    out.write_text(json.dumps(record(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {out}")
