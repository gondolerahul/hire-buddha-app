"""Runs know their depth; max_recursion_depth is one setting (EP-06, EP-28)

Revision ID: ep06_run_depth
Revises: ep03_retry_of_run_id
Create Date: 2026-10-01

``governance.max_recursion_depth`` was rendered into prompt text and nothing
counted depth, so only the credit balance bounded a recursive fan-out (EP-06).
Runs now carry ``depth`` (a top-level run is 0) and ``max_depth`` (the deepest a
descendant may go); a child run past it is refused. Existing child runs get
their depth from their ancestry.

The entity builder edited a second copy, ``governance.execution_limits.
max_recursion_depth``, which nothing read (EP-28). It is folded into the one
setting: where an entity has it, it becomes ``max_recursion_depth`` (it is the
value a person set; the other was the schema default) and is removed.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "ep06_run_depth"
down_revision: Union[str, Sequence[str], None] = "ep03_retry_of_run_id"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DEPTH_BACKFILL_SQL = """
WITH RECURSIVE tree AS (
    SELECT id, 0 AS depth FROM execution_runs WHERE parent_run_id IS NULL
    UNION ALL
    SELECT c.id, t.depth + 1 FROM execution_runs c JOIN tree t ON c.parent_run_id = t.id
)
UPDATE execution_runs r SET depth = tree.depth FROM tree WHERE r.id = tree.id AND tree.depth > 0
"""

FOLD_SQL = """
UPDATE hierarchical_entities
SET governance = jsonb_set(
    governance #- '{execution_limits,max_recursion_depth}',
    '{max_recursion_depth}',
    to_jsonb((governance -> 'execution_limits' ->> 'max_recursion_depth')::int)
)
WHERE jsonb_typeof(governance -> 'execution_limits') = 'object'
  AND (governance -> 'execution_limits' ->> 'max_recursion_depth') ~ '^[0-9]+$'
"""

DROP_LEFTOVER_SQL = """
UPDATE hierarchical_entities
SET governance = governance #- '{execution_limits,max_recursion_depth}'
WHERE jsonb_typeof(governance -> 'execution_limits') = 'object'
  AND (governance -> 'execution_limits') ->> 'max_recursion_depth' IS NOT NULL
"""


def upgrade() -> None:
    op.add_column("execution_runs", sa.Column("depth", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("execution_runs", sa.Column("max_depth", sa.Integer(), nullable=True))
    op.execute(DEPTH_BACKFILL_SQL)
    op.execute(FOLD_SQL)
    op.execute(DROP_LEFTOVER_SQL)   # a non-numeric leftover is dropped, not folded


def downgrade() -> None:
    op.drop_column("execution_runs", "max_depth")
    op.drop_column("execution_runs", "depth")
