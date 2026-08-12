"""orm/memory.py — Legacy EpisodicMemory ORM (v1 episodic backing table)."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.common.database import Base

__all__ = ["EpisodicMemory"]


class EpisodicMemory(Base):
    """S1: Short-term interaction record.

    One row per completed ExecutionRun (for top-level runs only).
    """
    __tablename__ = "episodic_memories"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("hierarchical_entities.id"), nullable=False)
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("execution_runs.id"), nullable=True)

    input_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    total_cost_usd: Mapped[str | None] = mapped_column(String(20), nullable=True)
    total_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    execution_time_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    metadata_info: Mapped[Any] = mapped_column(JSON, nullable=True)  # avoiding 'metadata' reserved word
    channel: Mapped[str | None] = mapped_column(String(50), nullable=True)
    tree_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("cortex_trees.id"), nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=datetime.utcnow)
