"""Phase 11: add agent-loop CORTEX node types (snapshot, health_record, health_root)

The Phase 11 agent loop and critic pipeline write CORTEX nodes of types
``snapshot`` (``core/agent_loop.py``), ``health_record`` and ``health_root``
(``planning/critic_pipeline.py``). These labels were never added to the
``cortex_node_type`` Postgres enum, so:

  * the snapshot / health-record *writes* failed silently (caught by the
    callers' try/except), leaving runs with no AgentState snapshot, and
  * the read endpoints ``GET /executions/{id}/agent_state`` (503) and
    ``GET /ai/phase11/executions/{id}/health_records`` (500) raised
    ``InvalidTextRepresentationError`` — which left the ExecutionDetail
    agent-loop view blank for finished runs.

This migration extends the enum so both the writes and the read endpoints
work.

IMPORTANT: ``ALTER TYPE ... ADD VALUE`` adds the label without using it in
the same statement, which is permitted on PostgreSQL 12+. ``IF NOT EXISTS``
keeps the migration idempotent (the values may already have been added as a
hotfix on a running database).

Revision ID: p11t_cortex_loop_node_types
Revises: p11_merge_2026_05_28
Create Date: 2026-05-30
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "p11t_cortex_loop_node_types"
down_revision = "p11_merge_2026_05_28"
branch_labels = None
depends_on = None

NEW_NODE_TYPES = ("snapshot", "health_record", "health_root")


def upgrade() -> None:
    for val in NEW_NODE_TYPES:
        op.execute(f"ALTER TYPE cortex_node_type ADD VALUE IF NOT EXISTS '{val}'")


def downgrade() -> None:
    # PostgreSQL does not support removing a value from an enum type without
    # recreating the type and rewriting every dependent column. These labels
    # are additive and harmless, so the downgrade is intentionally a no-op.
    pass
