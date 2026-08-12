"""Phase 11: make cortex_trees.entity_id nullable

The v2.0 four-domain memory architecture introduced tenant/app/partner-scoped
CORTEX trees that are NOT tied to a single hierarchical entity. The clearest
example is the Meta-Agent platform-intelligence tree created by
``meta/meta_intelligence_tree.py`` (``scope_level='tenant'``,
``memory_domain='intelligence'``), which is looked up and inserted with
``entity_id=NULL``.

The original ``cortex_trees`` table (``k1l2m3n4o5p6``) declared ``entity_id``
``NOT NULL``, so every attempt to create such a tree raised
``NotNullViolationError: null value in column "entity_id" of relation
"cortex_trees"`` and 500'd the ``/ai/phase11/meta/intelligence/*`` endpoints.

This migration drops the NOT NULL constraint. The foreign key is retained, so
any non-NULL ``entity_id`` still has to reference a real entity.

Revision ID: p11t10_cortex_entity_nullable
Revises: p11t_cortex_loop_node_types
Create Date: 2026-05-30
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "p11t10_cortex_entity_nullable"
down_revision = "p11t_cortex_loop_node_types"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("cortex_trees", "entity_id", nullable=True)


def downgrade() -> None:
    # Best-effort: only re-imposes NOT NULL. Rows with NULL entity_id (e.g. the
    # tenant-scoped meta-intelligence tree) must be removed first or this fails.
    op.alter_column("cortex_trees", "entity_id", nullable=False)
