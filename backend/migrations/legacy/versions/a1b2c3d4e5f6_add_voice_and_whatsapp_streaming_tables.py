"""Add voice and whatsapp streaming tables

Revision ID: a1b2c3d4e5f6
Revises: 9bc12d4c6cc6
Create Date: 2026-02-06 11:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '9bc12d4c6cc6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema to add streaming tables."""
    
    # Create voice_sessions table
    op.create_table(
        'voice_sessions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('company_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('companies.id'), nullable=False),
        sa.Column('customer_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('agent_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('hierarchical_entities.id'), nullable=False),
        sa.Column('phone_number', sa.String(20), nullable=False),
        sa.Column('provider', sa.String(20), nullable=False),  # 'twilio' | 'tata_tele'
        sa.Column('call_sid', sa.String(100), nullable=False, unique=True),
        sa.Column('stream_sid', sa.String(100), nullable=True),
        sa.Column('direction', sa.String(20), nullable=True),  # 'inbound' | 'outbound'
        sa.Column('status', sa.String(20), nullable=False, server_default='initiated'),
        sa.Column('started_at', sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column('ended_at', sa.DateTime, nullable=True),
        sa.Column('duration_seconds', sa.Integer, nullable=True),
        sa.Column('total_cost_usd', sa.Numeric(10, 4), nullable=False, server_default='0'),
        sa.Column('context_state', postgresql.JSONB, nullable=True),  # Conversation context
        sa.Column('conversation_log', postgresql.JSONB, nullable=True),  # Full transcript
        sa.Column('metadata', postgresql.JSONB, nullable=True),
        sa.Column('created_at', sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    
    # Create indexes for voice_sessions
    op.create_index('idx_voice_sessions_customer', 'voice_sessions', ['customer_id'])
    op.create_index('idx_voice_sessions_agent', 'voice_sessions', ['agent_id'])
    op.create_index('idx_voice_sessions_call_sid', 'voice_sessions', ['call_sid'])
    op.create_index('idx_voice_sessions_status', 'voice_sessions', ['status'])
    op.create_index('idx_voice_sessions_company', 'voice_sessions', ['company_id'])
    
    # Create whatsapp_sessions table
    op.create_table(
        'whatsapp_sessions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('company_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('companies.id'), nullable=False),
        sa.Column('customer_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('agent_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('hierarchical_entities.id'), nullable=False),
        sa.Column('phone_number', sa.String(20), nullable=False),
        sa.Column('provider', sa.String(20), nullable=False),  # 'twilio' | 'tata_tele'
        sa.Column('conversation_id', sa.String(100), nullable=False, unique=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='active'),
        sa.Column('session_window_expires', sa.DateTime, nullable=True),  # 24-hour window
        sa.Column('started_at', sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column('last_message_at', sa.DateTime, nullable=True),
        sa.Column('message_count', sa.Integer, nullable=False, server_default='0'),
        sa.Column('total_cost_usd', sa.Numeric(10, 4), nullable=False, server_default='0'),
        sa.Column('conversation_log', postgresql.JSONB, nullable=True),
        sa.Column('metadata', postgresql.JSONB, nullable=True),
        sa.Column('created_at', sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    
    # Create indexes for whatsapp_sessions
    op.create_index('idx_whatsapp_sessions_customer', 'whatsapp_sessions', ['customer_id'])
    op.create_index('idx_whatsapp_sessions_conversation', 'whatsapp_sessions', ['conversation_id'])
    op.create_index('idx_whatsapp_sessions_agent', 'whatsapp_sessions', ['agent_id'])
    op.create_index('idx_whatsapp_sessions_company', 'whatsapp_sessions', ['company_id'])
    
    # Create conversation_history table (unified across voice + WhatsApp)
    op.create_table(
        'conversation_history',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('company_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('companies.id'), nullable=False),
        sa.Column('customer_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('agent_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('hierarchical_entities.id'), nullable=False),
        sa.Column('session_id', postgresql.UUID(as_uuid=True), nullable=True),  # voice_sessions.id or whatsapp_sessions.id
        sa.Column('channel', sa.String(20), nullable=False),  # 'voice' | 'whatsapp'
        sa.Column('turn_number', sa.Integer, nullable=False),
        sa.Column('speaker', sa.String(20), nullable=False),  # 'customer' | 'agent'
        sa.Column('message_type', sa.String(20), nullable=True),  # 'text' | 'audio' | 'image'
        sa.Column('content', sa.Text, nullable=True),
        sa.Column('audio_duration_ms', sa.Integer, nullable=True),
        sa.Column('timestamp', sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column('metadata', postgresql.JSONB, nullable=True),
    )
    
    # Create indexes for conversation_history
    op.create_index(
        'idx_conversation_customer_agent', 
        'conversation_history', 
        ['customer_id', 'agent_id', 'timestamp'],
        postgresql_using='btree',
        postgresql_ops={'timestamp': 'DESC'}
    )
    op.create_index('idx_conversation_session', 'conversation_history', ['session_id'])
    op.create_index('idx_conversation_company', 'conversation_history', ['company_id'])
    
    # Create customer_phone_numbers table (number assignments)
    op.create_table(
        'customer_phone_numbers',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('company_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('companies.id'), nullable=False),
        sa.Column('customer_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('customer_name', sa.String(255), nullable=True),
        sa.Column('customer_metadata', postgresql.JSONB, nullable=True),  # Additional customer info
        sa.Column('phone_number', sa.String(20), nullable=False, unique=True),
        sa.Column('provider', sa.String(20), nullable=False),  # 'twilio' | 'tata_tele'
        sa.Column('agent_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('hierarchical_entities.id'), nullable=False),
        sa.Column('assigned_at', sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column('is_active', sa.Boolean, nullable=False, server_default='true'),
    )
    
    # Create indexes for customer_phone_numbers
    op.create_index('idx_customer_numbers_phone', 'customer_phone_numbers', ['phone_number'])
    op.create_index('idx_customer_numbers_customer', 'customer_phone_numbers', ['customer_id'])
    op.create_index('idx_customer_numbers_company', 'customer_phone_numbers', ['company_id'])


def downgrade() -> None:
    """Downgrade schema to remove streaming tables."""
    
    # Drop tables in reverse order
    op.drop_table('customer_phone_numbers')
    op.drop_table('conversation_history')
    op.drop_table('whatsapp_sessions')
    op.drop_table('voice_sessions')
