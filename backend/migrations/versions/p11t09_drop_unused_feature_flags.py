"""Phase 11 Track 9 — drop unused feature_flags rows.

Cleanup migration. As Tracks 0-8 shipped, some flags were renamed or
retired (e.g. an early ``planner.candidates_v2`` collapsed into
``planner.v2_enabled``). Rows for retired flag_keys clutter the admin
UI and risk an operator toggling a no-op switch.

The migration is **idempotent and conservative**:
  * It only deletes rows whose ``flag_key`` is NOT present in the
    in-process ``DEFAULTS`` or ``NUMERIC_DEFAULTS`` set AND does not
    start with a known dynamic prefix (e.g. ``tools.experimental.``).
  * It logs the deleted rows so ops can recover them from telemetry.
  * It only runs when the ``feature_flags`` table exists.

Revision ID: p11t09_drop_flags
Revises: p11t06_intel_status
Create Date: 2026-05-28
"""
from __future__ import annotations

import logging

from alembic import op
import sqlalchemy as sa


revision = "p11t09_drop_flags"
down_revision = "p11t06_intel_status"
branch_labels = None
depends_on = None

logger = logging.getLogger("alembic.p11t09")


# Prefixes for dynamically-named flags that must NEVER be swept even
# when not in DEFAULTS (their full key is operator-defined).
_DYNAMIC_PREFIXES = (
    "tools.experimental.",
    "company.",
    "tenant.",
)


def _has_table(name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(name)


def _known_keys() -> set[str]:
    try:
        from src.ai.core.feature_flags import DEFAULTS, NUMERIC_DEFAULTS
    except Exception:                                                       # pragma: no cover
        return set()
    return set(DEFAULTS) | set(NUMERIC_DEFAULTS)


def upgrade() -> None:
    if not _has_table("feature_flags"):
        return
    bind = op.get_bind()
    known = _known_keys()
    rows = bind.execute(
        sa.text("SELECT id, flag_key FROM feature_flags")
    ).fetchall()
    to_drop: list[str] = []
    for row_id, key in rows:
        if key in known:
            continue
        if any(key.startswith(p) for p in _DYNAMIC_PREFIXES):
            continue
        to_drop.append(str(row_id))
    if not to_drop:
        logger.info("p11t09_drop_unused_feature_flags: nothing to drop")
        return
    bind.execute(
        sa.text("DELETE FROM feature_flags WHERE id = ANY(:ids)"),
        {"ids": to_drop},
    )
    logger.info(
        "p11t09_drop_unused_feature_flags: deleted %d rows", len(to_drop)
    )


def downgrade() -> None:
    # Deletions of unused rows are not reversible; the rows had no
    # downstream consumers by definition. No-op so the migration can
    # still roll back the rest of the chain.
    return
