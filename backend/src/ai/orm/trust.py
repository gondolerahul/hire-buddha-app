"""orm/trust.py — learned per-source provenance trust (Phase 12 `07` §3).

``Provenance.trust_score`` is a static per-source-type prior in the CORTEX
package. This host-side table records the *learned*, in-tenant adjustment: how
often knowledge from a given source survived critic review / contributed to a
successful run. Trust is a smoothed (Beta-style) estimate over those outcomes,
blended with the static prior until enough observations accumulate.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.common.database import Base

if TYPE_CHECKING:
    from src.auth.models import Company

__all__ = ["SourceTrustScore"]


class SourceTrustScore(Base):
    """One learned trust record per (company, source identity)."""

    __tablename__ = "source_trust_scores"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False)
    # Canonical source identity, e.g. "tool:web_search" or "external_link:example.com".
    source_key: Mapped[str] = mapped_column(String(255), nullable=False)
    observations: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Accumulated positive-outcome weight (can be fractional).
    successes: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    # The static per-source-type prior captured at first observation.
    prior: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    # Current learned trust (smoothed estimate blended with the prior).
    learned_trust: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    company: Mapped["Company"] = relationship("Company")

    __table_args__ = (
        UniqueConstraint("company_id", "source_key", name="uq_source_trust_company_key"),
        Index("ix_source_trust_company", "company_id"),
    )
