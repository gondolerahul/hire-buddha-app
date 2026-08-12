"""
graph_service.py — Semantic Graph Layer (Phase E)

Manages the cortex_edges associative graph overlaying all CORTEX Trees.
Enables cross-domain search, graph-expanded retrieval, automatic edge
creation during embedding, and co-access tracking during execution.

Key capabilities:
  - create_edge / upsert edges with weight boosting
  - expand_from_node — BFS graph traversal with cycle detection
  - semantic_graph_search — Hybrid semantic + graph expansion search
  - create_similarity_edges — Automatic edges after embedding
  - track_co_access — Runtime co-access edge creation
  - decay_weights / prune_weak_edges — Graph maintenance
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from sqlalchemy import select, text, func
from sqlalchemy.ext.asyncio import AsyncSession

from cortex_memory.models import CortexNode, CortexEdge

logger = logging.getLogger(__name__)


class SemanticGraphService:
    """Manages the cortex_edges graph layer overlaying CORTEX Trees."""

    # Weight decay/boost parameters
    DECAY_RATE = 0.95
    BOOST_ON_TRAVERSAL = 0.05
    MIN_WEIGHT = 0.01
    MAX_WEIGHT = 1.0

    # Automatic edge creation thresholds
    SIMILARITY_THRESHOLD = 0.85
    MAX_AUTO_EDGES_PER_NODE = 5

    def __init__(self, db: AsyncSession, company_id: UUID, *, embedding: Any = None):
        self.db = db
        self.company_id = company_id
        # Injected cortex_memory.EmbeddingProvider; semantic seeding degrades to
        # graph-only when absent (standalone use).
        self._embedding = embedding

    # ===================================================================
    # Edge CRUD
    # ===================================================================

    async def create_edge(
        self,
        source_node_id: UUID,
        target_node_id: UUID,
        edge_type: str,
        weight: float = 0.5,
        created_by: str = "system",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> CortexEdge:
        """Create or update (upsert) an edge between two nodes."""
        result = await self.db.execute(
            select(CortexEdge).where(
                CortexEdge.source_node_id == source_node_id,
                CortexEdge.target_node_id == target_node_id,
                CortexEdge.edge_type == edge_type,
            )
        )
        edge = result.scalar_one_or_none()

        if edge:
            edge.weight = min(
                Decimal(str(self.MAX_WEIGHT)),
                edge.weight + Decimal(str(self.BOOST_ON_TRAVERSAL)),
            )
            edge.traversal_count = (edge.traversal_count or 0) + 1
            edge.last_traversed_at = datetime.utcnow()
            return edge

        edge = CortexEdge(
            id=uuid4(),
            source_node_id=source_node_id,
            target_node_id=target_node_id,
            edge_type=edge_type,
            weight=weight,
            created_by=created_by,
            metadata=metadata,
        )
        self.db.add(edge)
        return edge

    # ===================================================================
    # Graph Traversal
    # ===================================================================

    async def expand_from_node(
        self,
        node_id: UUID,
        max_depth: int = 2,
        edge_types: Optional[List[str]] = None,
        min_weight: float = 0.1,
        max_nodes: int = 20,
    ) -> List[Dict[str, Any]]:
        """
        BFS expansion from a starting node through edges.
        Returns connected nodes with edge metadata.
        """
        edge_type_filter = ""
        if edge_types:
            types_str = ", ".join(f"'{t}'" for t in edge_types)
            edge_type_filter = f"AND e.edge_type IN ({types_str})"

        stmt = text(f"""
            WITH RECURSIVE graph_walk AS (
                SELECT
                    e.target_node_id AS node_id,
                    e.edge_type,
                    -- Cast so the non-recursive term's type (numeric(5,4))
                    -- matches the recursive term (numeric after multiplication);
                    -- Postgres requires both branches to share a column type.
                    e.weight::numeric AS weight,
                    1 AS depth,
                    ARRAY[e.source_node_id, e.target_node_id] AS path
                FROM cortex_edges e
                WHERE e.source_node_id = :start_node
                  AND e.weight >= :min_weight
                  {edge_type_filter}

                UNION ALL

                SELECT
                    e.target_node_id,
                    e.edge_type,
                    e.weight * gw.weight AS weight,
                    gw.depth + 1,
                    gw.path || e.target_node_id
                FROM cortex_edges e
                JOIN graph_walk gw ON e.source_node_id = gw.node_id
                WHERE gw.depth < :max_depth
                  AND e.weight >= :min_weight
                  AND NOT (e.target_node_id = ANY(gw.path))
                  {edge_type_filter}
            )
            SELECT DISTINCT ON (gw.node_id)
                gw.node_id, gw.edge_type, gw.weight, gw.depth,
                cn.title, cn.summary, cn.node_type, cn.tree_id
            FROM graph_walk gw
            JOIN cortex_nodes cn ON cn.id = gw.node_id
            ORDER BY gw.node_id, gw.weight DESC
            LIMIT :max_nodes
        """)

        result = await self.db.execute(stmt, {
            "start_node": str(node_id),
            "min_weight": min_weight,
            "max_depth": max_depth,
            "max_nodes": max_nodes,
        })

        return [
            {
                "node_id": str(row[0]),
                "edge_type": row[1],
                "weight": float(row[2]),
                "depth": row[3],
                "title": row[4],
                "summary": row[5],
                "node_type": row[6],
                "tree_id": str(row[7]),
            }
            for row in result.fetchall()
        ]

    # ===================================================================
    # Hybrid Search (Semantic + Graph)
    # ===================================================================

    async def semantic_graph_search(
        self,
        query: str,
        entity_id: UUID,
        domains: Optional[List[str]] = None,
        top_k: int = 5,
        graph_expansion_depth: int = 1,
    ) -> List[Dict[str, Any]]:
        """
        Hybrid search: embedding similarity seeds + graph expansion.
        Primary search interface for the v2 memory system.
        """
        if self._embedding is None:
            return []  # no embedding provider injected — no semantic seed
        _res = await self._embedding.embed([query])
        query_vector = _res.vectors[0] if _res.vectors and _res.vectors[0] else None

        if not query_vector:
            return []

        # Step 1: Semantic seed
        domain_filter = ""
        if domains:
            domains_str = ", ".join(f"'{d}'" for d in domains)
            domain_filter = f"AND ct.memory_domain IN ({domains_str})"

        seed_result = await self.db.execute(text(f"""
            SELECT cn.id, cn.title, cn.summary, cn.node_type, cn.tree_id,
                   ct.memory_domain,
                   1 - (cn.embedding <=> CAST(:vec AS vector)) AS similarity
            FROM cortex_nodes cn
            JOIN cortex_trees ct ON ct.id = cn.tree_id
            WHERE cn.embedding IS NOT NULL
              AND ct.company_id = :company_id
              AND (ct.entity_id = :entity_id OR ct.scope_level IN ('app', 'tenant'))
              {domain_filter}
            ORDER BY cn.embedding <=> CAST(:vec AS vector)
            LIMIT :top_k
        """), {
            "vec": json.dumps(list(query_vector)),
            "company_id": str(self.company_id),
            "entity_id": str(entity_id),
            "top_k": top_k,
        })

        seed_nodes = seed_result.fetchall()
        if not seed_nodes:
            return []

        # Step 2: Graph expansion
        all_results: List[Dict[str, Any]] = []
        seen_ids: set[Any] = set()

        for seed in seed_nodes:
            seed_id = str(seed[0])
            if seed_id not in seen_ids:
                all_results.append({
                    "node_id": seed_id,
                    "title": seed[1],
                    "summary": seed[2],
                    "node_type": seed[3],
                    "tree_id": str(seed[4]),
                    "memory_domain": seed[5],
                    "similarity": float(seed[6]),
                    "graph_weight": 1.0,
                    "combined_score": float(seed[6]),
                    "source": "semantic",
                })
                seen_ids.add(seed_id)

            if graph_expansion_depth > 0:
                try:
                    expanded = await self.expand_from_node(
                        UUID(seed_id),
                        max_depth=graph_expansion_depth,
                        max_nodes=5,
                    )
                    for exp_node in expanded:
                        if exp_node["node_id"] not in seen_ids:
                            combined = float(seed[6]) * 0.7 + exp_node["weight"] * 0.3
                            all_results.append({
                                **exp_node,
                                "memory_domain": None,
                                "similarity": 0.0,
                                "combined_score": combined,
                                "source": "graph_expansion",
                                "expanded_from": seed_id,
                            })
                            seen_ids.add(exp_node["node_id"])
                except Exception as e:
                    logger.debug(f"Graph expansion failed for node {seed_id}: {e}")

        # Step 3: Re-rank
        all_results.sort(key=lambda x: x["combined_score"], reverse=True)
        return all_results[:top_k * 2]

    # ===================================================================
    # Automatic Edge Creation
    # ===================================================================

    async def create_similarity_edges(
        self,
        node_id: UUID,
    ) -> int:
        """
        After embedding a node, find similar nodes and create
        'semantic_similar' edges automatically.
        """
        result = await self.db.execute(
            select(CortexNode).where(CortexNode.id == node_id)
        )
        node = result.scalar_one_or_none()
        if not node or node.embedding is None:
            return 0

        similar = await self.db.execute(text("""
            SELECT cn.id,
                   1 - (cn.embedding <=> CAST(:vec AS vector)) AS similarity
            FROM cortex_nodes cn
            JOIN cortex_trees ct ON ct.id = cn.tree_id
            WHERE cn.id != :node_id
              AND cn.embedding IS NOT NULL
              AND ct.company_id = :company_id
              AND (1 - (cn.embedding <=> CAST(:vec AS vector))) >= :threshold
            ORDER BY cn.embedding <=> CAST(:vec AS vector)
            LIMIT :max_edges
        """), {
            "node_id": str(node_id),
            "vec": json.dumps([float(v) for v in node.embedding]),
            "company_id": str(self.company_id),
            "threshold": self.SIMILARITY_THRESHOLD,
            "max_edges": self.MAX_AUTO_EDGES_PER_NODE,
        })

        count = 0
        for row in similar.fetchall():
            await self.create_edge(
                source_node_id=node_id,
                target_node_id=row[0],
                edge_type="semantic_similar",
                weight=float(row[1]),
                created_by="embedding_pipeline",
            )
            count += 1

        return count

    # ===================================================================
    # Co-Access Tracking
    # ===================================================================

    async def track_co_access(
        self,
        node_ids: List[UUID],
        execution_run_id: Optional[UUID] = None,
    ) -> int:
        """
        When multiple nodes are accessed in the same execution step,
        create/strengthen 'co_accessed' edges between them.
        """
        count = 0
        for i, source_id in enumerate(node_ids):
            for target_id in node_ids[i + 1:]:
                await self.create_edge(
                    source_node_id=source_id,
                    target_node_id=target_id,
                    edge_type="co_accessed",
                    weight=0.3,
                    created_by="runtime_tracking",
                    metadata={"run_id": str(execution_run_id)} if execution_run_id else None,
                )
                count += 1
        return count

    # ===================================================================
    # Graph Maintenance
    # ===================================================================

    async def decay_weights(self, days_inactive: int = 30) -> int:
        """Decay edge weights not traversed recently."""
        result = await self.db.execute(text("""
            UPDATE cortex_edges
            SET weight = GREATEST(:min_weight, weight * :decay_rate)
            WHERE (last_traversed_at < NOW() - MAKE_INTERVAL(days => :days)
               OR last_traversed_at IS NULL)
              AND weight > :min_weight
            RETURNING id
        """), {
            "min_weight": self.MIN_WEIGHT,
            "decay_rate": self.DECAY_RATE,
            "days": days_inactive,
        })
        rows = result.fetchall()
        return len(rows)

    async def prune_weak_edges(self) -> int:
        """Remove edges below minimum weight threshold."""
        result = await self.db.execute(text("""
            DELETE FROM cortex_edges
            WHERE weight < :min_weight
            RETURNING id
        """), {"min_weight": self.MIN_WEIGHT})
        rows = result.fetchall()
        return len(rows)

    async def get_graph_stats(self) -> Dict[str, Any]:
        """Get graph statistics for monitoring."""
        result = await self.db.execute(text("""
            SELECT
                edge_type,
                COUNT(*) as count,
                AVG(weight) as avg_weight,
                MIN(weight) as min_weight,
                MAX(weight) as max_weight
            FROM cortex_edges
            GROUP BY edge_type
        """))
        rows = result.fetchall()
        return {
            row[0]: {
                "count": row[1],
                "avg_weight": float(row[2]),
                "min_weight": float(row[3]),
                "max_weight": float(row[4]),
            }
            for row in rows
        }
