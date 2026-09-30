"""orm/feature_flags.py — the ``feature_flags`` table (DM-03).

Created by migration ``p11t02_feature_flags`` and read with raw SQL by
``ai.core.feature_flags``. This model exists so Alembic autogenerate and the
schema census see the table: without it, autogenerate never proposed a change to
it, and a database missing it looked exactly like one where every flag sat at
its default.

One row per (flag, scope): an entity (``entity_id``), a company
(``company_id``, no entity) or the platform (neither). Each scope has its own
partial unique index, because NULLs are distinct in an ordinary unique index.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Index, JSON, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.common.database import Base

__all__ = ["FeatureFlag"]


class FeatureFlag(Base):
    __tablename__ = "feature_flags"
    __table_args__ = (
        Index("ix_feature_flags_global", "flag_key", unique=True,
              postgresql_where=text("company_id IS NULL AND entity_id IS NULL")),
        Index("ix_feature_flags_company", "flag_key", "company_id", unique=True,
              postgresql_where=text("company_id IS NOT NULL AND entity_id IS NULL")),
        Index("ix_feature_flags_entity", "flag_key", "entity_id", unique=True,
              postgresql_where=text("entity_id IS NOT NULL")),
        Index("ix_feature_flags_company_lookup", "company_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True,
                                          server_default=text("gen_random_uuid()"))
    company_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    flag_key: Mapped[str] = mapped_column(String(128), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    value_json: Mapped[Any] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=text("now()"))
