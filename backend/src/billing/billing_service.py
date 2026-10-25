"""
Billing Service — the staff costing and billing reports, from billing lines.

The customer price is ``src.billing.formulas`` (Phase 15 T3-2): versioned
``billing_formulas``, ``TB = c·mf·(1 + pf − d)``; daily credits are policies
(``src.billing.daily_credits``, T5-5). ``billing_config`` is read by nothing. ``calculate_tb`` is the formula as it
was — four fields with ``spf`` — kept for the golden billing suite (T3-1).

What was billed is ``billing_lines`` (T3-4), written at settlement; since T3-8
nothing writes ``billing_events`` and the reports below roll the lines up by
month.
"""
from decimal import Decimal
from datetime import date, timedelta
from typing import Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func, select


def calculate_tb(
    c: Decimal,
    mf: Decimal,
    pf: Decimal,
    spf: Decimal,
    d: Decimal,
) -> dict:
    """The formula before Phase 15: TB = (c*mf) + (c*mf*pf) + (c*mf*spf) - (c*mf*d).

    Only ``tests/golden/billing/record.py`` calls it, to show what the old code
    billed. Prices come from ``src.billing.formulas``.
    """
    multiplied = c * mf
    platform_fee = multiplied * pf
    partner_fee = multiplied * spf
    discount = multiplied * d
    total = multiplied + platform_fee + partner_fee - discount
    return {
        "base_cost": c,
        "multiplied_cost": multiplied,
        "platform_fee_amount": platform_fee,
        "partner_fee_amount": partner_fee,
        "discount_amount": discount,
        "total_billing": total,
    }


def month_bounds(period_month: date) -> tuple[date, date]:
    """The first day of ``period_month``'s month and of the next."""
    start = period_month.replace(day=1)
    return start, (start.replace(day=28) + timedelta(days=4)).replace(day=1)


class BillingService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_billing_lines(
        self,
        company_id: Optional[UUID] = None,
        period_month: Optional[date] = None,
        grouping_type: Optional[str] = None,
    ) -> list[dict]:
        """Billing lines rolled up per company, month, grouping, category and
        currency (internal view: cost included).

        ``company_id=None`` covers every company: lines are written under the
        company that ran the work.
        """
        from src.auth.models import Company
        from src.billing.billing_models import BillingLine as L

        month = func.date_trunc("month", L.period_day).label("month")
        query = (select(L.company_id, Company.name, month, L.grouping_type, L.grouping_id, L.category, L.currency,
                        func.sum(L.cost_usd), func.sum(L.billed_usd), func.sum(L.billed_ccy), func.sum(L.quantity),
                        func.sum(L.rows))
                 .join(Company, Company.id == L.company_id)
                 .group_by(L.company_id, Company.name, month, L.grouping_type, L.grouping_id, L.category, L.currency)
                 .order_by(month.desc(), func.sum(L.billed_usd).desc()))
        if company_id:
            query = query.where(L.company_id == company_id)
        if period_month:
            start, end = month_bounds(period_month)
            query = query.where(L.period_day >= start, L.period_day < end)
        if grouping_type:
            query = query.where(L.grouping_type == grouping_type)
        return [{
            "company_id": str(cid), "company_name": name, "period_month": f"{m:%Y-%m-%d}",
            "grouping_type": gtype, "grouping_id": str(gid) if gid else None, "category": category,
            "currency": currency, "cost_usd": Decimal(cost or 0), "billed_usd": Decimal(billed or 0),
            "billed_ccy": Decimal(billed_ccy or 0), "quantity": Decimal(quantity or 0), "rows": int(rows or 0),
        } for cid, name, m, gtype, gid, category, currency, cost, billed, billed_ccy, quantity, rows
            in (await self.db.execute(query)).all()]
