"""Schema engine and Data API tables (Phase 14 WS4 4.1).

Revision ID: p14_records
Revises: p14_notifications
Create Date: 2026-10-18

Tenant plane: ``schema_blueprints``, ``schema_changes``, ``audit_log``,
``api_keys``, ``records_settings``. A business's database gets them in its ``platform`` schema from
the models (WS2); here they are created in the shared database so the models
and the migration chain agree. The business tables (``business.*``,
``custom.*``) are made by the schema engine in each business's own database.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "p14_records"
down_revision: Union[str, Sequence[str], None] = "p14_notifications"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

UUID = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB()
TS = sa.DateTime(timezone=True)
NOW = sa.text("now()")


def upgrade() -> None:
    op.create_table(
        "schema_blueprints",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("company_id", UUID, nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("document", JSONB, nullable=False),
        sa.Column("change_id", UUID),
        sa.Column("created_at", TS, nullable=False, server_default=NOW),
        sa.CheckConstraint("status IN ('active', 'superseded')", name="ck_schema_blueprints_status"),
        sa.UniqueConstraint("company_id", "version", name="uq_schema_blueprints_company_version"),
    )
    op.create_index("uq_schema_blueprints_active", "schema_blueprints", ["company_id"], unique=True,
                    postgresql_where=sa.text("status = 'active'"))
    op.create_table(
        "schema_changes",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("company_id", UUID, nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("operations", JSONB, nullable=False),
        sa.Column("reason", sa.Text()),
        sa.Column("actor_kind", sa.Text(), nullable=False),
        sa.Column("actor_id", sa.Text()),
        sa.Column("run_id", UUID),
        sa.Column("base_version", sa.Integer(), nullable=False),
        sa.Column("result_version", sa.Integer()),
        sa.Column("plan", JSONB),
        sa.Column("impact", JSONB),
        sa.Column("error", sa.Text()),
        sa.Column("decided_by", sa.Text()),
        sa.Column("created_at", TS, nullable=False, server_default=NOW),
        sa.Column("decided_at", TS),
        sa.Column("applied_at", TS),
        sa.CheckConstraint("status IN ('proposed', 'awaiting_approval', 'applied', 'rejected', 'failed')",
                           name="ck_schema_changes_status"),
        sa.CheckConstraint("actor_kind IN ('user', 'agent', 'platform', 'key')", name="ck_schema_changes_actor"),
    )
    op.create_index("ix_schema_changes_company_created", "schema_changes", ["company_id", "created_at"])
    op.create_table(
        "audit_log",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("company_id", UUID, nullable=False),
        sa.Column("actor", sa.Text(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("object", sa.Text(), nullable=False),
        sa.Column("record_id", UUID, nullable=False),
        sa.Column("changed_fields", JSONB, nullable=False),
        sa.Column("at", TS, nullable=False, server_default=NOW),
    )
    op.create_index("ix_audit_log_record", "audit_log", ["object", "record_id", "at"])
    op.create_table(
        "api_keys",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("company_id", UUID, nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("prefix", sa.Text(), nullable=False),
        sa.Column("key_hash", sa.Text(), nullable=False),
        sa.Column("scopes", JSONB, nullable=False),
        sa.Column("external", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_by", sa.Text()),
        sa.Column("created_at", TS, nullable=False, server_default=NOW),
        sa.Column("last_used_at", TS),
        sa.Column("revoked_at", TS),
        sa.UniqueConstraint("key_hash", name="uq_api_keys_hash"),
    )
    op.create_table(
        "records_settings",
        sa.Column("company_id", UUID, primary_key=True),
        sa.Column("agents_auto_approve_additive", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("updated_by", sa.Text()),
        sa.Column("updated_at", TS, nullable=False, server_default=NOW),
    )


def downgrade() -> None:
    op.drop_table("records_settings")
    op.drop_table("api_keys")
    op.drop_index("ix_audit_log_record", table_name="audit_log")
    op.drop_table("audit_log")
    op.drop_index("ix_schema_changes_company_created", table_name="schema_changes")
    op.drop_table("schema_changes")
    op.drop_index("uq_schema_blueprints_active", table_name="schema_blueprints")
    op.drop_table("schema_blueprints")
