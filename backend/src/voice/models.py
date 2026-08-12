"""
SQLAlchemy models for Voice and WhatsApp streaming.
"""
from datetime import datetime
from uuid import uuid4
from sqlalchemy import (
    Column, String, Integer, Boolean, DateTime, Text,
    ForeignKey, Numeric, Index
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from src.common.database import Base
from src.ai.models import HierarchicalEntity


class VoiceSession(Base):
    """Voice call session model."""
    __tablename__ = "voice_sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False)
    customer_id = Column(UUID(as_uuid=True), nullable=False)
    agent_id = Column(UUID(as_uuid=True), ForeignKey("hierarchical_entities.id"), nullable=False)
    phone_number = Column(String(20), nullable=False)
    provider = Column(String(20), nullable=False)  # 'twilio' | 'tata_tele'
    call_sid = Column(String(100), nullable=False, unique=True)
    stream_sid = Column(String(100), nullable=True)
    direction = Column(String(20), nullable=True)  # 'inbound' | 'outbound'
    status = Column(String(20), nullable=False, default="initiated")
    started_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    ended_at = Column(DateTime, nullable=True)
    duration_seconds = Column(Integer, nullable=True)
    total_cost_usd = Column(Numeric(10, 4), nullable=False, default=0)
    context_state = Column(JSONB, nullable=True)  # Conversation context
    conversation_log = Column(JSONB, nullable=True)  # Full transcript
    session_metadata = Column(JSONB, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    # Relationships
    company = relationship("Company")
    agent = relationship("HierarchicalEntity")

    __table_args__ = (
        Index('idx_voice_sessions_customer', 'customer_id'),
        Index('idx_voice_sessions_agent', 'agent_id'),
        Index('idx_voice_sessions_call_sid', 'call_sid'),
        Index('idx_voice_sessions_status', 'status'),
        Index('idx_voice_sessions_company', 'company_id'),
    )


class WhatsAppSession(Base):
    """WhatsApp conversation session model."""
    __tablename__ = "whatsapp_sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False)
    customer_id = Column(UUID(as_uuid=True), nullable=False)
    agent_id = Column(UUID(as_uuid=True), ForeignKey("hierarchical_entities.id"), nullable=False)
    phone_number = Column(String(20), nullable=False)
    provider = Column(String(20), nullable=False)  # 'twilio' | 'tata_tele'
    conversation_id = Column(String(100), nullable=False, unique=True)
    status = Column(String(20), nullable=False, default="active")
    session_window_expires = Column(DateTime, nullable=True)  # 24-hour window
    started_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    last_message_at = Column(DateTime, nullable=True)
    message_count = Column(Integer, nullable=False, default=0)
    total_cost_usd = Column(Numeric(10, 4), nullable=False, default=0)
    conversation_log = Column(JSONB, nullable=True)
    session_metadata = Column(JSONB, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    # Relationships
    company = relationship("Company")
    agent = relationship("HierarchicalEntity")

    __table_args__ = (
        Index('idx_whatsapp_sessions_customer', 'customer_id'),
        Index('idx_whatsapp_sessions_conversation', 'conversation_id'),
        Index('idx_whatsapp_sessions_agent', 'agent_id'),
        Index('idx_whatsapp_sessions_company', 'company_id'),
    )


class ConversationHistory(Base):
    """Unified conversation history across voice and WhatsApp."""
    __tablename__ = "conversation_history"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False)
    customer_id = Column(UUID(as_uuid=True), nullable=False)
    agent_id = Column(UUID(as_uuid=True), ForeignKey("hierarchical_entities.id"), nullable=False)
    session_id = Column(UUID(as_uuid=True), nullable=True)  # voice_sessions.id or whatsapp_sessions.id
    channel = Column(String(20), nullable=False)  # 'voice' | 'whatsapp'
    turn_number = Column(Integer, nullable=False)
    speaker = Column(String(20), nullable=False)  # 'customer' | 'agent'
    message_type = Column(String(20), nullable=True)  # 'text' | 'audio' | 'image'
    content = Column(Text, nullable=True)
    audio_duration_ms = Column(Integer, nullable=True)
    timestamp = Column(DateTime, nullable=False, default=datetime.utcnow)
    message_metadata = Column(JSONB, nullable=True)

    # Relationships
    company = relationship("Company")
    agent = relationship("HierarchicalEntity")

    __table_args__ = (
        Index('idx_conversation_customer_agent', 'customer_id', 'agent_id', 'timestamp'),
        Index('idx_conversation_session', 'session_id'),
        Index('idx_conversation_company', 'company_id'),
    )



__all__ = [
    "VoiceSession",
    "WhatsAppSession",
    "ConversationHistory",
]
