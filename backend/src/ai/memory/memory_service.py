"""
memory_service.py — S1: Three-tier MemoryRouter

Memory tiers:
  WORKING   — Current ExecutionRun context_state (in-process, no persistence cost)
  EPISODIC  — Short-term interaction records persisted in EpisodicMemory table
              (last N interactions per entity, queryable by entity/user/channel)
  SEMANTIC  — Long-term vectorised knowledge in DocumentChunk table
              (retrieved via cosine similarity using pgvector)

Retrieval (``retrieve`` / ``format_for_prompt`` / ``_load_episodic``) was
removed in C2 — the AgentLoop reads context from CORTEX via the Perceiver and
the v2 ``MemoryAssemblyService``. What remains here is the episodic *writer*
(``write_episodic``) and the reusable semantic-search primitive
(``search_semantic``).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, JSON
from sqlalchemy import select, desc
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.ext.asyncio import AsyncSession
# ---------------------------------------------------------------------------
# ORM Model imported from models.py
# ---------------------------------------------------------------------------
from src.ai.models import EpisodicMemory
from src.ai.constants import EMBEDDING_MODEL

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# MemoryRouter
# ---------------------------------------------------------------------------

class MemoryRouter:
    """
    Episodic writer + semantic-search primitive.

    write_episodic() — Persists a completed run's summary to EpisodicMemory.
    search_semantic() — Vector/graph similarity search across memory domains.

    (The legacy ``retrieve`` reader was removed in C2; the loop reads context
    from CORTEX + the v2 MemoryAssemblyService.)
    """

    MAX_EPISODES = 10    # Keep last N episodic memories per entity/user pair
    MAX_SEMANTIC = 5     # Max semantic chunks to inject
    EPISODIC_CHARS = 300 # Max chars per episode in the injected context block

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def _get_company_id(self, entity_id: UUID) -> Optional[UUID]:
        """Lookup company_id for an entity."""
        try:
            from src.ai.models import HierarchicalEntity
            result = await self.db.execute(
                select(HierarchicalEntity.company_id)
                .where(HierarchicalEntity.id == entity_id)
            )
            return result.scalar_one_or_none()
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Write Episodic (S2 — called on ExecutionRun completion)
    # ------------------------------------------------------------------

    async def write_episodic(self, run: Any) -> Optional[EpisodicMemory]:
        """
        Persist the completed run as an episodic memory record.
        DUAL WRITE: v1 flat table + v2 Episodic Tree.

        Only top-level runs are written (parent_run_id is None).
        Sub-runs (child steps) are dropped to keep the episodic store lean.

        Args:
            run: ExecutionRun ORM instance
        Returns:
            EpisodicMemory row, or None if skipped (sub-run or error)
        """
        # Only top-level runs get episodic entries
        if getattr(run, "parent_run_id", None) is not None:
            return None

        episode = None

        # --- V1: Write to flat table (existing behavior) ---
        try:
            input_summary = _summarize(run.input_data)
            output_summary = _summarize(run.result_data)

            ctx = run.context_state or {}
            tools_used = list({
                tr["tool"]
                for step_key, step_val in ctx.items()
                if isinstance(step_val, dict)
                for tr in step_val.get("tool_results", [])
                if isinstance(tr, dict) and "tool" in tr
            })

            episode = EpisodicMemory(
                entity_id=run.entity_id,
                company_id=run.company_id,
                user_id=run.user_id,
                run_id=run.id,
                input_summary=input_summary,
                output_summary=output_summary,
                status=str(run.status),
                total_cost_usd=str(run.total_cost_usd) if run.total_cost_usd else None,
                total_tokens=run.total_tokens,
                execution_time_ms=run.execution_time_ms,
                metadata_info={
                    "tools_used": tools_used,
                    "step_count": len([k for k in ctx if k.startswith("step_")]),
                },
            )
            self.db.add(episode)
            await self.db.flush()

            await self._prune_old_episodes(run.entity_id, run.user_id)
            logger.debug(f"Episodic memory v1 written for run {run.id}")

        except Exception as e:
            logger.warning(f"EpisodicMemory v1 write failed for run {run.id}: {e}")

        # --- V2: Write to Episodic Tree (non-fatal) ---
        try:
            from src.ai.memory.episodic_tree_service import EpisodicTreeService
            episodic_service = EpisodicTreeService(self.db, run.company_id)

            ctx = run.context_state or {}
            runtime_tree_id_str = ctx.get("__cortex_tree_id__")
            runtime_tree_id = UUID(runtime_tree_id_str) if runtime_tree_id_str else None

            episode_node_id = await episodic_service.write_episode(
                entity_id=run.entity_id,
                run=run,
                runtime_tree_id=runtime_tree_id,
            )
            logger.info(f"Episodic Tree v2: episode {episode_node_id} for run {run.id}")
        except Exception as e:
            logger.warning(f"Episodic Tree v2 write failed for run {run.id}: {e}")

        return episode

    # ------------------------------------------------------------------
    # Semantic Search (pgvector)
    # ------------------------------------------------------------------

    async def search_semantic(
        self,
        entity_id: UUID,
        query: str,
        top_k: int = 5,
        api_key: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Hybrid semantic + graph search across all memory domains (v2).
        Falls back to v1 document_chunks search if v2 is unavailable.

        Returns empty list gracefully if embeddings or config unavailable.
        """
        # --- V2: Semantic Graph Search ---
        try:
            company_id = await self._get_company_id(entity_id)
            if company_id:
                from src.ai.memory.graph_service import SemanticGraphService
                graph = SemanticGraphService(self.db, company_id)
                results = await graph.semantic_graph_search(
                    query=query,
                    entity_id=entity_id,
                    domains=None,  # Search all domains
                    top_k=top_k,
                    graph_expansion_depth=1,
                )
                if results:
                    return [
                        {
                            "content": r.get("summary", ""),
                            "score": r.get("combined_score", 0.0),
                            "node_type": r.get("node_type"),
                            "memory_domain": r.get("memory_domain"),
                            "source": r.get("source", "semantic"),
                        }
                        for r in results
                    ]
        except Exception as e:
            logger.debug(f"V2 semantic graph search failed, falling back to v1: {e}")

        # --- V1 Fallback: document_chunks ---
        try:
            company_id = await self._get_company_id(entity_id)
            if not company_id:
                return []

            from src.ai.memory.embedding_service import EmbeddingService
            embedding_service = EmbeddingService(self.db, company_id)
            query_vector = await embedding_service.embed_query(query)

            if not query_vector:
                logger.debug("Semantic search skipped: embedding generation failed")
                return []

            from src.ai.models import DocumentChunk, Document
            from sqlalchemy import text

            stmt = text("""
                SELECT dc.content,
                       1 - (dc.embedding <=> CAST(:vec AS vector)) AS score
                FROM   document_chunks dc
                JOIN   documents d ON d.id = dc.document_id
                WHERE  d.entity_id = :entity_id
                ORDER  BY dc.embedding <=> CAST(:vec AS vector)
                LIMIT  :top_k
            """)
            result = await self.db.execute(stmt, {
                "vec": json.dumps(list(query_vector)),
                "entity_id": str(entity_id),
                "top_k": top_k,
            })
            rows = result.fetchall()
            return [{"content": r[0], "score": float(r[1])} for r in rows]

        except Exception as e:
            logger.debug(f"Semantic search skipped: {e}")
            return []

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _prune_old_episodes(self, entity_id: UUID, user_id: Optional[UUID]) -> None:
        """Delete records beyond MAX_EPISODES for this entity/user pair."""
        try:
            stmt = (
                select(EpisodicMemory.id)
                .where(EpisodicMemory.entity_id == entity_id)
                .order_by(desc(EpisodicMemory.created_at))
                .offset(self.MAX_EPISODES)
            )
            if user_id:
                stmt = stmt.where(EpisodicMemory.user_id == user_id)
            result = await self.db.execute(stmt)
            stale_ids = [r[0] for r in result.fetchall()]
            if stale_ids:
                from sqlalchemy import delete
                await self.db.execute(
                    delete(EpisodicMemory).where(EpisodicMemory.id.in_(stale_ids))
                )
        except Exception as e:
            logger.debug(f"Episode pruning failed: {e}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _summarize(data: Any, max_chars: int = 400) -> str:
    """Convert any value to a short readable string for episodic storage.

    Phase 10C: Delegates to shared utility. Kept as local alias for
    backward compat within this module.
    """
    from src.ai.shared.text_utils import truncate_for_storage
    return truncate_for_storage(data, max_chars=max_chars)

