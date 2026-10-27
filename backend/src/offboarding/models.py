"""A business's offboarding and the steps it went through (docs/phase15/13_offboarding_and_erasure.md).

One ``CompanyOffboarding`` per request. It names its company by id only — no
foreign key — so it outlives the company it erased: it is the proof (§12).
Each attempt of each step is a ``OffboardingStepLog`` row, as provisioning
writes ``tenant_provisioning_log``.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.common.tenancy.bases import ControlBase

MODES = ("erasure", "immediate")                 # Flow A, Flow B (§10)
STATES = ("requested", "cancelled", "exporting", "erasing", "erased", "failed")
OPEN_STATES = ("requested", "exporting", "erasing", "failed")
OUTCOMES = ("started", "succeeded", "skipped", "failed")


def _in(column: str, values: tuple) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class CompanyOffboarding(ControlBase):
    __tablename__ = "company_offboardings"
    __table_args__ = (
        CheckConstraint(_in("mode", MODES), name="ck_company_offboardings_mode"),
        CheckConstraint(_in("state", STATES), name="ck_company_offboardings_state"),
        # One offboarding in progress per company.
        Index("uq_company_offboardings_open", "company_id", unique=True,
              postgresql_where=text("state IN ('requested', 'exporting', 'erasing', 'failed')")),
        Index("ix_company_offboardings_state", "state", "grace_until"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)   # no FK: outlives it
    company_ref: Mapped[str] = mapped_column(Text, nullable=False)          # "B-1a2b3c4d", in certificates
    company_name: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # blanked once erased (Flow A)
    mode: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(Text, nullable=False, default="requested")
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    requested_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    requested_by_role: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    confirmed_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    grace_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    previous_status: Mapped[Optional[str]] = mapped_column(Text, nullable=True)   # what cancel restores
    export_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False,
                                                   server_default=text("false"))
    export_key: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    export_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_step: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    inventory: Mapped[Any] = mapped_column(JSONB, nullable=True)            # counts per item before erasure
    certificate: Mapped[Any] = mapped_column(JSONB, nullable=True)
    certificate_key: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                                 default=datetime.utcnow, server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                                 default=datetime.utcnow, server_default=text("now()"))


class OffboardingStepLog(ControlBase):
    __tablename__ = "offboarding_step_log"
    __table_args__ = (
        CheckConstraint(_in("outcome", OUTCOMES), name="ck_offboarding_step_log_outcome"),
        Index("ix_offboarding_step_log_offboarding", "offboarding_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    offboarding_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("company_offboardings.id",
                                                                                      ondelete="CASCADE"),
                                                      nullable=False)
    step: Mapped[str] = mapped_column(Text, nullable=False)
    outcome: Mapped[str] = mapped_column(Text, nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    detail: Mapped[Any] = mapped_column(JSONB, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                                 default=datetime.utcnow, server_default=text("now()"))
