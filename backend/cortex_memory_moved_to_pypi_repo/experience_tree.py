"""
experience_tree_service.py — Experience Memory Domain (Phase D)

Manages persistent Experience Trees that store learned observations and
patterns extracted by the Dreaming Engine. Each entity has one Experience
Tree with three section roots: Observations, Patterns, Suggestions.

Architecture:
  Experience Tree (per entity, scope=entity, domain=experience)
    └── ROOT ("🧠 Experience")
         ├── GROUP ("🔍 Observations")
         │    └── OBSERVATION nodes
         ├── GROUP ("🔄 Patterns")
         │    └── PATTERN nodes
         └── GROUP ("💡 Suggestions")
              └── SUGGESTION nodes
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from cortex_memory.models import (
    CortexTree, CortexNode,
    CortexTreeStatus, CortexNodeType, CortexNodeStatus,
    MemoryDomain, ScopeLevel,
)

logger = logging.getLogger(__name__)

# Section titles (used for lookup)
OBSERVATIONS_TITLE = "🔍 Observations"
PATTERNS_TITLE = "🔄 Patterns"
SUGGESTIONS_TITLE = "💡 Suggestions"


class ExperienceTreeService:
    """
    Manages persistent, entity-scoped Experience Trees.

    Populated by the Dreaming Engine — not by direct agent writes.
    """

    def __init__(self, db: AsyncSession, company_id: UUID):
        self.db = db
        self.company_id = company_id

    # ===================================================================
    # Tree Lifecycle
    # ===================================================================

    async def get_or_create_experience_tree(
        self,
        entity_id: UUID,
    ) -> CortexTree:
        """Get or create the persistent Experience Tree for an entity."""
        result = await self.db.execute(
            select(CortexTree).where(
                CortexTree.entity_id == entity_id,
                CortexTree.company_id == self.company_id,
                CortexTree.memory_domain == MemoryDomain.EXPERIENCE,
                CortexTree.scope_level == ScopeLevel.ENTITY,
                CortexTree.status != CortexTreeStatus.ARCHIVED,
            )
        )
        tree = result.scalar_one_or_none()
        if tree:
            return tree

        return await self._create_experience_tree(entity_id)

    async def _create_experience_tree(self, entity_id: UUID) -> CortexTree:
        """Create Experience Tree with three section roots."""
        tree_id = uuid4()
        tree = CortexTree(
            id=tree_id,
            entity_id=entity_id,
            company_id=self.company_id,
            task_description=f"Experience memory for entity {entity_id}",
            status=CortexTreeStatus.ACTIVE,
            memory_domain=MemoryDomain.EXPERIENCE,
            scope_level=ScopeLevel.ENTITY,
            is_persistent=True,
            total_nodes=0,
            max_children=100,
            page_size_tokens=8000,
            context_budget_pct=40,
        )
        self.db.add(tree)
        await self.db.flush()

        # Root node
        root = CortexNode(
            id=uuid4(), tree_id=tree_id, parent_id=None,
            node_type=CortexNodeType.ROOT,
            title="🧠 Experience",
            summary="Learned patterns and observations from execution history.",
            content=None, status=CortexNodeStatus.ACTIVE,
            depth=0, sibling_order=0,
        )
        self.db.add(root)
        await self.db.flush()

        tree.root_node_id = root.id
        tree.total_nodes = 1

        # Three section roots
        for idx, (title, summary) in enumerate([
            (OBSERVATIONS_TITLE, "Raw observations extracted from individual episodes."),
            (PATTERNS_TITLE, "Recurring patterns identified across multiple observations."),
            (SUGGESTIONS_TITLE, "Actionable suggestions derived from patterns."),
        ]):
            section = CortexNode(
                id=uuid4(), tree_id=tree_id, parent_id=root.id,
                node_type=CortexNodeType.GROUP,
                title=title, summary=summary,
                content=None, status=CortexNodeStatus.ACTIVE,
                depth=1, sibling_order=idx,
            )
            self.db.add(section)
            tree.total_nodes += 1

        await self.db.flush()
        logger.info(f"Created Experience Tree {tree_id} for entity {entity_id}")
        return tree

    # ===================================================================
    # Section Root Accessors
    # ===================================================================

    async def get_observations_root(self, entity_id: UUID) -> UUID:
        """Get the Observations section root node ID."""
        return await self._get_section_root(entity_id, OBSERVATIONS_TITLE)

    async def get_patterns_root(self, entity_id: UUID) -> UUID:
        """Get the Patterns section root node ID."""
        return await self._get_section_root(entity_id, PATTERNS_TITLE)

    async def get_suggestions_root(self, entity_id: UUID) -> UUID:
        """Get the Suggestions section root node ID."""
        return await self._get_section_root(entity_id, SUGGESTIONS_TITLE)

    async def _get_section_root(self, entity_id: UUID, title: str) -> UUID:
        """Find a section root node by title within the Experience Tree."""
        tree = await self.get_or_create_experience_tree(entity_id)
        result = await self.db.execute(
            select(CortexNode.id).where(
                CortexNode.tree_id == tree.id,
                CortexNode.parent_id == tree.root_node_id,
                CortexNode.title == title,
            )
        )
        node_id = result.scalar_one_or_none()
        if not node_id:
            raise ValueError(f"Section root '{title}' not found in Experience Tree {tree.id}")
        return node_id

    # ===================================================================
    # Observation Queries
    # ===================================================================

    async def get_observations(
        self, entity_id: UUID, limit: int = 50,
    ) -> List[CortexNode]:
        """Get all observation nodes for an entity."""
        tree = await self.get_or_create_experience_tree(entity_id)
        obs_root = await self.get_observations_root(entity_id)

        result = await self.db.execute(
            select(CortexNode).where(
                CortexNode.tree_id == tree.id,
                CortexNode.parent_id == obs_root,
                CortexNode.node_type == CortexNodeType.OBSERVATION,
            ).order_by(CortexNode.created_at.desc()).limit(limit)
        )
        return list(result.scalars().all())

    # ===================================================================
    # Pattern Queries
    # ===================================================================

    async def get_strong_patterns(
        self,
        entity_id: UUID,
        min_strength: float = 0.7,
        min_recurrence: int = 2,
    ) -> List[CortexNode]:
        """Get patterns that meet strength and recurrence thresholds."""
        tree = await self.get_or_create_experience_tree(entity_id)
        patterns_root = await self.get_patterns_root(entity_id)

        result = await self.db.execute(
            select(CortexNode).where(
                CortexNode.tree_id == tree.id,
                CortexNode.parent_id == patterns_root,
                CortexNode.node_type == CortexNodeType.PATTERN,
            ).order_by(CortexNode.created_at.desc())
        )
        all_patterns = result.scalars().all()

        # Filter by metadata thresholds
        strong = []
        for p in all_patterns:
            meta = p.metadata_extra or {}
            strength = meta.get("pattern_strength", 0)
            recurrence = meta.get("recurrence_count", 0)
            if strength >= min_strength and recurrence >= min_recurrence:
                strong.append(p)

        return strong

    async def get_all_patterns(self, entity_id: UUID) -> List[CortexNode]:
        """Get all pattern nodes for an entity."""
        tree = await self.get_or_create_experience_tree(entity_id)
        patterns_root = await self.get_patterns_root(entity_id)

        result = await self.db.execute(
            select(CortexNode).where(
                CortexNode.tree_id == tree.id,
                CortexNode.parent_id == patterns_root,
                CortexNode.node_type == CortexNodeType.PATTERN,
            ).order_by(CortexNode.created_at.desc())
        )
        return list(result.scalars().all())
