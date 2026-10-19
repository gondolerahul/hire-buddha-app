"""A retry or refinement points at the run it repeats, not at a parent (EP-03)

Revision ID: ep03_retry_of_run_id
Revises: r1_entity_levels
Create Date: 2026-10-01

``execution_runs.parent_run_id`` carried two relationships: a structural child
run (a CHILD_ENTITY_INVOCATION, or a CORTEX RECURSE subtree) and the previous
run of a retry or refine chain. Everything that reads it as structure — the
credit guard (admission, breaker, settlement only for runs without a parent),
the root run list, parent resume — treated a retry as a child: it was never
admitted against the wallet, never stopped by the breaker and never settled.

``retry_of_run_id`` now holds the chain; ``parent_run_id`` means structure only.
The backfill moves the rows the old code wrote: refinements (their input carries
``__refinement_feedback__``) and retries (the same entity as the run they point
at, without the ``subtree_root_id`` a RECURSE child carries).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "ep03_retry_of_run_id"
down_revision: Union[str, Sequence[str], None] = "r1_entity_levels"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Kept as a constant so tests can run it against rows in the old shape.
BACKFILL_SQL = """
UPDATE execution_runs AS c
SET retry_of_run_id = c.parent_run_id, parent_run_id = NULL
FROM execution_runs AS p
WHERE c.parent_run_id = p.id
  AND (
    c.input_data ->> '__refinement_feedback__' IS NOT NULL
    OR (c.entity_id = p.entity_id AND c.input_data ->> 'subtree_root_id' IS NULL)
  )
"""


def upgrade() -> None:
    op.add_column(
        "execution_runs",
        sa.Column("retry_of_run_id", UUID(as_uuid=True), sa.ForeignKey("execution_runs.id"), nullable=True),
    )
    op.create_index("ix_execution_runs_retry_of_run_id", "execution_runs", ["retry_of_run_id"])
    op.execute(BACKFILL_SQL)


def downgrade() -> None:
    op.execute(
        "UPDATE execution_runs SET parent_run_id = retry_of_run_id "
        "WHERE retry_of_run_id IS NOT NULL AND parent_run_id IS NULL"
    )
    op.drop_index("ix_execution_runs_retry_of_run_id", table_name="execution_runs")
    op.drop_column("execution_runs", "retry_of_run_id")
