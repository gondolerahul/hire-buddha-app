"""Daily credits: policies, bands, overrides and the local-midnight grant (Phase 15 T5-5, tech design §7).

Which policy a company gets (§7.2):

1. its override (``company_daily_credit_overrides``): ``none`` gives nothing,
   ``custom`` its own amount and duration, ``policy`` the steps below;
2. a tenant with an owning partner: that partner's ``partner`` policy, else
   (when ``daily_credits.inherit_up_partner_chain``) the nearest upline
   partner's, else the ``all_partners`` policy;
3. a direct tenant: the ``direct`` policy;
4. none found: no daily credits.

The amount (DC-2): day ``n`` = whole days since the company was created, in
its time zone, plus one; while ``n ≤ duration_days`` the band holding ``n``
gives the USD amount, granted in the company's currency at today's rate.

The grant (DC-3…DC-7): at 00:00 in the company's time zone the daily lot is
replaced — the old one expires, a new one is granted, expiring at the next
local midnight — once per company and local date (a unique index makes a
second grant for the same date impossible). Daily lots are not paid: they
never repay debt and a wallet in debt still gets them, with admission still
blocked. Only active companies get them.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

logger = logging.getLogger(__name__)

DURATIONS = (0, 10, 15, 30, 60, 90, 180, 365)
AUDIENCES = ("direct", "partner", "all_partners")
ZERO = Decimal(0)
UTC = ZoneInfo("UTC")


@dataclass
class Resolution:
    """What a company gets today, and why."""
    source: str                      # override_none | override_custom | partner | upline_partner | all_partners | direct | none
    policy_id: Optional[UUID] = None
    policy_name: Optional[str] = None
    day: int = 1
    duration_days: Optional[int] = None
    amount_usd: Decimal = ZERO
    local_date: Optional[date] = None
    next_midnight_utc: Optional[datetime] = None

    def as_dict(self) -> dict:
        return {"source": self.source, "policy_id": str(self.policy_id) if self.policy_id else None,
                "policy_name": self.policy_name, "day": self.day, "duration_days": self.duration_days,
                "amount_usd": str(self.amount_usd), "local_date": self.local_date.isoformat() if self.local_date else None,
                "next_midnight_utc": self.next_midnight_utc.isoformat() if self.next_midnight_utc else None}


def _zone(name: Optional[str]) -> ZoneInfo:
    try:
        return ZoneInfo(name or "Asia/Kolkata")
    except Exception:  # noqa: BLE001 - an unknown zone reads as the platform's
        return ZoneInfo("Asia/Kolkata")


def local_day(company_created_at: Optional[datetime], tz: str, now: datetime) -> tuple[date, int, datetime]:
    """(today's local date, day number n, the next local midnight in naive UTC) for a company (DC-2)."""
    zone = _zone(tz)
    local_now = now.replace(tzinfo=UTC).astimezone(zone)
    today = local_now.date()
    created = (company_created_at or now).replace(tzinfo=UTC).astimezone(zone).date()
    midnight = datetime.combine(today + timedelta(days=1), datetime.min.time(), tzinfo=zone)
    return today, (today - created).days + 1, midnight.astimezone(UTC).replace(tzinfo=None)


def band_amount(bands: list, day: int, duration_days: Optional[int]) -> Decimal:
    """The USD a policy gives on day ``day`` (nothing past its duration)."""
    if duration_days is not None and day > duration_days:
        return ZERO
    for band in sorted(bands, key=lambda b: b.from_day):
        if band.from_day <= day <= band.to_day:
            return Decimal(str(band.amount_usd))
    return ZERO


async def _policy(db: Any, audience: str, partner_id: Optional[UUID], at: datetime) -> Any:
    from src.billing.billing_models import DailyCreditPolicy

    query = select(DailyCreditPolicy).where(DailyCreditPolicy.audience == audience, DailyCreditPolicy.active,
                                            DailyCreditPolicy.effective_from <= at)
    query = query.where(DailyCreditPolicy.partner_id == partner_id) if partner_id else query
    return (await db.execute(query.order_by(DailyCreditPolicy.effective_from.desc()).limit(1))).scalar_one_or_none()


async def _bands(db: Any, policy_id: UUID) -> list:
    from src.billing.billing_models import DailyCreditBand

    return list((await db.execute(select(DailyCreditBand).where(DailyCreditBand.policy_id == policy_id))
                 ).scalars().all())


async def _partner_chain(db: Any, company: Any) -> list[UUID]:
    """The company's partner (its assignment, Phase 15 T8-2), then each upline partner (nearest first)."""
    from src.auth.models import Company
    from src.partners.scope import partner_of

    chain, parent_id, seen = [], await partner_of(db, company.id), set()
    while parent_id and parent_id not in seen:
        seen.add(parent_id)
        parent = (await db.execute(select(Company.id, Company.type, Company.parent_id)
                                   .where(Company.id == parent_id))).one_or_none()
        if parent is None:
            break
        if parent.type == "PARTNER":
            chain.append(parent.id)
        parent_id = parent.parent_id
    return chain


async def resolve(db: Any, company: Any, *, now: Optional[datetime] = None) -> Resolution:
    """What ``company`` (a ``Company`` row) gets today (§7.2)."""
    from src.billing.billing_models import CompanyDailyCreditOverride
    from src.billing.settings_catalogue import value

    now = now or datetime.utcnow()
    today, day, midnight = local_day(company.created_at, company.timezone, now)

    def out(source: str, **kw: Any) -> Resolution:
        return Resolution(source=source, day=day, local_date=today, next_midnight_utc=midnight, **kw)

    override = (await db.execute(select(CompanyDailyCreditOverride).where(
        CompanyDailyCreditOverride.company_id == company.id))).scalar_one_or_none()
    if override is not None and override.mode == "none":
        return out("override_none")
    if override is not None and override.mode == "custom":
        ended = ((override.duration_days is not None and day > override.duration_days)
                 or (override.until is not None and now >= override.until))
        return out("override_custom", duration_days=override.duration_days,
                   amount_usd=ZERO if ended else Decimal(str(override.amount_usd or 0)))
    chain = await _partner_chain(db, company)
    candidates: list[tuple[str, str, Optional[UUID]]] = []
    if chain:
        candidates.append(("partner", "partner", chain[0]))
        if await value(db, "daily_credits.inherit_up_partner_chain", company.id):
            candidates += [("upline_partner", "partner", p) for p in chain[1:]]
        candidates.append(("all_partners", "all_partners", None))
    else:
        candidates.append(("direct", "direct", None))
    for source, audience, partner_id in candidates:
        policy = await _policy(db, audience, partner_id, now)
        if policy is not None:
            amount = band_amount(await _bands(db, policy.id), day, policy.duration_days)
            return out(source, policy_id=policy.id, policy_name=policy.name, duration_days=policy.duration_days,
                       amount_usd=amount)
    return out("none")


async def grant_today(db: Any, company_id: UUID, *, now: Optional[datetime] = None) -> Optional[Any]:
    """Replace the company's daily lot for its local date, once (DC-3, DC-6). Commits.

    Returns the wallet change, or ``None`` when today's lot was granted
    already, the company is not active, or it gets nothing today (its old
    daily lot still expires at its local midnight).
    """
    from src.auth.models import Company
    from src.billing.billing_models import WalletLot
    from src.billing.currency import current_rate, to_ccy
    from src.billing.wallet import WalletService

    now = now or datetime.utcnow()
    company = (await db.execute(select(Company).where(Company.id == company_id))).scalar_one_or_none()
    if company is None or company.status != "active":
        return None
    resolution = await resolve(db, company, now=now)
    wallet_svc = WalletService(db)
    wallet = await wallet_svc.lock(company_id)
    granted = (await db.execute(select(WalletLot.id).where(
        WalletLot.company_id == company_id, WalletLot.kind == "daily",
        WalletLot.local_date == resolution.local_date))).first()
    if granted is not None:
        await db.commit()
        return None
    # Yesterday's lot ended at local midnight: it expires now if the job has not run since.
    await wallet_svc.expire(company_id, now=now)
    live = [lot for lot in await wallet_svc.live_lots(company_id, now=now, lock=True) if lot.kind == "daily"]
    if live:
        await wallet_svc.expire_lots(company_id, live, reason="replaced by today's daily credits", now=now)
    if resolution.amount_usd <= 0:
        await db.commit()
        return None
    rate = await current_rate(db, wallet.currency)
    try:
        change = await wallet_svc.grant(
            company_id, "daily", to_ccy(resolution.amount_usd, rate), expires_at=resolution.next_midnight_utc,
            paid=False, repay_debt=False, source_type="daily_policy",
            source_id=str(resolution.policy_id) if resolution.policy_id else resolution.source,
            reason=f"daily credits, day {resolution.day}", fx_rate_id=rate.id, policy_id=resolution.policy_id,
            local_date=resolution.local_date, now=now)
        await db.commit()
    except IntegrityError:
        await db.rollback()      # granted concurrently for this date
        return None
    return change


async def grant_due(db: Any, *, now: Optional[datetime] = None) -> dict:
    """The job (every 15 minutes): every active company whose local date has no daily lot yet."""
    from src.auth.models import Company

    now = now or datetime.utcnow()
    ids = list((await db.execute(select(Company.id).where(Company.status == "active",
                                                         Company.type == "TENANT"))).scalars().all())
    granted = errors = 0
    for company_id in ids:
        try:
            if await grant_today(db, company_id, now=now) is not None:
                granted += 1
        except Exception as error:  # noqa: BLE001 - one company's failure is its own
            await db.rollback()
            errors += 1
            logger.error("daily credits for %s failed: %s", company_id, error)
    return {"companies": len(ids), "granted": granted, "errors": errors}


async def preview(db: Any, *, audience: str, duration_days: Optional[int], bands: list[dict],
                  currency: str = "INR", days: int = 0) -> list[dict]:
    """What a policy would give on each day (the console's preview): ``bands`` as dicts."""
    from types import SimpleNamespace

    from src.billing.currency import current_rate, to_ccy

    rate = await current_rate(db, currency)
    rows = [SimpleNamespace(from_day=int(b["from_day"]), to_day=int(b["to_day"]),
                            amount_usd=Decimal(str(b["amount_usd"]))) for b in bands]
    last = days or (duration_days if duration_days is not None else max((r.to_day for r in rows), default=0))
    out, previous = [], None
    for day in range(1, min(last, 3650) + 1):
        usd = band_amount(rows, day, duration_days)
        if previous is None or usd != previous[0]:
            out.append({"from_day": day, "to_day": day, "amount_usd": str(usd), "amount": str(to_ccy(usd, rate)),
                        "currency": currency})
            previous = (usd,)
        else:
            out[-1]["to_day"] = day
    return out
