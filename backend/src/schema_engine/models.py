"""The schema engine's and the Data API's own tables (tenant plane, schema
``platform`` of the business's database; tech spec §8.4, §9.3, §9.4).

* ``schema_blueprints`` — every blueprint version, one ``active``;
* ``schema_changes``    — proposals: operations, actor, plan, impact, status;
* ``audit_log``         — every record write: who, what, which fields;
* ``api_keys``          — app and outside-system keys (stored hashed);
* ``records_settings``  — the owner's policy for schema changes.

The business tables themselves (``business.*``, ``custom.*``) are not models:
the schema engine creates them from the blueprint.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import Boolean, CheckConstraint, DateTime, Index, Integer, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.common.tenancy.bases import TenantBase

BLUEPRINT_STATUSES = ("active", "superseded")
CHANGE_STATUSES = ("proposed", "awaiting_approval", "applied", "rejected", "failed")
ACTOR_KINDS = ("user", "agent", "platform", "key")


def _now() -> Any:
    return text("now()")


class SchemaBlueprint(TenantBase):
    __tablename__ = "schema_blueprints"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'superseded')", name="ck_schema_blueprints_status"),
        UniqueConstraint("company_id", "version", name="uq_schema_blueprints_company_version"),
        Index("uq_schema_blueprints_active", "company_id", unique=True, postgresql_where=text("status = 'active'")),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="active")
    document: Mapped[Any] = mapped_column(JSONB, nullable=False)
    change_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow,
                                                 server_default=_now())


class SchemaChange(TenantBase):
    __tablename__ = "schema_changes"
    __table_args__ = (
        CheckConstraint("status IN ('proposed', 'awaiting_approval', 'applied', 'rejected', 'failed')",
                        name="ck_schema_changes_status"),
        CheckConstraint("actor_kind IN ('user', 'agent', 'platform', 'key')", name="ck_schema_changes_actor"),
        Index("ix_schema_changes_company_created", "company_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="proposed")
    operations: Mapped[Any] = mapped_column(JSONB, nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    actor_kind: Mapped[str] = mapped_column(Text, nullable=False)
    actor_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    run_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    base_version: Mapped[int] = mapped_column(Integer, nullable=False)
    result_version: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    plan: Mapped[Any] = mapped_column(JSONB, nullable=True)
    impact: Mapped[Any] = mapped_column(JSONB, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    decided_by: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow,
                                                 server_default=_now())
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    applied_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class AuditLog(TenantBase):
    __tablename__ = "audit_log"
    __table_args__ = (Index("ix_audit_log_record", "object", "record_id", "at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    actor: Mapped[str] = mapped_column(Text, nullable=False)            # user:<id> | run:<id> | key:<id>
    action: Mapped[str] = mapped_column(Text, nullable=False)           # created | updated | archived
    object: Mapped[str] = mapped_column(Text, nullable=False)
    record_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    changed_fields: Mapped[Any] = mapped_column(JSONB, nullable=False, default=list)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow,
                                         server_default=_now())


class ApiKey(TenantBase):
    __tablename__ = "api_keys"
    __table_args__ = (UniqueConstraint("key_hash", name="uq_api_keys_hash"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    prefix: Mapped[str] = mapped_column(Text, nullable=False)           # shown to tell keys apart
    key_hash: Mapped[str] = mapped_column(Text, nullable=False)         # sha256 of the key
    scopes: Mapped[Any] = mapped_column(JSONB, nullable=False, default=dict)
    external: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    created_by: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow,
                                                 server_default=_now())
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class RecordsSettings(TenantBase):
    """The owner's policy for the business's data structure (functional spec §4.4).

    ``agents_auto_approve_additive``: an agent's change that only adds (an
    object, an optional field, an index) applies without a person; anything
    else an agent proposes still waits. Off by default.
    """
    __tablename__ = "records_settings"

    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    agents_auto_approve_additive: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False,
                                                               server_default=text("false"))
    updated_by: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow,
                                                 server_default=_now())
