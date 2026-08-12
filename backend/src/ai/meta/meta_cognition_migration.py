"""
ai.meta.meta_cognition_migration — Preserve meta-cognition tiers
across the Phase 11 Track 5 default flip.

Before Track 5, ``resolve_meta_cognition`` auto-enabled
``registry_search`` and ``self_modification`` for any AGENT or PROCESS
entity. After Track 5 those tiers are *opt-in*; only the Meta-Agent
gets them automatically.

To avoid silently dropping capability for production agents, this
helper backfills explicit ``registry_search=true`` /
``self_modification=true`` for every existing AGENT/PROCESS that has
no explicit ``meta_cognition`` configuration. Run it BEFORE deploying
the code change.

Usage (CLI)::

    cd backend && .venv/bin/python -m src.ai.meta.meta_cognition_migration

Or programmatically (in a one-off script or a maintenance route)::

    from src.ai.meta.meta_cognition_migration import backfill_meta_cognition
    n = await backfill_meta_cognition(db)
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

__all__ = ["backfill_meta_cognition", "main"]


async def backfill_meta_cognition(db: AsyncSession) -> int:
    """Backfill explicit meta_cognition.* for AGENT/PROCESS entities.

    Returns the number of entities mutated. Idempotent: an entity with
    *any* explicit ``meta_cognition`` block is left untouched.
    """
    # Lazy import to avoid heavy ORM dependency at module-import time.
    from src.ai.orm.entity import HierarchicalEntity

    rows = (await db.execute(
        select(HierarchicalEntity).where(
            HierarchicalEntity.type.in_(["AGENT", "PROCESS"]),
        )
    )).scalars().all()

    mutated = 0
    for entity in rows:
        caps = dict(entity.capabilities or {})
        mc = caps.get("meta_cognition")
        if isinstance(mc, dict) and (
            "registry_search" in mc or "self_modification" in mc
        ):
            continue
        new_mc = dict(mc) if isinstance(mc, dict) else {}
        new_mc.setdefault("registry_search", True)
        new_mc.setdefault("self_modification", True)
        # Preserve any explicit platform_awareness or limits the caller
        # may have set; just fill in the now-explicit booleans.
        caps["meta_cognition"] = new_mc
        entity.capabilities = caps
        mutated += 1

    if mutated:
        await db.commit()
        logger.info(
            "backfill_meta_cognition: mutated %d AGENT/PROCESS entities "
            "to preserve registry_search/self_modification.",
            mutated,
        )
    else:
        logger.info(
            "backfill_meta_cognition: no entities required backfill."
        )
    return mutated


async def main() -> None:                                                   # pragma: no cover
    from src.common.database import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        await backfill_meta_cognition(db)


if __name__ == "__main__":                                                  # pragma: no cover
    asyncio.run(main())
