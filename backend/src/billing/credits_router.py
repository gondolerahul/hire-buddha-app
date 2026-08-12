"""
Credits Router — wallet balance, Razorpay top-up, and subscription management.
Razorpay credentials are fetched from integration_registry (service_sku='razorpay_keys').
"""
import hmac
import hashlib
import logging
from decimal import Decimal
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from src.common.database import get_db
from src.auth.router import get_current_user
from src.auth.models import User
from src.billing.credit_service import CreditService
from src.billing.billing_models import Subscription, PaymentTransaction, SubscriptionTier

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/credits", tags=["Credits & Payments"])


# ─── Helper: Get Razorpay credentials ─────────────────────────────────────────

async def _get_razorpay_creds(db: AsyncSession) -> Optional[dict]:
    """Fetch Razorpay key_id/key_secret from integration_registry."""
    try:
        from src.config.models import IntegrationRegistry
        stmt = select(IntegrationRegistry).where(
            IntegrationRegistry.service_sku == "razorpay_keys",
            IntegrationRegistry.status == "active",
        )
        result = await db.execute(stmt)
        entry = result.scalar_one_or_none()
        if entry and entry.service_metadata:
            return entry.service_metadata
        return None
    except Exception as e:
        logger.error(f"Failed to fetch Razorpay credentials: {e}")
        return None


# ─── Schemas ──────────────────────────────────────────────────────────────────

class TopUpRequest(BaseModel):
    amount: Decimal  # USD amount to top up (e.g., 10.00)


class TopUpVerify(BaseModel):
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str
    amount: Decimal


class SubscriptionCreate(BaseModel):
    tier_level: int   # 1, 2, 3, etc.


class SubscriptionTierCreate(BaseModel):
    name: str
    tier_level: int
    monthly_fee: Decimal
    bonus_pct: Decimal
    is_active: bool = True


class SubscriptionTierUpdate(BaseModel):
    name: Optional[str] = None
    monthly_fee: Optional[Decimal] = None
    bonus_pct: Optional[Decimal] = None
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

    # Verify Razorpay signature
    body = f"{payload.razorpay_order_id}|{payload.razorpay_payment_id}"
    expected_sig = hmac.new(
        creds["key_secret"].encode("utf-8"),
        body.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected_sig, payload.razorpay_signature):
        raise HTTPException(status_code=400, detail="Invalid payment signature")

    # Update transaction record
    result = await db.execute(
        select(PaymentTransaction).where(
            PaymentTransaction.razorpay_order_id == payload.razorpay_order_id,
            PaymentTransaction.company_id == current_user.company_id,
        )
    )
    txn = result.scalar_one_or_none()
    if txn:
        txn.razorpay_payment_id = payload.razorpay_payment_id
        txn.razorpay_signature = payload.razorpay_signature
        txn.status = "success"
        txn.credits_awarded = payload.amount

    # Credit the wallet
    credit_svc = CreditService(db)
    wallet = await credit_svc.add_wallet_credits(
        company_id=current_user.company_id,
        amount=payload.amount,
    )
    await db.commit()

    return {
        "message": "Payment verified and wallet credited",
        "message": "Payment verified and wallet credited",
        "credits_added": float(payload.amount),
        "new_balance": float(wallet.wallet_balance),
    }


# ─── Subscription Tiers ───────────────────────────────────────────────────────

@router.get("/subscription-tiers", summary="List available subscription tiers")
async def list_subscription_tiers(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(SubscriptionTier).where(SubscriptionTier.is_active == True).order_by(SubscriptionTier.tier_level)
    )
    tiers = result.scalars().all()
    return [
        {
            "id": str(t.id),
            "name": t.name,
            "tier_level": t.tier_level,
            "monthly_fee": float(t.monthly_fee),
            "bonus_pct": float(t.bonus_pct),
        }
        for t in tiers
    ]


@router.post("/subscription-tiers", summary="Create a subscription tier (Admin only)")
async def create_subscription_tier(
    payload: SubscriptionTierCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if current_user.role not in ("app_admin", "partner_admin"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

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
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if current_user.role not in ("app_admin", "partner_admin"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    result = await db.execute(select(SubscriptionTier).where(SubscriptionTier.id == tier_id))
    tier = result.scalar_one_or_none()
    if not tier:
        raise HTTPException(status_code=404, detail="Subscription tier not found")

    if payload.name is not None:
        tier.name = payload.name
    if payload.monthly_fee is not None:
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
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if current_user.role != "app_admin":
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    result = await db.execute(select(SubscriptionTier).where(SubscriptionTier.id == tier_id))
    tier = result.scalar_one_or_none()
    if not tier:
        raise HTTPException(status_code=404, detail="Subscription tier not found")

    await db.delete(tier)
    await db.commit()
    return {"message": "Tier deleted successfully"}


# ─── Subscriptions ────────────────────────────────────────────────────────────

@router.get("/subscriptions", summary="Get current subscription info")
async def get_subscription(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Subscription).where(
            Subscription.company_id == current_user.company_id,
            Subscription.status == "active",
        )
    )
    sub = result.scalar_one_or_none()
    if not sub:
        return {"subscription": None, "account_model": "pay_as_you_go"}

    return {
        "subscription": {
            "id": str(sub.id),
            "plan_tier": sub.plan_tier,
            "monthly_fee": float(sub.monthly_fee),
            "bonus_pct": float(sub.bonus_pct),
            "status": sub.status,
            "razorpay_subscription_id": sub.razorpay_subscription_id,
            "next_billing_date": sub.next_billing_date.isoformat() if sub.next_billing_date else None,
        },
        "account_model": "subscription",
    }


@router.post("/subscriptions", summary="Create subscription via Razorpay")
async def create_subscription(
    payload: SubscriptionCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Lookup the tier
    result = await db.execute(
        select(SubscriptionTier).where(
            SubscriptionTier.tier_level == payload.tier_level,
            SubscriptionTier.is_active == True,
        )
    )
    tier = result.scalar_one_or_none()
    if not tier:
        raise HTTPException(status_code=404, detail=f"Active subscription tier level {payload.tier_level} not found")

    creds = await _get_razorpay_creds(db)
    if not creds:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Payment gateway not configured. Add Razorpay keys to Integration Registry with SKU 'razorpay_keys'.",
        )

    try:
        import razorpay
        client = razorpay.Client(auth=(creds["key_id"], creds["key_secret"]))

        # Create a Razorpay order for the first month's subscription fee
        # Razorpay receipt must be ≤ 40 chars; use first 8 chars of company_id
        short_cid = str(current_user.company_id).replace("-", "")[:8]
        order_data = {
            "amount": int(tier.monthly_fee * 100),  # USD cents
            "currency": "USD",
            "receipt": f"sub_{short_cid}_t{tier.tier_level}",
            "notes": {
                "company_id": str(current_user.company_id),
                "type": "subscription",
                "plan_tier": str(tier.tier_level),
            },
        }
        order = client.order.create(data=order_data)
        logger.info(f"Razorpay order created for subscription tier {tier.tier_level}: {order['id']}")

        # Record pending subscription in DB — NOT active until payment verified
        sub = Subscription(
            company_id=current_user.company_id,
            plan_tier=tier.tier_level,
            monthly_fee=tier.monthly_fee,
            bonus_pct=tier.bonus_pct,
            status="pending_payment",
            razorpay_subscription_id=None,
        )
        db.add(sub)

        # Record the payment transaction
        txn = PaymentTransaction(
            company_id=current_user.company_id,
            razorpay_order_id=order["id"],
            amount=tier.monthly_fee,
            currency="USD",
            transaction_type="subscription_charge",
            status="pending",
        )
        db.add(txn)
        await db.commit()

        return {
            "order_id": order["id"],
            "amount": float(tier.monthly_fee),
            "currency": "USD",
            "key_id": creds["key_id"],
            "plan_tier": tier.tier_level,
            "bonus_credits_pct": float(tier.bonus_pct),
            "subscription_id": str(sub.id),
        }
    except ImportError:
        raise HTTPException(
            status_code=503,
            detail="razorpay package not installed. Run: pip install razorpay",
        )
    except Exception as e:
        logger.error(f"Razorpay subscription order creation failed: {e}")
        raise HTTPException(status_code=500, detail=f"Subscription initiation failed: {str(e)}")


class SubscriptionVerify(BaseModel):
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str
    subscription_id: str


@router.post("/subscriptions/verify", summary="Verify subscription payment and activate")
async def verify_subscription(
    payload: SubscriptionVerify,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    creds = await _get_razorpay_creds(db)
    if not creds:
        raise HTTPException(status_code=503, detail="Payment gateway not configured")

    # Verify Razorpay signature
    body = f"{payload.razorpay_order_id}|{payload.razorpay_payment_id}"
    expected_sig = hmac.new(
        creds["key_secret"].encode("utf-8"),
        body.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected_sig, payload.razorpay_signature):
        raise HTTPException(status_code=400, detail="Invalid payment signature")

    # Update payment transaction
    result = await db.execute(
        select(PaymentTransaction).where(
            PaymentTransaction.razorpay_order_id == payload.razorpay_order_id,
            PaymentTransaction.company_id == current_user.company_id,
        )
    )
    txn = result.scalar_one_or_none()
    if txn:
        txn.razorpay_payment_id = payload.razorpay_payment_id
        txn.razorpay_signature = payload.razorpay_signature
        txn.status = "success"

    # Activate the subscription
    result = await db.execute(
        select(Subscription).where(
            Subscription.id == UUID(payload.subscription_id),
            Subscription.company_id == current_user.company_id,
        )
    )
    sub = result.scalar_one_or_none()
    if not sub:
        raise HTTPException(status_code=404, detail="Subscription not found")

    sub.status = "active"

    # Update wallet account model to subscription
    credit_svc = CreditService(db)
    wallet = await credit_svc.get_or_create_wallet(current_user.company_id)
    wallet.account_model = "subscription"

    await db.commit()

    return {
        "message": f"Subscription activated for Tier {sub.plan_tier}",
        "plan_tier": sub.plan_tier,
        "monthly_fee": float(sub.monthly_fee),
        "bonus_credits_pct": float(sub.bonus_pct),
    }


@router.delete("/subscriptions/{subscription_id}", summary="Cancel subscription")
async def cancel_subscription(
    subscription_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from datetime import datetime
    result = await db.execute(
        select(Subscription).where(
            Subscription.id == subscription_id,
            Subscription.company_id == current_user.company_id,
        )
    )
    sub = result.scalar_one_or_none()
    if not sub:
        raise HTTPException(status_code=404, detail="Subscription not found")

    sub.status = "cancelled"
    sub.cancelled_at = datetime.utcnow()
    sub.updated_at = datetime.utcnow()

    # Revert wallet to PAYG
    credit_svc = CreditService(db)
    wallet = await credit_svc.get_or_create_wallet(current_user.company_id)
    wallet.account_model = "pay_as_you_go"

    await db.commit()
    return {"message": "Subscription cancelled successfully"}
