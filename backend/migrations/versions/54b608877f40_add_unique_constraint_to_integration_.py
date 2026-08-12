"""add unique constraint to integration_registry

Revision ID: 54b608877f40
Revises: 9bf859b51116
Create Date: 2025-12-18 12:12:47.032542

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '54b608877f40'
down_revision: Union[str, Sequence[str], None] = '9bf859b51116'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_unique_constraint('uq_integration_company_sku', 'integration_registry', ['company_id', 'service_sku'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('uq_integration_company_sku', 'integration_registry', type_='unique')
