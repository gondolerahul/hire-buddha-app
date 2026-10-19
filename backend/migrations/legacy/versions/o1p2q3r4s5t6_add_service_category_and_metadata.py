"""Add service_category and service_metadata to integration_registry

Revision ID: o1p2q3r4s5t6
Revises: n1o2p3q4r5s6
Create Date: 2026-04-01

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'o1p2q3r4s5t6'
down_revision = 'n1o2p3q4r5s6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'integration_registry',
        sa.Column('service_category', sa.String(), nullable=False, server_default='LLM'),
    )
    op.add_column(
        'integration_registry',
        sa.Column('service_metadata', sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('integration_registry', 'service_metadata')
    op.drop_column('integration_registry', 'service_category')
