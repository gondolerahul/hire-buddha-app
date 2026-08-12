"""
Lead Queue model for CRM-driven outbound calling.

Persists incoming CRM leads in a database-backed queue with:
- Deduplication via UNIQUE(company_id, lead_id)
- Retry tracking (attempt_count / max_attempts)
- Status lifecycle: pending → queued → calling → completed → failed
- Priority ordering for fair scheduling
"""
from datetime import datetime
from uuid import uuid4
from sqlalchemy import (
    Column, String, Integer, DateTime, Text, ForeignKey, Index, UniqueConstraint
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from src.common.database import Base


class LeadQueueEntry(Base):
    """Persistent queue entry for CRM leads awaiting outbound calls."""
    __tablename__ = "lead_queue"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False)
    agent_id = Column(UUID(as_uuid=True), ForeignKey("hierarchical_entities.id"), nullable=False)

    # CRM lead identification
    lead_id = Column(String(255), nullable=False)  # CRM's external lead ID
    phone = Column(String(20), nullable=False)
    lead_data = Column(JSONB, nullable=False)  # Full CRM webhook payload

    # Ad/project context for agent pitch
    ad_source = Column(String(100), nullable=True)  # google_ads, facebook, instagram
    project_id = Column(String(100), nullable=True)  # Tenant's project identifier

    # Queue status lifecycle
    status = Column(String(20), nullable=False, default="pending")
    # pending  → waiting to be picked up
    # queued   → picked by worker, about to place call
    # calling  → call in progress
    # completed → call finished successfully
    # failed   → exhausted retries or permanent failure

    priority = Column(Integer, nullable=False, default=5)  # 1=highest, 10=lowest
    attempt_count = Column(Integer, nullable=False, default=0)
    max_attempts = Column(Integer, nullable=False, default=3)
    last_error = Column(Text, nullable=True)

    # Correlation
    correlation_id = Column(String(100), nullable=True)
    voice_session_id = Column(UUID(as_uuid=True), ForeignKey("voice_sessions.id"), nullable=True)

    # Post-call result
    call_outcome = Column(JSONB, nullable=True)
    # {
    #   "outcome": "interested|not_interested|callback|no_answer|busy",
    #   "summary": "...",
    #   "next_action": "...",
    #   "lead_temperature": "hot|warm|cold",
    #   "duration_seconds": 120
    # }

    # Timestamps
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    processed_at = Column(DateTime, nullable=True)

    # Relationships
    company = relationship("Company")
    agent = relationship("HierarchicalEntity")

    __table_args__ = (
        UniqueConstraint("company_id", "lead_id", name="uq_lead_queue_company_lead"),
        Index(
            "idx_lead_queue_pending",
            "company_id", "status", "priority", "created_at",
            postgresql_where=(Column("status") == "pending"),
        ),
        Index("idx_lead_queue_voice_session", "voice_session_id"),
    )
