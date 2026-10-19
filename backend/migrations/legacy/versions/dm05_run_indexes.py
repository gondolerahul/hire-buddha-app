"""Index the run tables on the columns every query filters by (DM-05, DM-06)

Revision ID: dm05_run_indexes
Revises: dm21_schema_catch_up
Create Date: 2026-09-30

``execution_runs`` had no index but its primary key and the idempotency key, so
"list my runs" (company, newest first), "runs of this agent" and "children of
this run" were sequential scans. The four tables that hang off a run —
``llm_interaction_logs``, ``tool_interaction_logs``, ``human_approvals`` and
``usage_logs`` — are always read by ``run_id`` and had no index on it.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "dm05_run_indexes"
down_revision: Union[str, Sequence[str], None] = "dm21_schema_catch_up"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

INDEXES = [
    ("ix_execution_runs_company_created", "execution_runs", ["company_id", "created_at"]),
    ("ix_execution_runs_entity_created", "execution_runs", ["entity_id", "created_at"]),
    ("ix_execution_runs_parent_run_id", "execution_runs", ["parent_run_id"]),
    ("ix_llm_interaction_logs_run_id", "llm_interaction_logs", ["run_id"]),
    ("ix_tool_interaction_logs_run_id", "tool_interaction_logs", ["run_id"]),
    ("ix_human_approvals_run_id", "human_approvals", ["run_id"]),
    ("ix_usage_logs_run_id", "usage_logs", ["run_id"]),
]


def upgrade() -> None:
    for name, table, columns in INDEXES:
        op.create_index(name, table, columns, if_not_exists=True)


def downgrade() -> None:
    for name, table, _ in reversed(INDEXES):
        op.drop_index(name, table_name=table, if_exists=True)
