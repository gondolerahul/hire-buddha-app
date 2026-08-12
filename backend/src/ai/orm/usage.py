"""orm/usage.py — UsageLog ORM (billing source-of-truth)."""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, ForeignKey, Index, JSON, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.common.database import Base

if TYPE_CHECKING:
    from src.auth.models import Company
    from src.config.models import IntegrationRegistry
    from src.ai.orm.execution import ExecutionRun

__all__ = ["UsageLog"]


class UsageLog(Base):
    __tablename__ = "usage_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    timestamp: Mapped[datetime | None] = mapped_column(DateTime, default=datetime.utcnow)
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False)
    run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("execution_runs.id"), nullable=True)
    sku_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("integration_registry.id"), nullable=False)
    raw_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    calculated_cost: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    log_metadata: Mapped[Any] = mapped_column(JSON, nullable=True)
    # Structured attribution tag for cost breakdown (see services/cost_attribution.py).
    attribution: Mapped[str] = mapped_column(String(40), nullable=False, server_default="tool")

    company: Mapped["Company"] = relationship("Company")
    run: Mapped["ExecutionRun | None"] = relationship("ExecutionRun", back_populates="usage_logs")
    sku: Mapped["IntegrationRegistry"] = relationship("IntegrationRegistry")

    __table_args__ = (
        Index("ix_usage_logs_attribution", "attribution"),
    )
