"""orm/entity.py — HierarchicalEntity ORM (the agent kernel's primary table)."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, DateTime, ForeignKey, JSON, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.common.database import Base

if TYPE_CHECKING:
    from src.auth.models import Company, User
    from src.ai.orm.execution import ExecutionRun

__all__ = ["HierarchicalEntity"]


class HierarchicalEntity(Base):
    __tablename__ = "hierarchical_entities"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("hierarchical_entities.id"), nullable=True)
    version: Mapped[str] = mapped_column(String, nullable=False, default="1.0.0")
    type: Mapped[str] = mapped_column(String, nullable=False)  # ACTION, SKILL, AGENT, PROCESS
    status: Mapped[str] = mapped_column(String, nullable=False, default="ACTIVE")  # DRAFT, ACTIVE, DEPRECATED, ARCHIVED
    name: Mapped[str] = mapped_column(String, nullable=False)
    display_name: Mapped[str | None] = mapped_column(String, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    goal: Mapped[str | None] = mapped_column(Text, nullable=True)  # Entity's objective, used in prompt generation
    tags: Mapped[Any] = mapped_column(JSON, nullable=True)

    # Template fields
    is_template: Mapped[bool | None] = mapped_column(Boolean, default=False)  # True = blueprint, not executable
    template_source_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("hierarchical_entities.id"), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)

    # Unified structure fields
    identity: Mapped[Any] = mapped_column(JSON, nullable=True)
    hierarchy: Mapped[Any] = mapped_column(JSON, nullable=True)
    logic_gate: Mapped[Any] = mapped_column(JSON, nullable=True)
    planning: Mapped[Any] = mapped_column(JSON, nullable=True)
    capabilities: Mapped[Any] = mapped_column(JSON, nullable=True)
    governance: Mapped[Any] = mapped_column(JSON, nullable=True)
    io_contract: Mapped[Any] = mapped_column(JSON, nullable=True)
    observability: Mapped[Any] = mapped_column(JSON, nullable=True)
    metadata_extensions: Mapped[Any] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # Soft-delete timestamp; NULL = active

    company: Mapped["Company"] = relationship("Company")
    parent: Mapped["HierarchicalEntity | None"] = relationship(
        "HierarchicalEntity",
        remote_side=[id],
        backref="children",
        foreign_keys=[parent_id],
    )
    template_source: Mapped["HierarchicalEntity | None"] = relationship(
        "HierarchicalEntity",
        remote_side=[id],
        foreign_keys=[template_source_id],
    )
    creator: Mapped["User | None"] = relationship("User", foreign_keys=[created_by])
    execution_runs: Mapped[list["ExecutionRun"]] = relationship("ExecutionRun", back_populates="entity")
