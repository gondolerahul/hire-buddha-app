"""orm/execution.py — Execution-run ORM and its child interaction logs."""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.common.database import Base

if TYPE_CHECKING:
    from src.auth.models import Company, User
    from src.ai.orm.entity import HierarchicalEntity
    from src.ai.orm.usage import UsageLog

__all__ = [
    "ExecutionRun",
    "LLMInteractionLog",
    "ToolInteractionLog",
    "HumanApproval",
]


class ExecutionRun(Base):
    __tablename__ = "execution_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("hierarchical_entities.id"), nullable=False)
    parent_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("execution_runs.id"), nullable=True)
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    status: Mapped[str | None] = mapped_column(String, default="PENDING")
    input_data: Mapped[Any] = mapped_column(JSON, nullable=True)
    dynamic_plan: Mapped[Any] = mapped_column(JSON, nullable=True)
    result_data: Mapped[Any] = mapped_column(JSON, nullable=True)
    context_state: Mapped[Any] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Metrics and Tracing
    total_cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), default=0)
    billed_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 6), nullable=True)  # TB formula result — the user-facing charge
    total_tokens: Mapped[int | None] = mapped_column(Integer, default=0)
    execution_time_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    trace_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    span_id: Mapped[str | None] = mapped_column(String, nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)  # Step-level dedup

    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=datetime.utcnow)

    # First-party CSAT signal on a completed run (Phase 12 `07` §6, P-O2): the
    # only ground-truth "was this good?" signal — feeds critic false-pass
    # calibration. +1 = thumbs up, -1 = thumbs down, NULL = not yet rated.
    csat_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    csat_comment: Mapped[str | None] = mapped_column(Text, nullable=True)

    company: Mapped["Company"] = relationship("Company")
    entity: Mapped["HierarchicalEntity"] = relationship("HierarchicalEntity", back_populates="execution_runs")
    parent_run: Mapped["ExecutionRun | None"] = relationship("ExecutionRun", remote_side=[id], backref="child_runs")
    llm_logs: Mapped[list["LLMInteractionLog"]] = relationship("LLMInteractionLog", back_populates="run")
    usage_logs: Mapped[list["UsageLog"]] = relationship("UsageLog", back_populates="run")
    human_approvals: Mapped[list["HumanApproval"]] = relationship("HumanApproval", back_populates="run")
    tool_logs: Mapped[list["ToolInteractionLog"]] = relationship("ToolInteractionLog", back_populates="run")


class LLMInteractionLog(Base):
    __tablename__ = "llm_interaction_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("execution_runs.id"), nullable=False)
    model_provider: Mapped[str] = mapped_column(String, nullable=False)
    model_name: Mapped[str] = mapped_column(String, nullable=False)
    input_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    output_response: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(10, 6), default=0)
    reasoning_mode: Mapped[str | None] = mapped_column(String, nullable=True)
    step_name: Mapped[str | None] = mapped_column(String, nullable=True)  # Associates this log with a specific plan step
    log_metadata: Mapped[Any] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=datetime.utcnow)

    run: Mapped["ExecutionRun"] = relationship("ExecutionRun", back_populates="llm_logs")


class ToolInteractionLog(Base):
    __tablename__ = "tool_interaction_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("execution_runs.id"), nullable=False)
    tool_id: Mapped[str] = mapped_column(String, nullable=False)
    tool_name: Mapped[str] = mapped_column(String, nullable=False)
    provider: Mapped[str | None] = mapped_column(String, nullable=True)
    input_parameters: Mapped[Any] = mapped_column(JSON, nullable=True)
    output_result: Mapped[Any] = mapped_column(JSON, nullable=True)
    success: Mapped[bool | None] = mapped_column(Boolean, default=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    log_metadata: Mapped[Any] = mapped_column(JSON, nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)  # Step-level dedup
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=datetime.utcnow)

    run: Mapped["ExecutionRun"] = relationship("ExecutionRun", back_populates="tool_logs")


class HumanApproval(Base):
    __tablename__ = "human_approvals"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("execution_runs.id"), nullable=False)
    checkpoint_trigger: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str | None] = mapped_column(String, default="PENDING")  # PENDING, APPROVED, REJECTED, TIMEOUT
    requested_by: Mapped[str | None] = mapped_column(String, nullable=True)
    responded_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    context_snapshot: Mapped[Any] = mapped_column(JSON, nullable=True)
    reviewer_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    notification_channels: Mapped[Any] = mapped_column(JSON, nullable=True)
    timeout_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    requested_at: Mapped[datetime | None] = mapped_column(DateTime, default=datetime.utcnow)
    responded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    run: Mapped["ExecutionRun"] = relationship("ExecutionRun", back_populates="human_approvals")
    reviewer: Mapped["User | None"] = relationship("User")
