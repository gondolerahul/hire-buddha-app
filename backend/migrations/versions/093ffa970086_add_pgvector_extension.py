"""Add pgvector extension

Revision ID: 093ffa970086
Revises: fd743ae4b9ee
Create Date: 2025-11-24 06:33:49.304075

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '093ffa970086'
down_revision: Union[str, Sequence[str], None] = 'fd743ae4b9ee'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP EXTENSION IF EXISTS vector")
