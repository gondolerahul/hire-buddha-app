"""
episodic_tree_service.py — Structured Episodic Memory (Phase C)

Replaces the flat `episodic_memories` table with hierarchical Episodic Trees
organized as MONTH → DAY → EPISODE. Each entity gets one persistent
Episodic Tree that grows indefinitely (no 10-episode limit).

Architecture:
  Episodic Tree (per entity, scope=entity, domain=episodic)
    └── ROOT ("📚 Execution History")
         └── EPISODE_GROUP ("📅 May 2026")
              └── EPISODE_GROUP ("📅 Friday, May 16, 2026")
                   ├── EPISODE ("🎬 Q3 Revenue Analysis")
                   └── EPISODE ("🎬 Competitor Analysis")

Usage:
    svc = EpisodicTreeService(db, company_id)
    tree = await svc.get_or_create_episodic_tree(entity_id)
    episode_id = await svc.write_episode(entity_id, run, runtime_tree_id)
    episodes = await svc.query_by_time(entity_id, start, end)
    episodes = await svc.query_by_topic(entity_id, "revenue analysis")
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, cast
from uuid import UUID, uuid4

from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession

from cortex_memory.models import (
    CortexTree, CortexNode,
    CortexTreeStatus, CortexNodeType, CortexNodeStatus,
    MemoryDomain, ScopeLevel,
)

logger = logging.getLogger(__name__)


class EpisodicTreeService:
    """
    Manages persistent, entity-scoped Episodic Trees.

    Key differences from v1 episodic_memories:
    - Unlimited episodes (no 10-row cap)
    - Hierarchical: MONTH → DAY → EPISODE
    - Temporal queries via date-range SQL
    - Semantic queries via embedding vector search
    - Deep-dive links to runtime CORTEX trees
    """

    def __init__(self, db: AsyncSession, company_id: UUID, *, embedding: Any = None):
        self.db = db
        self.company_id = company_id
        self._embedding = embedding  # cortex_memory.EmbeddingProvider | None

    # ===================================================================
    # Tree Lifecycle
    # ===================================================================

    async def get_or_create_episodic_tree(
        self,
        entity_id: UUID,
    ) -> CortexTree:
        """
        Get the persistent Episodic Tree for an entity, creating one if needed.
        Each entity has exactly one Episodic Tree.
        """
        result = await self.db.execute(
            select(CortexTree).where(
                CortexTree.entity_id == entity_id,
                CortexTree.company_id == self.company_id,
                CortexTree.memory_domain == MemoryDomain.EPISODIC,
                CortexTree.scope_level == ScopeLevel.ENTITY,
                CortexTree.status != CortexTreeStatus.ARCHIVED,
            )
        )
        tree = result.scalar_one_or_none()
        if tree:
            return tree

        tree_id = uuid4()
        tree = CortexTree(
            id=tree_id,
            entity_id=entity_id,
            company_id=self.company_id,
            task_description=f"Episodic memory for entity {entity_id}",
            status=CortexTreeStatus.ACTIVE,
            memory_domain=MemoryDomain.EPISODIC,
            scope_level=ScopeLevel.ENTITY,
            is_persistent=True,
            total_nodes=0,
            max_children=100,  # Months can accumulate
            page_size_tokens=8000,
            context_budget_pct=40,
        )
        self.db.add(tree)
        await self.db.flush()

        root = CortexNode(
            id=uuid4(),
            tree_id=tree_id,
            parent_id=None,
            node_type=CortexNodeType.ROOT,
            title="📚 Execution History",
            summary="Chronological record of all executions for this entity.",
            content=None,
            status=CortexNodeStatus.ACTIVE,
            depth=0,
            sibling_order=0,
        )
        self.db.add(root)
        await self.db.flush()

        tree.root_node_id = root.id
        tree.total_nodes = 1
        await self.db.flush()

        logger.info(f"Created Episodic Tree {tree_id} for entity {entity_id}")
        return tree

    # ===================================================================
    # Episode Writing
    # ===================================================================

    async def write_episode(
        self,
        entity_id: UUID,
        run: Any,
        runtime_tree_id: Optional[UUID] = None,
    ) -> UUID:
        """
        Write a completed execution as an EPISODE node.
        Automatically creates MONTH and DAY group nodes as needed.
        """
        tree = await self.get_or_create_episodic_tree(entity_id)
        now = run.created_at or datetime.utcnow()

        month_key = now.strftime("%Y-%m")
        day_key = now.strftime("%Y-%m-%d")

        # Get or create month group
        month_node_id = await self._get_or_create_group(
            tree_id=tree.id,
            parent_id=cast(UUID, tree.root_node_id),
            group_key=month_key,
            title=f"📅 {now.strftime('%B %Y')}",
            depth=1,
        )

        # Get or create day group
        day_node_id = await self._get_or_create_group(
            tree_id=tree.id,
            parent_id=month_node_id,
            group_key=day_key,
            title=f"📅 {now.strftime('%A, %B %d, %Y')}",
            depth=2,
        )

        # C: Use shared utility instead of private cross-module import
        from cortex_memory._textutil import truncate_for_storage
        input_summary = truncate_for_storage(run.input_data, max_chars=1000)
        output_summary = truncate_for_storage(run.result_data, max_chars=1000)
        tools_used = self._extract_tools_used(run.context_state)
        episode_title = self._generate_episode_title(run, input_summary)

        # Determine next sibling order
        sibling_order = await self._next_sibling_order(day_node_id)

        # Create episode node
        episode_node = CortexNode(
            id=uuid4(),
            tree_id=tree.id,
            parent_id=day_node_id,
            node_type=CortexNodeType.EPISODE,
            title=f"🎬 {episode_title}",
            summary=f"[{run.status}] {input_summary[:200]} → {output_summary[:200]}",
            content=json.dumps({
                "input": input_summary,
                "output": output_summary,
                "status": str(run.status),
            }),
            content_tokens=len(input_summary + output_summary) // 4,
            status=CortexNodeStatus.COMPLETE,
            depth=3,
            sibling_order=sibling_order,
            execution_run_id=run.id,
            source_ref={
                "ref_type": "execution_run",
                "run_id": str(run.id),
                "runtime_tree_id": str(runtime_tree_id) if runtime_tree_id else None,
            },
            metadata_extra={
                "run_id": str(run.id),
                "runtime_tree_id": str(runtime_tree_id) if runtime_tree_id else None,
                "status": str(run.status),
                "cost_usd": float(run.total_cost_usd or 0),
                "total_tokens": run.total_tokens or 0,
                "execution_time_ms": run.execution_time_ms,
                "tools_used": tools_used,
                "channel": (run.context_state or {}).get("channel", "text"),
            },
        )
        self.db.add(episode_node)

        # Update tree node count
        tree.total_nodes = (tree.total_nodes or 0) + 1
        tree.last_active_at = datetime.utcnow()
        await self.db.flush()

        # Generate embedding for the episode (async, non-blocking)
        try:
            from cortex_memory.embedding import embed_node
            await embed_node(self._embedding, episode_node)
            await self.db.flush()
        except Exception as e:
            logger.debug(f"Episode embedding failed (non-fatal): {e}")

        logger.info(f"Episodic Tree: episode {episode_node.id} written for run {run.id}")
        return episode_node.id

    # ===================================================================
    # Temporal Query
    # ===================================================================

    async def query_by_time(
        self,
        entity_id: UUID,
        start_date: datetime,
        end_date: datetime,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """
        Query episodes by date range. Returns newest first.
        Direct SQL query — no tree traversal needed.
        """
        tree = await self._find_episodic_tree(entity_id)
        if not tree:
            return []

        result = await self.db.execute(
            select(CortexNode).where(
                CortexNode.tree_id == tree.id,
                CortexNode.node_type == CortexNodeType.EPISODE,
                CortexNode.created_at >= start_date,
                CortexNode.created_at <= end_date,
            ).order_by(CortexNode.created_at.desc()).limit(limit)
        )
        nodes = result.scalars().all()
        return [self._episode_node_to_dict(n) for n in nodes]

    # ===================================================================
    # Semantic Query
    # ===================================================================

    async def query_by_topic(
        self,
        entity_id: UUID,
        query: str,
        top_k: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        Semantic search across episode nodes — find past runs related to a topic.
        """
        tree = await self._find_episodic_tree(entity_id)
        if not tree:
            return []

        from cortex_memory.embedding import embed_query
        query_vector = await embed_query(self._embedding, query)
        if not query_vector:
            return []

        stmt = text("""
            SELECT cn.id, cn.title, cn.summary, cn.content,
                   cn.metadata_extra, cn.source_ref, cn.created_at,
                   1 - (cn.embedding <=> CAST(:vec AS vector)) AS score
            FROM cortex_nodes cn
            WHERE cn.tree_id = :tree_id
              AND cn.node_type = 'episode'
              AND cn.embedding IS NOT NULL
            ORDER BY cn.embedding <=> CAST(:vec AS vector)
            LIMIT :top_k
        """)

        result = await self.db.execute(stmt, {
            "vec": json.dumps(list(query_vector)),
            "tree_id": str(tree.id),
            "top_k": top_k,
        })
        rows = result.fetchall()

        return [
            {
                "node_id": str(r[0]),
                "title": r[1],
                "summary": r[2],
                "content": r[3],
                "metadata": r[4],
                "source_ref": r[5],
                "created_at": r[6].isoformat() if r[6] else None,
                "score": float(r[7]),
            }
            for r in rows
        ]

    # ===================================================================
    # Recent Episodes (for prompt injection)
    # ===================================================================

    async def get_recent_episodes(
        self,
        entity_id: UUID,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        Get the most recent episodes for prompt injection.
        Replaces the flat `_load_episodic()` with tree-based retrieval.
        """
        tree = await self._find_episodic_tree(entity_id)
        if not tree:
            return []

        result = await self.db.execute(
            select(CortexNode).where(
                CortexNode.tree_id == tree.id,
                CortexNode.node_type == CortexNodeType.EPISODE,
            ).order_by(CortexNode.created_at.desc()).limit(limit)
        )
        nodes = result.scalars().all()

        # Return in chronological order (oldest first) for reading
        return [
            {
                "input": self._extract_field(n, "input"),
                "output": self._extract_field(n, "output"),
                "status": (n.metadata_extra or {}).get("status", ""),
                "at": n.created_at.isoformat() if n.created_at else "",
            }
            for n in reversed(nodes)
        ]

    # ===================================================================
    # Internal Helpers
    # ===================================================================

    async def _get_or_create_group(
        self,
        tree_id: UUID,
        parent_id: UUID,
        group_key: str,
        title: str,
        depth: int,
    ) -> UUID:
        """Get or create a date-based group node (Month or Day)."""
        result = await self.db.execute(
            select(CortexNode).where(
                CortexNode.tree_id == tree_id,
                CortexNode.parent_id == parent_id,
                CortexNode.node_type == CortexNodeType.EPISODE_GROUP,
                CortexNode.title == title,
            )
        )
        existing = result.scalar_one_or_none()
        if existing:
            return existing.id

        sibling_order = await self._next_sibling_order(parent_id)
        node = CortexNode(
            id=uuid4(),
            tree_id=tree_id,
            parent_id=parent_id,
            node_type=CortexNodeType.EPISODE_GROUP,
            title=title,
            summary=f"Execution episodes for {group_key}",
            content=None,
            status=CortexNodeStatus.ACTIVE,
            depth=depth,
            sibling_order=sibling_order,
            metadata_extra={"group_key": group_key},
        )
        self.db.add(node)
        await self.db.flush()

        # Update tree count
        tree_result = await self.db.execute(
            select(CortexTree).where(CortexTree.id == tree_id)
        )
        tree = tree_result.scalar_one_or_none()
        if tree:
            tree.total_nodes = (tree.total_nodes or 0) + 1

        return node.id

    async def _find_episodic_tree(self, entity_id: UUID) -> Optional[CortexTree]:
        """Find an entity's episodic tree (returns None if not created yet)."""
        result = await self.db.execute(
            select(CortexTree).where(
                CortexTree.entity_id == entity_id,
                CortexTree.company_id == self.company_id,
                CortexTree.memory_domain == MemoryDomain.EPISODIC,
                CortexTree.scope_level == ScopeLevel.ENTITY,
                CortexTree.status != CortexTreeStatus.ARCHIVED,
            )
        )
        return result.scalar_one_or_none()

    async def _next_sibling_order(self, parent_id: UUID) -> int:
        """Get next sibling order for children of a node."""
        result = await self.db.execute(
            select(func.coalesce(func.max(CortexNode.sibling_order), -1))
            .where(CortexNode.parent_id == parent_id)
        )
        return int(result.scalar() or -1) + 1

    def _extract_tools_used(self, context_state: Optional[dict[str, Any]]) -> List[str]:
        """Extract unique tool names from context_state."""
        if not context_state:
            return []
        tools = set()
        for key, val in context_state.items():
            if isinstance(val, dict):
                for tr in val.get("tool_results", []):
                    if isinstance(tr, dict) and "tool" in tr:
                        tools.add(tr["tool"])
        return sorted(tools)

    def _generate_episode_title(self, run: Any, input_summary: str) -> str:
        """Generate a concise episode title from run data."""
        # Try entity name first
        entity_name = ""
        if hasattr(run, "entity") and run.entity:
            entity_name = getattr(run.entity, "name", "")

        if entity_name and input_summary:
            return f"{entity_name}: {input_summary[:60]}"
        elif input_summary:
            return input_summary[:80]
        elif entity_name:
            return entity_name
        return f"Execution {str(run.id)[:8]}"

    def _episode_node_to_dict(self, node: CortexNode) -> Dict[str, Any]:
        """Convert an episode node to a dict."""
        return {
            "node_id": str(node.id),
            "title": node.title,
            "summary": node.summary,
            "content": node.content,
            "metadata": node.metadata_extra,
            "source_ref": node.source_ref,
            "created_at": node.created_at.isoformat() if node.created_at else None,
        }

    def _extract_field(self, node: CortexNode, field: str) -> str:
        """Extract a field from episode node content JSON."""
        try:
            if node.content:
                data = json.loads(node.content)
                return str(data.get(field, ""))
        except (json.JSONDecodeError, TypeError):
            pass
        return ""
