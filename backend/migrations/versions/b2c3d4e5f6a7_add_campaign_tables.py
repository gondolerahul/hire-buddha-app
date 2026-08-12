"""Add campaign tables

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-02-06 11:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema to add campaign tables."""
    
    # Create campaigns table
    op.create_table(
        'campaigns',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('company_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('companies.id'), nullable=False),
        sa.Column('created_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('agent_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('hierarchical_entities.id'), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('description', sa.Text, nullable=True),
        sa.Column('total_contacts', sa.Integer, nullable=False, server_default='0'),
        sa.Column('contact_list', postgresql.JSONB, nullable=False),
        sa.Column('provider', sa.String(20), nullable=False, server_default='twilio'),
        sa.Column('call_script_template', sa.Text, nullable=True),
        sa.Column('scheduled_start', sa.DateTime, nullable=True),
        sa.Column('scheduled_end', sa.DateTime, nullable=True),
        sa.Column('max_concurrent_calls', sa.Integer, nullable=False, server_default='5'),
        sa.Column('max_calls_per_hour', sa.Integer, nullable=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='draft'),
        sa.Column('started_at', sa.DateTime, nullable=True),
        sa.Column('completed_at', sa.DateTime, nullable=True),
        sa.Column('calls_initiated', sa.Integer, nullable=False, server_default='0'),
        sa.Column('calls_completed', sa.Integer, nullable=False, server_default='0'),
        sa.Column('calls_failed', sa.Integer, nullable=False, server_default='0'),
        sa.Column('outcome_distribution', postgresql.JSONB, nullable=True),
        sa.Column('metadata', postgresql.JSONB, nullable=True),
        sa.Column('created_at', sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime, nullable=False, server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    
    # Create indexes for campaigns
    op.create_index('idx_campaigns_company', 'campaigns', ['company_id'])
    op.create_index('idx_campaigns_agent', 'campaigns', ['agent_id'])
    op.create_index('idx_campaigns_status', 'campaigns', ['status'])
    op.create_index('idx_campaigns_created_by', 'campaigns', ['created_by'])
    
    # Create campaign_calls table
    op.create_table(
        'campaign_calls',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('campaign_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('campaigns.id'), nullable=False),
        sa.Column('voice_session_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('voice_sessions.id'), nullable=True),
        sa.Column('contact_data', postgresql.JSONB, nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default='pending'),
        sa.Column('call_sid', sa.String(100), nullable=True),
        sa.Column('outcome', sa.String(50), nullable=True),
        sa.Column('outcome_notes', sa.Text, nullable=True),
        sa.Column('scheduled_at', sa.DateTime, nullable=True),
        sa.Column('called_at', sa.DateTime, nullable=True),
        sa.Column('completed_at', sa.DateTime, nullable=True),
        sa.Column('duration_seconds', sa.Integer, nullable=True),
        sa.Column('retry_count', sa.Integer, nullable=False, server_default='0'),
        sa.Column('max_retries', sa.Integer, nullable=False, server_default='2'),
        sa.Column('metadata', postgresql.JSONB, nullable=True),
        sa.Column('created_at', sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    
    # Create indexes for campaign_calls
    op.create_index('idx_campaign_calls_campaign', 'campaign_calls', ['campaign_id'])
    op.create_index('idx_campaign_calls_status', 'campaign_calls', ['status'])
    op.create_index('idx_campaign_calls_voice_session', 'campaign_calls', ['voice_session_id'])


def downgrade() -> None:
    """Downgrade schema to remove campaign tables."""
    
    op.drop_table('campaign_calls')
    op.drop_table('campaigns')
