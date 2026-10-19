"""Control baseline: the control tables as the old chain left them (Phase 14 WS2 2.7).

The old chain's 101 revisions squashed, for the control plane: every table of
``bases.CONTROL`` as ``alembic upgrade head`` built it at ``p14_run_settlement``
(columns, server defaults, indexes, check and unique constraints, foreign keys).
Rendered by Alembic's autogenerate from a database that chain built, so a
database stamped at the cut and one built from here are the same; the models
match it (``alembic check``, ``tests/integration/test_migration_trees.py``).

Foreign keys come last, after every table exists.

Revision ID: control_0001_baseline
Revises:
Create Date: 2026-10-19
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = 'control_0001_baseline'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (name, table, referred table, columns, referred columns, ON DELETE)
FOREIGN_KEYS = [
    ('automation_settings_company_id_fkey', 'automation_settings', 'companies', ['company_id'], ['id'], None),
    ('automation_settings_updated_by_fkey', 'automation_settings', 'users', ['updated_by'], ['id'], None),
    ('billing_config_company_id_fkey', 'billing_config', 'companies', ['company_id'], ['id'], None),
    ('billing_events_company_id_fkey', 'billing_events', 'companies', ['company_id'], ['id'], None),
    ('companies_parent_id_fkey', 'companies', 'companies', ['parent_id'], ['id'], None),
    ('credit_holds_company_id_fkey', 'credit_holds', 'companies', ['company_id'], ['id'], None),
    ('credit_wallets_company_id_fkey', 'credit_wallets', 'companies', ['company_id'], ['id'], None),
    ('integration_registry_company_id_fkey', 'integration_registry', 'companies', ['company_id'], ['id'], None),
    ('fk_model_task_defaults_fallback_integration', 'model_task_defaults', 'integration_registry', ['fallback_integration_id'], ['id'], 'SET NULL'),
    ('model_task_defaults_company_id_fkey', 'model_task_defaults', 'companies', ['company_id'], ['id'], None),
    ('model_task_defaults_integration_id_fkey', 'model_task_defaults', 'integration_registry', ['integration_id'], ['id'], None),
    ('notifications_company_id_fkey', 'notifications', 'companies', ['company_id'], ['id'], 'CASCADE'),
    ('notifications_user_id_fkey', 'notifications', 'users', ['user_id'], ['id'], 'CASCADE'),
    ('payment_transactions_company_id_fkey', 'payment_transactions', 'companies', ['company_id'], ['id'], None),
    ('phone_numbers_added_by_user_id_fkey', 'phone_numbers', 'users', ['added_by_user_id'], ['id'], None),
    ('phone_numbers_claimed_by_user_id_fkey', 'phone_numbers', 'users', ['claimed_by_user_id'], ['id'], None),
    ('phone_numbers_company_id_fkey', 'phone_numbers', 'companies', ['company_id'], ['id'], None),
    ('refresh_tokens_user_id_fkey', 'refresh_tokens', 'users', ['user_id'], ['id'], None),
    ('subscriptions_company_id_fkey', 'subscriptions', 'companies', ['company_id'], ['id'], None),
    ('tenant_directory_company_id_fkey', 'tenant_directory', 'companies', ['company_id'], ['id'], None),
    ('tenant_directory_server_id_fkey', 'tenant_directory', 'tenant_db_servers', ['server_id'], ['id'], None),
    ('tenant_provisioning_log_company_id_fkey', 'tenant_provisioning_log', 'companies', ['company_id'], ['id'], None),
    ('tool_registry_entries_company_id_fkey', 'tool_registry_entries', 'companies', ['company_id'], ['id'], None),
    ('tool_registry_entries_created_by_fkey', 'tool_registry_entries', 'users', ['created_by'], ['id'], None),
    ('usage_logs_company_id_fkey', 'usage_logs', 'companies', ['company_id'], ['id'], None),
    ('usage_logs_sku_id_fkey', 'usage_logs', 'integration_registry', ['sku_id'], ['id'], None),
    ('user_devices_company_id_fkey', 'user_devices', 'companies', ['company_id'], ['id'], None),
    ('user_devices_user_id_fkey', 'user_devices', 'users', ['user_id'], ['id'], None),
    ('users_company_id_fkey', 'users', 'companies', ['company_id'], ['id'], None),
    ('webhook_endpoints_company_id_fkey', 'webhook_endpoints', 'companies', ['company_id'], ['id'], 'CASCADE'),
    ('webhook_endpoints_created_by_fkey', 'webhook_endpoints', 'users', ['created_by'], ['id'], 'SET NULL'),
]


def upgrade() -> None:
    op.create_table('companies',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('name', sa.VARCHAR(), nullable=False),
    sa.Column('type', sa.VARCHAR(), nullable=False),
    sa.Column('parent_id', sa.UUID(), nullable=True),
    sa.Column('logo_url', sa.VARCHAR(), nullable=True),
    sa.Column('status', sa.VARCHAR(), nullable=True),
    sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('onboarding_status', sa.VARCHAR(), server_default=sa.text("'pending'::character varying"), nullable=True),
    sa.Column('onboarding_metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('default_daily_credits', sa.NUMERIC(precision=10, scale=4), nullable=True),
    sa.Column('monthly_spend_cap_usd', sa.NUMERIC(precision=14, scale=4), nullable=True),
    sa.Column('timezone', sa.VARCHAR(length=64), server_default=sa.text("'Asia/Kolkata'::character varying"), nullable=False),
    sa.CheckConstraint('monthly_spend_cap_usd IS NULL OR monthly_spend_cap_usd > 0::numeric', name='ck_companies_spend_cap_positive'),
    sa.PrimaryKeyConstraint('id', name='companies_pkey')
    )
    op.create_index('uq_companies_one_app', 'companies', ['type'], unique=True, postgresql_where="((type)::text = 'APP'::text)")
    op.create_table('feature_flags',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('company_id', sa.UUID(), nullable=True),
    sa.Column('entity_id', sa.UUID(), nullable=True),
    sa.Column('flag_key', sa.VARCHAR(length=128), nullable=False),
    sa.Column('enabled', sa.BOOLEAN(), server_default=sa.text('false'), nullable=False),
    sa.Column('value_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name='feature_flags_pkey')
    )
    op.create_index('ix_feature_flags_company', 'feature_flags', ['flag_key', 'company_id'], unique=True, postgresql_where='((company_id IS NOT NULL) AND (entity_id IS NULL))')
    op.create_index('ix_feature_flags_company_lookup', 'feature_flags', ['company_id'], unique=False)
    op.create_index('ix_feature_flags_entity', 'feature_flags', ['flag_key', 'entity_id'], unique=True, postgresql_where='(entity_id IS NOT NULL)')
    op.create_index('ix_feature_flags_global', 'feature_flags', ['flag_key'], unique=True, postgresql_where='((company_id IS NULL) AND (entity_id IS NULL))')
    op.create_table('subscription_tiers',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('name', sa.VARCHAR(length=50), nullable=False),
    sa.Column('tier_level', sa.INTEGER(), nullable=False),
    sa.Column('monthly_fee', sa.NUMERIC(precision=10, scale=2), nullable=False),
    sa.Column('bonus_pct', sa.NUMERIC(precision=5, scale=2), server_default=sa.text("'0'::numeric"), nullable=False),
    sa.Column('is_active', sa.BOOLEAN(), server_default=sa.text('true'), nullable=False),
    sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('razorpay_plan_id', sa.VARCHAR(length=200), nullable=True),
    sa.PrimaryKeyConstraint('id', name='subscription_tiers_pkey'),
    sa.UniqueConstraint('tier_level', name='subscription_tiers_tier_level_key')
    )
    op.create_table('tenant_db_servers',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('name', sa.TEXT(), nullable=False),
    sa.Column('host', sa.TEXT(), nullable=False),
    sa.Column('kind', sa.TEXT(), nullable=False),
    sa.Column('region', sa.TEXT(), nullable=False),
    sa.Column('capacity', sa.INTEGER(), nullable=False),
    sa.Column('status', sa.TEXT(), nullable=False),
    sa.CheckConstraint("kind = ANY (ARRAY['pool'::text, 'dedicated'::text])", name='ck_tenant_db_servers_kind'),
    sa.CheckConstraint("status = ANY (ARRAY['active'::text, 'draining'::text, 'retired'::text])", name='ck_tenant_db_servers_status'),
    sa.PrimaryKeyConstraint('id', name='tenant_db_servers_pkey'),
    sa.UniqueConstraint('name', name='tenant_db_servers_name_key')
    )
    op.create_table('time_index',
    sa.Column('company_id', sa.UUID(), nullable=False),
    sa.Column('ref_kind', sa.TEXT(), nullable=False),
    sa.Column('ref_id', sa.UUID(), nullable=False),
    sa.Column('due_at', postgresql.TIMESTAMP(timezone=True), nullable=False),
    sa.Column('lease_owner', sa.TEXT(), nullable=True),
    sa.Column('lease_until', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.CheckConstraint("ref_kind = ANY (ARRAY['trigger'::text, 'wait'::text, 'connection_refresh'::text, 'scratch_cleanup'::text])", name='ck_time_index_ref_kind'),
    sa.PrimaryKeyConstraint('company_id', 'ref_kind', 'ref_id', name='time_index_pkey')
    )
    op.create_index('ix_time_index_due_at', 'time_index', ['due_at'], unique=False)
    op.create_table('billing_config',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('company_id', sa.UUID(), nullable=True),
    sa.Column('config_name', sa.VARCHAR(length=100), server_default=sa.text("'default'::character varying"), nullable=False),
    sa.Column('multiplier_factor', sa.NUMERIC(precision=10, scale=4), server_default=sa.text('1.0'), nullable=False),
    sa.Column('platform_fee_pct', sa.NUMERIC(precision=10, scale=4), server_default=sa.text('0.0'), nullable=False),
    sa.Column('sales_partner_fee_pct', sa.NUMERIC(precision=10, scale=4), server_default=sa.text('0.0'), nullable=False),
    sa.Column('discount_pct', sa.NUMERIC(precision=10, scale=4), server_default=sa.text('0.0'), nullable=False),
    sa.Column('is_active', sa.BOOLEAN(), server_default=sa.text('true'), nullable=False),
    sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('default_daily_credits', sa.NUMERIC(precision=10, scale=4), server_default=sa.text('5.0'), nullable=False),
    sa.Column('base_cost_telephony', sa.NUMERIC(precision=14, scale=6), nullable=True),
    sa.Column('base_cost_llm', sa.NUMERIC(precision=14, scale=6), nullable=True),
    sa.Column('base_cost_image_gen', sa.NUMERIC(precision=14, scale=6), nullable=True),
    sa.PrimaryKeyConstraint('id', name='billing_config_pkey')
    )
    op.create_index('idx_billing_config_company', 'billing_config', ['company_id'], unique=False)
    op.create_table('billing_events',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('company_id', sa.UUID(), nullable=False),
    sa.Column('period_month', sa.DATE(), nullable=False),
    sa.Column('grouping_type', sa.VARCHAR(length=30), nullable=True),
    sa.Column('grouping_value', sa.VARCHAR(length=500), nullable=True),
    sa.Column('base_cost', sa.NUMERIC(precision=14, scale=6), server_default=sa.text("'0'::numeric"), nullable=False),
    sa.Column('multiplied_cost', sa.NUMERIC(precision=14, scale=6), server_default=sa.text("'0'::numeric"), nullable=False),
    sa.Column('platform_fee_amount', sa.NUMERIC(precision=14, scale=6), server_default=sa.text("'0'::numeric"), nullable=False),
    sa.Column('partner_fee_amount', sa.NUMERIC(precision=14, scale=6), server_default=sa.text("'0'::numeric"), nullable=False),
    sa.Column('discount_amount', sa.NUMERIC(precision=14, scale=6), server_default=sa.text("'0'::numeric"), nullable=False),
    sa.Column('total_billing', sa.NUMERIC(precision=14, scale=6), server_default=sa.text("'0'::numeric"), nullable=False),
    sa.Column('telephony_in_minutes', sa.NUMERIC(precision=10, scale=2), server_default=sa.text("'0'::numeric"), nullable=False),
    sa.Column('telephony_out_minutes', sa.NUMERIC(precision=10, scale=2), server_default=sa.text("'0'::numeric"), nullable=False),
    sa.Column('image_gen_count', sa.INTEGER(), server_default=sa.text('0'), nullable=False),
    sa.Column('video_gen_count', sa.INTEGER(), server_default=sa.text('0'), nullable=False),
    sa.Column('other_ai_cost', sa.NUMERIC(precision=14, scale=6), server_default=sa.text("'0'::numeric"), nullable=False),
    sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('telephony_charge', sa.NUMERIC(precision=14, scale=6), server_default=sa.text("'0'::numeric"), nullable=False),
    sa.Column('llm_charge', sa.NUMERIC(precision=14, scale=6), server_default=sa.text("'0'::numeric"), nullable=False),
    sa.Column('image_charge', sa.NUMERIC(precision=14, scale=6), server_default=sa.text("'0'::numeric"), nullable=False),
    sa.Column('video_charge', sa.NUMERIC(precision=14, scale=6), server_default=sa.text("'0'::numeric"), nullable=False),
    sa.Column('api_charge', sa.NUMERIC(precision=14, scale=6), server_default=sa.text("'0'::numeric"), nullable=False),
    sa.PrimaryKeyConstraint('id', name='billing_events_pkey'),
    sa.UniqueConstraint('company_id', 'period_month', 'grouping_type', 'grouping_value', name='uq_billing_events_period_grouping', postgresql_nulls_not_distinct=True)
    )
    op.create_index('idx_billing_events_company_month', 'billing_events', ['company_id', 'period_month'], unique=False)
    op.create_index('idx_billing_events_grouping', 'billing_events', ['grouping_type', 'grouping_value'], unique=False)
    op.create_table('credit_holds',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('company_id', sa.UUID(), nullable=False),
    sa.Column('run_id', sa.UUID(), nullable=False),
    sa.Column('amount', sa.NUMERIC(precision=14, scale=6), nullable=False),
    sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('released_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('settled_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('billed_amount', sa.NUMERIC(precision=14, scale=6), nullable=True),
    sa.PrimaryKeyConstraint('id', name='credit_holds_pkey'),
    sa.UniqueConstraint('run_id', name='credit_holds_run_id_key')
    )
    op.create_index('idx_credit_holds_open', 'credit_holds', ['company_id'], unique=False, postgresql_where='(released_at IS NULL)')
    op.create_table('credit_wallets',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('company_id', sa.UUID(), nullable=False),
    sa.Column('account_model', sa.VARCHAR(length=30), server_default=sa.text("'pay_as_you_go'::character varying"), nullable=False),
    sa.Column('daily_credits', sa.NUMERIC(precision=10, scale=4), server_default=sa.text('5.0'), nullable=False),
    sa.Column('daily_expires_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('wallet_balance', sa.NUMERIC(precision=12, scale=4), server_default=sa.text('0.0'), nullable=False),
    sa.Column('wallet_expires_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('subscription_credits', sa.NUMERIC(precision=12, scale=4), server_default=sa.text('0.0'), nullable=False),
    sa.Column('subscription_bonus_credits', sa.NUMERIC(precision=12, scale=4), server_default=sa.text('0.0'), nullable=False),
    sa.Column('sub_credits_expire_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name='credit_wallets_pkey'),
    sa.UniqueConstraint('company_id', name='credit_wallets_company_id_key')
    )
    op.create_index('idx_credit_wallets_company', 'credit_wallets', ['company_id'], unique=False)
    op.create_table('integration_registry',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('company_id', sa.UUID(), nullable=False),
    sa.Column('provider_name', sa.VARCHAR(), nullable=False),
    sa.Column('model_name', sa.VARCHAR(), nullable=True),
    sa.Column('service_sku', sa.VARCHAR(), nullable=False),
    sa.Column('component_type', sa.VARCHAR(), nullable=False),
    sa.Column('encrypted_api_key', sa.TEXT(), nullable=True),
    sa.Column('internal_cost', sa.NUMERIC(precision=18, scale=6), nullable=False),
    sa.Column('cost_unit', sa.VARCHAR(), nullable=False),
    sa.Column('status', sa.VARCHAR(), nullable=True),
    sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('service_category', sa.VARCHAR(), server_default=sa.text("'LLM'::character varying"), nullable=False),
    sa.Column('service_metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.CheckConstraint("service_category IN ('LLM', 'LLM_LIVE', 'EMBEDDING', 'IMAGE_GENERATION', 'VIDEO_GENERATION', 'SANDBOX', 'COMMUNICATION', 'EMAIL', 'SOCIAL_MEDIA', 'API_TOOL', 'OTHER')", name='ck_integration_registry_service_category'),
    sa.PrimaryKeyConstraint('id', name='integration_registry_pkey'),
    sa.UniqueConstraint('company_id', 'service_sku', name='uq_integration_company_sku')
    )
    op.create_table('payment_transactions',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('company_id', sa.UUID(), nullable=False),
    sa.Column('razorpay_order_id', sa.VARCHAR(length=200), nullable=True),
    sa.Column('razorpay_payment_id', sa.VARCHAR(length=200), nullable=True),
    sa.Column('razorpay_signature', sa.VARCHAR(length=500), nullable=True),
    sa.Column('amount', sa.NUMERIC(precision=10, scale=2), nullable=False),
    sa.Column('currency', sa.VARCHAR(length=10), server_default=sa.text("'USD'::character varying"), nullable=False),
    sa.Column('transaction_type', sa.VARCHAR(length=30), nullable=False),
    sa.Column('status', sa.VARCHAR(length=20), server_default=sa.text("'pending'::character varying"), nullable=False),
    sa.Column('credits_awarded', sa.NUMERIC(precision=12, scale=4), nullable=True),
    sa.Column('transaction_metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name='payment_transactions_pkey')
    )
    op.create_index('idx_payment_transactions_company', 'payment_transactions', ['company_id'], unique=False)
    op.create_index('uq_payment_transactions_razorpay_order', 'payment_transactions', ['razorpay_order_id'], unique=True, postgresql_where='(razorpay_order_id IS NOT NULL)')
    op.create_index('uq_payment_transactions_razorpay_payment', 'payment_transactions', ['razorpay_payment_id'], unique=True, postgresql_where='(razorpay_payment_id IS NOT NULL)')
    op.create_table('subscriptions',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('company_id', sa.UUID(), nullable=False),
    sa.Column('plan_tier', sa.INTEGER(), server_default=sa.text('1'), nullable=False),
    sa.Column('monthly_fee', sa.NUMERIC(precision=10, scale=2), nullable=False),
    sa.Column('bonus_pct', sa.NUMERIC(precision=5, scale=2), server_default=sa.text('20.0'), nullable=False),
    sa.Column('status', sa.VARCHAR(length=20), server_default=sa.text("'active'::character varying"), nullable=False),
    sa.Column('razorpay_subscription_id', sa.VARCHAR(length=200), nullable=True),
    sa.Column('razorpay_plan_id', sa.VARCHAR(length=200), nullable=True),
    sa.Column('next_billing_date', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('cancelled_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name='subscriptions_pkey')
    )
    op.create_index('idx_subscriptions_company', 'subscriptions', ['company_id'], unique=False)
    op.create_index('idx_subscriptions_status', 'subscriptions', ['status'], unique=False)
    op.create_table('tenant_directory',
    sa.Column('company_id', sa.UUID(), nullable=False),
    sa.Column('tenant_key', sa.TEXT(), nullable=False),
    sa.Column('slug', sa.TEXT(), nullable=False),
    sa.Column('server_id', sa.UUID(), nullable=False),
    sa.Column('db_name', sa.TEXT(), nullable=False),
    sa.Column('status', sa.TEXT(), nullable=False),
    sa.Column('automation_state', sa.TEXT(), server_default=sa.text("'running'::text"), nullable=False),
    sa.Column('timezone', sa.TEXT(), server_default=sa.text("'Asia/Kolkata'::text"), nullable=False),
    sa.Column('platform_schema_version', sa.TEXT(), nullable=True),
    sa.Column('business_schema_version', sa.TEXT(), nullable=True),
    sa.Column('blueprint_version', sa.INTEGER(), nullable=True),
    sa.Column('data_api_url', sa.TEXT(), nullable=True),
    sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("automation_state = ANY (ARRAY['running'::text, 'paused'::text, 'stopped'::text])", name='ck_tenant_directory_automation_state'),
    sa.CheckConstraint("status = ANY (ARRAY['requested'::text, 'db_created'::text, 'migrated'::text, 'identity_ready'::text, 'keys_ready'::text, 'namespace_ready'::text, 'storage_ready'::text, 'data_api_ready'::text, 'active'::text, 'suspended'::text, 'exporting'::text, 'retired'::text, 'failed'::text])", name='ck_tenant_directory_status'),
    sa.PrimaryKeyConstraint('company_id', name='tenant_directory_pkey'),
    sa.UniqueConstraint('slug', name='tenant_directory_slug_key'),
    sa.UniqueConstraint('tenant_key', name='tenant_directory_tenant_key_key')
    )
    op.create_index('ix_tenant_directory_server_id', 'tenant_directory', ['server_id'], unique=False)
    op.create_table('tenant_provisioning_log',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('company_id', sa.UUID(), nullable=False),
    sa.Column('tenant_key', sa.TEXT(), nullable=False),
    sa.Column('step', sa.TEXT(), nullable=False),
    sa.Column('outcome', sa.TEXT(), nullable=False),
    sa.Column('attempt', sa.INTEGER(), server_default=sa.text('1'), nullable=False),
    sa.Column('detail', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('error', sa.TEXT(), nullable=True),
    sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("outcome = ANY (ARRAY['started'::text, 'succeeded'::text, 'failed'::text, 'skipped'::text])", name='ck_tenant_provisioning_log_outcome'),
    sa.PrimaryKeyConstraint('id', name='tenant_provisioning_log_pkey')
    )
    op.create_index('ix_tenant_provisioning_log_company_created', 'tenant_provisioning_log', ['company_id', 'created_at'], unique=False)
    op.create_table('users',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('email', sa.VARCHAR(), nullable=False),
    sa.Column('full_name', sa.VARCHAR(), nullable=False),
    sa.Column('hashed_password', sa.VARCHAR(), nullable=False),
    sa.Column('role', sa.VARCHAR(), nullable=True),
    sa.Column('is_active', sa.BOOLEAN(), nullable=True),
    sa.Column('is_verified', sa.BOOLEAN(), nullable=True),
    sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('company_id', sa.UUID(), nullable=False),
    sa.Column('profile_picture_url', sa.VARCHAR(), nullable=True),
    sa.Column('token_version', sa.INTEGER(), server_default=sa.text('0'), nullable=False),
    sa.CheckConstraint('email::text = lower(email::text)', name='ck_users_email_lowercase'),
    sa.PrimaryKeyConstraint('id', name='users_pkey')
    )
    op.create_index('ix_users_email', 'users', ['email'], unique=True)
    op.create_table('automation_settings',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('company_id', sa.UUID(), nullable=True),
    sa.Column('limits', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('automation_state', sa.TEXT(), server_default=sa.text("'running'::text"), nullable=False),
    sa.Column('paused_reason', sa.TEXT(), nullable=True),
    sa.Column('updated_by', sa.UUID(), nullable=True),
    sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("automation_state = ANY (ARRAY['running'::text, 'paused'::text])", name='ck_automation_settings_state'),
    sa.PrimaryKeyConstraint('id', name='automation_settings_pkey')
    )
    op.create_index('uq_automation_settings_company', 'automation_settings', ['company_id'], unique=True, postgresql_where='(company_id IS NOT NULL)')
    op.create_index('uq_automation_settings_platform', 'automation_settings', [sa.literal_column('(company_id IS NULL)')], unique=True, postgresql_where='(company_id IS NULL)')
    op.create_table('model_task_defaults',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('company_id', sa.UUID(), nullable=False),
    sa.Column('task_type', sa.VARCHAR(length=50), nullable=False),
    sa.Column('integration_id', sa.UUID(), nullable=False),
    sa.Column('is_default', sa.BOOLEAN(), server_default=sa.text('true'), nullable=False),
    sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=True),
    sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=True),
    sa.Column('fallback_integration_id', sa.UUID(), nullable=True),
    sa.PrimaryKeyConstraint('id', name='model_task_defaults_pkey'),
    sa.UniqueConstraint('company_id', 'task_type', name='uq_task_defaults_company_task')
    )
    op.create_index('ix_model_task_defaults_company_id', 'model_task_defaults', ['company_id'], unique=False)
    op.create_index('ix_model_task_defaults_task_type', 'model_task_defaults', ['task_type'], unique=False)
    op.create_table('notifications',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('company_id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('kind', sa.TEXT(), nullable=False),
    sa.Column('severity', sa.TEXT(), server_default=sa.text("'warning'::text"), nullable=False),
    sa.Column('title', sa.TEXT(), nullable=False),
    sa.Column('body', sa.TEXT(), nullable=True),
    sa.Column('link', sa.TEXT(), nullable=True),
    sa.Column('dedupe_key', sa.TEXT(), nullable=False),
    sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('read_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('emailed_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.CheckConstraint("severity = ANY (ARRAY['info'::text, 'warning'::text, 'error'::text])", name='ck_notifications_severity'),
    sa.PrimaryKeyConstraint('id', name='notifications_pkey'),
    sa.UniqueConstraint('user_id', 'dedupe_key', name='uq_notifications_user_dedupe')
    )
    op.create_index('ix_notifications_user_unread', 'notifications', ['user_id', 'created_at'], unique=False, postgresql_where='(read_at IS NULL)')
    op.create_table('phone_numbers',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('phone_number', sa.VARCHAR(length=20), nullable=False),
    sa.Column('provider', sa.VARCHAR(length=20), nullable=False),
    sa.Column('country_code', sa.VARCHAR(length=5), server_default=sa.text("'+91'::character varying"), nullable=False),
    sa.Column('status', sa.VARCHAR(length=20), server_default=sa.text("'available'::character varying"), nullable=False),
    sa.Column('company_id', sa.UUID(), nullable=True),
    sa.Column('claimed_by_user_id', sa.UUID(), nullable=True),
    sa.Column('claimed_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('agent_id', sa.UUID(), nullable=True),
    sa.Column('customer_id', sa.UUID(), nullable=True),
    sa.Column('customer_name', sa.VARCHAR(length=255), nullable=True),
    sa.Column('customer_metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('assigned_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('provider_sid', sa.VARCHAR(length=100), nullable=True),
    sa.Column('capabilities', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('monthly_cost_usd', sa.NUMERIC(precision=10, scale=4), nullable=True),
    sa.Column('label', sa.VARCHAR(length=100), nullable=True),
    sa.Column('notes', sa.VARCHAR(length=500), nullable=True),
    sa.Column('added_by_user_id', sa.UUID(), nullable=True),
    sa.Column('is_active', sa.BOOLEAN(), server_default=sa.text('true'), nullable=False),
    sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=True),
    sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=True),
    sa.PrimaryKeyConstraint('id', name='phone_numbers_pkey'),
    sa.UniqueConstraint('phone_number', name='phone_numbers_phone_number_key')
    )
    op.create_index('idx_phone_numbers_agent', 'phone_numbers', ['agent_id'], unique=False)
    op.create_index('idx_phone_numbers_company', 'phone_numbers', ['company_id'], unique=False)
    op.create_index('idx_phone_numbers_customer', 'phone_numbers', ['customer_id'], unique=False)
    op.create_index('idx_phone_numbers_phone', 'phone_numbers', ['phone_number'], unique=False)
    op.create_index('idx_phone_numbers_provider', 'phone_numbers', ['provider'], unique=False)
    op.create_index('idx_phone_numbers_status', 'phone_numbers', ['status'], unique=False)
    op.create_table('refresh_tokens',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('expires_at', postgresql.TIMESTAMP(timezone=True), nullable=False),
    sa.Column('revoked', sa.BOOLEAN(), nullable=True),
    sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('token_hash', sa.VARCHAR(length=64), nullable=False),
    sa.PrimaryKeyConstraint('id', name='refresh_tokens_pkey'),
    sa.UniqueConstraint('token_hash', name='uq_refresh_tokens_token_hash')
    )
    op.create_table('tool_registry_entries',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('company_id', sa.UUID(), nullable=True),
    sa.Column('name', sa.VARCHAR(), nullable=False),
    sa.Column('display_name', sa.VARCHAR(), nullable=True),
    sa.Column('description', sa.TEXT(), nullable=True),
    sa.Column('category', sa.VARCHAR(), nullable=True),
    sa.Column('tool_type', sa.VARCHAR(), server_default=sa.text("'BUILT_IN'::character varying"), nullable=False),
    sa.Column('function_schema', postgresql.JSON(astext_type=sa.Text()), nullable=True),
    sa.Column('is_enabled', sa.BOOLEAN(), server_default=sa.text('true'), nullable=True),
    sa.Column('configuration', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id', name='tool_registry_entries_pkey'),
    sa.UniqueConstraint('company_id', 'name', name='uq_tool_registry_company_name', postgresql_nulls_not_distinct=True)
    )
    op.create_index('ix_tool_registry_entries_name', 'tool_registry_entries', ['name'], unique=False)
    op.create_index('ix_tool_registry_entries_tool_type', 'tool_registry_entries', ['tool_type'], unique=False)
    op.create_table('usage_logs',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('timestamp', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('company_id', sa.UUID(), nullable=False),
    sa.Column('sku_id', sa.UUID(), nullable=True),
    sa.Column('raw_quantity', sa.NUMERIC(precision=18, scale=6), nullable=False),
    sa.Column('calculated_cost', sa.NUMERIC(precision=18, scale=6), nullable=False),
    sa.Column('log_metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('run_id', sa.UUID(), nullable=True),
    sa.Column('attribution', sa.VARCHAR(length=40), server_default=sa.text("'tool'::character varying"), nullable=False),
    sa.PrimaryKeyConstraint('id', name='usage_logs_pkey')
    )
    op.create_index('ix_usage_logs_attribution', 'usage_logs', ['attribution'], unique=False)
    op.create_index('ix_usage_logs_run_id', 'usage_logs', ['run_id'], unique=False)
    op.create_table('user_devices',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('company_id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('install_id', sa.VARCHAR(length=64), nullable=False),
    sa.Column('platform', sa.VARCHAR(length=20), nullable=False),
    sa.Column('model', sa.VARCHAR(length=100), nullable=True),
    sa.Column('os_version', sa.VARCHAR(length=30), nullable=True),
    sa.Column('app_version', sa.VARCHAR(length=50), nullable=True),
    sa.Column('fcm_token', sa.VARCHAR(length=512), nullable=True),
    sa.Column('phone_account_label', sa.VARCHAR(length=100), nullable=True),
    sa.Column('presented_cli', sa.VARCHAR(length=40), nullable=True),
    sa.Column('verified_cli', sa.VARCHAR(length=20), nullable=True),
    sa.Column('cli_available', sa.BOOLEAN(), nullable=False),
    sa.Column('status', sa.VARCHAR(length=20), nullable=False),
    sa.Column('verification_code_hash', sa.VARCHAR(length=128), nullable=True),
    sa.Column('verification_did', sa.VARCHAR(length=20), nullable=True),
    sa.Column('verification_expires_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('verified_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('last_seen_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), nullable=False),
    sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id', name='user_devices_pkey'),
    sa.UniqueConstraint('install_id', name='user_devices_install_id_key')
    )
    op.create_index('ix_user_devices_company_id', 'user_devices', ['company_id'], unique=False)
    op.create_index('ix_user_devices_user_id', 'user_devices', ['user_id'], unique=False)
    op.create_index('ix_user_devices_verification_did', 'user_devices', ['verification_did', 'verification_expires_at'], unique=False)
    op.create_index('ix_user_devices_verified_cli', 'user_devices', ['verified_cli'], unique=False)
    op.create_table('webhook_endpoints',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('company_id', sa.UUID(), nullable=False),
    sa.Column('source', sa.VARCHAR(length=32), nullable=False),
    sa.Column('name', sa.VARCHAR(length=255), nullable=False),
    sa.Column('secret_encrypted', sa.TEXT(), nullable=False),
    sa.Column('entity_id', sa.UUID(), nullable=True),
    sa.Column('is_active', sa.BOOLEAN(), server_default=sa.text('true'), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('last_received_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.CheckConstraint("source IN ('github', 'facebook', 'instagram', 'linkedin', 'twitter', 'tiktok', 'youtube', 'twilio', 'email', 'crm', 'pinterest', 'generic')", name='ck_webhook_endpoints_source'),
    sa.PrimaryKeyConstraint('id', name='webhook_endpoints_pkey')
    )
    op.create_index('ix_webhook_endpoints_company', 'webhook_endpoints', ['company_id'], unique=False)
    for name, table, referred, columns, referred_columns, ondelete in FOREIGN_KEYS:
        op.create_foreign_key(name, table, referred, columns, referred_columns, ondelete=ondelete)


def downgrade() -> None:
    for name, table, *_ in reversed(FOREIGN_KEYS):
        op.drop_constraint(name, table, type_="foreignkey")
    for table in ('webhook_endpoints', 'user_devices', 'usage_logs', 'tool_registry_entries', 'refresh_tokens', 'phone_numbers', 'notifications', 'model_task_defaults', 'automation_settings', 'users', 'tenant_provisioning_log', 'tenant_directory', 'subscriptions', 'payment_transactions', 'integration_registry', 'credit_wallets', 'credit_holds', 'billing_events', 'billing_config', 'time_index', 'tenant_db_servers', 'subscription_tiers', 'feature_flags', 'companies'):
        op.drop_table(table)
