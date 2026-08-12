"""Phase 11 Track 6 — backfill intelligence rule status.

Track 6 introduced a candidate → confirmed lifecycle for nodes in the
intelligence memory domain. Every node that existed before the
lifecycle landed should be considered ``confirmed`` (operators or the
dreaming engine had already curated it). This migration stamps
``source_ref->>'status' = 'confirmed'`` on every node belonging to an
intelligence-domain CORTEX tree where ``source_ref`` does not already
carry a ``status`` key.

Idempotent. Batched at 1000 rows per chunk so big tenants don't lock
the table for long. Reversible: ``downgrade`` strips the keys we set,
preserving any operator-provided status.

Revision ID: p11t06_intel_status
Revises: p11t05_preserve_meta_cog
Create Date: 2026-05-28
"""
from __future__ import annotations

import logging

from alembic import op
import sqlalchemy as sa


revision = "p11t06_intel_status"
down_revision = "p11t05_preserve_meta_cog"
branch_labels = None
depends_on = None

logger = logging.getLogger("alembic.p11t06")


_BATCH = 1000


def _has_table(name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(name)


def upgrade() -> None:
    if not _has_table("cortex_nodes") or not _has_table("cortex_trees"):
        logger.info("p11t06: cortex tables missing, skipping")
        return
    bind = op.get_bind()
    total = 0
    while True:
        result = bind.execute(
            sa.text(
                """
                WITH targets AS (
                    SELECT n.id
                    FROM cortex_nodes n
                    JOIN cortex_trees t ON t.id = n.tree_id
                    WHERE t.memory_domain = 'intelligence'
                      AND (
                        n.source_ref IS NULL
                        OR NOT (n.source_ref ? 'status')
                      )
                    LIMIT :batch
                )
                UPDATE cortex_nodes
                   SET source_ref =
                         COALESCE(source_ref, '{}'::jsonb)
                         || jsonb_build_object(
                              'status', 'confirmed',
                              '_p11t06_backfilled', true
                            )
                 WHERE id IN (SELECT id FROM targets)
                """
            ),
            {"batch": _BATCH},
        )
        affected = result.rowcount or 0
        total += affected
        if affected < _BATCH:
            break
    logger.info("p11t06_backfill_intelligence_status: stamped %d nodes", total)


def downgrade() -> None:
    if not _has_table("cortex_nodes"):
        return
    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            UPDATE cortex_nodes
               SET source_ref = source_ref - 'status' - '_p11t06_backfilled'
             WHERE source_ref ? '_p11t06_backfilled'
            """
        )
    )
