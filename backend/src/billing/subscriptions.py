"""Subscriptions in the company's currency (Phase 15 T6-4, tech design §12.1).

* A plan is priced in USD and charged in the company's currency (SB-2): the
  gateway charges a plan made for (plan version, currency, rate, tax rate) —
  its override, or the USD fee at today's rate, plus GST (tax-exclusive, TX-1) —
  created on first use and kept in ``plan_gateway_plans``.
* Each paid cycle grants what was paid net of GST as a subscription lot and
  the plan's bonus % of it as a bonus lot; a new cycle replaces the last, a
  mid-cycle (upgrade) charge adds to the cycle held (SB-3, W-5); a tax invoice
  is issued for every charge (TX-3). Nothing grants credit without a payment.
* Upgrade: now — the gateway prorates and charges the difference, which is
  credited when paid. Downgrade: at the cycle's end. Cancel: at the cycle's end
  by default (SB-4, O-10).
* Renewal follows the price: a subscription whose plan version, FX rate or tax
  rate changed is moved to the new gateway plan at its cycle's end (the
  reconciliation job), so a rate change reaches every subscriber at renewal.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

logger = logging.getLogger(__name__)


class SubscriptionProblem(ValueError):
    def __init__(self, message: str, status: int = 409):
        super().__init__(message)
        self.status = status


async def _digits(db: Any, currency: str) -> int:
    from src.billing.currency import minor_units
    return await minor_units(db, currency)


async def gateway_plan_for(db: Any, gateway: Any, plan: Any, company: Any) -> Any:
    """The gateway plan that charges ``company`` for ``plan`` now (made on first use; the caller commits)."""
    from src.billing.billing_models import PlanGatewayPlan
    from src.billing.gateways import minor
    from src.billing.plans import price_in
    from src.billing.tax import apply, tax_for

    currency = company.billing_currency
    price = await price_in(db, plan, currency)
    tax = await tax_for(db, company)
    taxed = apply(price.net, tax, await _digits(db, currency))
    query = select(PlanGatewayPlan).where(
        PlanGatewayPlan.plan_id == plan.id, PlanGatewayPlan.plan_version == plan.version,
        PlanGatewayPlan.currency == currency, PlanGatewayPlan.tax_rate == tax.rate,
        PlanGatewayPlan.gateway == gateway.name,
        (PlanGatewayPlan.fx_rate_id == price.fx_rate_id) if price.fx_rate_id else PlanGatewayPlan.fx_rate_id.is_(None))
    existing = (await db.execute(query)).scalar_one_or_none()
    if existing is not None:
        return existing
    gateway_plan_id = await gateway.create_plan(
        name=f"HireBuddha {plan.name}", amount=taxed.gross, currency=currency,
        description=f"{plan.name} plan v{plan.version}, {plan.bonus_pct}% bonus credits"
                    + (f", incl. {tax.rate}% GST" if tax.rate else ""),
        notes={"plan": plan.code, "version": str(plan.version)})
    row = PlanGatewayPlan(plan_id=plan.id, plan_version=plan.version, currency=currency, fx_rate_id=price.fx_rate_id,
                          tax_rate=tax.rate, net_amount=taxed.net, amount_minor=await minor(db, taxed.gross, currency),
                          gateway=gateway.name, gateway_plan_id=gateway_plan_id)
    db.add(row)
    await db.flush()
    return row


def _snapshot_plan(sub: Any, plan: Any, gateway_plan: Any) -> None:
    sub.plan_id, sub.plan_version, sub.plan_tier = plan.id, gateway_plan.plan_version, plan.tier_level
    sub.monthly_fee, sub.bonus_pct = plan.monthly_fee_usd, plan.bonus_pct
    sub.currency, sub.amount_ccy = gateway_plan.currency, gateway_plan.net_amount
    sub.gateway_plan_ref, sub.razorpay_plan_id = gateway_plan.id, gateway_plan.gateway_plan_id


async def subscribe(db: Any, gateway: Any, *, company: Any, plan: Any) -> Dict[str, Any]:
    """Start a subscription; pending until its first payment is verified. Commits."""
    from src.billing.billing_models import Subscription
    from src.billing.plans import live_subscription
    from src.billing.settings_catalogue import value

    if plan.tier_level == 0 or not plan.active:
        raise SubscriptionProblem("that plan is not on offer", 404)
    live = await live_subscription(db, company.id)
    if live is not None:
        raise SubscriptionProblem(f"This company already has a {live.status} subscription. Change or cancel it.")
    gateway_plan = await gateway_plan_for(db, gateway, plan, company)
    await db.commit()                                    # the gateway plan exists either way
    rz_sub = await gateway.create_subscription(
        plan_id=gateway_plan.gateway_plan_id, total_count=int(await value(db, "subscriptions.total_cycles")),
        notes={"company_id": str(company.id), "plan": plan.code})
    sub = Subscription(company_id=company.id, status="pending_payment", razorpay_subscription_id=rz_sub["id"])
    _snapshot_plan(sub, plan, gateway_plan)
    db.add(sub)
    await db.commit()
    from src.billing.plans import forget
    forget(company.id)
    gross = Decimal(gateway_plan.amount_minor) / (Decimal(10) ** await _digits(db, gateway_plan.currency))
    return {"subscription_id": str(sub.id), "razorpay_subscription_id": rz_sub["id"], "key_id": gateway.key_id,
            "plan_id": str(plan.id), "plan_tier": plan.tier_level, "currency": gateway_plan.currency,
            "net": str(gateway_plan.net_amount), "tax": str(gross - Decimal(str(gateway_plan.net_amount))),
            "amount": str(gross), "bonus_credits_pct": float(plan.bonus_pct)}


async def record_charge(db: Any, sub: Any, *, payment_id: str, gross: Decimal,
                        cycle_end: Optional[datetime] = None) -> bool:
    """Credit one subscription payment, once (by payment id): its net as credit, its invoice. Commits.

    A charge that opens a new cycle first applies a change waiting for the
    cycle's end (a downgrade, a new price).
    """
    from src.auth.models import Company
    from src.billing.billing_models import PaymentTransaction, Plan, PlanGatewayPlan, PlanVersion
    from src.billing.credit_service import CreditService
    from src.billing.invoices import issue_invoice, store_pdf
    from src.billing.tax import net_of, tax_for

    if (await db.execute(select(PaymentTransaction.id).where(
            PaymentTransaction.razorpay_payment_id == payment_id))).first() is not None:
        return False
    company = await db.get(Company, sub.company_id)
    now = datetime.utcnow()
    cycle_end = cycle_end or now + timedelta(days=31)
    new_cycle = sub.next_billing_date is None or cycle_end > sub.next_billing_date + timedelta(minutes=5)
    if new_cycle and sub.pending_gateway_plan_ref:
        pending = await db.get(PlanGatewayPlan, sub.pending_gateway_plan_ref)
        plan = await db.get(Plan, pending.plan_id) if pending else None
        if pending is not None and plan is not None:
            _snapshot_plan(sub, plan, pending)
        sub.pending_plan_id = sub.pending_gateway_plan_ref = None
    currency = sub.currency or "USD"
    taxed = net_of(Decimal(str(gross)), await tax_for(db, company), await _digits(db, currency))
    version = (await db.execute(select(PlanVersion).where(
        PlanVersion.plan_id == sub.plan_id, PlanVersion.version == sub.plan_version))).scalar_one_or_none()
    bonus_pct = Decimal(str(version.bonus_pct if version else sub.bonus_pct or 0))
    plan_name = version.name if version else f"Tier {sub.plan_tier}"
    payment = PaymentTransaction(
        company_id=sub.company_id, razorpay_payment_id=payment_id, amount=taxed.gross, currency=currency,
        transaction_type="subscription_charge", purpose="subscription", status="success",
        net_amount=taxed.net, tax_amount=taxed.tax, gross_amount=taxed.gross,
        credits_awarded=taxed.net + taxed.net * bonus_pct / 100,
        transaction_metadata={"subscription_id": str(sub.id), "plan_id": str(sub.plan_id) if sub.plan_id else None,
                              "plan_version": sub.plan_version, "razorpay_subscription_id": sub.razorpay_subscription_id,
                              "cycle_end": cycle_end.isoformat(), "new_cycle": new_cycle})
    db.add(payment)
    if cycle_end > now:
        sub.status = "active"
    if sub.next_billing_date is None or cycle_end > sub.next_billing_date:
        sub.next_billing_date = cycle_end
    sub.updated_at = now
    from src.billing.wallet import WalletService
    await WalletService(db).ensure(sub.company_id)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()                              # the same payment, recorded concurrently
        return False
    invoice = await issue_invoice(db, payment=payment, company=company, taxed=taxed, currency=currency,
                                  lines=[(f"{plan_name} plan, cycle to {cycle_end:%d %b %Y}", taxed.net)])
    invoice_id = invoice.id
    await CreditService(db).grant_cycle(sub.company_id, taxed.net, bonus_pct, cycle_end, source_id=payment_id)  # commits
    await store_pdf(db, invoice_id)
    logger.info("Subscription %s: payment %s credited %s %s to %s", sub.id, payment_id, taxed.net, currency, cycle_end)
    return True


async def change_plan(db: Any, gateway: Any, sub: Any, plan: Any) -> Dict[str, Any]:
    """Upgrade now, or downgrade at the cycle's end (SB-4). Commits."""
    from src.auth.models import Company
    from src.billing.billing_models import Plan

    if sub.status not in ("active", "past_due") or not sub.razorpay_subscription_id:
        raise SubscriptionProblem("only an active subscription changes plan")
    if not plan.active or plan.tier_level == 0:
        raise SubscriptionProblem("that plan is not on offer (to go back to Pay-as-you-go, cancel)", 404)
    if plan.id == sub.plan_id:
        raise SubscriptionProblem("the subscription is on that plan already")
    current = await db.get(Plan, sub.plan_id) if sub.plan_id else None
    company = await db.get(Company, sub.company_id)
    gateway_plan = await gateway_plan_for(db, gateway, plan, company)
    await db.commit()
    upgrade = current is None or plan.tier_level > current.tier_level
    await gateway.change_subscription_plan(sub.razorpay_subscription_id, plan_id=gateway_plan.gateway_plan_id,
                                           at_cycle_end=not upgrade)
    if upgrade:
        _snapshot_plan(sub, plan, gateway_plan)
        sub.pending_plan_id = sub.pending_gateway_plan_ref = None
    else:
        sub.pending_plan_id, sub.pending_gateway_plan_ref = plan.id, gateway_plan.id
    sub.cancel_at_cycle_end = False
    sub.updated_at = datetime.utcnow()
    await db.commit()
    from src.billing.plans import forget
    forget(sub.company_id)
    return {"subscription_id": str(sub.id), "change": "upgrade" if upgrade else "downgrade",
            "effective": "now" if upgrade else (sub.next_billing_date.isoformat() if sub.next_billing_date else
                                                "the end of the cycle"),
            "plan_id": str(plan.id)}


async def cancel(db: Any, gateway: Optional[Any], sub: Any, *, at_cycle_end: bool = True) -> Dict[str, Any]:
    """Stop the mandate first (a cancelled row while the gateway charged would be wrong), then the row.

    At the cycle's end by default: the subscription stays active until then
    and the gateway's ``subscription.cancelled`` ends it. Commits.
    """
    from src.billing.payment_service import PaymentService

    if sub.razorpay_subscription_id and gateway is not None:
        await gateway.cancel_subscription(sub.razorpay_subscription_id, at_cycle_end=at_cycle_end)
    if at_cycle_end and sub.status in ("active", "past_due"):
        sub.cancel_at_cycle_end = True
        sub.pending_plan_id = sub.pending_gateway_plan_ref = None
        sub.updated_at = datetime.utcnow()
        await db.commit()
        return {"subscription_id": str(sub.id), "status": sub.status, "cancel_at_cycle_end": True,
                "ends": sub.next_billing_date.isoformat() if sub.next_billing_date else None}
    await PaymentService(db).set_subscription_status(sub, "cancelled")
    from src.billing.plans import forget
    forget(sub.company_id)
    return {"subscription_id": str(sub.id), "status": "cancelled", "cancel_at_cycle_end": False}


async def reprice_for_renewal(db: Any, gateway: Any) -> Dict[str, int]:
    """Move each live subscription whose price changed (plan version, FX, tax) to the new gateway
    plan at its cycle's end — the next renewal is charged at today's price (the reconciliation job)."""
    from src.auth.models import Company
    from src.billing.billing_models import Plan, Subscription

    counts = {"checked": 0, "moved": 0, "errors": 0}
    subs = (await db.execute(select(Subscription).where(
        Subscription.status.in_(("active", "past_due")), Subscription.cancel_at_cycle_end.is_(False),
        Subscription.razorpay_subscription_id.isnot(None), Subscription.plan_id.isnot(None)))).scalars().all()
    for sub in subs:
        counts["checked"] += 1
        try:
            plan = await db.get(Plan, sub.pending_plan_id or sub.plan_id)
            company = await db.get(Company, sub.company_id)
            wanted = await gateway_plan_for(db, gateway, plan, company)
            await db.commit()
            if wanted.id in (sub.pending_gateway_plan_ref or sub.gateway_plan_ref,):
                continue
            await gateway.change_subscription_plan(sub.razorpay_subscription_id, plan_id=wanted.gateway_plan_id,
                                                   at_cycle_end=True)
            sub.pending_plan_id, sub.pending_gateway_plan_ref = plan.id, wanted.id
            await db.commit()
            counts["moved"] += 1
        except Exception as error:  # noqa: BLE001 - one subscription's failure is its own
            await db.rollback()
            counts["errors"] += 1
            logger.error("repricing subscription %s failed: %s", sub.id, error)
    return counts
