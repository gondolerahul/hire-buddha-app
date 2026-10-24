"""
SQLAlchemy models for Billing Engine, Credit Wallets, Subscriptions, and Payments.
"""
import uuid
from datetime import datetime
from sqlalchemy import (
    CHAR, CheckConstraint, Column, String, Text, Integer, SmallInteger, Boolean, DateTime, Date,
    ForeignKey, Numeric, Index, UniqueConstraint, text
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship
from src.common.tenancy.bases import ControlBase, refers_to


class CostUnitRow(ControlBase):
    """A price's unit (Phase 15 T1-1): the table form of ``src.billing.units.UNITS``.

    Seeded by migration, never edited from the console; ``tests/integration/
    test_cost_units.py`` holds it equal to the enum. Registry rows name it by
    ``code`` (T1-2).
    """
    __tablename__ = "cost_units"
    __table_args__ = (CheckConstraint("per_quantity > 0", name="ck_cost_units_per_quantity"),)

    code = Column(Text, primary_key=True)
    dimension = Column(Text, nullable=False)
    per_quantity = Column(Numeric(24, 10), nullable=False)
    label = Column(Text, nullable=False)
    active = Column(Boolean, nullable=False, default=True, server_default=text("true"))


class BillingConfig(ControlBase):
    """
    Configurable billing formula parameters.
    TB = (c * mf) + (c * mf * pf) + (c * mf * spf) - (c * mf * d)
    company_id=NULL means global default; company-specific rows override the global.
    """
    __tablename__ = "billing_config"
    __table_args__ = (Index("idx_billing_config_company", "company_id"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=True)  # NULL = global default
    config_name = Column(String(100), nullable=False, default="default")

    multiplier_factor = Column(Numeric(10, 4), nullable=False, default=1.0)      # mf
    platform_fee_pct = Column(Numeric(10, 4), nullable=False, default=0.0)       # pf (percentage, e.g. 0.15 = 15%)
    sales_partner_fee_pct = Column(Numeric(10, 4), nullable=False, default=0.0)  # spf
    discount_pct = Column(Numeric(10, 4), nullable=False, default=0.0)           # d

    # Retired by the daily-credit policies (Phase 15 T5-5, control_0016): read by nothing.
    default_daily_credits = Column(Numeric(10, 4), nullable=False, default=0)

    # Base cost overrides
    base_cost_telephony = Column(Numeric(14, 6), nullable=True) 
    base_cost_llm = Column(Numeric(14, 6), nullable=True)
    base_cost_image_gen = Column(Numeric(14, 6), nullable=True)

    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    company = relationship("Company")


class CreditWallet(ControlBase):
    """
    A company's wallet (Phase 15 T4-1, tech design §6): its credit is the
    remaining amount of its live lots (``WalletLot``), in the company's billing
    currency; ``debt`` is what it owes; ``state`` gates new and running work
    (§6.3). Every change is an append-only ``WalletEntry``, made under this
    row's lock (``src.billing.wallet``).

    The four bucket columns below are the wallet before lots: read by nothing
    since the cutover migration (``control_0015_wallet_lots``) and dropped one
    release after (plan §4 step 10).
    """
    __tablename__ = "credit_wallets"
    __table_args__ = (
        Index("idx_credit_wallets_company", "company_id"),
        CheckConstraint("state IN ('ok', 'in_debt', 'over_tolerance', 'suspended')", name="ck_credit_wallets_state"),
        CheckConstraint("debt >= 0", name="ck_credit_wallets_debt"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False, unique=True)
    account_model = Column(String(30), nullable=False, default="pay_as_you_go")  # pay_as_you_go | subscription
    currency = Column(CHAR(3), ForeignKey("currencies.code"), nullable=False, default="INR", server_default="INR")
    state = Column(String(20), nullable=False, default="ok", server_default="ok")
    debt = Column(Numeric(24, 10), nullable=False, default=0, server_default="0")
    in_debt_since = Column(DateTime(timezone=True), nullable=True)
    over_tolerance_since = Column(DateTime(timezone=True), nullable=True)
    suspended_at = Column(DateTime(timezone=True), nullable=True)
    # Σ remaining of live lots, kept with every entry (W-8; the nightly check proves it).
    cached_available = Column(Numeric(24, 10), nullable=False, default=0, server_default="0")

    # Daily credits — injected daily per BillingConfig, expires at 00:00:00 next day (never carries forward)
    daily_credits = Column(Numeric(24, 10), nullable=False, default=0)
    daily_expires_at = Column(DateTime(timezone=True), nullable=True)

    # Wallet balance — topped up via Razorpay, 365-day validity
    wallet_balance = Column(Numeric(24, 10), nullable=False, default=0.0)
    wallet_expires_at = Column(DateTime(timezone=True), nullable=True)

    # Subscription credits — allocated monthly, strictly no carry-forward
    subscription_credits = Column(Numeric(24, 10), nullable=False, default=0.0)
    subscription_bonus_credits = Column(Numeric(24, 10), nullable=False, default=0.0)
    sub_credits_expire_at = Column(DateTime(timezone=True), nullable=True)

    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    company = relationship("Company")
    transactions = relationship(
        "PaymentTransaction",
        primaryjoin="CreditWallet.company_id == foreign(PaymentTransaction.company_id)",
        viewonly=True,
        overlaps="wallet",
    )


class SubscriptionTier(ControlBase):
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
    # The Razorpay plan subscriptions to this tier are created on; made on first
    # use and cleared when monthly_fee changes (Razorpay plans are immutable).
    razorpay_plan_id = Column(String(200), nullable=True)

    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class Subscription(ControlBase):
    """
    Subscription plan with Razorpay mandate for auto-debit billing.
    Tier bonus: Tier 1=20%, Tier 2=30%, Tier 3=40%
    """
    __tablename__ = "subscriptions"
    __table_args__ = (
        Index("idx_subscriptions_company", "company_id"),
        Index("idx_subscriptions_status", "status"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False)
    plan_tier = Column(Integer, nullable=False, default=1)           # 1, 2, or 3
    monthly_fee = Column(Numeric(10, 2), nullable=False)
    bonus_pct = Column(Numeric(5, 2), nullable=False, default=20.0)  # 20.0, 30.0, 40.0

    # pending_payment -> active <-> past_due | paused -> cancelled; failed = checkout abandoned
    status = Column(String(20), nullable=False, default="active")
    razorpay_subscription_id = Column(String(200), nullable=True)
    razorpay_plan_id = Column(String(200), nullable=True)
    next_billing_date = Column(DateTime(timezone=True), nullable=True)
    cancelled_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    company = relationship("Company")


class PaymentTransaction(ControlBase):
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
    credits_awarded = Column(Numeric(24, 10), nullable=True)
    transaction_metadata = Column(JSONB, nullable=True)

    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        # One transaction per Razorpay order and per payment, so a replayed
        # verification or webhook cannot credit a payment twice (BC-01).
        Index("uq_payment_transactions_razorpay_order", "razorpay_order_id", unique=True,
              postgresql_where=text("razorpay_order_id IS NOT NULL")),
        Index("uq_payment_transactions_razorpay_payment", "razorpay_payment_id", unique=True,
              postgresql_where=text("razorpay_payment_id IS NOT NULL")),
        Index("idx_payment_transactions_company", "company_id"),
    )

    company = relationship("Company", overlaps="transactions")
    wallet = relationship(
        "CreditWallet",
        primaryjoin="foreign(PaymentTransaction.company_id) == CreditWallet.company_id",
        viewonly=True,
        overlaps="transactions",
    )


BILLING_EVENT_UNIQUE_KEY = "uq_billing_events_period_grouping"


class BillingEvent(ControlBase):
    """
    Monthly aggregated billing records for costing and billing reports.
    Populated by cron job on the 1st of each month and on task completion.
    """
    __tablename__ = "billing_events"
    # One row per company, month and grouping; record_billing_event upserts on
    # it. NULL groupings count as equal (Postgres 15+), or two ungrouped rows
    # for the same month would both be allowed (DM-04).
    __table_args__ = (
        UniqueConstraint(
            "company_id", "period_month", "grouping_type", "grouping_value",
            name="uq_billing_events_period_grouping", postgresql_nulls_not_distinct=True,
        ),
        Index("idx_billing_events_company_month", "company_id", "period_month"),
        Index("idx_billing_events_grouping", "grouping_type", "grouping_value"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False)
    period_month = Column(Date, nullable=False)               # 1st of month

    # Grouping dimension
    grouping_type = Column(String(30), nullable=True)         # partner|tenant|user|process|agent
    grouping_value = Column(String(500), nullable=True)       # ID or name

    # TB formula breakdown
    base_cost = Column(Numeric(24, 10), nullable=False, default=0)
    multiplied_cost = Column(Numeric(24, 10), nullable=False, default=0)       # base_cost * mf
    platform_fee_amount = Column(Numeric(24, 10), nullable=False, default=0)
    partner_fee_amount = Column(Numeric(24, 10), nullable=False, default=0)
    discount_amount = Column(Numeric(24, 10), nullable=False, default=0)
    total_billing = Column(Numeric(24, 10), nullable=False, default=0)

    # Category breakdowns for final billing amount (user-facing)
    telephony_charge = Column(Numeric(24, 10), nullable=False, default=0)
    llm_charge = Column(Numeric(24, 10), nullable=False, default=0)
    image_charge = Column(Numeric(24, 10), nullable=False, default=0)
    video_charge = Column(Numeric(24, 10), nullable=False, default=0)
    api_charge = Column(Numeric(24, 10), nullable=False, default=0)

    # Usage breakdown
    # Billed seconds, exact (Phase 15 T1-4; were started minutes)
    telephony_in_seconds = Column(Numeric(24, 10), nullable=False, default=0)
    telephony_out_seconds = Column(Numeric(24, 10), nullable=False, default=0)
    image_gen_count = Column(Integer, nullable=False, default=0)
    video_gen_count = Column(Integer, nullable=False, default=0)
    other_ai_cost = Column(Numeric(24, 10), nullable=False, default=0)

    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    company = relationship("Company")


class CreditHold(ControlBase):
    """
    Credit reserved for a running top-level execution (BC-06).

    Placed when the run is admitted — the run's estimated bill, capped at what
    the wallet can spare — and released at settlement. What other runs of the
    company may start with, and when a running one is stopped, is the wallet
    minus the holds of the company's other unfinished runs. A hold is not a
    deduction: settlement still charges what the run actually cost.

    It is also the run's settlement record (Phase 14 WS2 2.6): ``settled_at``
    and ``billed_amount`` are set in the same control transaction as the
    wallet deduction and the billing event, and only while ``settled_at`` is
    empty — so settling a run again (a retried finalisation, a second worker)
    charges nothing. A run admitted without a hold gets a row at settlement.
    """
    __tablename__ = "credit_holds"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False)
    # The run is in its tenant's database (WS2 2.3): whatever deletes a run
    # deletes its hold.
    run_id = Column(UUID(as_uuid=True), nullable=False, unique=True,
                    info=refers_to("execution_runs.id", ondelete="CASCADE"))
    # Held, in the wallet's currency (Phase 15 T4-5; ``currency`` names it).
    amount = Column(Numeric(24, 10), nullable=False)
    currency = Column(CHAR(3), nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    released_at = Column(DateTime(timezone=True), nullable=True)
    settled_at = Column(DateTime(timezone=True), nullable=True)
    # What the settlement billed: USD, and in the wallet's currency.
    billed_amount = Column(Numeric(24, 10), nullable=True)
    billed_ccy = Column(Numeric(24, 10), nullable=True)

    __table_args__ = (
        Index("idx_credit_holds_open", "company_id",
              postgresql_where=text("released_at IS NULL")),
    )


# ─── Currency and geography (Phase 15 T2-1, tech design §3) ──────────────────

class Currency(ControlBase):
    """A billing currency: INR and USD, both through Razorpay (K-17)."""
    __tablename__ = "currencies"

    code = Column(CHAR(3), primary_key=True)
    name = Column(Text, nullable=False)
    symbol = Column(Text, nullable=False)
    minor_units = Column(SmallInteger, nullable=False)
    active = Column(Boolean, nullable=False, default=True, server_default=text("true"))
    gateway = Column(Text, nullable=True)


class FxRate(ControlBase):
    """Units of ``currency`` per USD from ``effective_from`` (FX-2). Append-only:
    a new rate is a new row; the current one is the latest already in effect."""
    __tablename__ = "fx_rates"
    __table_args__ = (
        CheckConstraint("units_per_usd > 0", name="ck_fx_rates_positive"),
        Index("ix_fx_rates_currency_from", "currency", "effective_from"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))
    currency = Column(CHAR(3), ForeignKey("currencies.code"), nullable=False)
    units_per_usd = Column(Numeric(24, 10), nullable=False)
    effective_from = Column(DateTime(timezone=True), nullable=False)
    created_by = Column(UUID(as_uuid=True), nullable=True)
    reason = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, server_default=text("now()"))


class CountryProfile(ControlBase):
    """A country's billing defaults: its currency (REQ-BL-1), time zone, phone code, tax regime."""
    __tablename__ = "country_profiles"
    __table_args__ = (
        CheckConstraint("tax_regime IN ('IN_GST', 'EXPORT', 'NONE')", name="ck_country_profiles_tax_regime"),
    )

    country_code = Column(CHAR(2), primary_key=True)
    name = Column(Text, nullable=False)
    billing_currency = Column(CHAR(3), ForeignKey("currencies.code"), nullable=False)
    default_timezone = Column(Text, nullable=False)
    phone_country_code = Column(Text, nullable=True)
    tax_regime = Column(Text, nullable=False)
    calling_rules = Column(JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, server_default=text("now()"))


class BillingFormula(ControlBase):
    """A version of the customer price formula (Phase 15 T3-2, tech design §8.1).

    ``TB = c·mf·(1 + pf − d)`` — ``spf`` is gone from the customer price (K-10).
    Append-only: a change is a new row from ``effective_from``. A company row
    overrides the platform row; a company row with ``active = false`` ends the
    override (the company is back on the platform's formula). ``plan`` scope
    is resolved once plans exist (T6-1).
    """
    __tablename__ = "billing_formulas"
    __table_args__ = (
        CheckConstraint("scope IN ('platform', 'plan', 'company')", name="ck_billing_formulas_scope"),
        CheckConstraint("mf > 0 AND mf <= 100", name="ck_billing_formulas_mf"),
        CheckConstraint("pf >= 0 AND pf <= 1 AND d >= 0 AND d <= 1", name="ck_billing_formulas_fractions"),
        Index("ix_billing_formulas_scope", "scope", "scope_id", "effective_from"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))
    scope = Column(Text, nullable=False)
    scope_id = Column(UUID(as_uuid=True), nullable=True)
    mf = Column(Numeric(24, 10), nullable=False)
    pf = Column(Numeric(24, 10), nullable=False)
    d = Column(Numeric(24, 10), nullable=False)
    active = Column(Boolean, nullable=False, default=True, server_default=text("true"))
    effective_from = Column(DateTime(timezone=True), nullable=False)
    created_by = Column(UUID(as_uuid=True), nullable=True)
    reason = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, server_default=text("now()"))


class BillingLine(ControlBase):
    """What a company was billed per day, category and grouping (Phase 15 T3-4, tech design §5.3).

    Upserted when usage is settled: the rows' cost, billed USD and billed amount
    in the company's currency at the rate locked for that settlement. It
    replaces ``billing_events`` for reporting (T3-8); monthly views roll up
    from it. ``grouping_id`` is the entity's (or agent's) id, not its name, so
    renaming an agent keeps one group.
    """
    __tablename__ = "billing_lines"
    __table_args__ = (
        UniqueConstraint("company_id", "period_day", "category", "grouping_type", "grouping_id", "currency",
                         name="uq_billing_lines_key", postgresql_nulls_not_distinct=True),
        Index("ix_billing_lines_company_day", "company_id", "period_day"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False)
    period_day = Column(Date, nullable=False)
    category = Column(String(30), nullable=False)
    grouping_type = Column(String(30), nullable=True)
    grouping_id = Column(UUID(as_uuid=True), nullable=True)
    currency = Column(CHAR(3), nullable=False)
    fx_rate_id = Column(UUID(as_uuid=True), nullable=True)
    cost_usd = Column(Numeric(24, 10), nullable=False, default=0)
    billed_usd = Column(Numeric(24, 10), nullable=False, default=0)
    billed_ccy = Column(Numeric(24, 10), nullable=False, default=0)
    quantity = Column(Numeric(24, 10), nullable=False, default=0)
    rows = Column(Integer, nullable=False, default=0)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, server_default=text("now()"))


class BillingShadowDiff(ControlBase):
    """One settled run or call priced both ways (Phase 15 T3-7): the old path's
    charge against the sum of its usage rows as rated at write. A non-zero
    ``diff_usd`` is a row the new path would bill differently — the shadow
    period explains every one before ``billing.v2_mode`` becomes ``on``."""
    __tablename__ = "billing_shadow_diffs"
    __table_args__ = (
        Index("ix_billing_shadow_diffs_company", "company_id", "created_at"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))
    company_id = Column(UUID(as_uuid=True), nullable=False)
    subject_type = Column(String(10), nullable=False)          # run | call
    subject_id = Column(UUID(as_uuid=True), nullable=True)     # the run (a call's run)
    v1_cost_usd = Column(Numeric(24, 10), nullable=False)
    v1_billed_usd = Column(Numeric(24, 10), nullable=False)
    v2_cost_usd = Column(Numeric(24, 10), nullable=False)
    v2_billed_usd = Column(Numeric(24, 10), nullable=False)
    diff_usd = Column(Numeric(24, 10), nullable=False)
    rows = Column(Integer, nullable=False, default=0)
    formula_ids = Column(JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb"))
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, server_default=text("now()"))


class WalletLot(ControlBase):
    """One grant of credit with its own expiry (Phase 15 T4-1, tech design §6.1, K-7).

    Spent in order (W-3): daily → subscription → subscription bonus → top-ups
    and grants by earliest ``expires_at``. ``paid`` lots are commissionable and
    repay debt first (W-7); daily credits and staff grants are not.
    """
    __tablename__ = "wallet_lots"
    __table_args__ = (
        CheckConstraint("kind IN ('daily', 'subscription', 'subscription_bonus', 'topup', 'grant')",
                        name="ck_wallet_lots_kind"),
        CheckConstraint("remaining >= 0 AND original >= 0", name="ck_wallet_lots_amounts"),
        Index("ix_wallet_lots_live", "company_id", "expires_at", postgresql_where=text("remaining > 0")),
        # One daily lot per company and local date (DC-6, control_0016).
        Index("uq_wallet_lots_daily_date", "company_id", "local_date", unique=True,
              postgresql_where=text("kind = 'daily' AND local_date IS NOT NULL")),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False)
    kind = Column(String(30), nullable=False)
    currency = Column(CHAR(3), nullable=False)
    original = Column(Numeric(24, 10), nullable=False)
    remaining = Column(Numeric(24, 10), nullable=False)
    granted_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, server_default=text("now()"))
    expires_at = Column(DateTime(timezone=True), nullable=True)
    paid = Column(Boolean, nullable=False, default=False, server_default=text("false"))
    source_type = Column(String(40), nullable=True)       # payment | subscription | daily_policy | staff | migration
    source_id = Column(Text, nullable=True)
    fx_rate_id = Column(UUID(as_uuid=True), nullable=True)
    policy_id = Column(UUID(as_uuid=True), nullable=True)  # the daily-credit policy that granted it
    local_date = Column(Date, nullable=True)              # a daily lot's day in the company's time zone


class WalletEntry(ControlBase):
    """An append-only line of the wallet's ledger (Phase 15 T4-1, W-9): every grant,
    deduction, expiry, debt change and adjustment, with the balance and debt after it."""
    __tablename__ = "wallet_entries"
    __table_args__ = (
        CheckConstraint("kind IN ('grant', 'deduct', 'expire', 'debt_add', 'debt_repay', 'adjust', 'refund', "
                        "'convert')", name="ck_wallet_entries_kind"),
        Index("ix_wallet_entries_company", "company_id", "created_at"),
        Index("ix_wallet_entries_source", "source_type", "source_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False)
    lot_id = Column(UUID(as_uuid=True), nullable=True)
    kind = Column(String(20), nullable=False)
    amount = Column(Numeric(24, 10), nullable=False)       # signed: + credit, − spent or expired
    currency = Column(CHAR(3), nullable=False)
    balance_after = Column(Numeric(24, 10), nullable=False)
    debt_after = Column(Numeric(24, 10), nullable=False)
    category = Column(String(30), nullable=True)            # a deduction's billing category
    reason = Column(Text, nullable=True)
    source_type = Column(String(40), nullable=True)         # settlement | payment | subscription | daily_policy | staff
    source_id = Column(Text, nullable=True)
    run_id = Column(UUID(as_uuid=True), nullable=True)      # W-2: what caused the spend
    user_id = Column(UUID(as_uuid=True), nullable=True)
    actor_id = Column(UUID(as_uuid=True), nullable=True)    # who did it (staff adjustments)
    fx_rate_id = Column(UUID(as_uuid=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, server_default=text("now()"))


class DailyCreditPolicy(ControlBase):
    """Who gets daily credits, for how long (Phase 15 T5-5, tech design §7.1).

    ``audience``: ``direct`` (tenants with no partner), ``partner`` (the
    tenants of ``partner_id``) or ``all_partners`` (tenants of a partner with
    no policy of its own). ``duration_days`` counts from the sign-up day (day
    1); NULL is no end (only the policies migrated from the old flat amount).
    """
    __tablename__ = "daily_credit_policies"
    __table_args__ = (
        CheckConstraint("audience IN ('direct', 'partner', 'all_partners')", name="ck_daily_credit_policies_audience"),
        CheckConstraint("(audience = 'partner') = (partner_id IS NOT NULL)", name="ck_daily_credit_policies_partner"),
        CheckConstraint("duration_days IS NULL OR duration_days IN (0, 10, 15, 30, 60, 90, 180, 365)",
                        name="ck_daily_credit_policies_duration"),
        Index("ix_daily_credit_policies_audience", "audience", "partner_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))
    name = Column(Text, nullable=False)
    audience = Column(String(20), nullable=False)
    partner_id = Column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=True)
    duration_days = Column(Integer, nullable=True)
    active = Column(Boolean, nullable=False, default=True, server_default=text("true"))
    effective_from = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow,
                            server_default=text("now()"))
    created_by = Column(UUID(as_uuid=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, server_default=text("now()"))


class DailyCreditBand(ControlBase):
    """A policy's amount for days ``from_day``…``to_day`` of a company's life (§7.1, DC-2)."""
    __tablename__ = "daily_credit_bands"
    __table_args__ = (
        CheckConstraint("from_day >= 1 AND to_day >= from_day", name="ck_daily_credit_bands_days"),
        CheckConstraint("amount_usd >= 0", name="ck_daily_credit_bands_amount"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))
    policy_id = Column(UUID(as_uuid=True), ForeignKey("daily_credit_policies.id", ondelete="CASCADE"),
                       nullable=False, index=True)
    from_day = Column(Integer, nullable=False)
    to_day = Column(Integer, nullable=False)
    amount_usd = Column(Numeric(24, 10), nullable=False)


class CompanyDailyCreditOverride(ControlBase):
    """One company's daily credits, whatever its policy (§7.2 step 1): ``none`` gives
    nothing; ``custom`` gives ``amount_usd`` a day for ``duration_days`` (NULL: no
    end) or until ``until``; ``policy`` follows the policies (the row records why)."""
    __tablename__ = "company_daily_credit_overrides"
    __table_args__ = (
        CheckConstraint("mode IN ('policy', 'custom', 'none')", name="ck_company_daily_credit_overrides_mode"),
        CheckConstraint("mode <> 'custom' OR amount_usd IS NOT NULL", name="ck_company_daily_credit_overrides_amount"),
    )

    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id"), primary_key=True)
    mode = Column(String(10), nullable=False)
    amount_usd = Column(Numeric(24, 10), nullable=True)
    duration_days = Column(Integer, nullable=True)
    until = Column(DateTime(timezone=True), nullable=True)
    reason = Column(Text, nullable=True)
    set_by = Column(UUID(as_uuid=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, server_default=text("now()"))


class PriceItem(ControlBase):
    """A fixed price (Phase 15 T5-3, tech design §8.3): not rated by the formula.

    ``amount_usd`` with per-currency overrides (``{"INR": 2000}``); an edit is a
    new ``version`` (``price_item_versions`` keeps each), applying from each
    recurring item's next charge.
    """
    __tablename__ = "price_items"
    __table_args__ = (
        CheckConstraint("kind IN ('recurring', 'one_time')", name="ck_price_items_kind"),
        CheckConstraint("interval IS NULL OR interval IN ('month', 'year')", name="ck_price_items_interval"),
        CheckConstraint("amount_usd >= 0", name="ck_price_items_amount"),
    )

    code = Column(Text, primary_key=True)
    name = Column(Text, nullable=False)
    kind = Column(String(20), nullable=False)
    interval = Column(String(10), nullable=True)
    amount_usd = Column(Numeric(24, 10), nullable=False)
    currency_overrides = Column(JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
    taxable = Column(Boolean, nullable=False, default=True, server_default=text("true"))
    active = Column(Boolean, nullable=False, default=True, server_default=text("true"))
    version = Column(Integer, nullable=False, default=1, server_default="1")
    updated_by = Column(UUID(as_uuid=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, server_default=text("now()"))


class PriceItemVersion(ControlBase):
    """Every version a price item has had (append-only; for audit and invoices)."""
    __tablename__ = "price_item_versions"
    __table_args__ = (UniqueConstraint("code", "version", name="uq_price_item_versions"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))
    code = Column(Text, ForeignKey("price_items.code"), nullable=False)
    version = Column(Integer, nullable=False)
    amount_usd = Column(Numeric(24, 10), nullable=False)
    currency_overrides = Column(JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
    active = Column(Boolean, nullable=False)
    reason = Column(Text, nullable=True)
    created_by = Column(UUID(as_uuid=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, server_default=text("now()"))


class CompanyLock(ControlBase):
    """A value of a company its tenant (or partner) may not change (Phase 15 T5-4, §8.5, Q5).

    A lock set by a partner blocks the tenant; one set by app_admin blocks the
    tenant and the partner.
    """
    __tablename__ = "company_locks"
    __table_args__ = (
        CheckConstraint("key IN ('spend_cap', 'plan')", name="ck_company_locks_key"),
        CheckConstraint("locked_by_role IN ('app_admin', 'partner')", name="ck_company_locks_role"),
    )

    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id"), primary_key=True)
    key = Column(String(20), primary_key=True)
    locked_by_role = Column(String(20), nullable=False)
    locked_by = Column(UUID(as_uuid=True), nullable=True)
    reason = Column(Text, nullable=True)
    at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, server_default=text("now()"))
