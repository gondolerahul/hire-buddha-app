"""
Campaign models for bulk voice calling.

Stores campaign metadata, execution state, and call tracking.
"""
from datetime import datetime
from uuid import uuid4
from sqlalchemy import (
    Column, String, Integer, Boolean, DateTime, Text, ForeignKey, case
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from src.common.database import Base

# Report ordering: positive responses first, then descending usefulness.
# Applied to both the campaign detail API and the Excel export.
DISPOSITION_PRIORITY = {
    "interested": 0,
    "not_interested": 1,
    "voicemail": 3,
    "rejected": 4,
    "busy": 5,
    "no_answer": 6,
    "failed": 7,
}

# Fallback rank for calls without a disposition yet: completed calls (awaiting
# LLM classification) outrank every failure bucket; in-flight calls sort last.
_STATUS_FALLBACK_PRIORITY = {
    "completed": 2,
    "completed-voicemail": 3,
    "failed": 7,
}


def campaign_call_sort_order():
    """SQL CASE expression ranking CampaignCall rows by disposition,
    falling back to status for unclassified rows."""
    return case(
        DISPOSITION_PRIORITY,
        value=CampaignCall.disposition,
        else_=case(
            _STATUS_FALLBACK_PRIORITY,
            value=CampaignCall.status,
            else_=50,
        ),
    )


class Campaign(Base):
    """Voice calling campaign model."""
    __tablename__ = "campaigns"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    agent_id = Column(UUID(as_uuid=True), ForeignKey("hierarchical_entities.id"), nullable=False)
    
    # Campaign details
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    
    # Contact list
    total_contacts = Column(Integer, nullable=False, default=0)
    contact_list = Column(JSONB, nullable=False)  # Array of contact objects
    
    # Configuration
    provider = Column(String(20), nullable=False, default="twilio")  # 'twilio' | 'tata_tele'
    call_script_template = Column(Text, nullable=True)  # Custom script template
    
    # Scheduling
    scheduled_start = Column(DateTime, nullable=True)
    scheduled_end = Column(DateTime, nullable=True)
    
    # Throttling
    max_concurrent_calls = Column(Integer, nullable=False, default=5)
    max_calls_per_hour = Column(Integer, nullable=True)
    
    # Execution mode: 'server_dialer' (Arq executor dials via provider API) or
    # 'mobile_conference' (reps dial from the Android app; never run by Arq).
    execution_mode = Column(String(30), nullable=False, default="server_dialer", server_default="server_dialer")
    contact_upload_id = Column(UUID(as_uuid=True), nullable=True)

    # Status
    status = Column(String(20), nullable=False, default="draft")  # draft | scheduled | running | paused | completed | failed
    
    # Execution tracking
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    calls_initiated = Column(Integer, nullable=False, default=0)
    calls_completed = Column(Integer, nullable=False, default=0)
    calls_failed = Column(Integer, nullable=False, default=0)
    
    # Results summary
    outcome_distribution = Column(JSONB, nullable=True)  # {"success": 10, "no_answer": 5, ...}
    
    # Metadata
    campaign_metadata = Column("metadata", JSONB, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    company = relationship("Company")
    created_by_user = relationship("User")
    agent = relationship("HierarchicalEntity")


class CampaignCall(Base):
    """Individual call within a campaign."""
    __tablename__ = "campaign_calls"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    campaign_id = Column(UUID(as_uuid=True), ForeignKey("campaigns.id"), nullable=False)
    voice_session_id = Column(UUID(as_uuid=True), ForeignKey("voice_sessions.id"), nullable=True)
    
    # Contact info
    contact_data = Column(JSONB, nullable=False)  # Phone, name, custom fields
    
    # Call status
    status = Column(String(20), nullable=False, default="pending")  # pending | leased | calling | completed | completed-voicemail | failed | skipped

    # Mobile dialer lease: a rep's device holds the lead while dialing it.
    leased_by_user_id = Column(UUID(as_uuid=True), nullable=True)
    leased_by_device_id = Column(UUID(as_uuid=True), nullable=True)
    lease_expires_at = Column(DateTime, nullable=True)
    call_sid = Column(String(100), nullable=True)

    # Outcome
    outcome = Column(String(50), nullable=True)  # success | no_answer | busy | failed | refused | voicemail
    outcome_notes = Column(Text, nullable=True)
    # Structured result for report sorting; see DISPOSITION_PRIORITY.
    # interested | not_interested | voicemail | rejected | busy | no_answer | failed
    # NULL while pending/calling, or for answered calls awaiting LLM classification.
    disposition = Column(String(30), nullable=True)
    # Why the lead was not interested (LLM-classified, only when
    # disposition = not_interested); see NOT_INTERESTED_REASONS in call_guards.
    # budget_low | not_suitable | not_investing | already_bought | other
    disposition_reason = Column(String(30), nullable=True)

    # The rep's own read of the call, captured in the app's wrap-up sheet. The rep
    # heard the conversation; the model only read a transcript of it. `disposition`
    # above stays the effective value every report uses -- these record where that
    # value came from, and keep the human answer if a later LLM pass disagrees.
    # db-scripts/mobile_dialer_002.sql
    rep_disposition = Column(String(30), nullable=True)
    rep_note = Column(Text, nullable=True)
    rep_dispositioned_at = Column(DateTime, nullable=True)
    rep_dispositioned_by = Column(UUID(as_uuid=True), nullable=True)
    disposition_source = Column(String(10), nullable=True)  # ai | rep

    # A lead the rep agreed to call back later. Held out of the leasing query
    # until its time comes; see src/mobile/service.py _LEASE_SQL.
    callback_at = Column(DateTime, nullable=True)

    # Timing
    scheduled_at = Column(DateTime, nullable=True)
    called_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    duration_seconds = Column(Integer, nullable=True)
    
    # Retry tracking
    retry_count = Column(Integer, nullable=False, default=0)
    max_retries = Column(Integer, nullable=False, default=2)
    
    # Metadata
    call_metadata = Column("metadata", JSONB, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    
    # Relationships
    campaign = relationship("Campaign")
    voice_session = relationship("VoiceSession")
