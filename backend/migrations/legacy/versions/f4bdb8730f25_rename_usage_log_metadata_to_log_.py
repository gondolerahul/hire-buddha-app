"""rename usage log metadata to log_metadata

Revision ID: f4bdb8730f25
Revises: a804c0db1551
Create Date: 2025-12-18 12:07:51.370886

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f4bdb8730f25'
down_revision: Union[str, Sequence[str], None] = 'a804c0db1551'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column('usage_logs', 'metadata', new_column_name='log_metadata')


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column('usage_logs', 'log_metadata', new_column_name='metadata')
