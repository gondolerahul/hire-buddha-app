"""daily-credit policies, fixed prices and company locks (Phase 15 T5-3, T5-4, T5-5)

Revision ID: control_0016_money_controls
Revises: control_0015_wallet_lots
Create Date: 2026-10-24

* ``daily_credit_policies`` / ``daily_credit_bands`` / ``company_daily_credit_overrides``
  (tech design §7): who gets daily credits, how much on which day of their
  life, and per-company exceptions. The old flat amount — the global
  ``billing_config.default_daily_credits`` — becomes a ``direct`` and an
  ``all_partners`` policy with no end, so nobody's credits change; a company
  whose own amount differed (``billing_config`` company row, or
  ``companies.default_daily_credits``) gets a ``custom`` override. Both old
  columns are read by nothing from now on (dropped with the wallet buckets).
* A daily lot is granted once per company and local date (DC-6): a unique
  partial index on ``wallet_lots``.
* ``price_items`` / ``price_item_versions`` (§8.3): fixed prices, seeded with
  the number rent (USD 20, ₹2,000 — K-5, O-2) and the partner annual fees
  (inactive until staff set them).
* ``company_locks`` (§8.5, Q5): spend cap and plan locks.

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'control_0016_money_controls'
down_revision: Union[str, Sequence[str], None] = 'control_0015_wallet_lots'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

EXACT = sa.Numeric(precision=24, scale=10)
NO_END = 100000          # the last day of a band with no end


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('daily_credit_policies',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('audience', sa.String(length=20), nullable=False),
    sa.Column('partner_id', sa.UUID(), nullable=True),
    sa.Column('duration_days', sa.Integer(), nullable=True),
    sa.Column('active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('effective_from', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("audience IN ('direct', 'partner', 'all_partners')", name='ck_daily_credit_policies_audience'),
    sa.CheckConstraint("(audience = 'partner') = (partner_id IS NOT NULL)", name='ck_daily_credit_policies_partner'),
    sa.CheckConstraint('duration_days IS NULL OR duration_days IN (0, 10, 15, 30, 60, 90, 180, 365)',
                       name='ck_daily_credit_policies_duration'),
    sa.ForeignKeyConstraint(['partner_id'], ['companies.id'], ),
    sa.PrimaryKeyConstraint('id'),
    info={'plane': 'control'}
    )
    op.create_index('ix_daily_credit_policies_audience', 'daily_credit_policies', ['audience', 'partner_id'],
                    unique=False)
    op.create_table('daily_credit_bands',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('policy_id', sa.UUID(), nullable=False),
    sa.Column('from_day', sa.Integer(), nullable=False),
    sa.Column('to_day', sa.Integer(), nullable=False),
    sa.Column('amount_usd', EXACT, nullable=False),
    sa.CheckConstraint('amount_usd >= 0', name='ck_daily_credit_bands_amount'),
    sa.CheckConstraint('from_day >= 1 AND to_day >= from_day', name='ck_daily_credit_bands_days'),
    sa.ForeignKeyConstraint(['policy_id'], ['daily_credit_policies.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    info={'plane': 'control'}
    )
    op.create_index(op.f('ix_daily_credit_bands_policy_id'), 'daily_credit_bands', ['policy_id'], unique=False)
    op.create_table('company_daily_credit_overrides',
    sa.Column('company_id', sa.UUID(), nullable=False),
    sa.Column('mode', sa.String(length=10), nullable=False),
    sa.Column('amount_usd', EXACT, nullable=True),
    sa.Column('duration_days', sa.Integer(), nullable=True),
    sa.Column('until', sa.DateTime(timezone=True), nullable=True),
    sa.Column('reason', sa.Text(), nullable=True),
    sa.Column('set_by', sa.UUID(), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("mode <> 'custom' OR amount_usd IS NOT NULL", name='ck_company_daily_credit_overrides_amount'),
    sa.CheckConstraint("mode IN ('policy', 'custom', 'none')", name='ck_company_daily_credit_overrides_mode'),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
    sa.PrimaryKeyConstraint('company_id'),
    info={'plane': 'control'}
    )
    op.create_index('uq_wallet_lots_daily_date', 'wallet_lots', ['company_id', 'local_date'], unique=True,
                    postgresql_where=sa.text("kind = 'daily' AND local_date IS NOT NULL"))
    op.create_table('price_items',
    sa.Column('code', sa.Text(), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('kind', sa.String(length=20), nullable=False),
    sa.Column('interval', sa.String(length=10), nullable=True),
    sa.Column('amount_usd', EXACT, nullable=False),
    sa.Column('currency_overrides', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"),
              nullable=False),
    sa.Column('taxable', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('version', sa.Integer(), server_default='1', nullable=False),
    sa.Column('updated_by', sa.UUID(), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('amount_usd >= 0', name='ck_price_items_amount'),
    sa.CheckConstraint("interval IS NULL OR interval IN ('month', 'year')", name='ck_price_items_interval'),
    sa.CheckConstraint("kind IN ('recurring', 'one_time')", name='ck_price_items_kind'),
    sa.PrimaryKeyConstraint('code'),
    info={'plane': 'control'}
    )
    op.create_table('price_item_versions',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('code', sa.Text(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('amount_usd', EXACT, nullable=False),
    sa.Column('currency_overrides', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"),
              nullable=False),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.Column('reason', sa.Text(), nullable=True),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['code'], ['price_items.code'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('code', 'version', name='uq_price_item_versions'),
    info={'plane': 'control'}
    )
    op.create_table('company_locks',
    sa.Column('company_id', sa.UUID(), nullable=False),
    sa.Column('key', sa.String(length=20), nullable=False),
    sa.Column('locked_by_role', sa.String(length=20), nullable=False),
    sa.Column('locked_by', sa.UUID(), nullable=True),
    sa.Column('reason', sa.Text(), nullable=True),
    sa.Column('at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("key IN ('spend_cap', 'plan')", name='ck_company_locks_key'),
    sa.CheckConstraint("locked_by_role IN ('app_admin', 'partner')", name='ck_company_locks_role'),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
    sa.PrimaryKeyConstraint('company_id', 'key'),
    info={'plane': 'control'}
    )

    # ── the old flat daily amount → policies with no end, and overrides ──────
    op.execute(f"""
        WITH old AS (
            SELECT default_daily_credits AS amount FROM billing_config
            WHERE company_id IS NULL AND is_active AND default_daily_credits > 0
            ORDER BY updated_at DESC LIMIT 1
        ), policies AS (
            INSERT INTO daily_credit_policies (name, audience, duration_days)
            SELECT p.name, p.audience, NULL FROM old,
                   (VALUES ('Direct tenants (migrated flat amount)', 'direct'),
                           ('Partner tenants (migrated flat amount)', 'all_partners')) AS p(name, audience)
            RETURNING id
        )
        INSERT INTO daily_credit_bands (policy_id, from_day, to_day, amount_usd)
        SELECT policies.id, 1, {NO_END}, old.amount FROM policies, old
    """)
    op.execute("""
        WITH global AS (
            SELECT COALESCE((SELECT default_daily_credits FROM billing_config
                             WHERE company_id IS NULL AND is_active ORDER BY updated_at DESC LIMIT 1), 0) AS amount
        ), own AS (
            SELECT c.id AS company_id,
                   COALESCE((SELECT b.default_daily_credits FROM billing_config b
                             WHERE b.company_id = c.id AND b.is_active ORDER BY b.updated_at DESC LIMIT 1),
                            c.default_daily_credits) AS amount
            FROM companies c WHERE c.type = 'TENANT'
        )
        INSERT INTO company_daily_credit_overrides (company_id, mode, amount_usd, reason)
        SELECT own.company_id, CASE WHEN own.amount > 0 THEN 'custom' ELSE 'none' END,
               CASE WHEN own.amount > 0 THEN own.amount END,
               'migrated: the company''s own daily amount (' || own.amount || ' USD)'
        FROM own, global WHERE own.amount IS NOT NULL AND own.amount <> global.amount
    """)

    # ── fixed prices ─────────────────────────────────────────────────────────
    op.execute("""
        INSERT INTO price_items (code, name, kind, interval, amount_usd, currency_overrides, taxable, active) VALUES
            ('phone_number_rent', 'Phone number rent', 'recurring', 'month', 20, '{"INR": 2000}', true, true),
            ('partner_annual_fee_silver', 'Silver partner annual fee', 'recurring', 'year', 0, '{}', true, false),
            ('partner_annual_fee_gold', 'Gold partner annual fee', 'recurring', 'year', 0, '{}', true, false)
    """)
    op.execute("""
        INSERT INTO price_item_versions (code, version, amount_usd, currency_overrides, active, reason)
        SELECT code, version, amount_usd, currency_overrides, active, 'seeded' FROM price_items
    """)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('company_locks')
    op.drop_table('price_item_versions')
    op.drop_table('price_items')
    op.drop_index('uq_wallet_lots_daily_date', table_name='wallet_lots')
    op.drop_table('company_daily_credit_overrides')
    op.drop_index(op.f('ix_daily_credit_bands_policy_id'), table_name='daily_credit_bands')
    op.drop_table('daily_credit_bands')
    op.drop_index('ix_daily_credit_policies_audience', table_name='daily_credit_policies')
    op.drop_table('daily_credit_policies')
