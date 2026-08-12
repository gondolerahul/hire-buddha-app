"""Add tool_registry_entries table

Revision ID: n1o2p3q4r5s6
Revises: m1n2o3p4q5r6
Create Date: 2026-03-09 08:42:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'n1o2p3q4r5s6'
down_revision: Union[str, Sequence[str], None] = 'm1n2o3p4q5r6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'tool_registry_entries',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('company_id', sa.UUID(), nullable=True),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('display_name', sa.String(), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('category', sa.String(), nullable=True),
        sa.Column('tool_type', sa.String(), nullable=False, server_default='BUILT_IN'),
        sa.Column('function_schema', sa.JSON(), nullable=True),
        sa.Column('is_enabled', sa.Boolean(), nullable=True, server_default=sa.text('true')),
        sa.Column('configuration', sa.JSON(), nullable=True),
        sa.Column('created_by', sa.UUID(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id']),
        sa.ForeignKeyConstraint(['created_by'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
    )
    op.create_index('ix_tool_registry_entries_name', 'tool_registry_entries', ['name'])
    op.create_index('ix_tool_registry_entries_tool_type', 'tool_registry_entries', ['tool_type'])


def downgrade() -> None:
    op.drop_index('ix_tool_registry_entries_tool_type', table_name='tool_registry_entries')
    op.drop_index('ix_tool_registry_entries_name', table_name='tool_registry_entries')
    op.drop_table('tool_registry_entries')
