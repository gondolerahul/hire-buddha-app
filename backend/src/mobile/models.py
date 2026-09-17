"""
ORM models for the mobile dialer (docs 06 §1).

Timestamps are naive UTC (``datetime.utcnow``) to match the rest of the
schema. Partial unique indexes enforce the identification invariants:
one open attempt per device, and DTMF tokens unique among open attempts on
a DID.
"""
from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    Boolean, Column, DateTime, ForeignKey, Index, Integer, PrimaryKeyConstraint,
    String, text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from src.common.database import Base

# Attempt statuses (docs 04 §6.1)
ATTEMPT_PENDING = "pending"
ATTEMPT_AI_CONNECTED = "ai_connected"
ATTEMPT_AI_READY = "ai_ready"
ATTEMPT_UNIDENTIFIED_READY = "unidentified_ready"
ATTEMPT_MERGED = "merged"
ATTEMPT_COMPLETED = "completed"
ATTEMPT_COMPLETED_VOICEMAIL = "completed_voicemail"
ATTEMPT_LEAD_FAILED = "lead_failed"
ATTEMPT_MERGE_FAILED = "merge_failed"
ATTEMPT_AI_FAILED = "ai_failed"
ATTEMPT_SKIPPED = "skipped"
ATTEMPT_EXPIRED = "expired"
ATTEMPT_SUPERSEDED = "superseded"
ATTEMPT_ABANDONED = "abandoned"

OPEN_ATTEMPT_STATUSES = (
    ATTEMPT_PENDING, ATTEMPT_AI_CONNECTED, ATTEMPT_AI_READY,
    ATTEMPT_UNIDENTIFIED_READY, ATTEMPT_MERGED,
)
# Attempts a new inbound AI leg may still bind to.
BINDABLE_ATTEMPT_STATUSES = (ATTEMPT_PENDING, ATTEMPT_AI_CONNECTED)

IDENT_CLI = "cli"
IDENT_DTMF = "dtmf"
IDENT_CLI_DTMF = "cli+dtmf"
IDENT_RECONCILED = "reconciled"
IDENT_UNIDENTIFIED = "unidentified"

DEVICE_UNVERIFIED = "unverified"
DEVICE_VERIFIED = "verified"
DEVICE_REVOKED = "revoked"

RUN_RUNNING = "running"
RUN_PAUSED = "paused"
RUN_STOPPED = "stopped"
RUN_COMPLETED = "completed"

EXECUTION_MODE_SERVER = "server_dialer"
EXECUTION_MODE_MOBILE = "mobile_conference"

# voice_sessions.session_metadata["mode"]
SESSION_MODE_MOBILE = "mobile_conference"
SESSION_MODE_VERIFICATION = "device_verification"


def _open_status_sql(statuses) -> str:
    return "status IN (" + ", ".join(f"'{s}'" for s in statuses) + ")"


class UserDevice(Base):
    __tablename__ = "user_devices"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    install_id = Column(String(64), nullable=False, unique=True)
    platform = Column(String(20), nullable=False, default="android")
    model = Column(String(100), nullable=True)
    os_version = Column(String(30), nullable=True)
    app_version = Column(String(50), nullable=True)
    fcm_token = Column(String(512), nullable=True)
    phone_account_label = Column(String(100), nullable=True)

    # Caller ID exactly as the provider presented it, plus its E.164 form.
    presented_cli = Column(String(40), nullable=True)
    verified_cli = Column(String(20), nullable=True, index=True)
    cli_available = Column(Boolean, nullable=False, default=False)

    status = Column(String(20), nullable=False, default=DEVICE_UNVERIFIED)
    verification_code_hash = Column(String(128), nullable=True)
    verification_did = Column(String(20), nullable=True)
    verification_expires_at = Column(DateTime, nullable=True)
    verified_at = Column(DateTime, nullable=True)
    last_seen_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("ix_user_devices_verification_did", "verification_did", "verification_expires_at"),
    )


class ContactUpload(Base):
    __tablename__ = "contact_uploads"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False, index=True)
    uploaded_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    filename = Column(String(255), nullable=False)
    file_type = Column(String(10), nullable=False)
    total_rows = Column(Integer, nullable=False, default=0)
    valid_rows = Column(Integer, nullable=False, default=0)
    invalid_rows = Column(Integer, nullable=False, default=0)
    duplicate_rows = Column(Integer, nullable=False, default=0)
    columns = Column(JSONB, nullable=False, default=list)
    phone_column = Column(String(255), nullable=True)
    valid_contacts = Column(JSONB, nullable=False, default=list)
    errors = Column(JSONB, nullable=False, default=list)
    consumed_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class CampaignAssignee(Base):
    __tablename__ = "campaign_assignees"

    campaign_id = Column(UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    assigned_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (PrimaryKeyConstraint("campaign_id", "user_id"),)


class MobileCampaignRun(Base):
    __tablename__ = "mobile_campaign_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False, index=True)
    campaign_id = Column(UUID(as_uuid=True), ForeignKey("campaigns.id"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    device_id = Column(UUID(as_uuid=True), ForeignKey("user_devices.id"), nullable=False)
    status = Column(String(20), nullable=False, default=RUN_RUNNING)
    dial_order = Column(String(20), nullable=False, default="ai_first")
    started_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    ended_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index(
            "uq_mobile_run_running_per_device", "device_id", unique=True,
            postgresql_where=text("status IN ('running', 'paused')"),
        ),
    )


class MobileCallAttempt(Base):
    __tablename__ = "mobile_call_attempts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False, index=True)
    campaign_id = Column(UUID(as_uuid=True), ForeignKey("campaigns.id"), nullable=False, index=True)
    campaign_call_id = Column(UUID(as_uuid=True), ForeignKey("campaign_calls.id"), nullable=False, index=True)
    run_id = Column(UUID(as_uuid=True), ForeignKey("mobile_campaign_runs.id"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    device_id = Column(UUID(as_uuid=True), ForeignKey("user_devices.id"), nullable=False)
    agent_id = Column(UUID(as_uuid=True), ForeignKey("hierarchical_entities.id"), nullable=False)

    device_cli = Column(String(20), nullable=True)
    did = Column(String(20), nullable=False)
    dtmf_token = Column(String(8), nullable=False)
    dial_order = Column(String(20), nullable=False, default="ai_first")
    status = Column(String(30), nullable=False, default=ATTEMPT_PENDING)
    identification_method = Column(String(20), nullable=True)
    identification_conflict = Column(Boolean, nullable=False, default=False)
    assisted = Column(Boolean, nullable=False, default=False)
    voice_session_id = Column(UUID(as_uuid=True), ForeignKey("voice_sessions.id"), nullable=True, index=True)

    expires_at = Column(DateTime, nullable=False)
    ai_answered_at = Column(DateTime, nullable=True)
    ai_ready_at = Column(DateTime, nullable=True)
    lead_dialed_at = Column(DateTime, nullable=True)
    lead_answered_at = Column(DateTime, nullable=True)
    merged_at = Column(DateTime, nullable=True)
    ended_at = Column(DateTime, nullable=True)

    lead_failure_cause = Column(String(30), nullable=True)
    end_reason = Column(String(50), nullable=True)
    lead_ring_seconds = Column(Integer, nullable=True)
    conversation_seconds = Column(Integer, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index(
            "uq_attempt_open_per_device", "device_id", unique=True,
            postgresql_where=text(_open_status_sql(OPEN_ATTEMPT_STATUSES)),
        ),
        Index(
            "ix_attempt_cli_lookup", "device_cli", "did",
            postgresql_where=text(_open_status_sql(BINDABLE_ATTEMPT_STATUSES)),
        ),
        Index(
            "uq_attempt_token_open", "did", "dtmf_token", unique=True,
            postgresql_where=text(_open_status_sql(OPEN_ATTEMPT_STATUSES)),
        ),
    )


class MobileCallEvent(Base):
    __tablename__ = "mobile_call_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    attempt_id = Column(UUID(as_uuid=True), ForeignKey("mobile_call_attempts.id", ondelete="CASCADE"), nullable=False)
    seq = Column(Integer, nullable=False)
    type = Column(String(40), nullable=False)
    device_ts = Column(DateTime, nullable=True)
    elapsed_ms = Column(Integer, nullable=True)
    received_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    payload = Column(JSONB, nullable=False, default=dict)

    __table_args__ = (
        Index("uq_event_seq", "attempt_id", "seq", unique=True),
    )
