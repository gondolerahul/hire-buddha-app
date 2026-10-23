"""orm/usage.py — UsageLog ORM (billing source-of-truth)."""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import CHAR, DateTime, ForeignKey, Index, Numeric, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.common.tenancy.bases import ControlBase, refers_to

if TYPE_CHECKING:
    from src.auth.models import Company
    from src.config.models import IntegrationRegistry

__all__ = ["UsageLog"]


class UsageLog(ControlBase):
    __tablename__ = "usage_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False)
    # The run is in its tenant's database: no foreign key (WS2 2.3).
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True, info=refers_to("execution_runs.id"))  # DM-06
    # NULL for a charge with no registry row — a fixed-cost tool (BC-07).
    sku_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("integration_registry.id"), nullable=True)
    # Exact to 10 decimals (Phase 15 T1-5; was 6).
    raw_quantity: Mapped[Decimal] = mapped_column(Numeric(24, 10), nullable=False)
    calculated_cost: Mapped[Decimal] = mapped_column(Numeric(24, 10), nullable=False)
    log_metadata: Mapped[Any] = mapped_column(JSONB, nullable=True)
    # Structured attribution tag for cost breakdown (see services/cost_attribution.py).
    attribution: Mapped[str] = mapped_column(String(40), nullable=False, server_default="tool")
    # Rated at write (Phase 15 T3-3, src/billing/rating.py): what the customer is
    # billed for this row, the formula version used, and the billing category.
    billed_usd: Mapped[Decimal | None] = mapped_column(Numeric(24, 10), nullable=True)
    formula_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    category: Mapped[str | None] = mapped_column(String(30), nullable=True)
    # Filled when the row is settled (WS15-4): the settlement, and the amount in
    # the company's currency at the locked rate (FX-4).
    settlement_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    currency: Mapped[str | None] = mapped_column(CHAR(3), nullable=True)
    billed_ccy: Mapped[Decimal | None] = mapped_column(Numeric(24, 10), nullable=True)
    fx_rate_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    company: Mapped["Company"] = relationship("Company")
    sku: Mapped["IntegrationRegistry | None"] = relationship("IntegrationRegistry")

    __table_args__ = (
        Index("ix_usage_logs_attribution", "attribution"),
        Index("ix_usage_logs_unsettled", "company_id", postgresql_where=text("settlement_id IS NULL")),
    )
