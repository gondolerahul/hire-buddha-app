"""Run logs carry their run's company_id, kept equal by a composite key (DM-09)

Revision ID: dm09_log_company_id
Revises: fe10_tool_log_step_name
Create Date: 2026-10-01

``llm_interaction_logs``, ``tool_interaction_logs`` and ``human_approvals`` had
no tenant column: a query that forgot to join ``execution_runs`` returned every
company's rows. Each now has ``company_id NOT NULL``, backfilled from its run.
The key ``(run_id, company_id) → execution_runs(id, company_id)`` replaces the
plain ``run_id`` key, so the copy cannot drift from the run's company.

``execution_trace_events.company_id`` already existed without a key; it gets
the same composite key (its plain ``run_id`` key stays, since its company may
be NULL).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "dm09_log_company_id"
down_revision: Union[str, Sequence[str], None] = "fe10_tool_log_step_name"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

LOGS = ("llm_interaction_logs", "tool_interaction_logs", "human_approvals")
INDEXES = {
    "llm_interaction_logs": ("ix_llm_interaction_logs_company_created", ["company_id", "created_at"]),
    "tool_interaction_logs": ("ix_tool_interaction_logs_company_created", ["company_id", "created_at"]),
    "human_approvals": ("ix_human_approvals_company_status", ["company_id", "status"]),
}


def upgrade() -> None:
    op.create_unique_constraint("uq_execution_runs_id_company", "execution_runs", ["id", "company_id"])
    for table in LOGS:
        op.add_column(table, sa.Column("company_id", UUID(as_uuid=True), nullable=True))
        op.execute(f"UPDATE {table} t SET company_id = r.company_id FROM execution_runs r WHERE r.id = t.run_id")
        op.alter_column(table, "company_id", nullable=False)
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {table}_run_id_fkey")
        op.create_foreign_key(f"fk_{table}_run_company", table, "execution_runs",
                              ["run_id", "company_id"], ["id", "company_id"])
        name, columns = INDEXES[table]
        op.create_index(name, table, columns)

    op.execute("""
        UPDATE execution_trace_events e SET company_id = r.company_id
        FROM execution_runs r
        WHERE r.id = e.run_id AND e.company_id IS NOT NULL AND e.company_id <> r.company_id
    """)
    op.create_foreign_key("fk_execution_trace_events_run_company", "execution_trace_events", "execution_runs",
                          ["run_id", "company_id"], ["id", "company_id"], ondelete="CASCADE")


def downgrade() -> None:
    op.drop_constraint("fk_execution_trace_events_run_company", "execution_trace_events", type_="foreignkey")
    for table in LOGS:
        op.drop_index(INDEXES[table][0], table_name=table)
        op.drop_constraint(f"fk_{table}_run_company", table, type_="foreignkey")
        op.create_foreign_key(f"{table}_run_id_fkey", table, "execution_runs", ["run_id"], ["id"])
        op.drop_column(table, "company_id")
    op.drop_constraint("uq_execution_runs_id_company", "execution_runs", type_="unique")
