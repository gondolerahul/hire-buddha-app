"""Code lanes and Git (Phase 14 WS6 6.3–6.5; tech spec §11.2, §11.3; decisions D35, D36).

Tenant plane (each business's own database):

* ``git_repos``    — a repository the business's code lives in: on GitHub
  (through its GitHub App connection) or in the built-in Git
* ``code_items``   — a script, tool, skill script or app an agent wrote:
  ``scratch`` (in Blob, kept a week, never loaded at runtime) until it is
  promoted to an ``asset`` (a path at a commit of a repository)
* ``code_reviews`` — the pull request a promotion (or an agent's change to
  an app) opened: its branch, checks, and who merged it
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import CheckConstraint, DateTime, Index, Integer, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.common.tenancy.bases import TenantBase

__all__ = ["CHECK_STATES", "CODE_KINDS", "CODE_STATUSES", "GIT_PROVIDERS", "LANES", "REVIEW_STATUSES",
           "CodeItem", "CodeReview", "GitRepo"]

LANES = ("scratch", "asset")
CODE_KINDS = ("script", "tool", "skill_script", "app")
CODE_STATUSES = ("active", "promoting", "promoted", "rejected", "expired")
GIT_PROVIDERS = ("github", "builtin")
REVIEW_STATUSES = ("open", "merged", "closed")
CHECK_STATES = ("pending", "running", "passed", "failed")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN (" + ", ".join(f"'{v}'" for v in values) + ")"


def _now() -> Any:
    return text("now()")


class GitRepo(TenantBase):
    __tablename__ = "git_repos"
    __table_args__ = (
        CheckConstraint(_in("provider", GIT_PROVIDERS), name="ck_git_repos_provider"),
        Index("uq_git_repos_name", "company_id", "provider", "full_name", unique=True),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    external_repo_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    full_name: Mapped[str] = mapped_column(Text, nullable=False)          # owner/name
    default_branch: Mapped[str] = mapped_column(Text, nullable=False, server_default="main")
    # The GitHub App connection it is reached through (provider github).
    connection_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # A built-in repository whose history was pushed to GitHub ("connect GitHub later").
    moved_to_repo_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=_now())


class CodeItem(TenantBase):
    __tablename__ = "code_items"
    __table_args__ = (
        CheckConstraint(_in("lane", LANES), name="ck_code_items_lane"),
        CheckConstraint(_in("kind", CODE_KINDS), name="ck_code_items_kind"),
        CheckConstraint(_in("status", CODE_STATUSES), name="ck_code_items_status"),
        Index("ix_code_items_company_lane", "company_id", "lane", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    lane: Mapped[str] = mapped_column(Text, nullable=False, server_default="scratch")
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # While scratch: the storage prefix holding its files, and their list.
    scratch_ref: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    files: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    # Once an asset: where it lives.
    repo_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    commit_sha: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    review_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    app_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    # A synthesized tool's registry row, promoted with it.
    tool_registry_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_by_run_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    retention_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=_now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=_now())


class CodeReview(TenantBase):
    __tablename__ = "code_reviews"
    __table_args__ = (
        CheckConstraint(_in("status", REVIEW_STATUSES), name="ck_code_reviews_status"),
        CheckConstraint(_in("checks_status", CHECK_STATES), name="ck_code_reviews_checks_status"),
        Index("uq_code_reviews_number", "repo_id", "number", unique=True),
        Index("ix_code_reviews_company_status", "company_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    repo_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    code_item_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    app_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    branch: Mapped[str] = mapped_column(Text, nullable=False)
    base_branch: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="open")
    head_sha: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    merge_sha: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    checks_status: Mapped[str] = mapped_column(Text, nullable=False, server_default="pending")
    # [{name, conclusion: success|failure|skipped|neutral, summary}]
    checks: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    opened_by_run_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    opened_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    merged_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    merged_by_login: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    merged_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=_now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=_now())
