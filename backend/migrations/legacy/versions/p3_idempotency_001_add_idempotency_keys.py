"""Add idempotency_key to execution_runs and tool_interaction_logs

Revision ID: p3_idempotency_001
Revises: w1x2y3z4a5b6_add_deleted_at_to_hierarchical_entities
Create Date: 2026-05-07 18:15:00.000000
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = 'p3_idempotency_001'
down_revision = 'w1x2y3z4a5b6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add idempotency_key to execution_runs
    op.add_column(
        'execution_runs',
        sa.Column('idempotency_key', sa.String(255), nullable=True)
    )
    op.create_index(
        'idx_exec_runs_idemp',
        'execution_runs',
        ['idempotency_key'],
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )

    # Add idempotency_key to tool_interaction_logs
    op.add_column(
        'tool_interaction_logs',
        sa.Column('idempotency_key', sa.String(255), nullable=True)
    )
    op.create_index(
        'idx_tool_logs_idemp',
        'tool_interaction_logs',
        ['idempotency_key'],
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index('idx_tool_logs_idemp', table_name='tool_interaction_logs')
    op.drop_column('tool_interaction_logs', 'idempotency_key')
    op.drop_index('idx_exec_runs_idemp', table_name='execution_runs')
    op.drop_column('execution_runs', 'idempotency_key')
