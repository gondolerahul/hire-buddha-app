"""Who changed a platform setting, when, and from what (Phase 15 T0-1, tech design §17).

One control-plane table, ``admin_audit_log``, for every staff write to a value
that changes how the product behaves or bills: feature flags first; FX rates,
money settings, formulas, price items, plans, locks and partner rules as they
arrive. A row keeps the actor, the company they acted as, the object, its value
before and after, and a reason when one was given.

It is not named ``audit_log``: in ``TENANCY_MODE=single`` the shared database
already holds the tenant plane's ``audit_log`` (record changes of the Data API).

``record_admin_change`` adds the row to the caller's session, so it commits —
or rolls back — with the change it describes.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import DateTime, Index, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.common.tenancy.bases import ControlBase

__all__ = ["AdminAuditLog", "record_admin_change"]


class AdminAuditLog(ControlBase):
    __tablename__ = "admin_audit_log"
    __table_args__ = (
        Index("ix_admin_audit_log_object", "object_type", "object_key", "at"),
        Index("ix_admin_audit_log_company", "target_company_id", "at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
                                          server_default=text("gen_random_uuid()"))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow,
                                         server_default=text("now()"))
    # Plain ids, not keys: the history outlives a deleted user or company.
    actor_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    actor_role: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    acting_company_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    action: Mapped[str] = mapped_column(Text, nullable=False)            # set | delete | …
    object_type: Mapped[str] = mapped_column(Text, nullable=False)       # feature_flag | …
    object_key: Mapped[str] = mapped_column(Text, nullable=False)
    target_company_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    scope: Mapped[Any] = mapped_column(JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
    old_value: Mapped[Any] = mapped_column(JSONB, nullable=True)
    new_value: Mapped[Any] = mapped_column(JSONB, nullable=True)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


def record_admin_change(
    db: Any,
    *,
    actor: Any,
    action: str,
    object_type: str,
    object_key: str,
    target_company_id: Optional[uuid.UUID] = None,
    scope: Optional[dict] = None,
    old_value: Any = None,
    new_value: Any = None,
    reason: Optional[str] = None,
) -> AdminAuditLog:
    """Add an audit row to ``db`` (the caller commits). ``actor`` is the signed-in ``User``."""
    role = getattr(actor, "role", None)
    row = AdminAuditLog(
        actor_user_id=getattr(actor, "id", None),
        actor_role=str(getattr(role, "value", role)) if role is not None else None,
        acting_company_id=getattr(actor, "company_id", None),
        action=action,
        object_type=object_type,
        object_key=object_key,
        target_company_id=target_company_id,
        scope=scope or {},
        old_value=old_value,
        new_value=new_value,
        reason=reason,
    )
    db.add(row)
    return row
