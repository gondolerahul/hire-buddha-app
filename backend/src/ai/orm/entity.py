"""orm/entity.py — HierarchicalEntity ORM (the agent kernel's primary table)."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, DateTime, ForeignKey, JSON, String, Text, event
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, ORMExecuteState, Session, mapped_column, relationship, with_loader_criteria

from src.common.database import Base

if TYPE_CHECKING:
    from src.auth.models import Company, User
    from src.ai.orm.execution import ExecutionRun

__all__ = ["HierarchicalEntity", "INCLUDE_DELETED"]


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


# ── Soft delete is filtered by default (DM-16) ──────────────────────────────
# Deleting an entity sets status = 'DELETED'; the row stays so runs, usage and
# billing keep their foreign keys. Every ORM SELECT *of entities* — the entity
# itself or any of its columns — hides those rows unless it opts out with
# ``.execution_options(include_deleted=True)``. Before this, each query had to
# remember ``status != 'DELETED'`` and about forty did not: a deleted agent still
# answered calls, could be given a phone number, and showed on the partner
# console.
#
# Not filtered, on purpose: a statement that only joins through entities
# without selecting them, relationship loads (``run.entity`` still returns the
# entity a historical run belongs to), and raw SQL (``text()``). Reports that
# show history by entity name opt out. The filter is attached only when the
# entity is selected because SQLAlchemy's selectin loader copies a statement's
# options into its own query: a criteria added to "SELECT runs" would hide a
# deleted run's entity from ``selectinload(ExecutionRun.entity)``.
INCLUDE_DELETED = "include_deleted"


def _selects_entities(state: ORMExecuteState) -> bool:
    descriptions = getattr(state.statement, "column_descriptions", None) or []
    return any(d.get("entity") is HierarchicalEntity for d in descriptions)


@event.listens_for(Session, "do_orm_execute")
def _hide_soft_deleted_entities(state: ORMExecuteState) -> None:
    if (
        state.is_select
        and not state.is_column_load
        and not state.is_relationship_load
        and not state.execution_options.get(INCLUDE_DELETED, False)
        and _selects_entities(state)
    ):
        state.statement = state.statement.options(
            with_loader_criteria(
                HierarchicalEntity,
                lambda cls: cls.status != "DELETED",
                include_aliases=False,
                propagate_to_loaders=False,
            )
        )
