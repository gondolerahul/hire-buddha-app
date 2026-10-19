"""add_lead_queue_table

Revision ID: u1v2w3x4y5z6
Revises: t1u2v3w4x5y6
Create Date: 2026-05-05

Creates the lead_queue table for CRM-driven outbound calling pipeline.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'u1v2w3x4y5z6'
down_revision: Union[str, Sequence[str], None] = 't1u2v3w4x5y6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create lead_queue table with indexes and constraints."""
    op.create_table(
        'lead_queue',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('company_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('companies.id'), nullable=False),
        sa.Column('agent_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('hierarchical_entities.id'), nullable=False),
        sa.Column('lead_id', sa.String(255), nullable=False),
        sa.Column('phone', sa.String(20), nullable=False),
        sa.Column('lead_data', postgresql.JSONB, nullable=False),
        sa.Column('ad_source', sa.String(100), nullable=True),
        sa.Column('project_id', sa.String(100), nullable=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='pending'),
        sa.Column('priority', sa.Integer, nullable=False, server_default='5'),
        sa.Column('attempt_count', sa.Integer, nullable=False, server_default='0'),
        sa.Column('max_attempts', sa.Integer, nullable=False, server_default='3'),
        sa.Column('last_error', sa.Text, nullable=True),
        sa.Column('correlation_id', sa.String(100), nullable=True),
        sa.Column('voice_session_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('voice_sessions.id'), nullable=True),
        sa.Column('call_outcome', postgresql.JSONB, nullable=True),
        sa.Column('created_at', sa.DateTime, nullable=False,
                  server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime, nullable=False,
                  server_default=sa.text('now()')),
        sa.Column('processed_at', sa.DateTime, nullable=True),
        sa.UniqueConstraint('company_id', 'lead_id', name='uq_lead_queue_company_lead'),
    )

    # Partial index for efficient pending lead lookups
    op.create_index(
        'idx_lead_queue_pending',
        'lead_queue',
        ['company_id', 'status', 'priority', 'created_at'],
        postgresql_where=sa.text("status = 'pending'"),
    )

    # Index for post-call session lookup
    op.create_index(
        'idx_lead_queue_voice_session',
        'lead_queue',
        ['voice_session_id'],
    )


def downgrade() -> None:
    """Drop lead_queue table and its indexes."""
    op.drop_index('idx_lead_queue_voice_session', table_name='lead_queue')
    op.drop_index('idx_lead_queue_pending', table_name='lead_queue')
    op.drop_table('lead_queue')
