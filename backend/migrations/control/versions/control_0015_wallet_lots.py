"""the lot wallet: lots, an append-only ledger, debt and state (Phase 15 T4-1, T4-2)

Revision ID: control_0015_wallet_lots
Revises: control_0014_billing_lines
Create Date: 2026-10-24

* ``credit_wallets`` + ``currency`` (the company's billing currency), ``state``
  (ok | in_debt | over_tolerance | suspended), ``debt``, ``in_debt_since``,
  ``over_tolerance_since``, ``suspended_at``, ``cached_available``.
* ``wallet_lots`` — one grant of credit with its own expiry; ``wallet_entries``
  — the append-only ledger (tech design §6.1).
* ``credit_holds`` + ``currency``, ``billed_ccy``: a hold is in the wallet's
  currency from now on.

The cutover (T4-2, one way): each wallet's live buckets become lots in the
company's currency at the rate in effect now — daily credits a ``daily`` lot,
subscription credits and their bonus ``subscription`` / ``subscription_bonus``
lots, the top-up balance a paid ``topup`` lot — each keeping its bucket's
expiry, with a ``grant`` entry (``source_type='migration'``). Open holds are
converted at the same rate. Every usage row written so far is marked settled
(``settlement_id`` = the cutover sentinel): the old path charged it, and the
new settlement (``src.billing.settlement``) charges only rows it has not seen.
Runs and calls must be drained before this runs (runbook T10-1); one still
running is billed only for the usage it writes afterwards.

The bucket columns are left as they were (read by nothing; dropped one release
later), so the downgrade restores the wallet as it stood at the cutover.
``python -m src.billing.wallet_cutover`` reports, per company, the buckets in
USD against the lots in currency (before the upgrade: what it would create).

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'control_0015_wallet_lots'
down_revision: Union[str, Sequence[str], None] = 'control_0014_billing_lines'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

EXACT = sa.Numeric(precision=24, scale=10)
CUTOVER = '00000000-0000-0000-0000-00000000c015'   # settlement_id of usage charged before the cutover

# (bucket column, its expiry column, lot kind, paid) — the old spend order.
BUCKETS = (
    ('daily_credits', 'daily_expires_at', 'daily', False),
    ('subscription_credits', 'sub_credits_expire_at', 'subscription', True),
    ('subscription_bonus_credits', 'sub_credits_expire_at', 'subscription_bonus', False),
    ('wallet_balance', 'wallet_expires_at', 'topup', True),
)

# The rate in effect now for a wallet's currency (USD is 1).
RATE = """
    LEFT JOIN LATERAL (
        SELECT r.id, r.units_per_usd FROM fx_rates r
        WHERE r.currency = w.currency AND r.effective_from <= now()
        ORDER BY r.effective_from DESC, r.created_at DESC LIMIT 1
    ) fx ON true
"""


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('credit_wallets', sa.Column('currency', sa.CHAR(length=3), server_default='INR', nullable=False))
    op.add_column('credit_wallets', sa.Column('state', sa.String(length=20), server_default='ok', nullable=False))
    op.add_column('credit_wallets', sa.Column('debt', EXACT, server_default='0', nullable=False))
    op.add_column('credit_wallets', sa.Column('in_debt_since', sa.DateTime(timezone=True), nullable=True))
    op.add_column('credit_wallets', sa.Column('over_tolerance_since', sa.DateTime(timezone=True), nullable=True))
    op.add_column('credit_wallets', sa.Column('suspended_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('credit_wallets', sa.Column('cached_available', EXACT, server_default='0', nullable=False))
    op.create_foreign_key('credit_wallets_currency_fkey', 'credit_wallets', 'currencies', ['currency'], ['code'])
    op.create_check_constraint('ck_credit_wallets_state', 'credit_wallets',
                               "state IN ('ok', 'in_debt', 'over_tolerance', 'suspended')")
    op.create_check_constraint('ck_credit_wallets_debt', 'credit_wallets', 'debt >= 0')
    op.add_column('credit_holds', sa.Column('currency', sa.CHAR(length=3), nullable=True))
    op.add_column('credit_holds', sa.Column('billed_ccy', EXACT, nullable=True))

    op.create_table('wallet_lots',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('company_id', sa.UUID(), nullable=False),
    sa.Column('kind', sa.String(length=30), nullable=False),
    sa.Column('currency', sa.CHAR(length=3), nullable=False),
    sa.Column('original', EXACT, nullable=False),
    sa.Column('remaining', EXACT, nullable=False),
    sa.Column('granted_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('paid', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('source_type', sa.String(length=40), nullable=True),
    sa.Column('source_id', sa.Text(), nullable=True),
    sa.Column('fx_rate_id', sa.UUID(), nullable=True),
    sa.Column('policy_id', sa.UUID(), nullable=True),
    sa.Column('local_date', sa.Date(), nullable=True),
    sa.CheckConstraint("kind IN ('daily', 'subscription', 'subscription_bonus', 'topup', 'grant')",
                       name='ck_wallet_lots_kind'),
    sa.CheckConstraint('remaining >= 0 AND original >= 0', name='ck_wallet_lots_amounts'),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
    sa.PrimaryKeyConstraint('id'),
    info={'plane': 'control'}
    )
    op.create_index('ix_wallet_lots_live', 'wallet_lots', ['company_id', 'expires_at'], unique=False,
                    postgresql_where=sa.text('remaining > 0'))
    op.create_table('wallet_entries',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('company_id', sa.UUID(), nullable=False),
    sa.Column('lot_id', sa.UUID(), nullable=True),
    sa.Column('kind', sa.String(length=20), nullable=False),
    sa.Column('amount', EXACT, nullable=False),
    sa.Column('currency', sa.CHAR(length=3), nullable=False),
    sa.Column('balance_after', EXACT, nullable=False),
    sa.Column('debt_after', EXACT, nullable=False),
    sa.Column('category', sa.String(length=30), nullable=True),
    sa.Column('reason', sa.Text(), nullable=True),
    sa.Column('source_type', sa.String(length=40), nullable=True),
    sa.Column('source_id', sa.Text(), nullable=True),
    sa.Column('run_id', sa.UUID(), nullable=True),
    sa.Column('user_id', sa.UUID(), nullable=True),
    sa.Column('actor_id', sa.UUID(), nullable=True),
    sa.Column('fx_rate_id', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("kind IN ('grant', 'deduct', 'expire', 'debt_add', 'debt_repay', 'adjust', 'refund', "
                       "'convert')", name='ck_wallet_entries_kind'),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
    sa.PrimaryKeyConstraint('id'),
    info={'plane': 'control'}
    )
    op.create_index('ix_wallet_entries_company', 'wallet_entries', ['company_id', 'created_at'], unique=False)
    op.create_index('ix_wallet_entries_source', 'wallet_entries', ['source_type', 'source_id'], unique=False)

    # ── the cutover ────────────────────────────────────────────────────────
    op.execute("""
        UPDATE credit_wallets w SET currency = c.billing_currency
        FROM companies c WHERE c.id = w.company_id AND c.billing_currency IS NOT NULL
          AND EXISTS (SELECT 1 FROM currencies k WHERE k.code = c.billing_currency)
    """)
    for column, expiry, kind, paid in BUCKETS:
        op.execute(f"""
            INSERT INTO wallet_lots (company_id, kind, currency, original, remaining, granted_at, expires_at, paid,
                                     source_type, source_id, fx_rate_id)
            SELECT w.company_id, '{kind}', w.currency,
                   w.{column} * COALESCE(fx.units_per_usd, 1), w.{column} * COALESCE(fx.units_per_usd, 1),
                   now(), w.{expiry}, {str(paid).lower()}, 'migration', '{column}', fx.id
            FROM credit_wallets w {RATE}
            WHERE w.{column} > 0 AND (w.{expiry} IS NULL OR w.{expiry} > now())
        """)
    # One grant entry per lot, the running balance in the old spend order.
    op.execute("""
        INSERT INTO wallet_entries (company_id, lot_id, kind, amount, currency, balance_after, debt_after, reason,
                                    source_type, source_id, fx_rate_id, created_at)
        SELECT l.company_id, l.id, 'grant', l.remaining, l.currency,
               SUM(l.remaining) OVER (PARTITION BY l.company_id ORDER BY
                   CASE l.kind WHEN 'daily' THEN 0 WHEN 'subscription' THEN 1 WHEN 'subscription_bonus' THEN 2
                   ELSE 3 END ROWS UNBOUNDED PRECEDING),
               0, 'the wallet''s ' || l.source_id || ' at the cutover', 'migration', l.source_id, l.fx_rate_id,
               l.granted_at
        FROM wallet_lots l WHERE l.source_type = 'migration'
    """)
    op.execute("""
        UPDATE credit_wallets w SET cached_available = COALESCE(
            (SELECT SUM(l.remaining) FROM wallet_lots l WHERE l.company_id = w.company_id), 0)
    """)
    op.execute(f"""
        UPDATE credit_holds h SET amount = h.amount * COALESCE(fx.units_per_usd, 1), currency = w.currency
        FROM credit_wallets w {RATE}
        WHERE w.company_id = h.company_id AND h.released_at IS NULL AND h.settled_at IS NULL
    """)
    op.execute(f"UPDATE usage_logs SET settlement_id = '{CUTOVER}' WHERE settlement_id IS NULL")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(f"UPDATE usage_logs SET settlement_id = NULL WHERE settlement_id = '{CUTOVER}'")
    op.execute("""
        UPDATE credit_holds h SET amount = h.amount / COALESCE(
            (SELECT r.units_per_usd FROM fx_rates r WHERE r.currency = h.currency AND r.effective_from <= now()
             ORDER BY r.effective_from DESC, r.created_at DESC LIMIT 1), 1)
        WHERE h.currency IS NOT NULL AND h.currency <> 'USD' AND h.released_at IS NULL AND h.settled_at IS NULL
    """)
    op.drop_index('ix_wallet_entries_source', table_name='wallet_entries')
    op.drop_index('ix_wallet_entries_company', table_name='wallet_entries')
    op.drop_table('wallet_entries')
    op.drop_index('ix_wallet_lots_live', table_name='wallet_lots')
    op.drop_table('wallet_lots')
    op.drop_column('credit_holds', 'billed_ccy')
    op.drop_column('credit_holds', 'currency')
    op.drop_constraint('ck_credit_wallets_debt', 'credit_wallets', type_='check')
    op.drop_constraint('ck_credit_wallets_state', 'credit_wallets', type_='check')
    op.drop_constraint('credit_wallets_currency_fkey', 'credit_wallets', type_='foreignkey')
    for column in ('cached_available', 'suspended_at', 'over_tolerance_since', 'in_debt_since', 'debt', 'state',
                   'currency'):
        op.drop_column('credit_wallets', column)
