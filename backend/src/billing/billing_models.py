"""
SQLAlchemy models for Billing Engine, Credit Wallets, Subscriptions, and Payments.
"""
import uuid
from datetime import datetime
from sqlalchemy import (
    Column, String, Text, Integer, Boolean, DateTime, Date,
    ForeignKey, Numeric, JSON
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from src.common.database import Base


class BillingConfig(Base):
    """
    Configurable billing formula parameters.
    TB = (c * mf) + (c * mf * pf) + (c * mf * spf) - (c * mf * d)
    company_id=NULL means global default; company-specific rows override the global.
    """
    __tablename__ = "billing_config"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=True)  # NULL = global default
    config_name = Column(String(100), nullable=False, default="default")

    multiplier_factor = Column(Numeric(10, 4), nullable=False, default=1.0)      # mf
    platform_fee_pct = Column(Numeric(10, 4), nullable=False, default=0.0)       # pf (percentage, e.g. 0.15 = 15%)
    sales_partner_fee_pct = Column(Numeric(10, 4), nullable=False, default=0.0)  # spf
    discount_pct = Column(Numeric(10, 4), nullable=False, default=0.0)           # d

    default_daily_credits = Column(Numeric(10, 4), nullable=False, default=0)

    # Base cost overrides
    base_cost_telephony = Column(Numeric(14, 6), nullable=True) 
    base_cost_llm = Column(Numeric(14, 6), nullable=True)
    base_cost_image_gen = Column(Numeric(14, 6), nullable=True)

    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    company = relationship("Company")


class CreditWallet(Base):
    """
    Per-company credit buckets consumed in priority order.
    Priority: daily_credits → wallet_balance (PAYG) or subscription_credits (Subscription)
    """
    __tablename__ = "credit_wallets"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False, unique=True)
    account_model = Column(String(30), nullable=False, default="pay_as_you_go")  # pay_as_you_go | subscription

    # Daily credits — injected daily per BillingConfig, expires at 00:00:00 next day (never carries forward)
    daily_credits = Column(Numeric(10, 4), nullable=False, default=0)
    daily_expires_at = Column(DateTime, nullable=True)

    # Wallet balance — topped up via Razorpay, 365-day validity
    wallet_balance = Column(Numeric(12, 4), nullable=False, default=0.0)
    wallet_expires_at = Column(DateTime, nullable=True)

    # Subscription credits — allocated monthly, strictly no carry-forward
    subscription_credits = Column(Numeric(12, 4), nullable=False, default=0.0)
    subscription_bonus_credits = Column(Numeric(12, 4), nullable=False, default=0.0)
    sub_credits_expire_at = Column(DateTime, nullable=True)

    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    company = relationship("Company")
    transactions = relationship(
        "PaymentTransaction",
        primaryjoin="CreditWallet.company_id == foreign(PaymentTransaction.company_id)",
        viewonly=True,
        overlaps="wallet",
    )


class SubscriptionTier(Base):
    """
    App Admin configurable subscription tiers.
    """
    __tablename__ = "subscription_tiers"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(50), nullable=False)
    tier_level = Column(Integer, nullable=False, unique=True)
    monthly_fee = Column(Numeric(10, 2), nullable=False)
    bonus_pct = Column(Numeric(5, 2), nullable=False, default=0.0)
    is_active = Column(Boolean, default=True, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class Subscription(Base):
    """
    Subscription plan with Razorpay mandate for auto-debit billing.
    Tier bonus: Tier 1=20%, Tier 2=30%, Tier 3=40%
    """
    __tablename__ = "subscriptions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False)
    plan_tier = Column(Integer, nullable=False, default=1)           # 1, 2, or 3
    monthly_fee = Column(Numeric(10, 2), nullable=False)
    bonus_pct = Column(Numeric(5, 2), nullable=False, default=20.0)  # 20.0, 30.0, 40.0

    status = Column(String(20), nullable=False, default="active")    # active | cancelled | past_due
    razorpay_subscription_id = Column(String(200), nullable=True)
    razorpay_plan_id = Column(String(200), nullable=True)
    next_billing_date = Column(DateTime, nullable=True)
    cancelled_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    company = relationship("Company")


class PaymentTransaction(Base):
    """
    Records every Razorpay payment, both one-time top-ups and subscription charges.
    """
    __tablename__ = "payment_transactions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False)
    razorpay_order_id = Column(String(200), nullable=True)
    razorpay_payment_id = Column(String(200), nullable=True)
    razorpay_signature = Column(String(500), nullable=True)
    amount = Column(Numeric(10, 2), nullable=False)
    currency = Column(String(10), nullable=False, default="USD")
    transaction_type = Column(String(30), nullable=False)       # topup | subscription_charge
    status = Column(String(20), nullable=False, default="pending")  # pending | success | failed
    credits_awarded = Column(Numeric(12, 4), nullable=True)
    transaction_metadata = Column(JSON, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    company = relationship("Company", overlaps="transactions")
    wallet = relationship(
        "CreditWallet",
        primaryjoin="foreign(PaymentTransaction.company_id) == CreditWallet.company_id",
        viewonly=True,
        overlaps="transactions",
    )


class BillingEvent(Base):
    """
    Monthly aggregated billing records for costing and billing reports.
    Populated by cron job on the 1st of each month and on task completion.
    """
    __tablename__ = "billing_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False)
    period_month = Column(Date, nullable=False)               # 1st of month

    # Grouping dimension
    grouping_type = Column(String(30), nullable=True)         # partner|tenant|user|process|agent
    grouping_value = Column(String(500), nullable=True)       # ID or name

    # TB formula breakdown
    base_cost = Column(Numeric(14, 6), nullable=False, default=0)
    multiplied_cost = Column(Numeric(14, 6), nullable=False, default=0)       # base_cost * mf
    platform_fee_amount = Column(Numeric(14, 6), nullable=False, default=0)
    partner_fee_amount = Column(Numeric(14, 6), nullable=False, default=0)
    discount_amount = Column(Numeric(14, 6), nullable=False, default=0)
    total_billing = Column(Numeric(14, 6), nullable=False, default=0)

    # Category breakdowns for final billing amount (user-facing)
    telephony_charge = Column(Numeric(14, 6), nullable=False, default=0)
    llm_charge = Column(Numeric(14, 6), nullable=False, default=0)
    image_charge = Column(Numeric(14, 6), nullable=False, default=0)
    video_charge = Column(Numeric(14, 6), nullable=False, default=0)
    api_charge = Column(Numeric(14, 6), nullable=False, default=0)

    # Usage breakdown
    telephony_in_minutes = Column(Numeric(10, 2), nullable=False, default=0)
    telephony_out_minutes = Column(Numeric(10, 2), nullable=False, default=0)
    image_gen_count = Column(Integer, nullable=False, default=0)
    video_gen_count = Column(Integer, nullable=False, default=0)
    other_ai_cost = Column(Numeric(14, 6), nullable=False, default=0)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    company = relationship("Company")
