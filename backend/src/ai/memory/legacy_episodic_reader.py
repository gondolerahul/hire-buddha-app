"""
ai.memory.legacy_episodic_reader — Read-only adapter for legacy episodes.

Phase 11 Track 6: the canonical episodic store is the per-entity
EpisodicTree (managed by :class:`EpisodicTreeService`). The flat
``episodic_memories`` table is retained for backward compatibility and
queried only when an entity has no EpisodicTree data yet — typically
on the first run after migration.

This reader is **read-only**. It never writes; it surfaces what was
already stored so freshly-migrated entities don't look amnesiac on
their first v2-pipeline run. Will be removed in Phase 12 once all
entities have accumulated tree-shaped episodic history.
"""
from __future__ import annotations

import logging
from typing import Any, ClassVar, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

__all__ = ["LegacyEpisodicReader"]


class LegacyEpisodicReader:
    """Reads the legacy flat ``episodic_memories`` table."""

    _warned: ClassVar[bool] = False

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        if not getattr(LegacyEpisodicReader, "_warned", False):
            logger.info(
                "LegacyEpisodicReader is deprecated as of Phase 11 Track 6 "
                "and will be removed in Phase 12; it now only fills the "
                "first-run gap for entities with no EpisodicTree yet."
            )
            LegacyEpisodicReader._warned = True

    async def read(
        self,
        *,
        entity_id: UUID,
        user_id: Optional[UUID] = None,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """Return up to ``limit`` recent episodes for the entity.

        Returned rows mirror the shape :class:`EpisodicTreeService`
        emits so downstream prompt builders don't need to special-case
        the legacy source.
        """
        from src.ai.orm.memory import EpisodicMemory
        try:
            stmt = (
                select(EpisodicMemory)
                .where(EpisodicMemory.entity_id == entity_id)
                .order_by(EpisodicMemory.created_at.desc())
                .limit(max(1, limit))
            )
            if user_id is not None:
                stmt = stmt.where(EpisodicMemory.user_id == user_id)
            rows = (await self.db.execute(stmt)).scalars().all()
        except Exception as exc:                                            # pragma: no cover
            logger.debug(f"LegacyEpisodicReader query failed: {exc}")
            return []

        episodes: list[dict[str, Any]] = []
        for row in reversed(rows):  # chronological
            episodes.append({
                "input": (row.input_summary or "")[:500],
                "output": (row.output_summary or "")[:500],
                "status": row.status or "",
                "at": row.created_at.isoformat() if row.created_at else "",
                "_source": "legacy_episodic_memories",
            })
        return episodes
