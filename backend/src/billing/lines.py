"""Billing lines: what a company was billed per day, category and grouping (Phase 15 T3-4, tech design §5.3).

When usage is settled, its rated rows (``src.billing.rating``) are summed by
category and added to the day's line for that grouping — in USD and in the
company's billing currency at the rate locked for the settlement (FX-4).
``billing_lines`` replaces ``billing_events`` for reporting (T3-8); until then
both are written. One ``INSERT … ON CONFLICT`` adds to a line, so concurrent
settlements cannot lose an increment.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Iterable, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert


async def settlement_rows(run_db: Any, control: Any, run_id: Optional[UUID]) -> list:
    """The usage rows a top-level run's settlement covers: its own and its descendants' (§6.5)."""
    if run_id is None:
        return []
    from src.ai.governance.run_cost import descendant_run_ids
    from src.ai.orm.usage import UsageLog

    ids = [run_id, *await descendant_run_ids(run_db, run_id)]
    return list((await control.execute(select(UsageLog).where(UsageLog.run_id.in_(ids)))).scalars().all())


async def record_lines(control: Any, *, company_id: UUID, rows: Iterable[Any], grouping_type: Optional[str],
                       grouping_id: Optional[UUID], at: Optional[datetime] = None) -> list[dict]:
    """Add ``rows`` to the company's lines for the day (the caller commits). Returns what was added."""
    from src.auth.models import Company
    from src.billing.billing_models import BillingLine
    from src.billing.currency import current_rate, to_ccy

    rows = list(rows)
    if not rows:
        return []
    currency = (await control.execute(select(Company.billing_currency).where(Company.id == company_id))
                ).scalar_one_or_none() or "INR"
    rate = await current_rate(control, currency)
    day: date = (at or datetime.utcnow()).date()
    sums: dict = defaultdict(lambda: {"cost_usd": Decimal(0), "billed_usd": Decimal(0), "quantity": Decimal(0),
                                      "rows": 0})
    for row in rows:
        line = sums[row.category or "tools"]
        line["cost_usd"] += Decimal(str(row.calculated_cost or 0))
        line["billed_usd"] += Decimal(str(row.billed_usd or 0))
        line["quantity"] += Decimal(str(row.raw_quantity or 0))
        line["rows"] += 1
    added = []
    table = BillingLine.__table__
    for category, line in sorted(sums.items()):
        values = {"company_id": company_id, "period_day": day, "category": category, "grouping_type": grouping_type,
                  "grouping_id": grouping_id, "currency": currency, "fx_rate_id": rate.id,
                  "cost_usd": line["cost_usd"], "billed_usd": line["billed_usd"],
                  "billed_ccy": to_ccy(line["billed_usd"], rate), "quantity": line["quantity"], "rows": line["rows"],
                  "updated_at": datetime.utcnow()}
        insert = pg_insert(BillingLine).values(**values)
        await control.execute(insert.on_conflict_do_update(
            constraint="uq_billing_lines_key",
            set_={**{c: table.c[c] + insert.excluded[c] for c in ("cost_usd", "billed_usd", "billed_ccy", "quantity",
                                                                    "rows")},
                  "fx_rate_id": insert.excluded.fx_rate_id, "updated_at": insert.excluded.updated_at}))
        added.append({"category": category, **{k: v for k, v in values.items() if k in (
            "cost_usd", "billed_usd", "billed_ccy", "currency")}})
    return added
