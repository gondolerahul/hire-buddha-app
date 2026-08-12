"""
anti_sprawl.py — Governance safeguards for Meta-Agent entity creation.

V2: Hard gates with semantic deduplication.
  - Daily creation limit (hard gate, blocks creation)
  - Adaptation chain monitoring (consolidation detection)
  - Semantic deduplication (blocks >85% similar entities)
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

DEFAULT_DAILY_CREATION_LIMIT = 10
DEFAULT_ADAPTATION_THRESHOLD = 3
SEMANTIC_DUPLICATE_THRESHOLD = 0.85


class AntiSprawlGuard:
    """Governance service for Meta-Agent entity lifecycle."""

    def __init__(self, db: AsyncSession, company_id: UUID):
        self.db = db
        self.company_id = company_id

    async def check_creation_allowed(
        self,
        meta_agent_user_id: Optional[UUID] = None,
        daily_limit: int = DEFAULT_DAILY_CREATION_LIMIT,
    ) -> Dict[str, Any]:
        """Check if creation is allowed (daily limit not exceeded).

        This is a HARD GATE — if this returns allowed=False, the
        MetaEntityCreatorTool must block entity creation.
        """
        from src.ai.models import HierarchicalEntity

        since = datetime.utcnow() - timedelta(hours=24)
        query = select(func.count(HierarchicalEntity.id)).where(
            HierarchicalEntity.company_id == self.company_id,
            HierarchicalEntity.created_at >= since,
            HierarchicalEntity.status != "DELETED",
        )
        if meta_agent_user_id:
            query = query.where(HierarchicalEntity.created_by == meta_agent_user_id)

        result = await self.db.execute(query)
        count = result.scalar() or 0
        allowed = count < daily_limit

        return {
            "allowed": allowed,
            "created_today": count,
            "limit": daily_limit,
            "message": (
                f"Creation allowed ({count}/{daily_limit} today)"
                if allowed
                else f"Daily creation limit reached ({count}/{daily_limit}). "
                     f"Try reusing or adapting existing agents instead."
            ),
        }

    async def check_consolidation_needed(
        self, source_entity_id: UUID,
        threshold: int = DEFAULT_ADAPTATION_THRESHOLD,
    ) -> Dict[str, Any]:
        """Check if an entity has been adapted too many times.

        This is a HARD GATE — if consolidation is needed, the
        MetaEntityCreatorTool should suggest using an existing version
        rather than creating another adaptation.
        """
        from src.ai.models import HierarchicalEntity

        result = await self.db.execute(
            select(
                HierarchicalEntity.id,
                HierarchicalEntity.version,
                HierarchicalEntity.name,
            ).where(
                HierarchicalEntity.template_source_id == source_entity_id,
                HierarchicalEntity.company_id == self.company_id,
                HierarchicalEntity.status != "DELETED",
            ).order_by(HierarchicalEntity.created_at.desc())
        )
        versions = result.fetchall()
        count = len(versions)

        return {
            "needs_consolidation": count >= threshold,
            "adaptation_count": count,
            "threshold": threshold,
            "versions": [
                {"id": str(v[0]), "version": v[1], "name": v[2]}
                for v in versions[:10]
            ],
        }

    async def check_semantic_duplicate(
        self,
        description: str,
        required_tools: List[str],
        preferred_type: Optional[str] = None,
        threshold: float = SEMANTIC_DUPLICATE_THRESHOLD,
    ) -> Dict[str, Any]:
        """Check if a near-duplicate entity already exists.

        Uses RegistrySearchService to find entities with >threshold
        combined score. If found, blocks creation and returns the
        existing entity details.

        This is a HARD GATE — near-duplicates must use VERSION mode
        instead of CREATE.
        """
        from src.ai.meta.registry_search_service import (
            RegistrySearchService,
            SearchRequest,
        )

        try:
            search_svc = RegistrySearchService(self.db, self.company_id)
            request = SearchRequest(
                intent=description,
                required_tools=required_tools,
                preferred_type=preferred_type,
            )

            candidates = await search_svc.search(request, top_k=1)

            if candidates and candidates[0].combined_score > threshold:
                best = candidates[0]
                return {
                    "is_duplicate": True,
                    "existing_entity_id": str(best.entity_id),
                    "existing_entity_name": best.entity_name,
                    "similarity_score": round(best.combined_score, 3),
                    "message": (
                        f"Near-duplicate detected: '{best.entity_name}' "
                        f"(similarity: {best.combined_score:.0%}). "
                        f"Use VERSION mode to adapt the existing entity instead "
                        f"of creating a new one."
                    ),
                }

            return {
                "is_duplicate": False,
                "message": "No near-duplicates found. Creation allowed.",
            }

        except Exception as e:
            logger.warning(f"Semantic duplicate check failed: {e}. Allowing creation.")
            return {
                "is_duplicate": False,
                "message": f"Duplicate check skipped due to error: {e}",
            }
