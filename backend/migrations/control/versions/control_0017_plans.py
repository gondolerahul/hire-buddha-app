"""plans, gateway plans and entitlements (Phase 15 T6-1, T6-2, T6-4)

Revision ID: control_0017_plans
Revises: control_0016_money_controls
Create Date: 2026-10-24

* ``plans`` replaces ``subscription_tiers`` (tech design §12.1): every tier
  becomes a plan at its level, fee and bonus; level 0 is **Pay-as-you-go**
  (free; the plan of every company without a subscription, SB-6). With no
  tiers, the O-12 plans are seeded: Starter USD 100 / 10 %, Growth 500 / 20 %,
  Scale 1,000 / 30 %, Enterprise 5,000 / 40 %. ``plan_versions`` keeps each
  version (SB-1).
* ``plan_gateway_plans``: the gateway's plan per (plan version, currency,
  rate, tax rate), created on first use (SB-2).
* ``plan_entitlements`` and ``company_entitlement_overrides`` (§10.2): empty —
  every feature is on and every limit is the catalogue's default until staff
  restrict a plan (REQ-SB-3).
* ``subscriptions`` + the plan and version bought, its currency and per-cycle
  amount, the gateway plan charged and one waiting for the cycle's end, and
  ``cancel_at_cycle_end``. Existing subscriptions point at their tier's plan,
  in USD.

``subscription_tiers`` is read by nothing from now on (dropped a release later).

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'control_0017_plans'
down_revision: Union[str, Sequence[str], None] = 'control_0016_money_controls'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

EXACT = sa.Numeric(precision=24, scale=10)
SEED = (("starter", "Starter", 1, 100, 10), ("growth", "Growth", 2, 500, 20), ("scale", "Scale", 3, 1000, 30),
        ("enterprise", "Enterprise", 4, 5000, 40))


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('plans',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('code', sa.String(length=40), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('tier_level', sa.Integer(), nullable=False),
    sa.Column('monthly_fee_usd', EXACT, nullable=False),
    sa.Column('bonus_pct', sa.Numeric(precision=10, scale=4), server_default='0', nullable=False),
    sa.Column('currency_overrides', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"),
              nullable=False),
    sa.Column('active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('sort', sa.Integer(), server_default='0', nullable=False),
    sa.Column('version', sa.Integer(), server_default='1', nullable=False),
    sa.Column('updated_by', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('monthly_fee_usd >= 0 AND bonus_pct >= 0 AND bonus_pct <= 100', name='ck_plans_amounts'),
    sa.CheckConstraint('tier_level >= 0', name='ck_plans_tier_level'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('code'),
    sa.UniqueConstraint('tier_level'),
    info={'plane': 'control'}
    )
    op.create_table('plan_versions',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('plan_id', sa.UUID(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('monthly_fee_usd', EXACT, nullable=False),
    sa.Column('bonus_pct', sa.Numeric(precision=10, scale=4), nullable=False),
    sa.Column('currency_overrides', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"),
              nullable=False),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.Column('reason', sa.Text(), nullable=True),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['plan_id'], ['plans.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('plan_id', 'version', name='uq_plan_versions'),
    info={'plane': 'control'}
    )
    op.create_table('plan_gateway_plans',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('plan_id', sa.UUID(), nullable=False),
    sa.Column('plan_version', sa.Integer(), nullable=False),
    sa.Column('currency', sa.CHAR(length=3), nullable=False),
    sa.Column('fx_rate_id', sa.UUID(), nullable=True),
    sa.Column('tax_rate', sa.Numeric(precision=10, scale=4), nullable=False),
    sa.Column('net_amount', EXACT, nullable=False),
    sa.Column('amount_minor', sa.Integer(), nullable=False),
    sa.Column('gateway', sa.String(length=20), server_default='razorpay', nullable=False),
    sa.Column('gateway_plan_id', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['plan_id'], ['plans.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('plan_id', 'plan_version', 'currency', 'fx_rate_id', 'tax_rate', 'gateway',
                        name='uq_plan_gateway_plans', postgresql_nulls_not_distinct=True),
    info={'plane': 'control'}
    )
    op.create_table('plan_entitlements',
    sa.Column('plan_id', sa.UUID(), nullable=False),
    sa.Column('feature_key', sa.String(length=80), nullable=False),
    sa.Column('enabled', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('limit_value', sa.Integer(), nullable=True),
    sa.Column('updated_by', sa.UUID(), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['plan_id'], ['plans.id'], ),
    sa.PrimaryKeyConstraint('plan_id', 'feature_key'),
    info={'plane': 'control'}
    )
    op.create_table('company_entitlement_overrides',
    sa.Column('company_id', sa.UUID(), nullable=False),
    sa.Column('feature_key', sa.String(length=80), nullable=False),
    sa.Column('enabled', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('limit_value', sa.Integer(), nullable=True),
    sa.Column('until', sa.DateTime(timezone=True), nullable=True),
    sa.Column('reason', sa.Text(), nullable=True),
    sa.Column('set_by', sa.UUID(), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
    sa.PrimaryKeyConstraint('company_id', 'feature_key'),
    info={'plane': 'control'}
    )
    for name, column in (('plan_id', sa.UUID()), ('plan_version', sa.Integer()), ('currency', sa.CHAR(length=3)),
                         ('amount_ccy', EXACT), ('gateway_plan_ref', sa.UUID()), ('pending_plan_id', sa.UUID()),
                         ('pending_gateway_plan_ref', sa.UUID())):
        op.add_column('subscriptions', sa.Column(name, column, nullable=True))
    op.add_column('subscriptions', sa.Column('cancel_at_cycle_end', sa.Boolean(), server_default=sa.text('false'),
                                             nullable=False))
    op.create_foreign_key('subscriptions_plan_id_fkey', 'subscriptions', 'plans', ['plan_id'], ['id'])

    # ── the data: tiers → plans, Pay-as-you-go, versions, subscriptions ──────
    op.execute("""
        INSERT INTO plans (code, name, tier_level, monthly_fee_usd, bonus_pct, active, sort)
        SELECT lower(regexp_replace(name, '[^A-Za-z0-9]+', '_', 'g')) || '_' || tier_level, name, tier_level,
               monthly_fee, bonus_pct, is_active, tier_level
        FROM subscription_tiers WHERE tier_level > 0
    """)
    values = ", ".join(f"('{c}', '{n}', {lvl}, {fee}, {bonus}, true, {lvl})" for c, n, lvl, fee, bonus in SEED)
    op.execute(f"""
        INSERT INTO plans (code, name, tier_level, monthly_fee_usd, bonus_pct, active, sort)
        SELECT * FROM (VALUES {values}) AS seed(code, name, tier_level, monthly_fee_usd, bonus_pct, active, sort)
        WHERE NOT EXISTS (SELECT 1 FROM subscription_tiers WHERE tier_level > 0)
    """)
    op.execute("""
        INSERT INTO plans (code, name, tier_level, monthly_fee_usd, bonus_pct, active, sort)
        VALUES ('payg', 'Pay-as-you-go', 0, 0, 0, true, 0)
    """)
    op.execute("""
        INSERT INTO plan_versions (plan_id, version, name, monthly_fee_usd, bonus_pct, currency_overrides, active, reason)
        SELECT id, 1, name, monthly_fee_usd, bonus_pct, currency_overrides, active, 'migrated' FROM plans
    """)
    op.execute("""
        UPDATE subscriptions s SET plan_id = p.id, plan_version = 1, currency = 'USD', amount_ccy = s.monthly_fee
        FROM plans p WHERE p.tier_level = s.plan_tier
    """)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('subscriptions_plan_id_fkey', 'subscriptions', type_='foreignkey')
    for name in ('cancel_at_cycle_end', 'pending_gateway_plan_ref', 'pending_plan_id', 'gateway_plan_ref',
                 'amount_ccy', 'currency', 'plan_version', 'plan_id'):
        op.drop_column('subscriptions', name)
    op.drop_table('company_entitlement_overrides')
    op.drop_table('plan_entitlements')
    op.drop_table('plan_gateway_plans')
    op.drop_table('plan_versions')
    op.drop_table('plans')
