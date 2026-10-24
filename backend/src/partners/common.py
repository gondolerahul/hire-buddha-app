"""Helpers the partner routers share."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, Iterable, Optional
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select

PARTNER_ROLES = ("partner_admin", "partner_user")


async def names(db: Any, ids: Iterable[Any]) -> Dict[Any, str]:
    from src.auth.models import Company

    wanted = {i for i in ids if i is not None}
    if not wanted:
        return {}
    return dict((await db.execute(select(Company.id, Company.name).where(Company.id.in_(wanted)))).all())


async def gateway(db: Any) -> Any:
    from src.billing.gateways import GatewayUnavailable, get_gateway

    try:
        return await get_gateway(db)
    except GatewayUnavailable as missing:
        raise HTTPException(status_code=503, detail=str(missing)) from None


def require_partner(user: Any, *, admin: bool = False) -> UUID:
    role = str(user.role)
    if role not in PARTNER_ROLES or (admin and role != "partner_admin"):
        raise HTTPException(status_code=403, detail="Partner admins only" if admin else "Partners only")
    return user.company_id


async def billed_mtd_usd(db: Any, tenant_ids: Iterable[Any], today: Optional[date] = None) -> Dict[Any, Decimal]:
    """Each tenant's billed amount this month (USD), from the billing lines."""
    from src.billing.billing_models import BillingLine

    ids = list(tenant_ids)
    if not ids:
        return {}
    today = today or datetime.utcnow().date()
    rows = (await db.execute(select(BillingLine.company_id, func.coalesce(func.sum(BillingLine.billed_usd), 0))
                             .where(BillingLine.company_id.in_(ids), BillingLine.period_day >= today.replace(day=1))
                             .group_by(BillingLine.company_id))).all()
    return {cid: Decimal(str(total)) for cid, total in rows}


async def in_currency(db: Any, usd: Decimal, currency: str) -> Decimal:
    from src.billing.currency import current_rate, to_ccy

    return to_ccy(Decimal(str(usd)), await current_rate(db, currency or "USD"))


def iso(value: Any) -> Optional[str]:
    return value.isoformat() if value is not None else None
