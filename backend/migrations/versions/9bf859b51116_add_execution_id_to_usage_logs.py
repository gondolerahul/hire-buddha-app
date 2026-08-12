"""add execution_id to usage_logs

Revision ID: 9bf859b51116
Revises: f4bdb8730f25
Create Date: 2025-12-18 12:11:18.389268

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9bf859b51116'
down_revision: Union[str, Sequence[str], None] = 'f4bdb8730f25'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('usage_logs', sa.Column('execution_id', sa.UUID(), nullable=True))
    op.create_foreign_key('fk_usage_logs_execution_id', 'usage_logs', 'executions', ['execution_id'], ['id'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('fk_usage_logs_execution_id', 'usage_logs', type_='foreignkey')
    op.drop_column('usage_logs', 'execution_id')
