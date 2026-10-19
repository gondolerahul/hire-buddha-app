"""run_subjects: contacts and leads a run found while it ran (TL-09)

Revision ID: p6_run_subjects
Revises: p6_tool_names
Create Date: 2026-10-02

Tools that send or write to a person or record take refs from the run's
subject scope instead of raw addresses (P6.11). The scope is derived from what
a run already stores — its input, the gateway event, the voice call, the
artifacts — except the subjects a run learns mid-run, such as the sender of a
message ``email_ingest`` fetched. This table holds those, keyed by the tree's
root run, with the run's company kept equal to the run's (DM-09).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "p6_run_subjects"
down_revision: Union[str, Sequence[str], None] = "p6_tool_names"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "run_subjects",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("label", sa.Text(), nullable=True),
        sa.Column("source", sa.String(40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["run_id", "company_id"], ["execution_runs.id", "execution_runs.company_id"],
                                name="fk_run_subjects_run_company", ondelete="CASCADE"),
        sa.UniqueConstraint("run_id", "kind", "value", name="uq_run_subjects_value"),
    )
    op.create_index("ix_run_subjects_run_id", "run_subjects", ["run_id"])


def downgrade() -> None:
    op.drop_index("ix_run_subjects_run_id", table_name="run_subjects")
    op.drop_table("run_subjects")
