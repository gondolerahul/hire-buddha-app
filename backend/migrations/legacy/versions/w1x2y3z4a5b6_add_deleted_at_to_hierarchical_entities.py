"""add_deleted_at_to_hierarchical_entities

Add deleted_at column to hierarchical_entities table for soft-delete support.
Entities are no longer physically deleted — they are marked status='DELETED'
with a deleted_at timestamp, preserving FK integrity for execution_runs,
usage_logs, and all billing-critical data.

Revision ID: w1x2y3z4a5b6
Revises: v1w2x3y4z5a6
Create Date: 2026-05-07 10:15:00.000000
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'w1x2y3z4a5b6'
down_revision = 't1u2v3w4x5y6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add deleted_at column for soft-delete tracking
    op.add_column(
        'hierarchical_entities',
        sa.Column('deleted_at', sa.DateTime(), nullable=True)
    )
    # Add a partial index for fast filtering of non-deleted entities
    op.create_index(
        'idx_entities_not_deleted',
        'hierarchical_entities',
        ['company_id', 'type'],
        postgresql_where=sa.text("status != 'DELETED'"),
    )


def downgrade() -> None:
    op.drop_index('idx_entities_not_deleted', table_name='hierarchical_entities')
    op.drop_column('hierarchical_entities', 'deleted_at')
