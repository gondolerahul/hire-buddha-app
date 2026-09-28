"""
cortex_memory.models — CORTEX ORM (CortexTree / CortexNode / CortexEdge).

Owned by the package on its own ``Base`` (``cortex_memory.db``). External
references (company/user/entity/run) are **opaque nullable UUID columns** — no
``ForeignKey`` to host tables and no cross-package relationships — so the schema
is self-contained (plan `04` K5). Column names/types/indexes/enum type names are
byte-for-byte the host's, so the models map onto an existing host DB unchanged.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

import pgvector.sqlalchemy
from sqlalchemy import (
    Boolean,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from cortex_memory.db import Base
from cortex_memory.enums import (
    CortexNodeStatus,
    CortexNodeType,
    CortexTreeStatus,
    MemoryDomain,
    ScopeLevel,
)


class CortexTree(Base):
    """A persistent cognitive tree owned by an entity (agent) for a task.

    The tree IS the agent's complete cognitive state; the context window is a
    viewport onto it. ``resume_cursor_id`` always points at the last node worked
    on, enabling deterministic resumption.
    """

    __tablename__ = "cortex_trees"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # Opaque external references (no FK to host tables — K5).
    entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    task_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[CortexTreeStatus] = mapped_column(
        SAEnum(CortexTreeStatus, name="cortex_tree_status", create_constraint=True,
               values_callable=lambda x: [e.value for e in x]),
        default=CortexTreeStatus.ACTIVE,
        nullable=False,
    )

    total_nodes: Mapped[int] = mapped_column(Integer, default=0, nullable=True)
    root_node_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    output_root_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    resume_cursor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    max_children: Mapped[int] = mapped_column(Integer, default=12, nullable=True)
    page_size_tokens: Mapped[int] = mapped_column(Integer, default=8000, nullable=True)
    context_budget_pct: Mapped[int] = mapped_column(Integer, default=40, nullable=True)

    resume_schedule: Mapped[str | None] = mapped_column(String(100), nullable=True)
    next_resume_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    memory_domain: Mapped[MemoryDomain] = mapped_column(
        SAEnum(MemoryDomain, name="memory_domain", create_constraint=False,
               values_callable=lambda x: [e.value for e in x]),
        default=MemoryDomain.KNOWLEDGE,
        server_default="knowledge",
        nullable=False,
    )
    scope_level: Mapped[ScopeLevel] = mapped_column(
        SAEnum(ScopeLevel, name="scope_level", create_constraint=False,
               values_callable=lambda x: [e.value for e in x]),
        default=ScopeLevel.RUNTIME,
        server_default="runtime",
        nullable=False,
    )

    # Opaque scope-hierarchy references (no FK — K5).
    app_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    partner_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    tree_category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    is_persistent: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", nullable=True)

    last_consolidated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    consolidation_generation: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=True)
    source_run_ids: Mapped[Any] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=True)
    last_active_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=True)

    # Intra-package relationship only.
    nodes: Mapped[list["CortexNode"]] = relationship(
        "CortexNode", back_populates="tree", cascade="all, delete-orphan",
        foreign_keys="CortexNode.tree_id",
    )

    __table_args__ = (
        Index("ix_cortex_trees_entity_id", "entity_id"),
        Index("ix_cortex_trees_company_id", "company_id"),
        Index("ix_cortex_trees_status", "status"),
        Index("ix_cortex_trees_domain_scope", "memory_domain", "scope_level"),
        Index("ix_cortex_trees_scope_company", "scope_level", "company_id"),
    )


class CortexNode(Base):
    """Every piece of CORTEX information — input section, finding, sub-task,
    output section — is a CortexNode."""

    __tablename__ = "cortex_nodes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tree_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("cortex_trees.id", ondelete="CASCADE"), nullable=False)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("cortex_nodes.id", ondelete="SET NULL"), nullable=True)

    node_type: Mapped[CortexNodeType] = mapped_column(
        SAEnum(CortexNodeType, name="cortex_node_type", create_constraint=False,
               values_callable=lambda x: [e.value for e in x]),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=True)

    status: Mapped[CortexNodeStatus] = mapped_column(
        SAEnum(CortexNodeStatus, name="cortex_node_status", create_constraint=True,
               values_callable=lambda x: [e.value for e in x]),
        default=CortexNodeStatus.PENDING,
        nullable=False,
    )

    source_ref: Mapped[Any] = mapped_column(JSONB, nullable=True)

    # Opaque execution-run reference (no FK — K5).
    execution_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    depth: Mapped[int] = mapped_column(Integer, default=0, nullable=True)
    sibling_order: Mapped[int] = mapped_column(Integer, default=0, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=True)

    metadata_extra: Mapped[Any] = mapped_column(JSONB, nullable=True)

    embedding: Mapped[Any] = mapped_column(pgvector.sqlalchemy.Vector(768), nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(100), nullable=True)

    cross_refs: Mapped[Any] = mapped_column(JSONB, nullable=True)

    access_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=True)
    last_accessed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    importance_score: Mapped[Decimal] = mapped_column(Numeric(5, 3), default=Decimal("0.500"), server_default="0.500", nullable=True)

    tree: Mapped["CortexTree"] = relationship("CortexTree", back_populates="nodes", foreign_keys=[tree_id])
    parent: Mapped["CortexNode | None"] = relationship(
        "CortexNode", remote_side=[id], backref="children", foreign_keys=[parent_id],
    )
    outgoing_edges: Mapped[list["CortexEdge"]] = relationship(
        "CortexEdge", foreign_keys="CortexEdge.source_node_id",
        back_populates="source_node", cascade="all, delete-orphan",
    )
    incoming_edges: Mapped[list["CortexEdge"]] = relationship(
        "CortexEdge", foreign_keys="CortexEdge.target_node_id",
        back_populates="target_node", cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_cortex_nodes_tree_id", "tree_id"),
        Index("ix_cortex_nodes_parent_id", "parent_id"),
        Index("ix_cortex_nodes_tree_parent", "tree_id", "parent_id"),
        Index("ix_cortex_nodes_tree_type", "tree_id", "node_type"),
        Index("ix_cortex_nodes_status", "status"),
        Index("ix_cortex_nodes_tree_type_status", "tree_id", "node_type", "status"),
    )


class CortexEdge(Base):
    """A weighted, typed edge connecting two CortexNodes (the semantic graph)."""

    __tablename__ = "cortex_edges"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_node_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cortex_nodes.id", ondelete="CASCADE"), nullable=False)
    target_node_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cortex_nodes.id", ondelete="CASCADE"), nullable=False)
    edge_type: Mapped[str] = mapped_column(String(50), nullable=False)
    weight: Mapped[Decimal] = mapped_column(Numeric(5, 4), default=Decimal("0.5000"), server_default="0.5000", nullable=True)
    traversal_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=True)
    last_traversed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(50), nullable=True)
    edge_metadata: Mapped[Any] = mapped_column("metadata", JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=True)

    source_node: Mapped["CortexNode"] = relationship(
        "CortexNode", foreign_keys=[source_node_id], back_populates="outgoing_edges")
    target_node: Mapped["CortexNode"] = relationship(
        "CortexNode", foreign_keys=[target_node_id], back_populates="incoming_edges")

    __table_args__ = (
        UniqueConstraint("source_node_id", "target_node_id", "edge_type",
                         name="uq_cortex_edges_src_tgt_type"),
        Index("ix_cortex_edges_source", "source_node_id"),
        Index("ix_cortex_edges_target", "target_node_id"),
        Index("ix_cortex_edges_type_weight", "edge_type", weight.desc()),
    )


__all__ = [
    "Base",
    "CortexTree",
    "CortexNode",
    "CortexEdge",
    "CortexTreeStatus",
    "CortexNodeType",
    "CortexNodeStatus",
    "MemoryDomain",
    "ScopeLevel",
]
