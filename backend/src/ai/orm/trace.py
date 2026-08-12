"""orm/trace.py — Execution trace spans (per-iteration transparency).

A single append-only ``execution_trace_events`` row models one **span** in a
run's work tree:

    run → iteration → executor → step → {tool, llm, child}

Spans are written by :class:`src.ai.core.trace.TraceRecorder`, which is bound to
a ``contextvars.ContextVar`` for the duration of a run so the deep legacy layers
(the ``@staticmethod`` tool executor, the LLM router) can record without
threading run context through their signatures. The table is observability data
ONLY — it is deliberately separate from the CORTEX memory trees so it can be
pruned independently and never pollutes semantic memory / the dreaming engine.

Read path: ``GET /ai/executions/{id}/trace`` returns every row for a run ordered
by ``seq``; the frontend assembles the tree from ``span_id`` / ``parent_span_id``.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.common.database import Base

__all__ = ["ExecutionTraceEvent"]


# Span kinds — the node types in the work tree.
TRACE_KINDS = ("iteration", "executor", "step", "child", "tool", "llm", "critic")

# Span lifecycle status.
TRACE_STATUSES = ("running", "success", "error")


class ExecutionTraceEvent(Base):
    """One span in a run's execution trace."""

    __tablename__ = "execution_trace_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("execution_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    company_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # Tree edges. ``span_id`` is the stable identity used by the close-update and
    # by the frontend to attach children; ``parent_span_id`` is NULL for the
    # run-root spans (iteration nodes).
    span_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    parent_span_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    iteration: Mapped[int | None] = mapped_column(Integer, nullable=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)        # see TRACE_KINDS
    name: Mapped[str | None] = mapped_column(String(512), nullable=True)        # tool id / model name / step name
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="running")

    # In-process monotonic ordering within a run (assigned by the recorder).
    seq: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)

    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    tokens_in: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tokens_out: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Links a ``child`` span to the sub-run whose own trace continues the tree.
    child_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # Full inputs / outputs / prompts / responses / error. The recorder caps any
    # single field at TRACE_MAX_FIELD_BYTES and replaces it with a truncation
    # marker, so a pathological multi-MB blob can't break the row.
    payload: Mapped[Any] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_execution_trace_events_run_seq", "run_id", "seq"),
        Index("ix_execution_trace_events_run_iter", "run_id", "iteration"),
        Index("ix_execution_trace_events_run_parent", "run_id", "parent_span_id"),
        # span_id lookup for the close-update.
        Index("ix_execution_trace_events_span", "span_id"),
    )
