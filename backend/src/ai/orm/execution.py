"""orm/execution.py — Execution-run ORM and its child interaction logs."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    event,
    select,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.orm.base import NO_VALUE

from src.common.database import Base

logger = logging.getLogger(__name__)

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
    # The list endpoints filter on company or entity and sort by newest; child
    # runs are found by their parent (DM-05). A B-tree serves ``DESC`` too.
    __table_args__ = (
        Index("ix_execution_runs_company_created", "company_id", "created_at"),
        Index("ix_execution_runs_entity_created", "entity_id", "created_at"),
        Index("ix_execution_runs_parent_run_id", "parent_run_id"),
        # Target of the child tables' (run_id, company_id) key (DM-09).
        UniqueConstraint("id", "company_id", name="uq_execution_runs_id_company"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("hierarchical_entities.id"), nullable=False)
    parent_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("execution_runs.id"), nullable=True)
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    status: Mapped[str | None] = mapped_column(String, default="PENDING")
    input_data: Mapped[Any] = mapped_column(JSONB, nullable=True)
    dynamic_plan: Mapped[Any] = mapped_column(JSONB, nullable=True)
    result_data: Mapped[Any] = mapped_column(JSONB, nullable=True)
    # Stays JSON (DM-13): key order is step order — the step executor keeps the
    # most recent steps when it trims — and a resumed run reads it back.
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

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

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


@event.listens_for(ExecutionRun.status, "set", retval=True)
def _enforce_run_transition(target: ExecutionRun, value: Any, oldvalue: Any, initiator: Any) -> Any:
    """Refuse an illegal run-status change; keep the old status (DM-17).

    Every ORM write of ``ExecutionRun.status`` passes here. A change the state
    machine (``schemas.enums.VALID_TRANSITIONS``) does not allow is refused —
    the attribute keeps its old value and a warning is logged — rather than
    raised, so the rest of the caller's write (a cancelled run's cost and
    result, say) still lands. A status that was never loaded cannot be checked
    and is let through; so are Core ``UPDATE`` statements, which bypass the ORM.
    """
    if oldvalue is NO_VALUE or oldvalue is None:
        return value
    from src.ai.schemas.enums import validate_transition

    old, new = str(getattr(oldvalue, "value", oldvalue)), str(getattr(value, "value", value))
    if validate_transition(old, new):
        return value
    logger.warning("run %s: refused status change %s -> %s; it stays %s", target.id, old, new, old)
    return oldvalue


def run_company_key(table: str, **kw: Any) -> ForeignKeyConstraint:
    """``(run_id, company_id) → execution_runs(id, company_id)`` (DM-09).

    The child row's ``company_id`` is a copy of its run's, so a query can be
    scoped without joining the run — a forgotten join is then still scoped
    rather than cross-tenant. The composite key keeps the copy equal to the
    run's company; it also does the job of a plain ``run_id`` key.
    """
    return ForeignKeyConstraint(["run_id", "company_id"], ["execution_runs.id", "execution_runs.company_id"],
                                name=f"fk_{table}_run_company", **kw)


class LLMInteractionLog(Base):
    __tablename__ = "llm_interaction_logs"
    __table_args__ = (
        run_company_key("llm_interaction_logs"),
        Index("ix_llm_interaction_logs_company_created", "company_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)  # DM-06
    # The run's company; filled from the run on insert when not given (DM-09).
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
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
    log_metadata: Mapped[Any] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    run: Mapped["ExecutionRun"] = relationship("ExecutionRun", back_populates="llm_logs")


class ToolInteractionLog(Base):
    __tablename__ = "tool_interaction_logs"
    __table_args__ = (
        run_company_key("tool_interaction_logs"),
        Index("ix_tool_interaction_logs_company_created", "company_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)  # DM-06
    # The run's company; filled from the run on insert when not given (DM-09).
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    tool_id: Mapped[str] = mapped_column(String, nullable=False)
    tool_name: Mapped[str] = mapped_column(String, nullable=False)
    # The plan step that made the call, as on llm_interaction_logs (FE-10).
    step_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    provider: Mapped[str | None] = mapped_column(String, nullable=True)
    input_parameters: Mapped[Any] = mapped_column(JSONB, nullable=True)
    output_result: Mapped[Any] = mapped_column(JSONB, nullable=True)
    success: Mapped[bool | None] = mapped_column(Boolean, default=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    log_metadata: Mapped[Any] = mapped_column(JSONB, nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)  # Step-level dedup
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    run: Mapped["ExecutionRun"] = relationship("ExecutionRun", back_populates="tool_logs")


class HumanApproval(Base):
    __tablename__ = "human_approvals"
    __table_args__ = (
        run_company_key("human_approvals"),
        # The approvals inbox: a company's PENDING requests.
        Index("ix_human_approvals_company_status", "company_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)  # DM-06
    # The run's company; filled from the run on insert when not given (DM-09).
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    checkpoint_trigger: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str | None] = mapped_column(String, default="PENDING")  # PENDING, APPROVED, REJECTED, TIMEOUT
    requested_by: Mapped[str | None] = mapped_column(String, nullable=True)
    responded_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    context_snapshot: Mapped[Any] = mapped_column(JSONB, nullable=True)
    reviewer_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    notification_channels: Mapped[Any] = mapped_column(JSONB, nullable=True)
    timeout_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    run: Mapped["ExecutionRun"] = relationship("ExecutionRun", back_populates="human_approvals")
    reviewer: Mapped["User | None"] = relationship("User")


def _company_from_run(mapper: Any, connection: Any, target: Any) -> None:
    """Copy the run's company onto a new child row that was not given one (DM-09).

    The writers pass ``run_id``; this saves each of them from also looking up
    the company, and a new writer from forgetting to.
    """
    if target.company_id is None and target.run_id is not None:
        runs = ExecutionRun.__table__
        target.company_id = connection.execute(
            select(runs.c.company_id).where(runs.c.id == target.run_id)
        ).scalar_one_or_none()


for _child in (LLMInteractionLog, ToolInteractionLog, HumanApproval):
    event.listen(_child, "before_insert", _company_from_run)
