"""orm/versions.py — immutable entity versions and their assets (EP-10, R2).

A run executes a version, not the live entity row: the row is the head that
edits change, and every run pins the version that matched it when the run was
created (see ``ai.governance.entity_versions``). Versions are append-only.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.common.tenancy.bases import TenantBase, refers_to

__all__ = ["EntityAsset", "EntityVersion"]


class EntityVersion(TenantBase):
    __tablename__ = "entity_versions"
    __table_args__ = (
        UniqueConstraint("entity_id", "version_number", name="uq_entity_versions_number"),
        Index("ix_entity_versions_content", "entity_id", "content_hash"),
        # A published version is its content: no two share it. A draft may
        # match one while it is edited; publishing it is refused.
        Index("uq_entity_versions_published_content", "entity_id", "content_hash",
              unique=True, postgresql_where=text("published")),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("hierarchical_entities.id"), nullable=False)
    # The entity's company — the APP company for a template's versions (PO-23).
    company_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, info=refers_to("companies.id"))
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    label: Mapped[str | None] = mapped_column(String, nullable=True)  # the entity's ``version`` string then
    # Name, type, goal and the nine blocks (``SNAPSHOT_FIELDS``). JSON, not
    # JSONB: ``io_contract``'s key order is the form's field order (DM-13).
    snapshot: Mapped[Any] = mapped_column(JSON, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    # A draft is authored and test-run; publishing makes it the head.
    published: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, info=refers_to("users.id"))
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, info=refers_to("users.id"))
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class EntityAsset(TenantBase):
    """A script or small text file belonging to one version (R2 §7)."""
    __tablename__ = "entity_assets"
    __table_args__ = (
        UniqueConstraint("entity_version_id", "path", name="uq_entity_assets_path"),
        Index("ix_entity_assets_version", "entity_version_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    entity_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("entity_versions.id", ondelete="CASCADE"), nullable=False,
    )
    path: Mapped[str] = mapped_column(String, nullable=False)          # relative POSIX path
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    language: Mapped[str | None] = mapped_column(String, nullable=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
