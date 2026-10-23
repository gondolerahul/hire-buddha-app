"""Rating at write: each usage row carries what the customer is billed for it (Phase 15 T3-3, tech design §5.1).

Every writer of a ``usage_logs`` row — ``UsageService.log_usage``,
``CostLedger.add`` and the call meter — rates it before adding it:

* ``billed_usd`` = the company's formula applied to the row's cost (no rounding);
* ``formula_id`` = the formula version used — one per run (``formula_for_run``),
  so a run is priced by one version end to end;
* ``category`` = what the charge is, for customers (``src.billing.categories``).

The formula is linear, so a run's Σ ``billed_usd`` is what settling its total
bills (the shadow comparison of T3-7 checks it run by run). ``currency``,
``billed_ccy``, ``fx_rate_id`` and ``settlement_id`` are filled when the row is
settled (WS15-4); until then they are NULL.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Optional

from src.billing.categories import category_for
from src.billing.formulas import formula_for_run


async def rate_row(db: Any, row: Any, *, sku: Optional[str] = None, sku_category: Optional[str] = None) -> Any:
    """Fill ``row``'s ``billed_usd``, ``formula_id`` and ``category`` (it is not added or flushed here)."""
    formula = await formula_for_run(db, row.company_id, row.run_id)
    row.billed_usd = formula.rate(Decimal(str(row.calculated_cost or 0)))
    row.formula_id = formula.id
    row.category = category_for(row.attribution, sku_category=sku_category, sku=sku).value
    return row
