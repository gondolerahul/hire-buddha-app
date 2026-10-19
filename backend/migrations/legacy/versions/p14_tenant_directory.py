"""The tenant directory and server registry (Phase 14 WS2 2.8)

Revision ID: p14_tenant_directory
Revises: p14_company_timezone
Create Date: 2026-10-17

Control tables of tech spec §6.1: ``tenant_db_servers`` (where tenant
databases live), ``tenant_directory`` (company → tenant key, server, database,
provisioning status, automation state, time zone, schema versions) and
``tenant_provisioning_log`` (each provisioning step tried). Nothing reads them
while ``TENANCY_MODE=single``; existing companies get rows when they are
provisioned (WS7), dev tenants from ``scripts/dev_tenants.py``.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "p14_tenant_directory"
down_revision: Union[str, Sequence[str], None] = "p14_company_timezone"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TENANT_STATUSES = ("requested", "db_created", "migrated", "identity_ready", "keys_ready",
                    "namespace_ready", "storage_ready", "data_api_ready", "active",
                    "suspended", "exporting", "retired", "failed")


def _in(column: str, values: Sequence[str]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def upgrade() -> None:
    op.create_table(
        "tenant_db_servers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False, unique=True),
        sa.Column("host", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("region", sa.Text(), nullable=False),
        sa.Column("capacity", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.CheckConstraint(_in("kind", ("pool", "dedicated")), name="ck_tenant_db_servers_kind"),
        sa.CheckConstraint(_in("status", ("active", "draining", "retired")),
                           name="ck_tenant_db_servers_status"),
    )
    op.create_table(
        "tenant_directory",
        sa.Column("company_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("companies.id"),
                  primary_key=True),
        sa.Column("tenant_key", sa.Text(), nullable=False, unique=True),
        sa.Column("slug", sa.Text(), nullable=False, unique=True),
        sa.Column("server_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenant_db_servers.id"),
                  nullable=False),
        sa.Column("db_name", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("automation_state", sa.Text(), nullable=False, server_default="running"),
        sa.Column("timezone", sa.Text(), nullable=False, server_default="Asia/Kolkata"),
        sa.Column("platform_schema_version", sa.Text(), nullable=True),
        sa.Column("business_schema_version", sa.Text(), nullable=True),
        sa.Column("blueprint_version", sa.Integer(), nullable=True),
        sa.Column("data_api_url", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(_in("status", _TENANT_STATUSES), name="ck_tenant_directory_status"),
        sa.CheckConstraint(_in("automation_state", ("running", "paused", "stopped")),
                           name="ck_tenant_directory_automation_state"),
    )
    op.create_index("ix_tenant_directory_server_id", "tenant_directory", ["server_id"])
    op.create_table(
        "tenant_provisioning_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("companies.id"),
                  nullable=False),
        sa.Column("tenant_key", sa.Text(), nullable=False),
        sa.Column("step", sa.Text(), nullable=False),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("detail", postgresql.JSONB(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(_in("outcome", ("started", "succeeded", "failed", "skipped")),
                           name="ck_tenant_provisioning_log_outcome"),
    )
    op.create_index("ix_tenant_provisioning_log_company_created", "tenant_provisioning_log",
                    ["company_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_tenant_provisioning_log_company_created", table_name="tenant_provisioning_log")
    op.drop_table("tenant_provisioning_log")
    op.drop_index("ix_tenant_directory_server_id", table_name="tenant_directory")
    op.drop_table("tenant_directory")
    op.drop_table("tenant_db_servers")
