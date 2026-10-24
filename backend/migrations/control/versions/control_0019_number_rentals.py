"""number rentals (Phase 15 T7-1)

Revision ID: control_0019_number_rentals
Revises: control_0018_invoices
Create Date: 2026-10-24

* ``number_rentals``: a company's rent of a number, charged per 30-day period
  in advance (tech design §13). Every number a company holds now (claimed or
  assigned) gets an active rental from now, due at once: the rent job charges
  its first period on its next run.
* ``phone_numbers.monthly_cost_usd`` → ``provider_monthly_cost_usd`` (what the
  provider charges: cost side, staff only — NR-6).

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'control_0019_number_rentals'
down_revision: Union[str, Sequence[str], None] = 'control_0018_invoices'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('number_rentals',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('phone_number_id', sa.UUID(), nullable=False),
    sa.Column('company_id', sa.UUID(), nullable=False),
    sa.Column('status', sa.String(length=10), server_default='active', nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('next_charge_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('periods_charged', sa.Integer(), server_default='0', nullable=False),
    sa.Column('price_item_version', sa.Integer(), nullable=True),
    sa.Column('last_amount', sa.Numeric(precision=24, scale=10), nullable=True),
    sa.Column('currency', sa.CHAR(length=3), nullable=True),
    sa.Column('held_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("status IN ('active', 'held', 'ended')", name='ck_number_rentals_status'),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
    sa.ForeignKeyConstraint(['phone_number_id'], ['phone_numbers.id'], ),
    sa.PrimaryKeyConstraint('id'),
    info={'plane': 'control'}
    )
    op.create_index(op.f('ix_number_rentals_company_id'), 'number_rentals', ['company_id'], unique=False)
    op.create_index('ix_number_rentals_due', 'number_rentals', ['next_charge_at'], unique=False,
                    postgresql_where=sa.text("status <> 'ended'"))
    op.create_index('uq_number_rentals_open', 'number_rentals', ['phone_number_id'], unique=True,
                    postgresql_where=sa.text("status <> 'ended'"))
    op.alter_column('phone_numbers', 'monthly_cost_usd', new_column_name='provider_monthly_cost_usd')
    op.execute("""
        INSERT INTO number_rentals (phone_number_id, company_id, status, started_at, next_charge_at)
        SELECT id, company_id, 'active', now(), now() FROM phone_numbers
        WHERE company_id IS NOT NULL AND status IN ('claimed', 'assigned')
    """)


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column('phone_numbers', 'provider_monthly_cost_usd', new_column_name='monthly_cost_usd')
    op.drop_index('uq_number_rentals_open', table_name='number_rentals')
    op.drop_index('ix_number_rentals_due', table_name='number_rentals')
    op.drop_index(op.f('ix_number_rentals_company_id'), table_name='number_rentals')
    op.drop_table('number_rentals')
