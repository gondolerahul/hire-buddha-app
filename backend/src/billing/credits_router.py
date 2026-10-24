"""
Credits Router — wallet balance, top-ups and the company's subscription.

Payments go through the gateway interface (``src.billing.gateways``, Phase 15
T6-3); prices are tax-exclusive, so what is charged is the net amount plus GST
(``src.billing.tax``, T6-5), and each payment received gets a tax invoice.
Plans are ``/api/v1/plans`` (``plans_router``); staff edit them at
``/api/v1/admin/plans``.
"""
import logging
from decimal import Decimal
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from src.common.tenancy.session import get_control_db
from src.auth.router import get_current_user
from src.auth.dependencies import RoleChecker
from src.auth.models import Company, User
from src.auth.roles import Role
from src.billing.credit_service import CreditService
from src.billing.gateways import GatewayError, GatewayUnavailable, get_gateway
from src.billing.payment_service import (
    LIVE_SUBSCRIPTION_STATUSES, PaymentNotFound, PaymentService, razorpay_time,
)
from src.billing.billing_models import Plan, Subscription, PaymentTransaction

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/credits", tags=["Credits & Payments"])

# Paying, subscribing and cancelling are the company's admins' (Phase 15 T0-3,
# B-15): any user of the company could, tenant_user included. The Gold
# partner joins them with the partner programme (WS15-8).
billing_admin = RoleChecker([Role.PARTNER_ADMIN, Role.TENANT_ADMIN])


async def _gateway(db: AsyncSession):
    try:
        return await get_gateway(db)
    except GatewayUnavailable as missing:
        raise HTTPException(status_code=503, detail=str(missing)) from None


# ─── Schemas ──────────────────────────────────────────────────────────────────

class TopUpRequest(BaseModel):
    # The credit wanted, in the company's billing currency (Phase 15 T4-3), at
    # most two decimals: GST is added on top (T6-5). The limits are the settings
    # wallet.topup_min_usd / max_usd at today's rate (tech design §6.6).
    amount: Decimal = Field(gt=0, decimal_places=2)


async def topup_limits(db: AsyncSession, company_id: UUID) -> dict:
    """The top-up form's limits and presets in the company's currency, and its tax (§6.6, TX-1)."""
    from src.billing.currency import current_rate, to_ccy
    from src.billing.settings_catalogue import value
    from src.billing.tax import tax_for

    currency = (await CreditService(db).get_or_create_wallet(company_id)).currency
    rate = await current_rate(db, currency)

    def ccy(usd) -> Decimal:
        return to_ccy(Decimal(str(usd)), rate).quantize(Decimal("0.01"))

    company = await db.get(Company, company_id)
    tax = await tax_for(db, company)
    return {
        "currency": currency,
        "min": ccy(await value(db, "wallet.topup_min_usd", company_id)),
        "max": ccy(await value(db, "wallet.topup_max_usd", company_id)),
        "presets": [ccy(p) for p in await value(db, "wallet.topup_presets_usd", company_id)],
        "validity_days": await value(db, "wallet.topup_validity_days", company_id),
        "tax_rate": tax.rate, "tax_regime": tax.regime,
    }


class TopUpVerify(BaseModel):
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str


class SubscriptionCreate(BaseModel):
    plan_id: Optional[UUID] = None
    tier_level: Optional[int] = None      # the plan's level, as the wallet page sent it before plans


class SubscriptionChange(BaseModel):
    plan_id: UUID


# ─── Balance ──────────────────────────────────────────────────────────────────

@router.get("/balance", summary="Get credit wallet balance")
async def get_balance(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_control_db),
):
    svc = CreditService(db)
    return await svc.get_balance(current_user.company_id)


# ─── Wallet Top-Up ────────────────────────────────────────────────────────────

@router.get("/topup-options", summary="Top-up limits and preset amounts")
async def get_topup_options(current_user: User = Depends(get_current_user),
                            db: AsyncSession = Depends(get_control_db)):
    """What the top-up form offers, in the company's currency, its GST, and whether this user may pay."""
    limits = await topup_limits(db, current_user.company_id)
    return {
        "currency": limits["currency"],
        "min": str(limits["min"]),
        "max": str(limits["max"]),
        "presets": [str(p) for p in limits["presets"]],
        "validity_days": limits["validity_days"],
        "tax_rate": str(limits["tax_rate"]),
        "tax_regime": limits["tax_regime"],
        "can_pay": current_user.role in billing_admin.allowed_roles,
    }


@router.post("/topup", summary="Initiate a gateway order for a wallet top-up")
async def initiate_topup(
    payload: TopUpRequest,
    current_user: User = Depends(billing_admin),
    db: AsyncSession = Depends(get_control_db),
):
    """The order is for the credit plus GST (TX-1): ₹1,000 of credit is a ₹1,180 payment in Karnataka."""
    from src.billing.currency import minor_units
    from src.billing.tax import apply, tax_for

    limits = await topup_limits(db, current_user.company_id)
    currency = limits["currency"]
    if not limits["min"] <= payload.amount <= limits["max"]:
        raise HTTPException(status_code=422, detail=(
            f"A top-up is between {currency} {limits['min']:,.2f} and {currency} {limits['max']:,.2f}."))
    gateway = await _gateway(db)
    company = await db.get(Company, current_user.company_id)
    taxed = apply(payload.amount, await tax_for(db, company), await minor_units(db, currency))
    try:
        order = await gateway.create_order(
            taxed.gross, currency, receipt=f"topup_{str(current_user.company_id).replace('-', '')[:8]}",
            notes={"company_id": str(current_user.company_id), "type": "topup"})
    except GatewayError as error:
        logger.error(f"Top-up order creation failed: {error}")
        raise HTTPException(status_code=502, detail=f"Payment initiation failed: {error}") from None
    db.add(PaymentTransaction(
        company_id=current_user.company_id, razorpay_order_id=order["id"], amount=taxed.gross, currency=currency,
        transaction_type="topup", purpose="topup", status="pending",
        net_amount=taxed.net, tax_amount=taxed.tax, gross_amount=taxed.gross,
    ))
    await db.commit()
    return {
        "order_id": order["id"],
        "amount": str(taxed.gross),            # what Checkout charges
        "net": str(taxed.net), "tax": str(taxed.tax), "tax_rate": str(taxed.rate),
        "currency": currency,
        "key_id": gateway.key_id,               # sent to the frontend for Razorpay.js
    }


@router.post("/topup/verify", summary="Verify the payment and credit the wallet")
async def verify_topup(
    payload: TopUpVerify,
    current_user: User = Depends(billing_admin),
    db: AsyncSession = Depends(get_control_db),
):
    gateway = await _gateway(db)
    # Razorpay signs order_id|payment_id: proof this payment paid this order.
    if not gateway.payment_signature_valid(payload.razorpay_order_id, payload.razorpay_payment_id,
                                           payload.razorpay_signature):
        raise HTTPException(status_code=400, detail="Invalid payment signature")

    # The amount credited is the order's, stored when it was created (BC-01);
    # an order already credited is not credited again.
    try:
        txn, wallet, credited = await PaymentService(db).credit_topup(
            order_id=payload.razorpay_order_id,
            payment_id=payload.razorpay_payment_id,
            signature=payload.razorpay_signature,
            company_id=current_user.company_id,
        )
    except PaymentNotFound:
        raise HTTPException(status_code=404, detail="Top-up order not found")

    return {
        "message": "Payment verified and wallet credited" if credited else "Payment already credited",
        "currency": wallet.currency,
        "credits_added": str(txn.credits_awarded) if credited else "0",
        "new_balance": str(wallet.cached_available),
        "debt": str(wallet.debt),
        "invoice_id": str(txn.invoice_id) if txn.invoice_id else None,
    }


# ─── Subscription ─────────────────────────────────────────────────────────────
#
# A subscription is a gateway subscription on a plan made for the company's
# currency, rate and GST (src.billing.subscriptions): its first charge is
# authorised in Checkout, and each charge grants that cycle's credits — through
# the checkout callback for the first and the ``subscription.charged`` webhook
# (or the reconciliation job) for every one. Nothing grants credits without a
# payment (BC-03, BC-04, BC-16).


def _subscription_to_dict(sub: Subscription) -> dict:
    return {
        "id": str(sub.id),
        "plan_id": str(sub.plan_id) if sub.plan_id else None,
        "plan_tier": sub.plan_tier,
        "monthly_fee": float(sub.monthly_fee),
        "bonus_pct": float(sub.bonus_pct),
        "currency": sub.currency or "USD",
        "amount": str(sub.amount_ccy) if sub.amount_ccy is not None else str(sub.monthly_fee),
        "status": sub.status,
        "cancel_at_cycle_end": bool(sub.cancel_at_cycle_end),
        "pending_plan_id": str(sub.pending_plan_id) if sub.pending_plan_id else None,
        "razorpay_subscription_id": sub.razorpay_subscription_id,
        "next_billing_date": sub.next_billing_date.isoformat() if sub.next_billing_date else None,
    }


async def _live_subscription(db: AsyncSession, company_id) -> Optional[Subscription]:
    result = await db.execute(
        select(Subscription)
        .where(Subscription.company_id == company_id,
               Subscription.status.in_(LIVE_SUBSCRIPTION_STATUSES))
        .order_by(Subscription.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


@router.get("/subscriptions", summary="Get current subscription info")
async def get_subscription(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_control_db),
):
    sub = await _live_subscription(db, current_user.company_id)
    if not sub:
        return {"subscription": None, "account_model": "pay_as_you_go"}
    return {"subscription": _subscription_to_dict(sub), "account_model": "subscription"}


async def _plan_for(db: AsyncSession, payload: SubscriptionCreate) -> Plan:
    query = select(Plan).where(Plan.active.is_(True), Plan.tier_level > 0)
    if payload.plan_id is not None:
        query = query.where(Plan.id == payload.plan_id)
    elif payload.tier_level is not None:
        query = query.where(Plan.tier_level == payload.tier_level)
    else:
        raise HTTPException(status_code=422, detail="name the plan (plan_id)")
    plan = (await db.execute(query)).scalar_one_or_none()
    if plan is None:
        raise HTTPException(status_code=404, detail="That plan is not on offer")
    return plan


@router.post("/subscriptions", summary="Subscribe to a plan")
async def create_subscription(
    payload: SubscriptionCreate,
    current_user: User = Depends(billing_admin),
    db: AsyncSession = Depends(get_control_db),
):
    from src.billing.locks import require_unlocked
    from src.billing.subscriptions import SubscriptionProblem, subscribe

    plan = await _plan_for(db, payload)
    await require_unlocked(db, current_user.company_id, "plan", current_user)   # Phase 15 T5-4
    gateway = await _gateway(db)
    company = await db.get(Company, current_user.company_id)
    try:
        return await subscribe(db, gateway, company=company, plan=plan)
    except SubscriptionProblem as problem:
        raise HTTPException(status_code=problem.status, detail=str(problem)) from None
    except GatewayError as error:
        logger.error(f"Subscription creation failed: {error}")
        raise HTTPException(status_code=502, detail=f"Subscription initiation failed: {error}") from None


class SubscriptionVerify(BaseModel):
    razorpay_payment_id: str
    razorpay_subscription_id: str
    razorpay_signature: str


@router.post("/subscriptions/verify", summary="Verify the first subscription payment and grant its credits")
async def verify_subscription(
    payload: SubscriptionVerify,
    current_user: User = Depends(billing_admin),
    db: AsyncSession = Depends(get_control_db),
):
    from src.billing.currency import minor_units
    from src.billing.subscriptions import record_charge

    gateway = await _gateway(db)
    # Razorpay signs payment_id|subscription_id for a subscription checkout.
    if not gateway.subscription_signature_valid(payload.razorpay_payment_id, payload.razorpay_subscription_id,
                                                payload.razorpay_signature):
        raise HTTPException(status_code=400, detail="Invalid payment signature")

    payments = PaymentService(db)
    sub = await payments.subscription_by_razorpay_id(
        payload.razorpay_subscription_id, current_user.company_id)
    if not sub:
        raise HTTPException(status_code=404, detail="Subscription not found")

    # The cycle this payment paid for ends at the gateway's current_end.
    cycle_end = None
    try:
        cycle_end = razorpay_time((await gateway.fetch_subscription(sub.razorpay_subscription_id)).get("current_end"))
    except GatewayError as e:
        logger.warning(f"Could not fetch subscription {sub.razorpay_subscription_id}: {e}")
    # What the first charge took: the gateway plan's amount (net + GST).
    from src.billing.billing_models import PlanGatewayPlan
    currency = sub.currency or "USD"
    gateway_plan = await db.get(PlanGatewayPlan, sub.gateway_plan_ref) if sub.gateway_plan_ref else None
    gross = (Decimal(gateway_plan.amount_minor) / (Decimal(10) ** await minor_units(db, currency))
             if gateway_plan else Decimal(str(sub.monthly_fee)))
    credited = await record_charge(db, sub, payment_id=payload.razorpay_payment_id, gross=gross, cycle_end=cycle_end)
    await db.refresh(sub)
    return {
        "message": f"Subscription activated on plan level {sub.plan_tier}" if credited
        else "Subscription payment already recorded",
        "plan_tier": sub.plan_tier,
        "monthly_fee": float(sub.monthly_fee),
        "bonus_credits_pct": float(sub.bonus_pct),
        "credits_granted": credited,
    }


@router.post("/subscriptions/change", summary="Change plan: upgrade now, downgrade at the cycle's end")
async def change_subscription(
    payload: SubscriptionChange,
    current_user: User = Depends(billing_admin),
    db: AsyncSession = Depends(get_control_db),
):
    from src.billing.locks import require_unlocked
    from src.billing.subscriptions import SubscriptionProblem, change_plan

    await require_unlocked(db, current_user.company_id, "plan", current_user)
    sub = await _live_subscription(db, current_user.company_id)
    if sub is None:
        raise HTTPException(status_code=404, detail="No subscription to change: subscribe to a plan")
    plan = await db.get(Plan, payload.plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="That plan is not on offer")
    gateway = await _gateway(db)
    try:
        return await change_plan(db, gateway, sub, plan)
    except SubscriptionProblem as problem:
        raise HTTPException(status_code=problem.status, detail=str(problem)) from None
    except GatewayError as error:
        raise HTTPException(status_code=502, detail=f"The plan could not be changed: {error}") from None


@router.delete("/subscriptions/{subscription_id}", summary="Cancel the subscription (at the cycle's end)")
async def cancel_subscription(
    subscription_id: UUID,
    immediately: bool = Query(False, description="End it now instead of at the end of the paid cycle"),
    current_user: User = Depends(billing_admin),
    db: AsyncSession = Depends(get_control_db),
):
    from src.billing.locks import require_unlocked
    from src.billing.subscriptions import cancel

    sub = (await db.execute(select(Subscription).where(
        Subscription.id == subscription_id, Subscription.company_id == current_user.company_id))).scalar_one_or_none()
    if not sub:
        raise HTTPException(status_code=404, detail="Subscription not found")
    await require_unlocked(db, current_user.company_id, "plan", current_user)   # Phase 15 T5-4
    gateway = None
    if sub.razorpay_subscription_id:
        gateway = await _gateway(db)
    try:
        # The mandate is stopped first: a cancelled row while the gateway kept
        # charging would take money for a subscription shown as cancelled.
        result = await cancel(db, gateway, sub, at_cycle_end=not immediately)
    except GatewayError as error:
        logger.error(f"Subscription cancellation failed: {error}")
        raise HTTPException(status_code=502, detail=(
            "The subscription could not be cancelled with the payment gateway; nothing was changed. "
            "Try again.")) from None
    return {"message": "Subscription cancelled" if result["status"] == "cancelled"
            else "The subscription ends at the end of the paid cycle", **result}
