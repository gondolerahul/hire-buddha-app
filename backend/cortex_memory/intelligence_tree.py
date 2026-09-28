"""
intelligence_tree_service.py — Intelligence Memory Domain (Phase D)

Manages persistent Intelligence Trees that store distilled rules, strategies,
and preferences. These are the highest-order memory — actionable directives
that guide agent behavior, populated by the Dreaming Engine's distillation phase.

Architecture:
  Intelligence Tree (per entity, scope=entity, domain=intelligence)
    └── ROOT ("🎯 Intelligence")
         ├── GROUP ("📏 Instructions")
         │    └── INSTRUCTION nodes
         ├── GROUP ("🎯 Strategies")
         │    └── STRATEGY nodes
         └── GROUP ("❤️ Preferences")
              └── PREFERENCE nodes
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession

from cortex_memory.models import (
    CortexTree, CortexNode,
    CortexTreeStatus, CortexNodeType, CortexNodeStatus,
    MemoryDomain, ScopeLevel,
)

logger = logging.getLogger(__name__)

# Section titles
INSTRUCTIONS_TITLE = "📏 Instructions"
STRATEGIES_TITLE = "🎯 Strategies"
PREFERENCES_TITLE = "❤️ Preferences"

# Map rule types to section titles
RULE_TYPE_TO_SECTION = {
    "instruction": INSTRUCTIONS_TITLE,
    "strategy": STRATEGIES_TITLE,
    "preference": PREFERENCES_TITLE,
}


class IntelligenceTreeService:
    """
    Manages persistent, entity-scoped Intelligence Trees.

    Provides semantic search for applicable rules during execution,
    enabling agents to benefit from learned intelligence.
    """

    def __init__(self, db: AsyncSession, company_id: UUID, *, embedding: Any = None):
        self.db = db
        self.company_id = company_id
        self._embedding = embedding  # cortex_memory.EmbeddingProvider | None

    # ===================================================================
    # Tree Lifecycle
    # ===================================================================

    async def get_or_create_intelligence_tree(
        self,
        entity_id: UUID,
    ) -> CortexTree:
        """Get or create the persistent Intelligence Tree for an entity."""
        result = await self.db.execute(
            select(CortexTree).where(
                CortexTree.entity_id == entity_id,
                CortexTree.company_id == self.company_id,
                CortexTree.memory_domain == MemoryDomain.INTELLIGENCE,
                CortexTree.scope_level == ScopeLevel.ENTITY,
                CortexTree.status != CortexTreeStatus.ARCHIVED,
            )
        )
        tree = result.scalar_one_or_none()
        if tree:
            return tree

        return await self._create_intelligence_tree(entity_id)

    async def _create_intelligence_tree(self, entity_id: UUID) -> CortexTree:
        """Create Intelligence Tree with three section roots."""
        tree_id = uuid4()
        tree = CortexTree(
            id=tree_id,
            entity_id=entity_id,
            company_id=self.company_id,
            task_description=f"Intelligence memory for entity {entity_id}",
            status=CortexTreeStatus.ACTIVE,
            memory_domain=MemoryDomain.INTELLIGENCE,
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
            title="🎯 Intelligence",
            summary="Distilled rules, strategies, and preferences guiding agent behavior.",
            content=None, status=CortexNodeStatus.ACTIVE,
            depth=0, sibling_order=0,
        )
        self.db.add(root)
        await self.db.flush()

        tree.root_node_id = root.id
        tree.total_nodes = 1

        # Three section roots
        for idx, (title, summary) in enumerate([
            (INSTRUCTIONS_TITLE, "Specific, concrete rules to follow or avoid."),
            (STRATEGIES_TITLE, "High-level workflow templates and approaches."),
            (PREFERENCES_TITLE, "Learned user and context preferences."),
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
        logger.info(f"Created Intelligence Tree {tree_id} for entity {entity_id}")
        return tree

    # ===================================================================
    # Section Root Accessors
    # ===================================================================

    async def get_section_root(
        self, entity_id: UUID, rule_type: str,
    ) -> UUID:
        """Get the section root node ID for a given rule type."""
        title = RULE_TYPE_TO_SECTION.get(rule_type, INSTRUCTIONS_TITLE)
        tree = await self.get_or_create_intelligence_tree(entity_id)
        result = await self.db.execute(
            select(CortexNode.id).where(
                CortexNode.tree_id == tree.id,
                CortexNode.parent_id == tree.root_node_id,
                CortexNode.title == title,
            )
        )
        node_id = result.scalar_one_or_none()
        if not node_id:
            raise ValueError(f"Section root '{title}' not found in Intelligence Tree {tree.id}")
        return node_id

    # ===================================================================
    # Rule Queries
    # ===================================================================

    async def get_all_rules(self, entity_id: UUID) -> List[CortexNode]:
        """Get all rule nodes (instructions, strategies, preferences)."""
        tree = await self.get_or_create_intelligence_tree(entity_id)
        result = await self.db.execute(
            select(CortexNode).where(
                CortexNode.tree_id == tree.id,
                CortexNode.node_type.in_([
                    CortexNodeType.INSTRUCTION,
                    CortexNodeType.STRATEGY,
                    CortexNodeType.PREFERENCE,
                ]),
            ).order_by(CortexNode.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_applicable_rules(
        self,
        entity_id: UUID,
        task_description: str,
        max_rules: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        Semantic search for rules applicable to the current task.
        Returns sorted by: confidence × relevance_score.
        """
        tree = await self.get_or_create_intelligence_tree(entity_id)

        from cortex_memory.embedding import embed_query
        query_vector = await embed_query(self._embedding, task_description)

        if not query_vector:
            return []

        result = await self.db.execute(text("""
            SELECT cn.id, cn.title, cn.summary, cn.node_type, cn.metadata_extra,
                   1 - (cn.embedding <=> CAST(:vec AS vector)) AS relevance
            FROM cortex_nodes cn
            WHERE cn.tree_id = :tree_id
              AND cn.node_type IN ('instruction', 'strategy', 'preference')
              AND cn.embedding IS NOT NULL
            ORDER BY
                COALESCE((cn.metadata_extra->>'confidence')::numeric, 0.5) *
                (1 - (cn.embedding <=> CAST(:vec AS vector))) DESC
            LIMIT :max_rules
        """), {
            "tree_id": str(tree.id),
            "vec": json.dumps(list(query_vector)),
            "max_rules": max_rules,
        })

        rows = result.fetchall()

        # Update access tracking
        if rows:
            node_ids = [r[0] for r in rows]
            placeholders = ", ".join(f":id_{i}" for i in range(len(node_ids)))
            params = {f"id_{i}": str(nid) for i, nid in enumerate(node_ids)}
            await self.db.execute(text(
                f"UPDATE cortex_nodes SET access_count = access_count + 1, "
                f"last_accessed_at = NOW() "
                f"WHERE id IN ({placeholders})"
            ), params)

        return [
            {
                "rule_id": str(r[0]),
                "title": r[1],
                "rule": r[2],
                "type": r[3],
                "confidence": (r[4] or {}).get("confidence", 0.5),
                "relevance": float(r[5]),
            }
            for r in rows
        ]

    # ===================================================================
    # Prompt Injection
    # ===================================================================

    async def get_rules_for_prompt(
        self,
        entity_id: UUID,
        task_description: str,
        max_rules: int = 5,
    ) -> str:
        """
        Get applicable rules formatted for prompt injection.
        Returns empty string if no rules or no Intelligence Tree.
        """
        try:
            rules = await self.get_applicable_rules(
                entity_id, task_description, max_rules=max_rules,
            )
            if not rules:
                return ""

            lines = ["## Learned Intelligence (apply these rules)"]
            for i, rule in enumerate(rules, 1):
                emoji = {"instruction": "📏", "strategy": "🎯", "preference": "❤️"}.get(
                    rule["type"], "💡"
                )
                lines.append(
                    f"  [{i}] {emoji} {rule['title']} (confidence: {rule['confidence']:.0%})\n"
                    f"      {rule['rule']}"
                )
            return "\n".join(lines)
        except Exception as e:
            logger.debug(f"Intelligence rules injection failed: {e}")
            return ""
