"""add episodic_memories table

Revision ID: q1r2s3t4u5v6
Revises: p1q2r3s4t5u6
Create Date: 2026-04-07 10:13:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'q1r2s3t4u5v6'
down_revision: Union[str, None] = 'p1q2r3s4t5u6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'episodic_memories',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('entity_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('hierarchical_entities.id'), nullable=False),
        sa.Column('company_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('companies.id'), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('run_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('execution_runs.id'), nullable=True),
        sa.Column('input_summary', sa.Text(), nullable=True),
        sa.Column('output_summary', sa.Text(), nullable=True),
        sa.Column('status', sa.String(50), nullable=True),
        sa.Column('total_cost_usd', sa.String(20), nullable=True),
        sa.Column('total_tokens', sa.Integer(), nullable=True),
        sa.Column('execution_time_ms', sa.Integer(), nullable=True),
        sa.Column('metadata_info', sa.JSON(), nullable=True),
        sa.Column('channel', sa.String(50), nullable=True),
        sa.Column('tree_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('cortex_trees.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
    )
    op.create_index('ix_episodic_memories_entity_id', 'episodic_memories', ['entity_id'])
    op.create_index('ix_episodic_memories_user_id', 'episodic_memories', ['user_id'])


def downgrade() -> None:
    op.drop_index('ix_episodic_memories_user_id', 'episodic_memories')
    op.drop_index('ix_episodic_memories_entity_id', 'episodic_memories')
    op.drop_table('episodic_memories')
