"""The annual partnership fee (Phase 15 T8-6, tech design §11.4; REQ-PT-2).

A price item per partner type (``partner_annual_fee_silver``/``_gold``),
billed to the partner's company in its currency with GST and an invoice.
**Never commissionable and never distributed to uplines** (K-12): nothing
here writes to the partner ledger. A paid fee covers a year from the later of
today and the paid-until date; reminders 30, 7 and 1 days before it ends.
An inactive or zero-priced item means no fee is due.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from sqlalchemy import select

from src.partners.models import PartnerProfile, PartnerType

logger = logging.getLogger(__name__)

YEAR = timedelta(days=365)
REMINDER_DAYS = (30, 7, 1)


async def fee_due(db: Any, profile: PartnerProfile) -> Optional[Any]:
    """The fee's price in the partner's currency, or ``None`` when its type has none."""
    from src.billing.price_items import UnknownPriceItem, price_for

    kind = await db.get(PartnerType, profile.partner_type)
    if kind is None or not kind.annual_fee_item:
        return None
    try:
        price = await price_for(db, kind.annual_fee_item, profile.billing_currency or "USD")
    except UnknownPriceItem:
        return None
    return price if price.amount > 0 else None


async def fee_view(db: Any, profile: PartnerProfile) -> Dict[str, Any]:
    price = await fee_due(db, profile)
    return {"required": price is not None, "amount": str(price.amount) if price else None,
            "currency": price.currency if price else profile.billing_currency,
            "paid_until": profile.fee_paid_until.isoformat() if profile.fee_paid_until else None}


async def start(db: Any, gateway: Any, profile: PartnerProfile) -> Dict[str, Any]:
    from fastapi import HTTPException

    from src.auth.models import Company
    from src.partners.payments import create_order

    price = await fee_due(db, profile)
    if price is None:
        raise HTTPException(status_code=409, detail="No partnership fee is due")
    if profile.status in ("suspended", "terminated"):
        raise HTTPException(status_code=403, detail=f"The partnership is {profile.status}")
    kind = await db.get(PartnerType, profile.partner_type)
    company = await db.get(Company, profile.company_id)
    return await create_order(db, gateway, company=company, net=price.amount, purpose="partner_fee",
                              description=f"{kind.name} partnership fee, one year",
                              metadata={"price_item": kind.annual_fee_item, "version": price.version})


async def on_fee_paid(db: Any, payment: Any) -> None:
    """A year more; an approved (and signed) or lapsed partnership becomes active (the caller commits)."""
    from src.partners.lifecycle import latest_agreement, set_status

    profile = (await db.execute(select(PartnerProfile).where(PartnerProfile.company_id == payment.company_id)
                                .with_for_update())).scalar_one_or_none()
    if profile is None:
        return
    now = datetime.utcnow()
    start_at = max(now, profile.fee_paid_until or now)
    profile.fee_paid_until, profile.updated_at = start_at + YEAR, now
    agreement = await latest_agreement(db, profile.company_id)
    signed = agreement is not None and agreement.signed_at is not None
    if profile.status in ("renewal_due", "lapsed") or (profile.status == "approved" and signed):
        await set_status(db, profile, "active", reason="partnership fee paid")


async def lifecycle(db: Any, *, now: Optional[datetime] = None) -> Dict[str, int]:
    """The daily job: renewal reminders, renewal_due, lapsed, suspended after the grace."""
    from src.billing.settings_catalogue import value
    from src.partners.lifecycle import notify_partner, set_status

    now = now or datetime.utcnow()
    grace = timedelta(days=int(await value(db, "partners.fee_grace_days")))
    out = {"renewal_due": 0, "lapsed": 0, "suspended": 0, "reminded": 0}
    rows = (await db.execute(select(PartnerProfile).where(
        PartnerProfile.fee_paid_until.isnot(None),
        PartnerProfile.status.in_(("active", "renewal_due", "lapsed"))))).scalars().all()
    for profile in rows:
        if await fee_due(db, profile) is None:
            continue
        until = profile.fee_paid_until
        left = (until - now).days
        try:
            if profile.status == "active" and until - timedelta(days=30) <= now:
                await set_status(db, profile, "renewal_due", reason="the partnership fee is due")
                out["renewal_due"] += 1
            if profile.status == "renewal_due" and now >= until:
                await set_status(db, profile, "lapsed", reason="the partnership fee was not paid")
                out["lapsed"] += 1
            elif profile.status == "lapsed" and now >= until + grace:
                await set_status(db, profile, "suspended", reason="the partnership fee was not paid in the grace")
                out["suspended"] += 1
            if profile.status == "renewal_due":
                for days in REMINDER_DAYS:
                    if 0 <= left <= days:
                        await notify_partner(profile.company_id, kind="partner.fee_due",
                                             title=f"Your partnership fee is due in {max(left, 0)} days",
                                             body="Pay it on the Partnership page to keep earning.",
                                             dedupe=f"partner.fee_due:{until:%Y-%m-%d}:{days}")
                        out["reminded"] += 1
                        break
            await db.commit()
        except Exception:  # noqa: BLE001 - one partner's failure is its own
            await db.rollback()
            logger.exception("partner fee lifecycle for %s failed", profile.company_id)
    return out
