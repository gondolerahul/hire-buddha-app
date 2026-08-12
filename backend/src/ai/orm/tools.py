"""orm/tools.py — Tool registry ORM."""
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

__all__ = ["ToolRegistryEntry"]


class ToolRegistryEntry(Base):
    """Persistent registry of both built-in and custom tools.

    Built-in tools are seeded at startup. Custom tools are created/managed
    by Application Admins via the Tool Management API.
    """
    __tablename__ = "tool_registry_entries"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=True)  # null = system-wide
    name: Mapped[str] = mapped_column(String, nullable=False, unique=True)  # Tool identifier (matches Tool.name)
    display_name: Mapped[str | None] = mapped_column(String, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str | None] = mapped_column(String, nullable=True)  # e.g., "browser", "social", "document", "utility"
    tool_type: Mapped[str] = mapped_column(String, nullable=False, default="BUILT_IN")  # BUILT_IN | CUSTOM
    function_schema: Mapped[Any] = mapped_column(JSON, nullable=True)  # OpenAI-compatible function schema
    is_enabled: Mapped[bool | None] = mapped_column(Boolean, default=True)
    configuration: Mapped[Any] = mapped_column(JSON, nullable=True)  # Custom config (API keys ref, etc.)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    company: Mapped["Company | None"] = relationship("Company")
    creator: Mapped["User | None"] = relationship("User", foreign_keys=[created_by])
