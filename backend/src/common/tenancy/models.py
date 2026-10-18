"""The tenant directory and server registry (Phase 14 WS2 2.8, tech spec §6.1).

Control tables, created by migration ``p14_tenant_directory``:

* ``tenant_db_servers`` — the PostgreSQL servers tenant databases live on: a
  pool server holds many (``capacity``), a dedicated one holds one tenant;
* ``tenant_directory`` — one row per provisioned company: its tenant key, the
  server and database that hold its data, its provisioning ``status`` (the
  state machine of §6.2), whether its automation runs, its time zone and the
  schema versions its database is at;
* ``tenant_provisioning_log`` — every provisioning step tried, so a retry
  resumes from the last good step and an operator sees what failed.

A company with no directory row has no database of its own: with
``TENANCY_MODE=single`` none needs one.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.common.tenancy.bases import ControlBase

__all__ = [
    "AUTOMATION_STATES", "DATABASE_READY_STATUSES", "PROVISIONING_STEPS", "SERVER_KINDS",
    "SERVER_STATUSES", "STEP_OUTCOMES", "TENANT_STATUSES",
    "TenantDbServer", "TenantDirectoryEntry", "TenantProvisioningLog",
]

SERVER_KINDS = ("pool", "dedicated")
SERVER_STATUSES = ("active", "draining", "retired")

# The provisioning state machine (§6.2), in order: each step's state is the one it ends in.
PROVISIONING_STEPS = ("requested", "db_created", "migrated", "identity_ready", "keys_ready",
                      "namespace_ready", "storage_ready", "data_api_ready", "active")
TENANT_STATUSES = PROVISIONING_STEPS + ("suspended", "exporting", "retired", "failed")
# A tenant session may open once the database has its tables, until it is retired.
DATABASE_READY_STATUSES = frozenset(PROVISIONING_STEPS[2:] + ("suspended", "exporting"))
AUTOMATION_STATES = ("running", "paused", "stopped")
STEP_OUTCOMES = ("started", "succeeded", "failed", "skipped")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class TenantDbServer(ControlBase):
    __tablename__ = "tenant_db_servers"
    __table_args__ = (
        CheckConstraint(_in("kind", SERVER_KINDS), name="ck_tenant_db_servers_kind"),
        CheckConstraint(_in("status", SERVER_STATUSES), name="ck_tenant_db_servers_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(Text, unique=True, nullable=False)   # psql-hb-prod-pool-01
    host: Mapped[str] = mapped_column(Text, nullable=False)                # private FQDN
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    region: Mapped[str] = mapped_column(Text, nullable=False)
    capacity: Mapped[int] = mapped_column(Integer, nullable=False)         # max tenants (pool)
    status: Mapped[str] = mapped_column(Text, nullable=False)


class TenantDirectoryEntry(ControlBase):
    __tablename__ = "tenant_directory"
    __table_args__ = (
        CheckConstraint(_in("status", TENANT_STATUSES), name="ck_tenant_directory_status"),
        CheckConstraint(_in("automation_state", AUTOMATION_STATES),
                        name="ck_tenant_directory_automation_state"),
        Index("ix_tenant_directory_server_id", "server_id"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("companies.id"),
                                                  primary_key=True)
    tenant_key: Mapped[str] = mapped_column(Text, unique=True, nullable=False)  # immutable
    slug: Mapped[str] = mapped_column(Text, unique=True, nullable=False)        # hostnames; changeable
    server_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenant_db_servers.id"),
                                                 nullable=False)
    db_name: Mapped[str] = mapped_column(Text, nullable=False)                  # t_<key>
    status: Mapped[str] = mapped_column(Text, nullable=False)
    automation_state: Mapped[str] = mapped_column(Text, nullable=False, default="running",
                                                  server_default="running")
    timezone: Mapped[str] = mapped_column(Text, nullable=False, default="Asia/Kolkata",
                                          server_default="Asia/Kolkata")
    platform_schema_version: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    business_schema_version: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    blueprint_version: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    data_api_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                                 server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                                 server_default=text("now()"), onupdate=datetime.utcnow)


class TenantProvisioningLog(ControlBase):
    __tablename__ = "tenant_provisioning_log"
    __table_args__ = (
        CheckConstraint(_in("outcome", STEP_OUTCOMES), name="ck_tenant_provisioning_log_outcome"),
        Index("ix_tenant_provisioning_log_company_created", "company_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("companies.id"),
                                                  nullable=False)
    tenant_key: Mapped[str] = mapped_column(Text, nullable=False)
    step: Mapped[str] = mapped_column(Text, nullable=False)       # the state the step leads to
    outcome: Mapped[str] = mapped_column(Text, nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    detail: Mapped[Optional[Any]] = mapped_column(JSONB, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                                 server_default=text("now()"))
