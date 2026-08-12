"""add_assets_billing_credits

Revision ID: g1h2i3j4k5l6
Revises: e1a2b3c4d5e6, b2c3d4e5f6a7
Create Date: 2026-02-23 16:17:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'g1h2i3j4k5l6'
down_revision: Union[str, Sequence[str], None] = ('e1a2b3c4d5e6', 'b2c3d4e5f6a7')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add assets, call intelligence, billing, credit, and payment tables."""

    # =========================================================================
    # 1. ASSETS TABLE
    # Stores metadata and file paths for all system-generated media
    # Path convention: assets/{tenant_id}/{campaign_id}/{asset_type}/{YYYY-MM-DD}/{file_name}
    # =========================================================================
    op.create_table(
        'assets',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('company_id', sa.UUID(), nullable=False),
        sa.Column('campaign_id', sa.UUID(), nullable=True),   # FK to hierarchical_entities (campaign/process)
        sa.Column('agent_id', sa.UUID(), nullable=True),      # FK to hierarchical_entities (agent)
        sa.Column('run_id', sa.UUID(), nullable=True),         # FK to execution_runs
        sa.Column('file_type', sa.String(20), nullable=False), # recordings | images | videos
        sa.Column('file_name', sa.String(500), nullable=False),
        sa.Column('file_path', sa.Text(), nullable=False),     # Full relative path
        sa.Column('file_size', sa.BigInteger(), nullable=True),  # bytes
        sa.Column('duration_seconds', sa.Integer(), nullable=True), # For audio/video
        sa.Column('mime_type', sa.String(100), nullable=True),
        sa.Column('asset_metadata', sa.JSON(), nullable=True),  # Extra info (e.g., image dimensions, call SID)
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id']),
        sa.ForeignKeyConstraint(['campaign_id'], ['hierarchical_entities.id']),
        sa.ForeignKeyConstraint(['agent_id'], ['hierarchical_entities.id']),
        sa.ForeignKeyConstraint(['run_id'], ['execution_runs.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_assets_company', 'assets', ['company_id'])
    op.create_index('idx_assets_campaign', 'assets', ['campaign_id'])
    op.create_index('idx_assets_agent', 'assets', ['agent_id'])
    op.create_index('idx_assets_file_type', 'assets', ['file_type'])
    op.create_index('idx_assets_created_at', 'assets', ['created_at'])

    # =========================================================================
    # 2. CALL LOGS TABLE
    # Telephony call metadata (complements voice_sessions)
    # =========================================================================
    op.create_table(
        'call_logs',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('company_id', sa.UUID(), nullable=False),
        sa.Column('voice_session_id', sa.UUID(), nullable=True),  # FK voice_sessions.id
        sa.Column('agent_id', sa.UUID(), nullable=True),
        sa.Column('direction', sa.String(20), nullable=True),     # inbound | outbound
        sa.Column('status', sa.String(30), nullable=True),        # completed | failed | no-answer
        sa.Column('duration_seconds', sa.Integer(), nullable=True),
        sa.Column('from_number', sa.String(30), nullable=True),
        sa.Column('to_number', sa.String(30), nullable=True),
        sa.Column('provider', sa.String(30), nullable=True),       # twilio | tata_tele
        sa.Column('call_cost_usd', sa.Numeric(10, 6), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id']),
        sa.ForeignKeyConstraint(['agent_id'], ['hierarchical_entities.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_call_logs_company', 'call_logs', ['company_id'])
    op.create_index('idx_call_logs_agent', 'call_logs', ['agent_id'])
    op.create_index('idx_call_logs_created_at', 'call_logs', ['created_at'])

    # =========================================================================
    # 3. CALL CONTENT TABLE
    # Transcript and summary linked to call_logs and audio asset
    # =========================================================================
    op.create_table(
        'call_content',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('call_log_id', sa.UUID(), nullable=False),
        sa.Column('audio_asset_id', sa.UUID(), nullable=True),   # FK to assets.id
        sa.Column('transcript_text', sa.Text(), nullable=True),
        sa.Column('summary_text', sa.Text(), nullable=True),
        sa.Column('sentiment', sa.String(20), nullable=True),     # positive | neutral | negative
        sa.Column('content_metadata', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['call_log_id'], ['call_logs.id']),
        sa.ForeignKeyConstraint(['audio_asset_id'], ['assets.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_call_content_call_log', 'call_content', ['call_log_id'])

    # =========================================================================
    # 4. BILLING CONFIG TABLE
    # Configurable billing formula parameters per company/globally
    # TB = (c * mf) + (c * mf * pf) + (c * mf * spf) - (c * mf * d)
    # =========================================================================
    op.create_table(
        'billing_config',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('company_id', sa.UUID(), nullable=True),         # NULL = global default
        sa.Column('config_name', sa.String(100), nullable=False, server_default='default'),
        sa.Column('multiplier_factor', sa.Numeric(10, 4), nullable=False, server_default='1.0'),
        sa.Column('platform_fee_pct', sa.Numeric(10, 4), nullable=False, server_default='0.0'),
        sa.Column('sales_partner_fee_pct', sa.Numeric(10, 4), nullable=False, server_default='0.0'),
        sa.Column('discount_pct', sa.Numeric(10, 4), nullable=False, server_default='0.0'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_billing_config_company', 'billing_config', ['company_id'])

    # Seed global default billing config
    op.execute("""
        INSERT INTO billing_config (id, company_id, config_name, multiplier_factor, platform_fee_pct, sales_partner_fee_pct, discount_pct, is_active, created_at, updated_at)
        VALUES (gen_random_uuid(), NULL, 'global_default', 1.3, 0.15, 0.10, 0.0, true, now(), now())
    """)

    # =========================================================================
    # 5. CREDIT WALLETS TABLE
    # Per-company credit buckets, consumed in priority order
    # Order: daily_credits → wallet_balance (PAYG) or subscription_credits (Sub)
    # =========================================================================
    op.create_table(
        'credit_wallets',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('company_id', sa.UUID(), nullable=False, unique=True),
        sa.Column('account_model', sa.String(30), nullable=False, server_default='pay_as_you_go'),  # pay_as_you_go | subscription
        # Daily credits — $5 injected daily, expires at 00:00 next day
        sa.Column('daily_credits', sa.Numeric(10, 4), nullable=False, server_default='5.0'),
        sa.Column('daily_expires_at', sa.DateTime(), nullable=True),
        # Wallet balance — topped up via Razorpay, 365-day validity (PAYG)
        sa.Column('wallet_balance', sa.Numeric(12, 4), nullable=False, server_default='0.0'),
        sa.Column('wallet_expires_at', sa.DateTime(), nullable=True),
        # Subscription tier credits (monthly, no carry forward)
        sa.Column('subscription_credits', sa.Numeric(12, 4), nullable=False, server_default='0.0'),
        sa.Column('subscription_bonus_credits', sa.Numeric(12, 4), nullable=False, server_default='0.0'),
        sa.Column('sub_credits_expire_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_credit_wallets_company', 'credit_wallets', ['company_id'])

    # =========================================================================
    # 6. SUBSCRIPTIONS TABLE
    # Subscription plan tracking with Razorpay mandate
    # =========================================================================
    op.create_table(
        'subscriptions',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('company_id', sa.UUID(), nullable=False),
        sa.Column('plan_tier', sa.Integer(), nullable=False, server_default='1'),  # 1, 2, 3
        sa.Column('monthly_fee', sa.Numeric(10, 2), nullable=False),
        sa.Column('bonus_pct', sa.Numeric(5, 2), nullable=False, server_default='20.0'), # 20, 30, 40
        sa.Column('status', sa.String(20), nullable=False, server_default='active'),     # active | cancelled | past_due
        sa.Column('razorpay_subscription_id', sa.String(200), nullable=True),
        sa.Column('razorpay_plan_id', sa.String(200), nullable=True),
        sa.Column('next_billing_date', sa.DateTime(), nullable=True),
        sa.Column('cancelled_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_subscriptions_company', 'subscriptions', ['company_id'])
    op.create_index('idx_subscriptions_status', 'subscriptions', ['status'])

    # =========================================================================
    # 7. PAYMENT TRANSACTIONS TABLE
    # Razorpay payment records (top-ups and subscription charges)
    # =========================================================================
    op.create_table(
        'payment_transactions',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('company_id', sa.UUID(), nullable=False),
        sa.Column('razorpay_order_id', sa.String(200), nullable=True),
        sa.Column('razorpay_payment_id', sa.String(200), nullable=True),
        sa.Column('razorpay_signature', sa.String(500), nullable=True),
        sa.Column('amount', sa.Numeric(10, 2), nullable=False),
        sa.Column('currency', sa.String(10), nullable=False, server_default='USD'),
        sa.Column('transaction_type', sa.String(30), nullable=False),  # topup | subscription_charge
        sa.Column('status', sa.String(20), nullable=False, server_default='pending'),  # pending | success | failed
        sa.Column('credits_awarded', sa.Numeric(12, 4), nullable=True),
        sa.Column('transaction_metadata', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_payment_transactions_company', 'payment_transactions', ['company_id'])
    op.create_index('idx_payment_transactions_razorpay_order', 'payment_transactions', ['razorpay_order_id'])

    # =========================================================================
    # 8. BILLING EVENTS TABLE
    # Monthly aggregated billing records for reporting
    # =========================================================================
    op.create_table(
        'billing_events',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('company_id', sa.UUID(), nullable=False),
        sa.Column('period_month', sa.Date(), nullable=False),           # 1st of month
        sa.Column('grouping_type', sa.String(30), nullable=True),       # partner|tenant|user|process|agent
        sa.Column('grouping_value', sa.String(500), nullable=True),     # ID or name of the group
        # Billing formula inputs
        sa.Column('base_cost', sa.Numeric(14, 6), nullable=False, server_default='0'),
        sa.Column('multiplied_cost', sa.Numeric(14, 6), nullable=False, server_default='0'),
        sa.Column('platform_fee_amount', sa.Numeric(14, 6), nullable=False, server_default='0'),
        sa.Column('partner_fee_amount', sa.Numeric(14, 6), nullable=False, server_default='0'),
        sa.Column('discount_amount', sa.Numeric(14, 6), nullable=False, server_default='0'),
        sa.Column('total_billing', sa.Numeric(14, 6), nullable=False, server_default='0'),
        # Breakdown
        sa.Column('telephony_in_minutes', sa.Numeric(10, 2), nullable=False, server_default='0'),
        sa.Column('telephony_out_minutes', sa.Numeric(10, 2), nullable=False, server_default='0'),
        sa.Column('image_gen_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('video_gen_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('other_ai_cost', sa.Numeric(14, 6), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_billing_events_company_month', 'billing_events', ['company_id', 'period_month'])
    op.create_index('idx_billing_events_grouping', 'billing_events', ['grouping_type', 'grouping_value'])


def downgrade() -> None:
    """Remove all tables added in this migration."""
    op.drop_table('billing_events')
    op.drop_table('payment_transactions')
    op.drop_table('subscriptions')
    op.drop_table('credit_wallets')
    op.drop_table('billing_config')
    op.drop_table('call_content')
    op.drop_table('call_logs')
    op.drop_table('assets')
