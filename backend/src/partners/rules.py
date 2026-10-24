"""Commission and fee rules, versioned (Phase 15 T8-7, T8-8; tech design §11.5, §11.6, 07 §5.10).

A rule is never edited in place: a change is a new version (the old one
stays, inactive), audited. Agreements snapshot the rules in force when they
are made (``terms``).
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, List, Optional

from fastapi import HTTPException
from sqlalchemy import func, select

from src.partners.models import FEE_KINDS, REVENUE_KINDS, CommissionRule, FeeRule

COMMISSION_KINDS = ("usage_topup", "subscription")
FEE_REVENUE = {"setup": "setup_fee", "customisation": "customisation_fee"}
SPLIT_KEYS = ("originator", "level1", "level2", "platform")


@dataclass(frozen=True)
class Rate:
    rate_pct: Decimal
    cap_pct: Optional[Decimal]
    months: Optional[int]
    version: int


async def commission_rule(db: Any, partner_type: str, revenue_kind: str, level: int) -> Optional[Rate]:
    row = (await db.execute(select(CommissionRule).where(
        CommissionRule.partner_type == partner_type, CommissionRule.revenue_kind == revenue_kind,
        CommissionRule.level == level, CommissionRule.active.is_(True))
        .order_by(CommissionRule.version.desc()).limit(1))).scalar_one_or_none()
    if row is None:
        return None
    return Rate(Decimal(str(row.rate_pct)), Decimal(str(row.cap_pct)) if row.cap_pct is not None else None,
                row.months, row.version)


async def fee_rule(db: Any, partner_type: str, fee_kind: str) -> Optional[FeeRule]:
    return (await db.execute(select(FeeRule).where(
        FeeRule.partner_type == partner_type, FeeRule.fee_kind == fee_kind, FeeRule.active.is_(True))
        .order_by(FeeRule.version.desc()).limit(1))).scalar_one_or_none()


async def current_rules(db: Any) -> Dict[str, List[dict]]:
    """Every rule in force (the rules page, agreements' snapshots)."""
    commissions = (await db.execute(select(CommissionRule).where(CommissionRule.active.is_(True))
                                    .order_by(CommissionRule.partner_type, CommissionRule.revenue_kind,
                                              CommissionRule.level))).scalars().all()
    fees = (await db.execute(select(FeeRule).where(FeeRule.active.is_(True))
                             .order_by(FeeRule.partner_type, FeeRule.fee_kind))).scalars().all()
    return {"commission_rules": [commission_view(r) for r in commissions], "fee_rules": [fee_view(r) for r in fees]}


def commission_view(r: CommissionRule) -> dict:
    return {"id": str(r.id), "partner_type": r.partner_type, "revenue_kind": r.revenue_kind, "level": r.level,
            "rate_pct": str(r.rate_pct), "cap_pct": str(r.cap_pct) if r.cap_pct is not None else None,
            "months": r.months, "active": r.active, "version": r.version, "reason": r.reason,
            "created_at": r.created_at.isoformat() if r.created_at else None}


def fee_view(r: FeeRule) -> dict:
    return {"id": str(r.id), "partner_type": r.partner_type, "fee_kind": r.fee_kind, "min_usd": str(r.min_usd),
            "max_usd": str(r.max_usd), "split": r.split, "active": r.active, "version": r.version, "reason": r.reason,
            "created_at": r.created_at.isoformat() if r.created_at else None}


async def set_commission_rule(db: Any, *, partner_type: str, revenue_kind: str, level: int, rate_pct: Decimal,
                              cap_pct: Optional[Decimal], months: Optional[int], actor: Any,
                              reason: Optional[str]) -> CommissionRule:
    """A new version of one rule (the caller commits); audited."""
    from src.common.admin_audit import record_admin_change

    if revenue_kind not in COMMISSION_KINDS:
        raise HTTPException(status_code=422, detail=f"commission rules are for {', '.join(COMMISSION_KINDS)} "
                                                    "(setup and customisation fees are split by fee rules)")
    if level not in (0, 1, 2):
        raise HTTPException(status_code=422, detail="level is 0 (the partner), 1 or 2 (its uplines)")
    if not Decimal(0) <= rate_pct <= Decimal(100) or (cap_pct is not None and not Decimal(0) <= cap_pct <= 100):
        raise HTTPException(status_code=422, detail="rates are percentages from 0 to 100")
    if level == 0 and cap_pct is None:
        raise HTTPException(status_code=422, detail="level 0 carries the pool cap (cap_pct)")
    current = (await db.execute(select(CommissionRule).where(
        CommissionRule.partner_type == partner_type, CommissionRule.revenue_kind == revenue_kind,
        CommissionRule.level == level, CommissionRule.active.is_(True)).with_for_update())).scalars().all()
    version = (await db.execute(select(func.coalesce(func.max(CommissionRule.version), 0)).where(
        CommissionRule.partner_type == partner_type, CommissionRule.revenue_kind == revenue_kind,
        CommissionRule.level == level))).scalar() + 1
    for old in current:
        old.active = False
    row = CommissionRule(partner_type=partner_type, revenue_kind=revenue_kind, level=level, rate_pct=rate_pct,
                         cap_pct=cap_pct if level == 0 else None, months=months, version=version, reason=reason,
                         created_by=getattr(actor, "id", None))
    db.add(row)
    record_admin_change(db, actor=actor, action="set", object_type="commission_rule",
                        object_key=f"{partner_type}:{revenue_kind}:{level}",
                        old_value=[commission_view(o) for o in current] or None,
                        new_value={"rate_pct": str(rate_pct), "cap_pct": str(cap_pct) if cap_pct is not None else None,
                                   "months": months, "version": version}, reason=reason)
    await db.flush()
    return row


def check_split(split: Dict[str, Any]) -> Dict[str, Decimal]:
    unknown = set(split) - set(SPLIT_KEYS)
    if unknown:
        raise HTTPException(status_code=422, detail=f"a split has {', '.join(SPLIT_KEYS)}")
    out = {k: Decimal(str(split.get(k, 0))) for k in SPLIT_KEYS}
    if any(v < 0 for v in out.values()) or sum(out.values()) != Decimal(100):
        raise HTTPException(status_code=422, detail="a split's shares are positive and add up to 100 %")
    return out


async def set_fee_rule(db: Any, *, partner_type: str, fee_kind: str, min_usd: Decimal, max_usd: Decimal,
                       split: Dict[str, Any], actor: Any, reason: Optional[str]) -> FeeRule:
    from src.common.admin_audit import record_admin_change

    if fee_kind not in FEE_KINDS:
        raise HTTPException(status_code=422, detail=f"fee kinds are {', '.join(FEE_KINDS)}")
    if min_usd < 0 or max_usd < min_usd:
        raise HTTPException(status_code=422, detail="0 ≤ minimum ≤ maximum")
    clean = check_split(split)
    current = (await db.execute(select(FeeRule).where(FeeRule.partner_type == partner_type,
                                                      FeeRule.fee_kind == fee_kind, FeeRule.active.is_(True))
                                .with_for_update())).scalars().all()
    version = (await db.execute(select(func.coalesce(func.max(FeeRule.version), 0)).where(
        FeeRule.partner_type == partner_type, FeeRule.fee_kind == fee_kind))).scalar() + 1
    for old in current:
        old.active = False
    row = FeeRule(partner_type=partner_type, fee_kind=fee_kind, min_usd=min_usd, max_usd=max_usd,
                  split={k: float(v) for k, v in clean.items()}, version=version, reason=reason,
                  created_by=getattr(actor, "id", None))
    db.add(row)
    record_admin_change(db, actor=actor, action="set", object_type="fee_rule", object_key=f"{partner_type}:{fee_kind}",
                        old_value=[fee_view(o) for o in current] or None,
                        new_value={"min_usd": str(min_usd), "max_usd": str(max_usd), "split": row.split,
                                   "version": version}, reason=reason)
    await db.flush()
    return row


async def snapshot(db: Any, partner_type: str) -> dict:
    """The terms an agreement records: the type's rules and the payout policy, now."""
    from src.billing.settings_catalogue import value

    rules = await current_rules(db)
    policy = {key: str(await value(db, key)) for key in (
        "partners.holdback_days", "partners.probation_holdback_days", "partners.probation_days",
        "partners.payout_min_usd", "partners.tds_pct", "partners.override_months",
        "partners.override_min_monthly_revenue_usd", "partners.max_margin_share_pct")}
    return {"partner_type": partner_type,
            # A partner earns at its own type's rate at every level (as the originator and as an upline).
            "commission_rules": [r for r in rules["commission_rules"] if r["partner_type"] == partner_type],
            "fee_rules": [r for r in rules["fee_rules"] if r["partner_type"] == partner_type],
            "policy": policy}


def unknown_kind(kind: str) -> None:
    if kind not in REVENUE_KINDS:
        raise HTTPException(status_code=422, detail=f"revenue kinds are {', '.join(REVENUE_KINDS)}")

