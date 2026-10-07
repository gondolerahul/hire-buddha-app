"""gateway/models.py — where a tenant's providers post their webhooks (GW-01).

A webhook is accepted only at ``/webhook/inbound/{endpoint_id}``. The endpoint
row says which company the events belong to, which source signs them, the
secret that signature is checked against (encrypted), and optionally the agent
the events go to. Nothing about the tenant or the signing scheme is taken from
the request itself.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.common.database import Base

__all__ = ["WEBHOOK_SOURCES", "WebhookEndpoint"]

# The sources an endpoint may name; each has a signature scheme in
# ``gateway.webhook_signatures`` and a normaliser in ``gateway.webhook_inbound``.
WEBHOOK_SOURCES: tuple[str, ...] = (
    "github", "facebook", "instagram", "linkedin", "twitter", "tiktok", "youtube",
    "twilio", "email", "crm", "pinterest", "generic",
)


class WebhookEndpoint(Base):
    __tablename__ = "webhook_endpoints"
    __table_args__ = (
        CheckConstraint(
            "source IN (" + ", ".join(f"'{s}'" for s in WEBHOOK_SOURCES) + ")",
            name="ck_webhook_endpoints_source",
        ),
        Index("ix_webhook_endpoints_company", "company_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # ``common.security.encrypt_api_key``; shown to the caller once, at creation.
    secret_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    # The agent this endpoint's events run; NULL leaves the choice to the worker.
    entity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("hierarchical_entities.id", ondelete="SET NULL"), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    last_received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
