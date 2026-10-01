"""
Credits Router — wallet balance, Razorpay top-up, and subscription management.
Razorpay credentials are fetched from integration_registry (service_sku='razorpay_keys').
"""
import logging
from decimal import Decimal
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from src.common.database import get_db
from src.auth.router import get_current_user
from src.auth.dependencies import RoleChecker
from src.auth.models import User
from src.billing.credit_service import CreditService
from src.billing.payment_service import (
    LIVE_SUBSCRIPTION_STATUSES, PaymentNotFound, PaymentService, razorpay_signature_valid, razorpay_time,
)
from src.billing.razorpay_gateway import get_razorpay_creds, razorpay_client
from src.billing.billing_models import Subscription, PaymentTransaction, SubscriptionTier

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/credits", tags=["Credits & Payments"])


# ─── Helper: Get Razorpay credentials ─────────────────────────────────────────

async def _get_razorpay_creds(db: AsyncSession) -> Optional[dict]:
    """Fetch Razorpay key_id/key_secret from integration_registry."""
    return await get_razorpay_creds(db)


# ─── Schemas ──────────────────────────────────────────────────────────────────

class TopUpRequest(BaseModel):
    amount: Decimal  # USD amount to top up (e.g., 10.00)


class TopUpVerify(BaseModel):
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str


class SubscriptionCreate(BaseModel):
    tier_level: int   # 1, 2, 3, etc.


# Tiers are platform-wide, so only app_admin writes them (BC-19; partner_admin
# could). bonus_pct is a percentage — 30 is 30% — unlike the billing config's
# fractions.
app_admin_only = RoleChecker(["app_admin"])


class SubscriptionTierCreate(BaseModel):
    name: str
    tier_level: int = Field(ge=1)
    monthly_fee: Decimal = Field(gt=0)
    bonus_pct: Decimal = Field(ge=0, le=100)
    is_active: bool = True


class SubscriptionTierUpdate(BaseModel):
    name: Optional[str] = None
    monthly_fee: Optional[Decimal] = Field(None, gt=0)
    bonus_pct: Optional[Decimal] = Field(None, ge=0, le=100)
    is_active: Optional[bool] = None


# ─── Balance ──────────────────────────────────────────────────────────────────

@router.get("/balance", summary="Get credit wallet balance")
async def get_balance(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    svc = CreditService(db)
    return await svc.get_balance(current_user.company_id)


# ─── Wallet Top-Up ────────────────────────────────────────────────────────────

@router.post("/topup", summary="Initiate Razorpay order for wallet top-up")
async def initiate_topup(
    payload: TopUpRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    creds = await _get_razorpay_creds(db)
    if not creds:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Payment gateway not configured. Add Razorpay keys to Integration Registry with SKU 'razorpay_keys'.",
        )

    try:
        import razorpay
        client = razorpay.Client(auth=(creds["key_id"], creds["key_secret"]))
        # Razorpay receipt must be ≤ 40 chars; use first 8 chars of company_id
        short_cid = str(current_user.company_id).replace("-", "")[:8]
        order_data = {
            "amount": int(payload.amount * 100),  # USD cents (e.g. $10 = 1000 cents)
            "currency": "USD",
            "receipt": f"topup_{short_cid}",
            "notes": {"company_id": str(current_user.company_id), "type": "topup"},
        }
        order = client.order.create(data=order_data)

        # Record pending transaction
        txn = PaymentTransaction(
            company_id=current_user.company_id,
            razorpay_order_id=order["id"],
            amount=payload.amount,
            currency="USD",
            transaction_type="topup",
            status="pending",
        )
        db.add(txn)
        await db.commit()

        return {
            "order_id": order["id"],
            "amount": payload.amount,
            "currency": "USD",
            "key_id": creds["key_id"],  # Sent to frontend for Razorpay.js
        }
    except ImportError:
        raise HTTPException(
            status_code=503,
            detail="razorpay package not installed. Run: pip install razorpay",
        )
    except Exception as e:
        logger.error(f"Razorpay order creation failed: {e}")
        raise HTTPException(status_code=500, detail=f"Payment initiation failed: {str(e)}")


@router.post("/topup/verify", summary="Verify Razorpay payment and credit wallet")
async def verify_topup(
    payload: TopUpVerify,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    creds = await _get_razorpay_creds(db)
    if not creds:
        raise HTTPException(status_code=503, detail="Payment gateway not configured")

    # Razorpay signs order_id|payment_id: proof this payment paid this order.
    body = f"{payload.razorpay_order_id}|{payload.razorpay_payment_id}"
    if not razorpay_signature_valid(creds["key_secret"], body, payload.razorpay_signature):
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
        "credits_added": float(txn.amount) if credited else 0.0,
        "new_balance": float(wallet.wallet_balance),
    }


# ─── Subscription Tiers ───────────────────────────────────────────────────────

@router.get("/subscription-tiers", summary="List available subscription tiers")
async def list_subscription_tiers(
    include_inactive: bool = Query(False, description="app_admin only: archived tiers too"),
    current_user: User = Depends(get_current_user),  # BC-20: was open to anyone
    db: AsyncSession = Depends(get_db),
):
    # The Billing Settings page manages archived tiers too (BC-30); everyone
    # else sees the plans on offer.
    stmt = select(SubscriptionTier).order_by(SubscriptionTier.tier_level)
    if not (include_inactive and current_user.role == "app_admin"):
        stmt = stmt.where(SubscriptionTier.is_active == True)
    tiers = (await db.execute(stmt)).scalars().all()
    return [
        {
            "id": str(t.id),
            "name": t.name,
            "tier_level": t.tier_level,
            "monthly_fee": float(t.monthly_fee),
            "bonus_pct": float(t.bonus_pct),
            "is_active": t.is_active,
        }
        for t in tiers
    ]


@router.post("/subscription-tiers", summary="Create a subscription tier (Admin only)")
async def create_subscription_tier(
    payload: SubscriptionTierCreate,
    current_user: User = Depends(app_admin_only),
    db: AsyncSession = Depends(get_db),
):

    tier = SubscriptionTier(
        name=payload.name,
        tier_level=payload.tier_level,
        monthly_fee=payload.monthly_fee,
        bonus_pct=payload.bonus_pct,
        is_active=payload.is_active,
    )
    db.add(tier)
    try:
        await db.commit()
        await db.refresh(tier)
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=400, detail="Failed to create tier (check for duplicate tier_level)")

    return {"id": str(tier.id), "message": "Tier created successfully"}


@router.put("/subscription-tiers/{tier_id}", summary="Update a subscription tier (Admin only)")
async def update_subscription_tier(
    tier_id: UUID,
    payload: SubscriptionTierUpdate,
    current_user: User = Depends(app_admin_only),
    db: AsyncSession = Depends(get_db),
):

    result = await db.execute(select(SubscriptionTier).where(SubscriptionTier.id == tier_id))
    tier = result.scalar_one_or_none()
    if not tier:
        raise HTTPException(status_code=404, detail="Subscription tier not found")

    if payload.name is not None:
        tier.name = payload.name
    if payload.monthly_fee is not None:
        if Decimal(str(tier.monthly_fee)) != payload.monthly_fee:
            tier.razorpay_plan_id = None  # new subscribers get a plan at the new fee
        tier.monthly_fee = payload.monthly_fee
    if payload.bonus_pct is not None:
        tier.bonus_pct = payload.bonus_pct
    if payload.is_active is not None:
        tier.is_active = payload.is_active

    await db.commit()
    await db.refresh(tier)
    return {"id": str(tier.id), "message": "Tier updated successfully"}


@router.delete("/subscription-tiers/{tier_id}", summary="Delete a subscription tier (Admin only)")
async def delete_subscription_tier(
    tier_id: UUID,
    current_user: User = Depends(app_admin_only),
    db: AsyncSession = Depends(get_db),
):

    result = await db.execute(select(SubscriptionTier).where(SubscriptionTier.id == tier_id))
    tier = result.scalar_one_or_none()
    if not tier:
        raise HTTPException(status_code=404, detail="Subscription tier not found")

    await db.delete(tier)
    await db.commit()
    return {"message": "Tier deleted successfully"}


# ─── Subscriptions ────────────────────────────────────────────────────────────
#
# A subscription is a Razorpay Subscription on a plan made from the tier: the
# customer authorises a recurring mandate once, Razorpay charges every month,
# and each charge grants that cycle's credits — through the checkout callback
# for the first charge and the ``subscription.charged`` webhook (or the
# reconciliation job) for every one. Nothing grants credits without a payment
# (BC-03, BC-04, BC-16).

# Razorpay needs a finite number of cycles; ten years of monthly charges.
SUBSCRIPTION_TOTAL_COUNT = 120


def _subscription_to_dict(sub: Subscription) -> dict:
    return {
        "id": str(sub.id),
        "plan_tier": sub.plan_tier,
        "monthly_fee": float(sub.monthly_fee),
        "bonus_pct": float(sub.bonus_pct),
        "status": sub.status,
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


def _razorpay_client_or_503(creds: Optional[dict]):
    client = razorpay_client(creds)
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Payment gateway not configured. Add Razorpay keys to Integration Registry with SKU 'razorpay_keys'.",
        )
    return client


async def _plan_for_tier(db: AsyncSession, client, tier: SubscriptionTier) -> str:
    """The tier's Razorpay plan, created on first use. Razorpay plans are
    immutable, so changing a tier's fee clears it and the next subscriber
    gets a new plan; existing subscribers keep theirs."""
    if tier.razorpay_plan_id:
        return tier.razorpay_plan_id
    plan = client.plan.create(data={
        "period": "monthly",
        "interval": 1,
        "item": {
            "name": f"HireBuddha {tier.name}",
            "amount": int(Decimal(str(tier.monthly_fee)) * 100),  # USD cents
            "currency": "USD",
            "description": f"Tier {tier.tier_level}, {tier.bonus_pct}% bonus credits",
        },
        "notes": {"tier_level": str(tier.tier_level)},
    })
    tier.razorpay_plan_id = plan["id"]
    await db.commit()
    return tier.razorpay_plan_id


@router.get("/subscriptions", summary="Get current subscription info")
async def get_subscription(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    sub = await _live_subscription(db, current_user.company_id)
    if not sub:
        return {"subscription": None, "account_model": "pay_as_you_go"}
    return {"subscription": _subscription_to_dict(sub), "account_model": "subscription"}


@router.post("/subscriptions", summary="Create a Razorpay subscription for a tier")
async def create_subscription(
    payload: SubscriptionCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(SubscriptionTier).where(
            SubscriptionTier.tier_level == payload.tier_level,
            SubscriptionTier.is_active == True,
        )
    )
    tier = result.scalar_one_or_none()
    if not tier:
        raise HTTPException(status_code=404, detail=f"Active subscription tier level {payload.tier_level} not found")

    live = await _live_subscription(db, current_user.company_id)
    if live:
        raise HTTPException(
            status_code=409,
            detail=f"This company already has a {live.status} subscription (Tier {live.plan_tier}). Cancel it first.",
        )

    creds = await _get_razorpay_creds(db)
    client = _razorpay_client_or_503(creds)
    try:
        plan_id = await _plan_for_tier(db, client, tier)
        rz_sub = client.subscription.create(data={
            "plan_id": plan_id,
            "total_count": SUBSCRIPTION_TOTAL_COUNT,
            "customer_notify": 1,
            "notes": {"company_id": str(current_user.company_id), "tier_level": str(tier.tier_level)},
        })
    except Exception as e:
        logger.error(f"Razorpay subscription creation failed: {e}")
        raise HTTPException(status_code=502, detail=f"Subscription initiation failed: {e}")

    # Pending until the first charge is verified (callback or webhook).
    sub = Subscription(
        company_id=current_user.company_id,
        plan_tier=tier.tier_level,
        monthly_fee=tier.monthly_fee,
        bonus_pct=tier.bonus_pct,
        status="pending_payment",
        razorpay_subscription_id=rz_sub["id"],
        razorpay_plan_id=plan_id,
    )
    db.add(sub)
    await db.commit()

    return {
        "razorpay_subscription_id": rz_sub["id"],
        "amount": float(tier.monthly_fee),
        "currency": "USD",
        "key_id": creds["key_id"],
        "plan_tier": tier.tier_level,
        "bonus_credits_pct": float(tier.bonus_pct),
        "subscription_id": str(sub.id),
    }


class SubscriptionVerify(BaseModel):
    razorpay_payment_id: str
    razorpay_subscription_id: str
    razorpay_signature: str


@router.post("/subscriptions/verify", summary="Verify the first subscription payment and grant its credits")
async def verify_subscription(
    payload: SubscriptionVerify,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    creds = await _get_razorpay_creds(db)
    if not creds:
        raise HTTPException(status_code=503, detail="Payment gateway not configured")

    # Razorpay signs payment_id|subscription_id for a subscription checkout.
    body = f"{payload.razorpay_payment_id}|{payload.razorpay_subscription_id}"
    if not razorpay_signature_valid(creds["key_secret"], body, payload.razorpay_signature):
        raise HTTPException(status_code=400, detail="Invalid payment signature")

    payments = PaymentService(db)
    sub = await payments.subscription_by_razorpay_id(
        payload.razorpay_subscription_id, current_user.company_id)
    if not sub:
        raise HTTPException(status_code=404, detail="Subscription not found")

    # The cycle this payment paid for ends at Razorpay's current_end.
    cycle_end = None
    client = razorpay_client(creds)
    if client is not None:
        try:
            cycle_end = razorpay_time(client.subscription.fetch(sub.razorpay_subscription_id).get("current_end"))
        except Exception as e:
            logger.warning(f"Could not fetch Razorpay subscription {sub.razorpay_subscription_id}: {e}")

    credited = await payments.record_subscription_charge(
        sub, payment_id=payload.razorpay_payment_id,
        amount=Decimal(str(sub.monthly_fee)), cycle_end=cycle_end,
    )
    await db.refresh(sub)
    return {
        "message": f"Subscription activated for Tier {sub.plan_tier}" if credited
        else "Subscription payment already recorded",
        "plan_tier": sub.plan_tier,
        "monthly_fee": float(sub.monthly_fee),
        "bonus_credits_pct": float(sub.bonus_pct),
        "credits_granted": credited,
    }


@router.delete("/subscriptions/{subscription_id}", summary="Cancel subscription")
async def cancel_subscription(
    subscription_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Subscription).where(
            Subscription.id == subscription_id,
            Subscription.company_id == current_user.company_id,
        )
    )
    sub = result.scalar_one_or_none()
    if not sub:
        raise HTTPException(status_code=404, detail="Subscription not found")

    # Stop the mandate first: marking the row cancelled while Razorpay kept
    # charging would take money for a subscription we show as cancelled.
    if sub.razorpay_subscription_id:
        client = _razorpay_client_or_503(await _get_razorpay_creds(db))
        try:
            client.subscription.cancel(sub.razorpay_subscription_id, {"cancel_at_cycle_end": 0})
        except Exception as e:
            try:
                rz_status = client.subscription.fetch(sub.razorpay_subscription_id).get("status")
            except Exception:
                rz_status = None
            if rz_status not in ("cancelled", "completed", "expired"):
                logger.error(f"Razorpay cancel failed for {sub.razorpay_subscription_id}: {e}")
                raise HTTPException(status_code=502, detail=f"Could not cancel with Razorpay: {e}")

    await PaymentService(db).set_subscription_status(sub, "cancelled")
    return {"message": "Subscription cancelled. Credits already paid for last until they expire."}
