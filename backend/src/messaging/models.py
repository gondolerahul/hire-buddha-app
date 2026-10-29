"""Conversation state and opt-ins (tenant plane; META-E4, META-E5).

* ``messaging_conversations`` — one per customer per business account (a Page,
  an Instagram account, a WhatsApp number): when the customer last wrote, when
  the AI assistant last answered and said it is one, and whether a person has
  taken the conversation over.
* ``messaging_opt_ins``       — a WhatsApp contact agreed to (``in``) or
  refused (``out``) messages the business starts, with where that came from.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import CheckConstraint, DateTime, Index, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.common.tenancy.bases import TenantBase

__all__ = ["CHANNELS", "OPT_IN_STATUSES", "MessagingConversation", "MessagingOptIn"]

CHANNELS = ("messenger", "instagram", "whatsapp")
OPT_IN_STATUSES = ("in", "out")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN (" + ", ".join(f"'{v}'" for v in values) + ")"


def _now() -> Any:
    return text("now()")


class MessagingConversation(TenantBase):
    __tablename__ = "messaging_conversations"
    __table_args__ = (
        CheckConstraint(_in("channel", CHANNELS), name="ck_messaging_conversations_channel"),
        Index("uq_messaging_conversations_contact", "company_id", "channel", "account_id", "contact_id",
              unique=True),
        # The business's "waiting for a person" list.
        Index("ix_messaging_conversations_handed_off", "company_id",
              postgresql_where=text("handed_off_at IS NOT NULL")),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    channel: Mapped[str] = mapped_column(Text, nullable=False)
    account_id: Mapped[str] = mapped_column(Text, nullable=False)       # the Page, the Instagram account, the number
    contact_id: Mapped[str] = mapped_column(Text, nullable=False)       # the PSID / IGSID, the customer's number
    last_inbound_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_ai_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    disclosed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    handed_off_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    handoff_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    handed_back_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    handed_back_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=_now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=_now())


class MessagingOptIn(TenantBase):
    __tablename__ = "messaging_opt_ins"
    __table_args__ = (
        CheckConstraint(_in("channel", CHANNELS), name="ck_messaging_opt_ins_channel"),
        CheckConstraint(_in("status", OPT_IN_STATUSES), name="ck_messaging_opt_ins_status"),
        Index("uq_messaging_opt_ins_contact", "company_id", "channel", "contact_id", unique=True),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    channel: Mapped[str] = mapped_column(Text, nullable=False)
    contact_id: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    # keyword (the customer wrote START / STOP), form, import, staff …; and what shows it.
    source: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    recorded_by: Mapped[Optional[str]] = mapped_column(Text, nullable=True)   # user:<id>, customer, run:<id>
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=_now())
