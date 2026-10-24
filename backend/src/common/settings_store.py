"""Scoped platform settings: where values of the settings catalogue are stored (Phase 15 T2-1, T5-1).

``platform_settings`` holds one value per (key, scope, scope_id): the platform
value (``scope='platform'``, no id) and plan, partner and company values. What
a key means — its type, bounds, default and allowed scopes — and how a
company's value is resolved is ``src.billing.settings_catalogue``; this
module only reads and writes rows.

Every write is audited in ``admin_audit_log`` (``object_type='setting'``).
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Iterable, Optional

from sqlalchemy import CheckConstraint, DateTime, Text, UniqueConstraint, delete, select, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.common.tenancy.bases import ControlBase

__all__ = ["PlatformSetting", "get_platform_setting", "set_platform_setting", "set_setting", "delete_setting",
           "read_values"]


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


def _where(key: str, scope: str, scope_id: Optional[uuid.UUID]) -> list:
    return [PlatformSetting.key == key, PlatformSetting.scope == scope,
            PlatformSetting.scope_id == scope_id if scope_id is not None else PlatformSetting.scope_id.is_(None)]


async def read_values(db: Any, key: str, scopes: Iterable[tuple[str, Optional[uuid.UUID]]]) -> dict:
    """``{(scope, scope_id): value}`` of the rows of ``key`` at the given scopes (one query)."""
    scopes = list(scopes)
    rows = (await db.execute(select(PlatformSetting.scope, PlatformSetting.scope_id, PlatformSetting.value_json)
                             .where(PlatformSetting.key == key,
                                    PlatformSetting.scope.in_({s for s, _ in scopes})))).all()
    wanted = set(scopes)
    return {(r.scope, r.scope_id): r.value_json for r in rows if (r.scope, r.scope_id) in wanted}


async def get_platform_setting(db: Any, key: str) -> Any:
    """The platform value of ``key`` as stored (its catalogue default when no row is set)."""
    from src.billing.settings_catalogue import CATALOGUE, _jsonable

    row = (await db.execute(select(PlatformSetting.value_json).where(*_where(key, "platform", None)))
           ).scalar_one_or_none()
    if row is None:
        spec = CATALOGUE.get(key)
        return _jsonable(spec.default) if spec else None
    return row


async def set_setting(db: Any, key: str, value: Any, *, scope: str = "platform", scope_id: Optional[uuid.UUID] = None,
                      actor: Any, reason: Optional[str] = None) -> None:
    """Set ``key`` at a scope and audit it (the caller commits). The value is already validated."""
    from src.common.admin_audit import record_admin_change

    row = (await db.execute(select(PlatformSetting).where(*_where(key, scope, scope_id)))).scalar_one_or_none()
    old = None if row is None else row.value_json
    if row is None:
        db.add(PlatformSetting(key=key, scope=scope, scope_id=scope_id, value_json=value,
                               updated_by=getattr(actor, "id", None)))
    else:
        row.value_json, row.updated_by, row.updated_at = value, getattr(actor, "id", None), datetime.utcnow()
    record_admin_change(db, actor=actor, action="set", object_type="setting", object_key=key,
                        target_company_id=scope_id if scope == "company" else None,
                        scope={"scope": scope, "scope_id": str(scope_id) if scope_id else None},
                        old_value=old, new_value=value, reason=reason)


async def delete_setting(db: Any, key: str, *, scope: str, scope_id: Optional[uuid.UUID], actor: Any,
                         reason: Optional[str] = None) -> bool:
    """Remove the value at one scope (the next scope's value applies again); audited."""
    from src.common.admin_audit import record_admin_change

    row = (await db.execute(select(PlatformSetting).where(*_where(key, scope, scope_id)))).scalar_one_or_none()
    if row is None:
        return False
    old = row.value_json
    await db.execute(delete(PlatformSetting).where(PlatformSetting.id == row.id))
    record_admin_change(db, actor=actor, action="delete", object_type="setting", object_key=key,
                        target_company_id=scope_id if scope == "company" else None,
                        scope={"scope": scope, "scope_id": str(scope_id) if scope_id else None},
                        old_value=old, new_value=None, reason=reason)
    return True


async def set_platform_setting(db: Any, key: str, value: Any, *, actor: Any, reason: Optional[str] = None) -> None:
    await set_setting(db, key, value, scope="platform", scope_id=None, actor=actor, reason=reason)
