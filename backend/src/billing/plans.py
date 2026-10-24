"""Plans (Phase 15 T6-1, tech design §12.1).

A plan has a USD monthly fee, a bonus %, optional per-currency price overrides
and a version. Level 0 is Pay-as-you-go: the plan of every company without a
live subscription (SB-6). Only app_admin edits plans; an edit is a new version,
and a subscription keeps the version it bought until its next renewal (SB-1).
Plans are archived, never deleted.

A plan's money settings — its negative tolerance, top-up validity, minimum
balances — are settings at the ``plan`` scope (``src.billing.settings_catalogue``),
so a company's value is resolved company → partner → **plan** → platform.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, Optional, Tuple
from uuid import UUID

from sqlalchemy import select

PAYG = "payg"
CACHE_SECONDS = 30.0
_plan_cache: Dict[str, Tuple[Optional[UUID], float]] = {}


class PlanProblem(ValueError):
    pass


@dataclass(frozen=True)
class PlanPrice:
    currency: str
    net: Decimal                 # the monthly fee in the currency, before tax
    overridden: bool
    fx_rate_id: Optional[UUID]


async def payg_plan(db: Any) -> Any:
    from src.billing.billing_models import Plan

    return (await db.execute(select(Plan).where(Plan.tier_level == 0))).scalar_one_or_none()


async def live_subscription(db: Any, company_id: UUID) -> Any:
    from src.billing.billing_models import Subscription
    from src.billing.payment_service import LIVE_SUBSCRIPTION_STATUSES

    return (await db.execute(select(Subscription).where(
        Subscription.company_id == company_id, Subscription.status.in_(LIVE_SUBSCRIPTION_STATUSES))
        .order_by(Subscription.created_at.desc()).limit(1))).scalar_one_or_none()


async def plan_id_of(db: Any, company_id: Optional[UUID]) -> Optional[UUID]:
    """The company's plan: its live subscription's, else Pay-as-you-go (cached half a minute)."""
    if company_id is None:
        return None
    key = str(company_id)
    hit = _plan_cache.get(key)
    if hit and hit[1] > time.monotonic():
        return hit[0]
    sub = await live_subscription(db, company_id)
    plan_id = sub.plan_id if sub is not None and sub.plan_id else None
    if plan_id is None:
        payg = await payg_plan(db)
        plan_id = payg.id if payg is not None else None
    _plan_cache[key] = (plan_id, time.monotonic() + CACHE_SECONDS)
    return plan_id


async def plan_of(db: Any, company_id: UUID) -> Any:
    from src.billing.billing_models import Plan

    plan_id = await plan_id_of(db, company_id)
    return await db.get(Plan, plan_id) if plan_id else None


def forget(company_id: Any = None) -> None:
    """Drop the cached plan of a company (or every company) after a subscription changes."""
    if company_id is None:
        _plan_cache.clear()
    else:
        _plan_cache.pop(str(company_id), None)
    from src.billing.features import forget as forget_entitlements
    forget_entitlements(company_id)


async def price_in(db: Any, plan: Any, currency: str) -> PlanPrice:
    """The plan's monthly fee in ``currency``: its override, else the USD fee at today's rate (SB-2)."""
    from src.billing.currency import current_rate, to_ccy

    currency = currency.upper()
    override = (plan.currency_overrides or {}).get(currency)
    if override not in (None, ""):
        return PlanPrice(currency, Decimal(str(override)), True, None)
    rate = await current_rate(db, currency)
    return PlanPrice(currency, to_ccy(Decimal(str(plan.monthly_fee_usd)), rate), False, rate.id)


def _snapshot(plan: Any) -> dict:
    return {"code": plan.code, "name": plan.name, "tier_level": plan.tier_level, "version": plan.version,
            "monthly_fee_usd": str(plan.monthly_fee_usd), "bonus_pct": str(plan.bonus_pct),
            "currency_overrides": plan.currency_overrides or {}, "active": plan.active, "sort": plan.sort}


async def save_plan(db: Any, *, actor: Any, reason: Optional[str], plan_id: Optional[UUID] = None,
                    **fields: Any) -> Any:
    """Create a plan, or change one as a new version (the caller commits); audited.

    ``fields``: code, name, tier_level, monthly_fee_usd, bonus_pct, currency_overrides, active, sort.
    Pay-as-you-go keeps its level 0 and a fee of 0.
    """
    from src.billing.billing_models import Plan, PlanVersion
    from src.common.admin_audit import record_admin_change

    if plan_id is None:
        plan = Plan(code=fields["code"], name=fields["name"], tier_level=fields["tier_level"],
                    monthly_fee_usd=Decimal(str(fields.get("monthly_fee_usd", 0))),
                    bonus_pct=Decimal(str(fields.get("bonus_pct", 0))),
                    currency_overrides=_overrides(fields.get("currency_overrides")),
                    active=fields.get("active", True), sort=fields.get("sort", fields["tier_level"]), version=1,
                    updated_by=getattr(actor, "id", None))
        if plan.tier_level == 0:
            raise PlanProblem("level 0 is Pay-as-you-go, which exists already")
        db.add(plan)
        await db.flush()
        old = None
    else:
        plan = (await db.execute(select(Plan).where(Plan.id == plan_id).with_for_update())).scalar_one_or_none()
        if plan is None:
            raise LookupError("no such plan")
        old = _snapshot(plan)
        if plan.tier_level == 0:
            if fields.get("monthly_fee_usd") not in (None, 0, "0") and Decimal(str(fields["monthly_fee_usd"])) != 0:
                raise PlanProblem("Pay-as-you-go has no fee")
            if fields.get("active") is False:
                raise PlanProblem("Pay-as-you-go cannot be archived: it is the plan of every company without one")
            fields.pop("tier_level", None)
        price_fields = ("name", "monthly_fee_usd", "bonus_pct", "currency_overrides", "active")
        changes_version = any(k in fields and _differs(getattr(plan, k), fields[k]) for k in price_fields)
        for key in ("name", "tier_level", "sort", "active"):
            if key in fields and fields[key] is not None:
                setattr(plan, key, fields[key])
        for key in ("monthly_fee_usd", "bonus_pct"):
            if key in fields and fields[key] is not None:
                setattr(plan, key, Decimal(str(fields[key])))
        if "currency_overrides" in fields and fields["currency_overrides"] is not None:
            plan.currency_overrides = _overrides(fields["currency_overrides"])
        if changes_version:
            plan.version += 1
        plan.updated_by, plan.updated_at = getattr(actor, "id", None), datetime.utcnow()
        await db.flush()
        if not changes_version:
            record_admin_change(db, actor=actor, action="update", object_type="plan", object_key=plan.code,
                                old_value=old, new_value=_snapshot(plan), reason=reason)
            return plan
    db.add(PlanVersion(plan_id=plan.id, version=plan.version, name=plan.name, monthly_fee_usd=plan.monthly_fee_usd,
                       bonus_pct=plan.bonus_pct, currency_overrides=plan.currency_overrides or {},
                       active=plan.active, reason=reason, created_by=getattr(actor, "id", None)))
    record_admin_change(db, actor=actor, action="create" if old is None else "update", object_type="plan",
                        object_key=plan.code, old_value=old, new_value=_snapshot(plan), reason=reason)
    await db.flush()
    return plan


def _differs(current: Any, new: Any) -> bool:
    if new is None:
        return False
    if isinstance(current, Decimal) or isinstance(new, (int, float, Decimal)):
        try:
            return Decimal(str(current)) != Decimal(str(new))
        except Exception:  # noqa: BLE001
            return True
    if isinstance(current, dict) or isinstance(new, dict):
        return _overrides(current) != _overrides(new)
    return current != new


def _overrides(value: Any) -> dict:
    return {k.upper(): str(Decimal(str(v))) for k, v in (value or {}).items() if v not in (None, "")}
