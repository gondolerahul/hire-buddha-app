"""add user_id to execution_runs

Revision ID: p1q2r3s4t5u6
Revises: o1p2q3r4s5t6
Create Date: 2026-04-07 09:47:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'p1q2r3s4t5u6'
down_revision: Union[str, None] = 'o1p2q3r4s5t6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'execution_runs',
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=True)
    )
    op.create_foreign_key(
        'execution_runs_user_id_fkey',
        'execution_runs',
        'users',
        ['user_id'],
        ['id'],
    )


def downgrade() -> None:
    op.drop_constraint('execution_runs_user_id_fkey', 'execution_runs', type_='foreignkey')
    op.drop_column('execution_runs', 'user_id')
