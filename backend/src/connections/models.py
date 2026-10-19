"""Connection tables (Phase 14 WS5 5.1, 5.2; tech spec §10.2–§10.3; decision D40).

Control plane:

* ``connector_catalog``       — what a business can connect (synced from
  ``catalog/*.yaml`` on deploy) with the platform's approval state per provider
* ``external_account_routes`` — which tenant owns an outside account (a Page,
  a WhatsApp number, a GitHub installation): one business per account
* ``unrouted_events``         — provider webhooks for accounts nobody connected
  (payload hashed, kept 7 days) for platform staff

Tenant plane (each business's own database):

* ``connections``         — one per connected outside account
* ``connection_secrets``  — its tokens, AES-256-GCM under the tenant's DEK,
  the connection id as associated data
* ``connection_grants``   — who may use it: all agents, one agent, an app
* ``connection_audit``    — connected, token issued, refreshed, used, revoked …
* ``tenant_keys``         — the tenant's DEK versions, wrapped by its KEK
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, LargeBinary, Text, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.common.tenancy.bases import ControlBase, TenantBase

__all__ = [
    "AUTH_TYPES", "CATALOG_STATUSES", "CONNECTION_STATUSES", "GRANT_KINDS",
    "Connection", "ConnectionAudit", "ConnectionGrant", "ConnectionSecret", "ConnectorCatalogEntry",
    "ExternalAccountRoute", "TenantKey", "UnroutedEvent",
]

AUTH_TYPES = ("oauth2", "github_app", "meta_embedded_signup", "api_key", "mailbox", "mcp")
CATALOG_STATUSES = ("available", "preview", "unavailable", "planned")
CONNECTION_STATUSES = ("active", "expiring", "needs_reconnect", "revoked", "error")
GRANT_KINDS = ("all_agents", "entity", "app")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN (" + ", ".join(f"'{v}'" for v in values) + ")"


def _now() -> Any:
    return text("now()")


# ── Control plane ───────────────────────────────────────────────────────────

class ConnectorCatalogEntry(ControlBase):
    __tablename__ = "connector_catalog"
    __table_args__ = (
        CheckConstraint(_in("auth_type", AUTH_TYPES), name="ck_connector_catalog_auth_type"),
        CheckConstraint(_in("status", CATALOG_STATUSES), name="ck_connector_catalog_status"),
        CheckConstraint(f"status_override IS NULL OR {_in('status_override', CATALOG_STATUSES)}",
                        name="ck_connector_catalog_status_override"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)            # facebook_pages, github, …
    provider: Mapped[str] = mapped_column(Text, nullable=False)        # meta, github, google, …
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(Text, nullable=False)        # social, messaging, dev, docs, mail, crm, ai
    auth_type: Mapped[str] = mapped_column(Text, nullable=False)
    scopes: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    # What the connector can do and which webhook events it delivers.
    capabilities: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    # The registry row holding HireBuddha's own app with this provider (OAUTH_APP).
    oauth_app_ref: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False)          # from the YAML
    # Platform staff's switch (E09-S11): wins over the YAML's status until cleared.
    status_override: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Provider review state (E09-S11): verification, expiry, limits, notes.
    approval: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    icon: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=_now())

    @property
    def effective_status(self) -> str:
        return self.status_override or self.status


class ExternalAccountRoute(ControlBase):
    """One outside account belongs to one business (functional spec §6.5)."""
    __tablename__ = "external_account_routes"
    __table_args__ = (Index("ix_external_account_routes_company", "company_id"),)

    provider: Mapped[str] = mapped_column(Text, primary_key=True)
    external_account_id: Mapped[str] = mapped_column(Text, primary_key=True)
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False)
    tenant_key: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    connection_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=_now())


class UnroutedEvent(ControlBase):
    __tablename__ = "unrouted_events"
    __table_args__ = (Index("ix_unrouted_events_received", "received_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    external_account_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    event_type: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    payload_sha256: Mapped[str] = mapped_column(Text, nullable=False)   # the payload itself is not kept
    payload_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=_now())


# ── Tenant plane ────────────────────────────────────────────────────────────

class Connection(TenantBase):
    __tablename__ = "connections"
    __table_args__ = (
        CheckConstraint(_in("status", CONNECTION_STATUSES), name="ck_connections_status"),
        Index("ix_connections_company_connector", "company_id", "connector_id"),
        Index("ix_connections_expiring", "token_expires_at",
              postgresql_where=text("status IN ('active', 'expiring')")),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    connector_id: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    external_account_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    external_account_name: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    scopes_granted: Mapped[list] = mapped_column(ARRAY(Text), nullable=False, server_default=text("'{}'::text[]"))
    status: Mapped[str] = mapped_column(Text, nullable=False, default="active", server_default="active")
    token_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    # last_check_at, last_ok_at, last_error, refresh_failures, warned_expiry_at
    health: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    # Non-secret provider settings (page id, WABA id, installation id, IMAP host …).
    settings: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    connected_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)  # a user
    connected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=_now())
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))


class ConnectionSecret(TenantBase):
    __tablename__ = "connection_secrets"

    connection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("connections.id", ondelete="CASCADE"), primary_key=True)
    dek_version: Mapped[int] = mapped_column(Integer, nullable=False)
    nonce: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=_now())


class ConnectionGrant(TenantBase):
    __tablename__ = "connection_grants"
    __table_args__ = (
        CheckConstraint(_in("principal_kind", GRANT_KINDS), name="ck_connection_grants_kind"),
        CheckConstraint("(principal_kind = 'all_agents') = (principal_id IS NULL)",
                        name="ck_connection_grants_principal"),
        # One grant per principal: "all agents" once, each agent or app once.
        Index("uq_connection_grants_all", "connection_id", "principal_kind", unique=True,
              postgresql_where=text("principal_id IS NULL")),
        Index("uq_connection_grants_principal", "connection_id", "principal_kind", "principal_id", unique=True,
              postgresql_where=text("principal_id IS NOT NULL")),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    connection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("connections.id", ondelete="CASCADE"), nullable=False)
    principal_kind: Mapped[str] = mapped_column(Text, nullable=False)
    principal_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    actions: Mapped[list] = mapped_column(ARRAY(Text), nullable=False, server_default=text("'{*}'::text[]"))


class ConnectionAudit(TenantBase):
    __tablename__ = "connection_audit"
    __table_args__ = (Index("ix_connection_audit_connection_at", "connection_id", "at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    connection_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    # connected, token_issued, refreshed, refresh_failed, used, revoked, test_ok, test_failed,
    # grants_changed, reconnected, refused
    action: Mapped[str] = mapped_column(Text, nullable=False)
    actor_kind: Mapped[Optional[str]] = mapped_column(Text, nullable=True)     # user, agent, app, system
    actor_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    run_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=_now())
    detail: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)


class TenantKey(TenantBase):
    """A version of the business's DEK, wrapped by its KEK (§10.4)."""
    __tablename__ = "tenant_keys"

    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    wrapped_dek: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    kek_key_id: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=_now())
    retired_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
