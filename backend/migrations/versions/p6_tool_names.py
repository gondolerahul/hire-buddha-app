"""Entities name registered tools: scraper_tool, batch_web_search, docx_tool, ... (TL-67)

Revision ID: p6_tool_names
Revises: p5_draft_hash
Create Date: 2026-10-02

The deep-research and autonomous-BI seeds and a test fixture granted tools by
names nothing registers — ``scraper``, ``batch_search``, ``docx_generator``,
``sandbox_executor``, ``terminal_tool`` — so the entities seeded from them
planned steps no executor could run (TL-67). The seeds are corrected; this
renames the same ids in the entities already created, wherever a ``tool_id``
appears in ``capabilities`` or ``planning``.
"""
from typing import Any, Sequence, Union
import json

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "p6_tool_names"
down_revision: Union[str, Sequence[str], None] = "p5_draft_hash"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

RENAMES = {
    "scraper": "scraper_tool",
    "batch_search": "batch_web_search",
    "docx_generator": "docx_tool",
    "sandbox_executor": "sandbox_code",
    "terminal_tool": "terminal",
}


def _rename(node: Any, renames: dict) -> Any:
    if isinstance(node, dict):
        return {k: (renames.get(v, v) if k == "tool_id" and isinstance(v, str) else _rename(v, renames))
                for k, v in node.items()}
    if isinstance(node, list):
        return [_rename(v, renames) for v in node]
    return node


def _apply(renames: dict) -> None:
    conn = op.get_bind()
    like = " OR ".join(f"(capabilities::text LIKE '%\"{old}\"%' OR planning::text LIKE '%\"{old}\"%')"
                       for old in renames)
    rows = conn.execute(
        sa.text(f"SELECT id, capabilities, planning FROM hierarchical_entities WHERE {like}")
        .columns(capabilities=postgresql.JSONB(), planning=postgresql.JSONB())
    ).mappings().all()
    update = sa.text("UPDATE hierarchical_entities SET capabilities = CAST(:c AS jsonb), "
                     "planning = CAST(:p AS jsonb) WHERE id = :id")
    for row in rows:
        caps, plan = _rename(row["capabilities"], renames), _rename(row["planning"], renames)
        if caps != row["capabilities"] or plan != row["planning"]:
            conn.execute(update, {"id": row["id"], "c": json.dumps(caps), "p": json.dumps(plan)})


def upgrade() -> None:
    _apply(RENAMES)


def downgrade() -> None:
    # Only the ids this migration could have written; an entity that named the
    # registered tool before keeps it.
    pass
