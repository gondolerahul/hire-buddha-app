"""Phase 11 Track 5 — preserve meta-cognition tiers across the default flip.

Before Track 5, ``resolve_meta_cognition`` auto-enabled
``registry_search`` and ``self_modification`` for any AGENT or PROCESS.
After Track 5 those tiers are opt-in (only the Meta-Agent gets them
implicitly), so existing entities relying on the old defaults would
silently lose capability the moment the new code rolls out.

This migration writes explicit ``registry_search=true`` and
``self_modification=true`` into ``hierarchical_entities.capabilities``
for every AGENT / PROCESS entity that has no explicit
``meta_cognition`` block. Idempotent: any entity with even a partial
``meta_cognition`` config is left untouched (the operator already made
a choice).

Batched at 500 rows per chunk so big tenants don't hold a long write
lock. Reversible: ``downgrade`` strips the keys we *added*, leaving
operator-set entries alone via a stamp inside the block.

Revision ID: p11t05_preserve_meta_cog
Revises: p11t02_feature_flags
Create Date: 2026-05-28
"""
from __future__ import annotations

import json
import logging

from alembic import op
import sqlalchemy as sa


revision = "p11t05_preserve_meta_cog"
down_revision = "p11t02_feature_flags"
branch_labels = None
depends_on = None

logger = logging.getLogger("alembic.p11t05")

_BATCH = 500
_STAMP_KEY = "_p11t05_backfilled"


def upgrade() -> None:
    bind = op.get_bind()
    last_id = "00000000-0000-0000-0000-000000000000"
    total = 0
    while True:
        rows = bind.execute(
            sa.text(
                """
                SELECT id, capabilities
                FROM hierarchical_entities
                WHERE type IN ('AGENT', 'PROCESS')
                  AND id > :last_id
                ORDER BY id
                LIMIT :batch
                """
            ),
            {"last_id": last_id, "batch": _BATCH},
        ).fetchall()
        if not rows:
            break
        for ent_id, caps in rows:
            last_id = str(ent_id)
            cap_dict = caps if isinstance(caps, dict) else (
                json.loads(caps) if isinstance(caps, str) and caps else {}
            )
            mc = cap_dict.get("meta_cognition")
            if isinstance(mc, dict) and (
                "registry_search" in mc or "self_modification" in mc
            ):
                continue
            new_mc = dict(mc) if isinstance(mc, dict) else {}
            new_mc.setdefault("registry_search", True)
            new_mc.setdefault("self_modification", True)
            new_mc[_STAMP_KEY] = True
            cap_dict["meta_cognition"] = new_mc
            bind.execute(
                sa.text(
                    "UPDATE hierarchical_entities SET capabilities = :c "
                    "WHERE id = :id"
                ),
                {"c": json.dumps(cap_dict, default=str), "id": ent_id},
            )
            total += 1
    logger.info("p11t05_preserve_meta_cognition: backfilled %d entities", total)


def downgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            """
            SELECT id, capabilities
            FROM hierarchical_entities
            WHERE capabilities::text LIKE '%' || :stamp || '%'
            """
        ),
        {"stamp": _STAMP_KEY},
    ).fetchall()
    for ent_id, caps in rows:
        cap_dict = caps if isinstance(caps, dict) else (
            json.loads(caps) if isinstance(caps, str) and caps else {}
        )
        mc = cap_dict.get("meta_cognition") or {}
        if not isinstance(mc, dict) or not mc.get(_STAMP_KEY):
            continue
        # Strip only what we added.
        mc.pop("registry_search", None)
        mc.pop("self_modification", None)
        mc.pop(_STAMP_KEY, None)
        if mc:
            cap_dict["meta_cognition"] = mc
        else:
            cap_dict.pop("meta_cognition", None)
        bind.execute(
            sa.text(
                "UPDATE hierarchical_entities SET capabilities = :c "
                "WHERE id = :id"
            ),
            {"c": json.dumps(cap_dict, default=str), "id": ent_id},
        )
