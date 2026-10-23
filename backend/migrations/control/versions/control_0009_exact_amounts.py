"""exact amounts on the control plane (Phase 15 T1-5)

Revision ID: control_0009_exact_amounts
Revises: control_0008_exact_quantities
Create Date: 2026-10-23

Money that is computed — billing events, holds and their settled amounts,
wallet buckets (until WS15-4 replaces them with lots), credits awarded, the
spend cap — is stored ``NUMERIC(24,10)``: a column at 4 or 6 decimals rounded
every charge as it was written. Payment amounts stay at 2 decimals: that is
the gateway edge K-1 allows. ``billing_config`` is not touched (it is retired
by T3-2).

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'control_0009_exact_amounts'
down_revision: Union[str, Sequence[str], None] = 'control_0008_exact_quantities'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

EXACT = sa.Numeric(precision=24, scale=10)

# table → [(column, type before, nullable)]
COLUMNS = {
    'billing_events': [(c, sa.Numeric(14, 6), False) for c in (
        'base_cost', 'multiplied_cost', 'platform_fee_amount', 'partner_fee_amount', 'discount_amount',
        'total_billing', 'telephony_charge', 'llm_charge', 'image_charge', 'video_charge', 'api_charge',
        'other_ai_cost')],
    'credit_holds': [('amount', sa.Numeric(14, 6), False), ('billed_amount', sa.Numeric(14, 6), True)],
    'credit_wallets': [('daily_credits', sa.Numeric(10, 4), False), ('wallet_balance', sa.Numeric(12, 4), False),
                       ('subscription_credits', sa.Numeric(12, 4), False),
                       ('subscription_bonus_credits', sa.Numeric(12, 4), False)],
    'payment_transactions': [('credits_awarded', sa.Numeric(12, 4), True)],
    'companies': [('monthly_spend_cap_usd', sa.Numeric(14, 4), True)],
}


def upgrade() -> None:
    """Upgrade schema."""
    for table, columns in COLUMNS.items():
        for column, before, nullable in columns:
            op.alter_column(table, column, type_=EXACT, existing_type=before, existing_nullable=nullable)


def downgrade() -> None:
    """Downgrade schema."""
    for table, columns in COLUMNS.items():
        for column, before, nullable in columns:
            op.alter_column(table, column, type_=before, existing_type=EXACT, existing_nullable=nullable)
