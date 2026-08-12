"""Phase 11 Track 2 — feature_flags table.

Creates the per-(company, entity) feature-flag table referenced by
``ai.core.feature_flags.FeatureFlags._db_lookup`` and by
``ai.phase11_router.toggle_experimental_tool`` /
``get_my_feature_flags``. Resolution order is:

    1. ``entity.metadata_extensions.feature_flags[flag_key]``
    2. row with ``entity_id = e``
    3. row with ``company_id = c AND entity_id IS NULL``
    4. row with ``company_id IS NULL AND entity_id IS NULL`` (global default)
    5. code default (see ``DEFAULTS`` in ``feature_flags.py``)

This migration was authored at Track 2 but only persisted to disk after
the canary work proved the table was required (see Phase 12 backlog).
``CREATE TABLE IF NOT EXISTS`` semantics are achieved via Alembic's
inspector check so re-running on databases where ops manually pre-
created the table is a no-op.

Revision ID: p11t02_feature_flags
Revises: p11t09_kpi_rollup
Create Date: 2026-05-28
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSON, UUID


revision = "p11t02_feature_flags"
down_revision = "p11t09_kpi_rollup"
branch_labels = None
depends_on = None


def _has_table(name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return inspector.has_table(name)


def upgrade() -> None:
    if _has_table("feature_flags"):
        # Operator created the table manually before the migration
        # landed. Make sure the columns + index we rely on are in
        # place but never raise.
        bind = op.get_bind()
        cols = {c["name"] for c in sa.inspect(bind).get_columns("feature_flags")}
        with op.batch_alter_table("feature_flags") as batch:
            if "value_json" not in cols:
                batch.add_column(sa.Column("value_json", JSON, nullable=True))
            if "entity_id" not in cols:
                batch.add_column(sa.Column("entity_id", UUID(as_uuid=True), nullable=True))
        return

    op.create_table(
        "feature_flags",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("company_id", UUID(as_uuid=True), nullable=True),
        sa.Column("entity_id", UUID(as_uuid=True), nullable=True),
        sa.Column("flag_key", sa.String(128), nullable=False),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("value_json", JSON, nullable=True),
        sa.Column(
            "created_at", sa.DateTime,
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime,
            server_default=sa.text("now()"), nullable=False,
        ),
    )
    # Three partial unique indexes — one per scope tier — so each
    # (flag_key, scope) pair is unique even when NULLs are present.
    # Required for Postgres < 15 where each NULL in a multi-column
    # unique index is treated as distinct.
    op.execute(
        "CREATE UNIQUE INDEX ix_feature_flags_global "
        "ON feature_flags (flag_key) "
        "WHERE company_id IS NULL AND entity_id IS NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX ix_feature_flags_company "
        "ON feature_flags (flag_key, company_id) "
        "WHERE company_id IS NOT NULL AND entity_id IS NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX ix_feature_flags_entity "
        "ON feature_flags (flag_key, entity_id) "
        "WHERE entity_id IS NOT NULL"
    )
    op.create_index(
        "ix_feature_flags_company_lookup", "feature_flags", ["company_id"],
    )


def downgrade() -> None:
    if not _has_table("feature_flags"):
        return
    for ix in (
        "ix_feature_flags_company_lookup",
        "ix_feature_flags_entity",
        "ix_feature_flags_company",
        "ix_feature_flags_global",
    ):
        op.execute(f"DROP INDEX IF EXISTS {ix}")
    op.drop_table("feature_flags")
