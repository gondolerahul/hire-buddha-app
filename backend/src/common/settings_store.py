"""Scoped platform settings (Phase 15 T2-1; the catalogue and resolver come with T5-1).

``platform_settings`` holds one value per (key, scope, scope_id): the platform
default (``scope='platform'``, no id), and later plan, partner and company
values. T2-1 needs two platform values — ``billing.display_currency`` (what
staff views show) and ``billing.default_currency`` (the currency of a country
with no profile, REQ-BL-2) — so this module has just the table and a
platform-scope get and set; T5-1 adds the catalogue (type, bounds, editors),
the scope resolver with "explain", and its UI.

Writes are audited in ``admin_audit_log`` (``object_type='setting'``).
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import CheckConstraint, DateTime, Text, UniqueConstraint, select, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.common.tenancy.bases import ControlBase

__all__ = ["PlatformSetting", "get_platform_setting", "set_platform_setting"]

# Platform values before any row exists (the migration seeds the same).
DEFAULTS: dict[str, Any] = {
    "billing.display_currency": "INR",
    "billing.default_currency": "INR",
    # The new rating and settlement path (plan §6): off | shadow | on. Shadow
    # records each settlement priced both ways (T3-7); "on" needs WS15-4.
    "billing.v2_mode": "shadow",
}


class PlatformSetting(ControlBase):
    __tablename__ = "platform_settings"
    __table_args__ = (
        CheckConstraint("scope IN ('platform', 'plan', 'partner_type', 'partner', 'company')",
                        name="ck_platform_settings_scope"),
        UniqueConstraint("key", "scope", "scope_id", name="uq_platform_settings_key_scope",
                         postgresql_nulls_not_distinct=True),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
                                          server_default=text("gen_random_uuid()"))
    key: Mapped[str] = mapped_column(Text, nullable=False)
    scope: Mapped[str] = mapped_column(Text, nullable=False, default="platform", server_default="platform")
    scope_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    value_json: Mapped[Any] = mapped_column(JSONB, nullable=False)
    updated_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow,
                                                 server_default=text("now()"))


async def get_platform_setting(db: Any, key: str) -> Any:
    """The platform value of ``key`` (its default when no row is set)."""
    row = (await db.execute(select(PlatformSetting.value_json).where(
        PlatformSetting.key == key, PlatformSetting.scope == "platform",
        PlatformSetting.scope_id.is_(None)))).scalar_one_or_none()
    return DEFAULTS.get(key) if row is None else row


async def set_platform_setting(db: Any, key: str, value: Any, *, actor: Any, reason: Optional[str] = None) -> None:
    """Set the platform value of ``key`` and audit the change (the caller commits)."""
    from src.common.admin_audit import record_admin_change

    row = (await db.execute(select(PlatformSetting).where(
        PlatformSetting.key == key, PlatformSetting.scope == "platform",
        PlatformSetting.scope_id.is_(None)))).scalar_one_or_none()
    old = DEFAULTS.get(key) if row is None else row.value_json
    if row is None:
        db.add(PlatformSetting(key=key, scope="platform", value_json=value, updated_by=getattr(actor, "id", None)))
    else:
        row.value_json, row.updated_by, row.updated_at = value, getattr(actor, "id", None), datetime.utcnow()
    record_admin_change(db, actor=actor, action="set", object_type="setting", object_key=key,
                        scope={"scope": "platform"}, old_value=old, new_value=value, reason=reason)
