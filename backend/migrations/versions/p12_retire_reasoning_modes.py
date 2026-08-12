"""Phase 12 (D-3): retire REFLECTION / TREE_OF_THOUGHTS per-entity reasoning modes.

The per-entity reasoning-mode dispatch for ``REFLECTION`` and
``TREE_OF_THOUGHTS`` was removed from ``step_executor._execute_thought`` (their
logic is superseded by the AgentLoop ``Reflector`` and the Strategist-selected
``DebateExecutor`` respectively — see
``docs/phase12/plans/01_phase11_consolidation.md`` §8.3). This data migration
rewrites every entity still configured with one of those modes to ``REACT`` so
no live entity points at a removed branch. ``REACT`` and ``CHAIN_OF_THOUGHT`` are
left untouched.

The mode lives at ``hierarchical_entities.logic_gate -> reasoning_config ->
reasoning_mode`` (a JSON column). The rewrite is done in Python via SQLAlchemy
core so it is portable across backends and the per-row logic
(``rewrite_logic_gate``) is unit-testable.

Revision ID: p12_retire_reasoning_modes
Revises: p11_execution_trace_events
Create Date: 2026-06-03
"""
from __future__ import annotations

import copy
from typing import Any, Optional

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "p12_retire_reasoning_modes"  # 26 chars — under the 32-char cap
down_revision = "p11_execution_trace_events"
branch_labels = None
depends_on = None


# Modes retired as per-entity settings; all rewritten to REACT.
RETIRED_MODES = ("REFLECTION", "TREE_OF_THOUGHTS")
TARGET_MODE = "REACT"


def rewrite_logic_gate(logic_gate: Any) -> Optional[dict]:
    """Return an updated ``logic_gate`` dict if its reasoning_mode is retired.

    Returns ``None`` when nothing needs to change (no reasoning_config, a
    supported mode, or a non-dict value), so callers only write rows that
    actually changed.
    """
    if not isinstance(logic_gate, dict):
        return None
    reasoning_config = logic_gate.get("reasoning_config")
    if not isinstance(reasoning_config, dict):
        return None
    mode = reasoning_config.get("reasoning_mode")
    if not isinstance(mode, str) or mode.upper() not in RETIRED_MODES:
        return None
    updated = copy.deepcopy(logic_gate)
    updated["reasoning_config"]["reasoning_mode"] = TARGET_MODE
    return updated


def upgrade() -> None:
    bind = op.get_bind()
    entities = sa.table(
        "hierarchical_entities",
        sa.column("id"),
        sa.column("logic_gate", sa.JSON),
    )
    rows = bind.execute(sa.select(entities.c.id, entities.c.logic_gate)).fetchall()
    rewritten = 0
    for row in rows:
        updated = rewrite_logic_gate(row.logic_gate)
        if updated is None:
            continue
        bind.execute(
            sa.update(entities)
            .where(entities.c.id == row.id)
            .values(logic_gate=updated)
        )
        rewritten += 1
    print(f"[p12_retire_reasoning_modes] rewrote {rewritten} entity/entities to REACT")


def downgrade() -> None:
    # Irreversible: the original REFLECTION / TREE_OF_THOUGHTS values are not
    # recorded, and the dispatch branches that honoured them no longer exist, so
    # there is nothing meaningful to restore. No-op.
    pass
