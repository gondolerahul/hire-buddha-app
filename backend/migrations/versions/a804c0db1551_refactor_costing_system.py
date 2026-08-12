"""refactor_costing_system

Revision ID: a804c0db1551
Revises: c3e80da7ca0a
Create Date: 2025-12-18 11:49:06.919788

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a804c0db1551'
down_revision: Union[str, Sequence[str], None] = 'c3e80da7ca0a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 1. Create integration_registry table
    op.create_table('integration_registry',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('company_id', sa.UUID(), nullable=False),
        sa.Column('provider_name', sa.String(), nullable=False),
        sa.Column('model_name', sa.String(), nullable=True),
        sa.Column('service_sku', sa.String(), nullable=False),
        sa.Column('component_type', sa.String(), nullable=False),
        sa.Column('encrypted_api_key', sa.Text(), nullable=True),
        sa.Column('internal_cost', sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column('cost_unit', sa.String(), nullable=False),
        sa.Column('status', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
        sa.PrimaryKeyConstraint('id')
    )

    # 2. Create usage_logs table
    op.create_table('usage_logs',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('timestamp', sa.DateTime(), nullable=True),
        sa.Column('company_id', sa.UUID(), nullable=False),
        sa.Column('sku_id', sa.UUID(), nullable=False),
        sa.Column('raw_quantity', sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column('calculated_cost', sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column('metadata', sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
        sa.ForeignKeyConstraint(['sku_id'], ['integration_registry.id'], ),
        sa.PrimaryKeyConstraint('id')
    )

    # 3. Drop legacy tables
    # Order: ledger_entries first as it depends on others
    op.drop_table('ledger_entries')
    op.drop_table('partner_rates')
    op.drop_table('system_rates')
    op.drop_table('invoices')
    op.drop_table('subscriptions')
    op.drop_table('payment_methods')
    # These are not billing but requested to be removed
    op.drop_table('system_configs')
    op.drop_table('ai_models')


def downgrade() -> None:
    """Downgrade schema."""
    # This is a complex downgrade, but for a prototype we can provide basic table recovery if needed.
    # However, since this is a major refactor, we usually don't support perfect data recovery.
    op.drop_table('usage_logs')
    op.drop_table('integration_registry')
    
    # Re-create tables (structure might be slightly different from original if simplified)
    # Skipping full re-creation for brevity as this is a one-way cleanup usually.
    pass
