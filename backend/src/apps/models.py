"""Tenant apps (Phase 14 WS6 6.6–6.12; tech spec §11.4–§11.7; decisions D34, D48).

Tenant plane (each business's own database):

* ``apps``             — one per app the business runs: its template, repo,
  mode, limits, outbound allow-list, and the deployment that is published
* ``app_builds``       — one per image built from a commit (ACR Tasks, or
  local Docker): digest, SBOM, scan, time and cost
* ``app_deployments``  — a build running as a preview (per pull request,
  7 days) or as the published app; the last ones are what rollback uses
* ``app_users``, ``app_roles``, ``app_user_roles`` — the people who sign in
  to an app (not HireBuddha users) and what each role may do
* ``app_user_sessions`` — refresh tokens (hashed), revocable
* ``app_auth_keys``    — the key app-user tokens are signed with, sealed
  under the business's DEK
* ``app_usage``        — hourly hosting use per app (what metering billed)

Control plane:

* ``custom_domains``   — every hostname the tenant app edge serves (custom
  domains with their DNS verification, and the platform's own
  ``<app>-<slug>.apps.<domain>`` names), so the edge's ``ask`` and routes
  read one table
"""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import CheckConstraint, DateTime, Index, Integer, LargeBinary, Numeric, Text, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.common.tenancy.bases import ControlBase, TenantBase

__all__ = [
    "APP_MODES", "APP_STATUSES", "APP_USER_STATUSES", "BUILD_STATUSES", "CERT_STATUSES", "DEPLOYMENT_KINDS",
    "DEPLOYMENT_STATUSES", "DOMAIN_KINDS", "DOMAIN_STATUSES",
    "App", "AppAuthKey", "AppBuild", "AppDeployment", "AppRole", "AppUsage", "AppUser", "AppUserRole",
    "AppUserSession", "CustomDomain",
]

APP_STATUSES = ("draft", "building", "ready", "published", "stopped", "failed", "archived")
APP_MODES = ("always_on", "sleep")
BUILD_STATUSES = ("queued", "running", "succeeded", "failed", "cancelled")
DEPLOYMENT_KINDS = ("preview", "published")
DEPLOYMENT_STATUSES = ("pending", "active", "superseded", "stopped", "failed", "expired")
APP_USER_STATUSES = ("active", "invited", "disabled")
DOMAIN_KINDS = ("custom", "platform", "preview")
DOMAIN_STATUSES = ("pending", "verified", "failed", "removed")
CERT_STATUSES = ("none", "pending", "issued", "failed")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN (" + ", ".join(f"'{v}'" for v in values) + ")"


def _now() -> Any:
    return text("now()")


def _uuid() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class App(TenantBase):
    __tablename__ = "apps"
    __table_args__ = (
        CheckConstraint(_in("status", APP_STATUSES), name="ck_apps_status"),
        CheckConstraint(_in("mode", APP_MODES), name="ck_apps_mode"),
        Index("uq_apps_name", "company_id", "name", unique=True),
    )

    id: Mapped[uuid.UUID] = _uuid()
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)                # DNS label: crm
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    template: Mapped[str] = mapped_column(Text, nullable=False)            # static_site, crm_admin, …
    template_version: Mapped[str] = mapped_column(Text, nullable=False)
    repo_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    repo_path: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    # The blueprint version the app was generated (or last built) against.
    blueprint_version: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="draft")
    mode: Mapped[str] = mapped_column(Text, nullable=False, server_default="always_on")
    # {"cpu": "250m", "memory": "256Mi", "max_replicas": 2}
    resources: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    env: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    outbound_allowlist: Mapped[list] = mapped_column(ARRAY(Text), nullable=False, server_default=text("'{}'::text[]"))
    # The Data API key the app's pods use (api_keys row), and its roles' scopes.
    app_key_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    published_deployment_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    settings: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=_now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=_now())


class AppBuild(TenantBase):
    __tablename__ = "app_builds"
    __table_args__ = (
        CheckConstraint(_in("status", BUILD_STATUSES), name="ck_app_builds_status"),
        Index("ix_app_builds_app_created", "app_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = _uuid()
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    app_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    commit_sha: Mapped[str] = mapped_column(Text, nullable=False)
    template_version: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    builder: Mapped[str] = mapped_column(Text, nullable=False)              # docker | acr_tasks
    external_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # the ACR run id
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="queued")
    image: Mapped[Optional[str]] = mapped_column(Text, nullable=True)       # repository:tag
    image_digest: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    base_image_digest: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    sbom_key: Mapped[Optional[str]] = mapped_column(Text, nullable=True)    # storage key of the SBOM
    log_key: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # {"tool": "trivy", "critical": 0, "high": 1, …} or {"skipped": "…"}
    scan: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    duration_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    cost: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 6), nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    requested_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    review_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=_now())
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class AppDeployment(TenantBase):
    __tablename__ = "app_deployments"
    __table_args__ = (
        CheckConstraint(_in("kind", DEPLOYMENT_KINDS), name="ck_app_deployments_kind"),
        CheckConstraint(_in("status", DEPLOYMENT_STATUSES), name="ck_app_deployments_status"),
        Index("ix_app_deployments_app_created", "app_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = _uuid()
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    app_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    build_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    pr_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    hostnames: Mapped[list] = mapped_column(ARRAY(Text), nullable=False, server_default=text("'{}'::text[]"))
    url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    image_digest: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="pending")
    # What the runtime calls it (a TenantApp name, a container id) and its state.
    runtime_ref: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    runtime_status: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    deployed_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=_now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=_now())


class AppUser(TenantBase):
    __tablename__ = "app_users"
    __table_args__ = (
        CheckConstraint(_in("status", APP_USER_STATUSES), name="ck_app_users_status"),
        Index("uq_app_users_email", "app_id", "email", unique=True),
    )

    id: Mapped[uuid.UUID] = _uuid()
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    app_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    email: Mapped[str] = mapped_column(Text, nullable=False)                # lower-case
    name: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    password_hash: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # Argon2id
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="active")
    token_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=_now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=_now())


class AppRole(TenantBase):
    __tablename__ = "app_roles"
    __table_args__ = (Index("uq_app_roles_name", "app_id", "name", unique=True),)

    id: Mapped[uuid.UUID] = _uuid()
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    app_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # {"objects": {"lead": ["read", "create", "update"]}, "reports": false}
    permissions: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=_now())


class AppUserRole(TenantBase):
    __tablename__ = "app_user_roles"

    app_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    role_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)


class AppUserSession(TenantBase):
    __tablename__ = "app_user_sessions"
    __table_args__ = (Index("uq_app_user_sessions_hash", "token_hash", unique=True),)

    id: Mapped[uuid.UUID] = _uuid()
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    app_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    token_hash: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=_now())


class AppAuthKey(TenantBase):
    __tablename__ = "app_auth_keys"

    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    dek_version: Mapped[int] = mapped_column(Integer, nullable=False)
    nonce: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=_now())
    retired_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class AppUsage(TenantBase):
    __tablename__ = "app_usage"
    __table_args__ = (Index("uq_app_usage_window", "app_id", "window_start", unique=True),)

    id: Mapped[uuid.UUID] = _uuid()
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    app_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    vcpu_hours: Mapped[Decimal] = mapped_column(Numeric(14, 6), nullable=False, server_default=text("0"))
    gb_hours: Mapped[Decimal] = mapped_column(Numeric(14, 6), nullable=False, server_default=text("0"))
    egress_gb: Mapped[Decimal] = mapped_column(Numeric(14, 6), nullable=False, server_default=text("0"))
    source: Mapped[str] = mapped_column(Text, nullable=False)                # prometheus | requests
    logged_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=_now())


# ── Control plane ───────────────────────────────────────────────────────────

class CustomDomain(ControlBase):
    __tablename__ = "custom_domains"
    __table_args__ = (
        CheckConstraint(_in("kind", DOMAIN_KINDS), name="ck_custom_domains_kind"),
        CheckConstraint(_in("status", DOMAIN_STATUSES), name="ck_custom_domains_status"),
        CheckConstraint(_in("cert_status", CERT_STATUSES), name="ck_custom_domains_cert_status"),
        Index("ix_custom_domains_app", "company_id", "app_id"),
    )

    hostname: Mapped[str] = mapped_column(Text, primary_key=True)
    tenant_key: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    app_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False, server_default="custom")
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="pending")
    verification_token: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    cert_status: Mapped[str] = mapped_column(Text, nullable=False, server_default="none")
    # The CNAME it must point at, and where the edge sends its requests.
    target: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    upstream: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    last_checked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=_now())
