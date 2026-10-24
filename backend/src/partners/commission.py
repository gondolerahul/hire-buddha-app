"""The commission engine (Phase 15 T8-7, tech design §11.6).

Commission is on **cash a customer actually paid**, net of GST: a top-up, a
subscription charge, a setup or customisation fee — never daily credits,
bonuses, staff grants or partnership fees (K-12). One payment of a tenant
attributed to partner P0 (recruited by P1, recruited by P2):

* top-ups and subscriptions: P_k earns ``rule(P_k.type, kind, k).rate × B``;
  setup and customisation fees are split by the fee rule of P0's type
  (originator, level 1, level 2, platform);
* every level must be eligible: ``active`` or ``renewal_due`` (a ``lapsed``
  partner's share is ``held``; a partner whose KYC is not verified has it
  ``held`` until it is); an upline (k ≥ 1) must also have its own paid
  revenue in the month (``partners.override_min_monthly_revenue_usd``) and be
  within ``partners.override_months`` of the partner below it becoming
  active. An ineligible share stays with the platform (no compression);
* the pool cap (``cap_pct`` of P0's level-0 rule) bounds the total: level ≥ 1
  is scaled down first, then level 0;
* each share is a ledger entry in the partner's currency at the event's rate,
  ``accrued`` until ``partners.holdback_days`` (probation: longer) have passed,
  then ``payable``. The monthly margin guard and refunds' clawbacks take back
  what the cash or the margin does not support.

``compute`` is the arithmetic alone (the simulator uses it); ``distribute``
writes the entries, once per payment (a unique key per source, partner, level).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import func, select

from src.partners.models import EARNING_STATUSES, PartnerLedgerEntry, PartnerProfile

logger = logging.getLogger(__name__)

HUNDRED = Decimal(100)
COMMISSION_KINDS = ("usage_topup", "subscription")
FEE_KIND_OF = {"setup_fee": "setup", "customisation_fee": "customisation"}


@dataclass
class LevelIn:
    """One level of the chain as ``compute`` sees it."""
    level: int
    partner_id: Optional[Any]
    rate_pct: Decimal
    eligible: bool = True
    hold: Optional[str] = None          # lapsed | kyc: earned, not yet payable
    why: Optional[str] = None           # why it is not eligible


@dataclass
class Share:
    level: int
    partner_id: Optional[Any]
    rate_pct: Decimal
    amount: Decimal
    status: str                         # accrued | held | platform
    why: Optional[str] = None


@dataclass
class Result:
    base: Decimal
    shares: List[Share] = field(default_factory=list)
    platform: Decimal = Decimal(0)
    pool_cap: Optional[Decimal] = None
    capped: bool = False

    def view(self) -> dict:
        return {"base": str(self.base), "platform": str(self.platform),
                "pool_cap": str(self.pool_cap) if self.pool_cap is not None else None, "capped": self.capped,
                "shares": [{"level": s.level, "partner_id": str(s.partner_id) if s.partner_id else None,
                            "rate_pct": str(s.rate_pct), "amount": str(s.amount), "status": s.status, "why": s.why}
                           for s in self.shares]}


def compute(base: Decimal, levels: List[LevelIn], *, cap_pct: Optional[Decimal]) -> Result:
    """The shares of ``base`` for a chain: ineligible levels to the platform, the pool cap applied."""
    base = Decimal(str(base))
    shares = [Share(lv.level, lv.partner_id, lv.rate_pct, base * lv.rate_pct / HUNDRED if lv.eligible else Decimal(0),
                    ("held" if lv.hold else "accrued") if lv.eligible else "platform", lv.why or lv.hold)
              for lv in levels]
    result = Result(base, shares)
    if cap_pct is not None:
        pool = base * cap_pct / HUNDRED
        result.pool_cap = pool
        total = sum((s.amount for s in shares), Decimal(0))
        if total > pool:
            result.capped = True
            first = [s for s in shares if s.level == 0]
            up = [s for s in shares if s.level > 0]
            lead = sum((s.amount for s in first), Decimal(0))
            room = max(pool - lead, Decimal(0))
            upper = sum((s.amount for s in up), Decimal(0))
            if upper > room:
                for s in up:
                    s.amount = s.amount * room / upper if upper else Decimal(0)
            if lead > pool:
                for s in first:
                    s.amount = s.amount * pool / lead
    result.platform = base - sum((s.amount for s in shares), Decimal(0))
    return result


# ── the chain ────────────────────────────────────────────────────────────────

async def chain(db: Any, partner_id: UUID, depth: int = 3) -> List[PartnerProfile]:
    """The partner, then its recruiter and the recruiter's (at most ``depth`` profiles)."""
    out: List[PartnerProfile] = []
    current: Optional[UUID] = partner_id
    while current is not None and len(out) < depth:
        profile = await db.get(PartnerProfile, current)
        if profile is None or any(p.company_id == profile.company_id for p in out):
            break
        out.append(profile)
        current = profile.recruiter_partner_id
    return out


async def own_revenue_usd(db: Any, partner_id: UUID, at: datetime) -> Decimal:
    """What the partner's own customers paid in ``at``'s month (its level-0 bases, USD)."""
    start = at.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    total = (await db.execute(select(func.coalesce(func.sum(PartnerLedgerEntry.base_usd), 0)).where(
        PartnerLedgerEntry.partner_id == partner_id, PartnerLedgerEntry.level == 0,
        PartnerLedgerEntry.kind.in_(("commission", "fee_share")), PartnerLedgerEntry.created_at >= start))).scalar()
    return Decimal(str(total or 0))


def _months_between(start: datetime, end: datetime) -> int:
    return (end.year - start.year) * 12 + (end.month - start.month) - (1 if end.day < start.day else 0)


async def levels_for(db: Any, profiles: List[PartnerProfile], *, revenue_kind: str, at: datetime,
                     assignment_since: Optional[datetime]) -> tuple[List[LevelIn], Optional[Decimal], Optional[int]]:
    """Each level's rate and eligibility, the pool cap, and the fee rule's version (fees)."""
    from src.billing.settings_catalogue import value
    from src.partners.rules import commission_rule, fee_rule

    levels: List[LevelIn] = []
    cap: Optional[Decimal] = None
    version: Optional[int] = None
    split: Dict[str, Decimal] = {}
    if revenue_kind in FEE_KIND_OF:
        rule = await fee_rule(db, profiles[0].partner_type, FEE_KIND_OF[revenue_kind])
        if rule is None:
            return [], None, None
        split = {k: Decimal(str(v)) for k, v in (rule.split or {}).items()}
        version = rule.version
    min_override = Decimal(str(await value(db, "partners.override_min_monthly_revenue_usd")))
    override_months = int(await value(db, "partners.override_months"))
    for k, profile in enumerate(profiles):
        if revenue_kind in FEE_KIND_OF:
            rate = split.get("originator" if k == 0 else f"level{k}", Decimal(0))
            rule_months = None
        else:
            rule = await commission_rule(db, profile.partner_type, revenue_kind, k)
            rate = rule.rate_pct if rule else Decimal(0)
            rule_months = rule.months if rule else None
            if k == 0:
                cap = rule.cap_pct if rule else Decimal(0)
        lv = LevelIn(k, profile.company_id, rate)
        if profile.status == "lapsed":
            lv.hold = "lapsed"
        elif profile.status not in EARNING_STATUSES:
            lv.eligible, lv.why = False, f"partner {profile.status}"
        if lv.eligible and profile.kyc_status != "verified":
            lv.hold = lv.hold or "kyc"
        if lv.eligible and rule_months is not None and assignment_since is not None \
                and _months_between(assignment_since, at) >= rule_months:
            lv.eligible, lv.why = False, f"the rule ends after {rule_months} months"
        if lv.eligible and k >= 1:
            below = profiles[k - 1]
            if below.activated_at is not None and _months_between(below.activated_at, at) >= override_months:
                lv.eligible, lv.why = False, f"overrides end {override_months} months after the partner below joined"
            elif await own_revenue_usd(db, profile.company_id, at) < min_override:
                lv.eligible, lv.why = False, "no own paid revenue this month"
        if rate == 0:
            lv.eligible, lv.why = False, lv.why or "no rate"
        levels.append(lv)
    return levels, cap, version


async def distribute(db: Any, *, tenant_id: UUID, revenue_kind: str, base: Decimal, currency: str,
                     source_type: str, source_id: str, at: Optional[datetime] = None) -> List[PartnerLedgerEntry]:
    """Write the partners' shares of one payment (the caller commits). Nothing twice for one source."""
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from src.billing.currency import current_rate, to_ccy, to_usd
    from src.billing.settings_catalogue import value
    from src.partners.scope import assignment_of, partner_of

    at = at or datetime.utcnow()
    base = Decimal(str(base))
    if base <= 0:
        return []
    assignment = await assignment_of(db, tenant_id, at)
    partner_id = assignment.partner_id if assignment else await partner_of(db, tenant_id, at)
    if partner_id is None:
        return []
    if assignment is not None and assignment.commission_until is not None and at >= assignment.commission_until:
        return []
    profiles = await chain(db, partner_id)
    if not profiles:
        return []
    rate = await current_rate(db, currency)
    base_usd = to_usd(base, rate)
    levels, cap, _version = await levels_for(db, profiles, revenue_kind=revenue_kind, at=at,
                                             assignment_since=assignment.since if assignment else None)
    result = compute(base, levels, cap_pct=cap if revenue_kind not in FEE_KIND_OF else None)
    holdback = int(await value(db, "partners.holdback_days"))
    probation_holdback = int(await value(db, "partners.probation_holdback_days"))
    written: List[PartnerLedgerEntry] = []
    by_id = {p.company_id: p for p in profiles}
    for share in result.shares:
        if share.status == "platform" or share.amount <= 0:
            continue
        profile = by_id[share.partner_id]
        ccy = profile.billing_currency or "USD"
        partner_rate = await current_rate(db, ccy)
        usd = to_usd(share.amount, rate)
        amount = to_ccy(usd, partner_rate)
        on_probation = profile.probation_until is not None and profile.probation_until > at
        days = probation_holdback if on_probation else holdback
        kind = "fee_share" if revenue_kind in FEE_KIND_OF else ("commission" if share.level == 0 else "override")
        values = dict(partner_id=profile.company_id, kind=kind, amount=amount, currency=ccy,
                      fx_rate_id=partner_rate.id or rate.id, amount_usd=usd, revenue_kind=revenue_kind,
                      base_amount=base, base_currency=currency.upper(), base_usd=base_usd, rate_pct=share.rate_pct,
                      source_type=source_type, source_id=str(source_id), tenant_id=tenant_id, level=share.level,
                      origin_partner_id=profiles[0].company_id,
                      status=share.status, hold_reason=share.why if share.status == "held" else None,
                      payable_after=at + timedelta(days=days), created_at=at, updated_at=at,
                      reason=_reason(revenue_kind, share, base, currency))
        stmt = pg_insert(PartnerLedgerEntry).values(**values).on_conflict_do_nothing(
            index_elements=["source_type", "source_id", "partner_id", "level", "kind"],
            index_where=PartnerLedgerEntry.kind.in_(("commission", "override", "fee_share", "clawback")))
        inserted = (await db.execute(stmt.returning(PartnerLedgerEntry.id))).scalar_one_or_none()
        if inserted is not None:
            written.append(await db.get(PartnerLedgerEntry, inserted))
    if written:
        logger.info("%s %s of tenant %s: %d partner entries", revenue_kind, source_id, tenant_id, len(written))
    return written


def _reason(kind: str, share: Share, base: Decimal, currency: str) -> str:
    what = {"usage_topup": "top-up", "subscription": "subscription payment", "setup_fee": "setup fee",
            "customisation_fee": "customisation fee"}.get(kind, kind)
    who = "your customer" if share.level == 0 else f"a level-{share.level} partner's customer"
    return f"{share.rate_pct.normalize()} % of a {currency.upper()} {base:,.2f} {what} by {who}"


async def on_payment(db: Any, payment: Any, *, revenue_kind: str, base: Optional[Decimal] = None) -> int:
    """A captured payment's commissions; best-effort, never fails the payment. Commits."""
    try:
        net = Decimal(str(base if base is not None else (payment.net_amount if payment.net_amount is not None
                                                          else payment.amount)))
        rows = await distribute(db, tenant_id=payment.company_id, revenue_kind=revenue_kind, base=net,
                                currency=payment.currency or "USD", source_type="payment", source_id=str(payment.id))
        await db.commit()
        return len(rows)
    except Exception:  # noqa: BLE001 - the payment stands; the daily sweep writes them later
        await db.rollback()
        logger.exception("commissions of payment %s not written", getattr(payment, "id", None))
        return 0


async def clawback(db: Any, payment: Any, refund: Any) -> int:
    """A refund takes back, on every level, the share of what it refunds (§11.7). The caller commits."""
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    paid_net = Decimal(str(payment.net_amount if payment.net_amount is not None else payment.amount))
    if paid_net <= 0:
        return 0
    portion = Decimal(str(refund.net)) / paid_net
    entries = (await db.execute(select(PartnerLedgerEntry).where(
        PartnerLedgerEntry.source_type == "payment", PartnerLedgerEntry.source_id == str(payment.id),
        PartnerLedgerEntry.kind.in_(("commission", "override", "fee_share")),
        PartnerLedgerEntry.status != "reversed"))).scalars().all()
    now = datetime.utcnow()
    count = 0
    for entry in entries:
        status = "payable" if entry.status in ("payable", "paid") else entry.status
        values = dict(partner_id=entry.partner_id, kind="clawback", amount=-Decimal(str(entry.amount)) * portion,
                      currency=entry.currency, fx_rate_id=entry.fx_rate_id,
                      amount_usd=-Decimal(str(entry.amount_usd or 0)) * portion, revenue_kind=entry.revenue_kind,
                      base_amount=-Decimal(str(refund.net)), base_currency=entry.base_currency,
                      base_usd=-Decimal(str(entry.base_usd or 0)) * portion, rate_pct=entry.rate_pct,
                      source_type="refund", source_id=str(refund.id), tenant_id=entry.tenant_id, level=entry.level,
                      origin_partner_id=entry.origin_partner_id,
                      status=status, payable_after=now if status == "payable" else entry.payable_after,
                      reason=f"refund of {refund.currency} {Decimal(str(refund.net)):,.2f}: {refund.reason or ''}"[:500],
                      created_at=now, updated_at=now)
        stmt = pg_insert(PartnerLedgerEntry).values(**values).on_conflict_do_nothing(
            index_elements=["source_type", "source_id", "partner_id", "level", "kind"],
            index_where=PartnerLedgerEntry.kind.in_(("commission", "override", "fee_share", "clawback")))
        count += (await db.execute(stmt)).rowcount or 0
    return count


async def on_refund(db: Any, payment: Any, refund: Any) -> None:
    """``hooks.on_refund`` listener: the clawback, committed."""
    if await clawback(db, payment, refund):
        await db.commit()


async def sweep(db: Any, *, days: int = 7) -> Dict[str, int]:
    """The daily safety net: payments of the last ``days`` whose commissions were not written."""
    from src.billing.billing_models import PaymentTransaction

    since = datetime.utcnow() - timedelta(days=days)
    rows = (await db.execute(select(PaymentTransaction).where(
        PaymentTransaction.status == "success", PaymentTransaction.created_at >= since,
        PaymentTransaction.purpose.in_(("topup", "subscription", "one_time_charge"))))).scalars().all()
    written = 0
    for payment in rows:
        kind = {"topup": "usage_topup", "subscription": "subscription"}.get(payment.purpose)
        if payment.purpose == "one_time_charge":
            kind = (payment.transaction_metadata or {}).get("revenue_kind")
        if not kind:
            continue
        written += await on_payment(db, payment, revenue_kind=kind)
    return {"payments": len(rows), "entries": written}
