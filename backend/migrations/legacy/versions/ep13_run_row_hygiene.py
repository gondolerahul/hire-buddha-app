"""Run rows lose two dead columns; finished runs get their execution time (EP-13, EP-15)

Revision ID: ep13_run_row_hygiene
Revises: au26_email_lowercase
Create Date: 2026-10-01

``execution_runs.idempotency_key`` (with its partial index) and ``span_id`` were
written by nothing and read by nothing (EP-13). Run idempotency is the arq
dispatch guard on terminal status; step-level dedup belongs to
``tool_interaction_logs.idempotency_key`` (TL-39), which stays.

``execution_time_ms`` was read by the reports, registry search and the run
episodes, and written by nothing (EP-15). The loop now writes it at
finalisation; this fills it for runs that already finished.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "ep13_run_row_hygiene"
down_revision: Union[str, Sequence[str], None] = "au26_email_lowercase"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_exec_runs_idemp")
    op.execute("DROP INDEX IF EXISTS ix_execution_runs_idempotency_key")
    op.drop_column("execution_runs", "idempotency_key")
    op.drop_column("execution_runs", "span_id")
    op.execute(
        "UPDATE execution_runs "
        "SET execution_time_ms = GREATEST(0, (EXTRACT(EPOCH FROM (completed_at - started_at)) * 1000)::bigint)::int "
        "WHERE execution_time_ms IS NULL AND completed_at IS NOT NULL AND started_at IS NOT NULL"
    )


def downgrade() -> None:
    op.add_column("execution_runs", sa.Column("span_id", sa.String(), nullable=True))
    op.add_column("execution_runs", sa.Column("idempotency_key", sa.String(255), nullable=True))
    op.create_index(
        "idx_exec_runs_idemp",
        "execution_runs",
        ["idempotency_key"],
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )
