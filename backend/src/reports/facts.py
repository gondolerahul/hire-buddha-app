"""Queries the reports share: billing lines, names, months (Phase 15 T9-4; 07 §7.4)."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from sqlalchemy import func, select

ZERO = Decimal(0)
CATEGORY_LABEL = {"ai_models": "AI models", "knowledge": "Knowledge", "tools": "Tools", "media": "Media",
                  "voice": "Voice", "video": "Video", "sandbox": "Sandbox", "hosting": "Hosting",
                  "database": "Database", "phone_numbers": "Phone numbers"}


def d(value: Any) -> Decimal:
    return Decimal(str(value or 0))


def pct(part: Any, whole: Any) -> Decimal:
    whole = d(whole)
    return (d(part) * 100 / whole).quantize(Decimal("0.1")) if whole else ZERO


def month(day: Any) -> str:
    return f"{day:%Y-%m}"


def months_between(start: date, end: date) -> List[str]:
    out, current = [], start.replace(day=1)
    while current < end:
        out.append(month(current))
        current = (current.replace(day=28) + timedelta(days=4)).replace(day=1)
    return out


async def names(db: Any, ids: Iterable[Any]) -> Dict[Any, str]:
    from src.auth.models import Company

    wanted = {i for i in ids if i is not None}
    if not wanted:
        return {}
    return dict((await db.execute(select(Company.id, Company.name).where(Company.id.in_(wanted)))).all())


async def lines(ctx: Any, *group: Any, where: Sequence[Any] = ()) -> List[Any]:
    """Σ billed (USD and own currency) and cost per ``group`` over the period and scope, from ``billing_lines``."""
    from src.billing.billing_models import BillingLine as L

    query = (select(*group, func.coalesce(func.sum(L.billed_usd), 0).label("billed_usd"),
                    func.coalesce(func.sum(L.cost_usd), 0).label("cost_usd"),
                    func.coalesce(func.sum(L.billed_ccy), 0).label("billed_ccy"),
                    func.coalesce(func.sum(L.quantity), 0).label("quantity"))
             .where(L.period_day >= ctx.start, L.period_day < ctx.end, ctx.scoped(L.company_id), *where))
    if group:
        query = query.group_by(*group)
    return list((await ctx.db.execute(query)).all())


def billed(ctx: Any, row: Any) -> Decimal:
    """What the viewer sees: a business its own currency (exact, locked at settlement); others USD converted."""
    if ctx.workspace == "business" and ctx.company_id is not None:
        return d(row.billed_ccy)
    return ctx.money(row.billed_usd)


async def by_category_day(ctx: Any, where: Sequence[Any] = ()) -> Tuple[List[Dict[str, Any]], List[Dict[str, str]]]:
    """Daily billed per category (a stacked chart's data and series)."""
    from src.billing.billing_models import BillingLine as L

    rows = await lines(ctx, L.period_day, L.category, where=where)
    days: Dict[str, Dict[str, Any]] = defaultdict(dict)
    categories = set()
    for r in rows:
        key = r.period_day.isoformat()
        days[key]["day"] = key
        days[key][r.category] = d(days[key].get(r.category)) + billed(ctx, r)
        categories.add(r.category)
    series = [{"key": c, "label": CATEGORY_LABEL.get(c, c)} for c in sorted(categories)]
    return [days[k] for k in sorted(days)], series


async def wallet_states(ctx: Any) -> Dict[Any, Any]:
    from src.billing.billing_models import CreditWallet

    rows = (await ctx.db.execute(select(CreditWallet).where(ctx.scoped(CreditWallet.company_id)))).scalars().all()
    return {w.company_id: w for w in rows}


async def usd_of(db: Any, amount: Any, currency: Optional[str]) -> Decimal:
    from src.billing.currency import current_rate, to_usd

    return to_usd(d(amount), await current_rate(db, (currency or "USD").upper()))


def since_days(days: int) -> datetime:
    return datetime.utcnow() - timedelta(days=days)
