"""Entity versions and assets; runs pin the version they execute (EP-10, R2)

Revision ID: p5_entity_versions
Revises: ep06_run_depth
Create Date: 2026-10-02

``hierarchical_entities.version`` was a label nothing read, and every run read
the live row, so an edit reached runs already in flight (EP-10). Versions are
append-only snapshots of an entity's definition (``entity_versions``) with the
scripts and small files that belong to them (``entity_assets``); the entity
points at its head (``active_version_id``) and a run at the version it executes
(``entity_version_id``).

Every existing entity gets a published version 1 of its current content, with
the hash the application computes, so the first run after the upgrade reuses it.
Runs created before the upgrade stay unpinned: what they executed is not known.
"""
from typing import Sequence, Union
import json
import uuid
from datetime import datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "p5_entity_versions"
down_revision: Union[str, Sequence[str], None] = "ep06_run_depth"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "entity_versions",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("entity_id", UUID, sa.ForeignKey("hierarchical_entities.id"), nullable=False),
        sa.Column("company_id", UUID, sa.ForeignKey("companies.id"), nullable=True),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(), nullable=True),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("published", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_by", UUID, sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_by", UUID, sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("entity_id", "version_number", name="uq_entity_versions_number"),
        sa.UniqueConstraint("entity_id", "content_hash", name="uq_entity_versions_content"),
    )
    op.create_table(
        "entity_assets",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("entity_version_id", UUID, sa.ForeignKey("entity_versions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("path", sa.String(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("language", sa.String(), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("entity_version_id", "path", name="uq_entity_assets_path"),
    )
    op.create_index("ix_entity_assets_version", "entity_assets", ["entity_version_id"])
    op.add_column("hierarchical_entities", sa.Column("active_version_id", UUID, nullable=True))
    op.create_foreign_key("fk_hierarchical_entities_active_version", "hierarchical_entities",
                          "entity_versions", ["active_version_id"], ["id"])
    op.add_column("execution_runs", sa.Column("entity_version_id", UUID, nullable=True))
    op.create_foreign_key("execution_runs_entity_version_id_fkey", "execution_runs",
                          "entity_versions", ["entity_version_id"], ["id"])
    op.create_index("ix_execution_runs_entity_version_id", "execution_runs", ["entity_version_id"])

    _backfill_version_one()


def _backfill_version_one() -> None:
    from src.ai.governance.entity_versions import SNAPSHOT_FIELDS, content_hash

    conn = op.get_bind()
    cols = ", ".join(("id", "company_id", *SNAPSHOT_FIELDS))
    # Typed, so JSON comes back decoded exactly as the application reads it.
    json_types = {f: postgresql.JSONB() for f in (
        "identity", "hierarchy", "logic_gate", "planning", "capabilities", "governance",
        "observability", "metadata_extensions")}
    json_types["io_contract"] = sa.JSON()
    rows = conn.execute(
        sa.text(f"SELECT {cols} FROM hierarchical_entities").columns(**json_types)
    ).mappings().all()
    now = datetime.utcnow()
    insert = sa.text(
        "INSERT INTO entity_versions (id, entity_id, company_id, version_number, label, snapshot, "
        "content_hash, published, published_at, created_at) "
        "VALUES (:id, :entity_id, :company_id, 1, :label, CAST(:snapshot AS json), :hash, true, :now, :now)"
    )
    point = sa.text("UPDATE hierarchical_entities SET active_version_id = :vid WHERE id = :eid")
    for row in rows:
        snapshot = {f: row[f] for f in SNAPSHOT_FIELDS}
        vid = uuid.uuid4()
        conn.execute(insert, {
            "id": vid, "entity_id": row["id"], "company_id": row["company_id"], "label": row["version"],
            "snapshot": json.dumps(snapshot, default=str), "hash": content_hash(snapshot), "now": now,
        })
        conn.execute(point, {"vid": vid, "eid": row["id"]})


def downgrade() -> None:
    op.drop_index("ix_execution_runs_entity_version_id", table_name="execution_runs")
    op.drop_constraint("execution_runs_entity_version_id_fkey", "execution_runs", type_="foreignkey")
    op.drop_column("execution_runs", "entity_version_id")
    op.drop_constraint("fk_hierarchical_entities_active_version", "hierarchical_entities", type_="foreignkey")
    op.drop_column("hierarchical_entities", "active_version_id")
    op.drop_index("ix_entity_assets_version", table_name="entity_assets")
    op.drop_table("entity_assets")
    op.drop_table("entity_versions")
