"""
dreaming_engine.py — The Learning Engine (Phase D)

Background learning pipeline that extracts patterns from episodic history
and distills them into actionable intelligence. Runs as a background
worker task, triggered after execution completion.

Three-phase pipeline:
  Phase 1: Observation Extraction  (Episodic → Experience.Observations)
  Phase 2: Pattern Recognition     (Observations → Experience.Patterns)
  Phase 3: Intelligence Distillation (Patterns → Intelligence.Rules)

Usage:
    engine = DreamingEngine(db, company_id)
    result = await engine.dream(entity_id, force=True)
    # result = {"observations_created": 3, "patterns_created": 1, "rules_created": 1}
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from cortex_memory.models import (
    CortexTree, CortexNode, CortexEdge,
    CortexTreeStatus, CortexNodeType, CortexNodeStatus,
    MemoryDomain, ScopeLevel,
)
from cortex_memory.dreaming_prompts import (
    OBSERVATION_EXTRACTION_PROMPT,
    PATTERN_RECOGNITION_PROMPT,
    INTELLIGENCE_DISTILLATION_PROMPT,
)

logger = logging.getLogger(__name__)


class _Resp:
    """Minimal LLMResponse-shaped object the dreaming phases read (.output)."""

    def __init__(self, output: str = "", model_name: str = "",
                 prompt_tokens: int = 0, completion_tokens: int = 0) -> None:
        self.output = output
        self.model_name = model_name
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens


class _ProviderLLMAdapter:
    """Adapts a cortex_memory.LLMProvider to the ``call_llm(...)`` interface."""

    def __init__(self, provider: Any) -> None:
        self._p = provider

    async def call_llm(self, *, task_type: str = "text_generation",
                       system_prompt: str = "", user_prompt: str = "",
                       temperature: float = 0.7, max_tokens: Any = None,
                       **_kw: Any) -> _Resp:
        if self._p is None:
            return _Resp("")
        r = await self._p.complete(
            system=system_prompt, user=user_prompt, task_type=task_type,
            temperature=temperature, max_tokens=max_tokens,
        )
        return _Resp(r.text or "", r.model, r.input_tokens, r.output_tokens)


class DreamingEngine:
    """
    Background learning engine — the "dreaming" process.

    Extracts observations from episodes, identifies patterns across
    observations, and distills validated patterns into rules.
    """

    # Configuration (overridable via constants.py defaults)
    MIN_EPISODES_FOR_DREAMING = 5
    MIN_OBSERVATIONS_FOR_PATTERNS = 3
    MIN_PATTERNS_FOR_DISTILLATION = 2
    BATCH_SIZE = 20
    CONSOLIDATION_INTERVAL_HOURS = 24
    OBSERVATION_CONFIDENCE_THRESHOLD = 0.5
    PATTERN_STRENGTH_THRESHOLD = 0.7

    def __init__(
        self,
        db: AsyncSession,
        company_id: UUID,
        *,
        llm: Any = None,
        embedding: Any = None,
    ) -> None:
        self.db = db
        self.company_id = company_id
        # Injected cortex_memory providers. Both optional; dreaming degrades to
        # a no-op when absent (standalone use).
        self._llm = llm
        self._embedding = embedding

    def _get_llm(self) -> Any:
        """Adapt the injected LLMProvider to the call_llm(...) interface the
        dreaming phases use."""
        return _ProviderLLMAdapter(self._llm)

    async def _log_dreaming_usage(self, response: Any) -> None:
        # The injected provider's host adapter self-meters; nothing to do.
        return None

    # ===================================================================
    # Main Entry Point
    # ===================================================================

    async def dream(
        self,
        entity_id: UUID,
        force: bool = False,
    ) -> Dict[str, int]:
        """
        Run the full dreaming pipeline for an entity.

        Returns counts of created nodes per phase.
        """
        if not force:
            should_run = await self._should_run(entity_id)
            if not should_run:
                return {"observations_created": 0, "patterns_created": 0, "rules_created": 0}

        logger.info(f"Dreaming engine starting for entity {entity_id}")

        # Extract Observations
        obs_ids = await self._extract_observations(entity_id)

        # Pattern Recognition
        pat_ids = await self._recognize_patterns(entity_id)

        # Intelligence Distillation
        rule_ids = await self._distill_intelligence(entity_id)

        # Update consolidation timestamps
        await self._update_consolidation_timestamp(entity_id)

        result = {
            "observations_created": len(obs_ids),
            "patterns_created": len(pat_ids),
            "rules_created": len(rule_ids),
        }
        logger.info(f"Dreaming engine completed for entity {entity_id}: {result}")
        return result

    # ===================================================================
    # Observation Extraction
    # ===================================================================

    async def _extract_observations(self, entity_id: UUID) -> List[UUID]:
        """
        Analyze recent episode nodes and extract observations via LLM.
        """
        from cortex_memory.episodic_tree import EpisodicTreeService
        from cortex_memory.experience_tree import ExperienceTreeService

        episodic_svc = EpisodicTreeService(self.db, self.company_id, embedding=self._embedding)
        experience_svc = ExperienceTreeService(self.db, self.company_id)

        experience_tree = await experience_svc.get_or_create_experience_tree(entity_id)
        last_consolidated = experience_tree.last_consolidated_at or datetime.min

        # Get unprocessed episodes
        episodes = await episodic_svc.query_by_time(
            entity_id=entity_id,
            start_date=last_consolidated,
            end_date=datetime.utcnow(),
            limit=self.BATCH_SIZE,
        )

        if len(episodes) < self.MIN_EPISODES_FOR_DREAMING:
            logger.debug(
                f"Skipping observation extraction: {len(episodes)} episodes "
                f"(min {self.MIN_EPISODES_FOR_DREAMING})"
            )
            return []

        # Build episode summaries for LLM
        episode_summaries = []
        for ep in episodes:
            meta = ep.get("metadata", {}) or {}
            episode_summaries.append({
                "id": ep.get("node_id", ""),
                "task": ep.get("summary", ""),
                "status": meta.get("status", "unknown"),
                "tools_used": meta.get("tools_used", []),
                "cost_usd": meta.get("cost_usd", 0),
                "execution_time_ms": meta.get("execution_time_ms", 0),
            })

        try:
            llm = self._get_llm()
            response = await llm.call_llm(
                task_type="text_generation",
                system_prompt=OBSERVATION_EXTRACTION_PROMPT,
                user_prompt=json.dumps(episode_summaries),
                temperature=0.2,
                max_tokens=2000,
            )
            await self._log_dreaming_usage(response)
        except Exception as e:
            logger.warning(f"LLM call failed in observation extraction: {e}")
            return []

        from cortex_memory._textutil import parse_json_array
        observations = parse_json_array(response.output)
        if not observations:
            return []

        # Write observation nodes
        obs_root = await experience_svc.get_observations_root(entity_id)
        created_ids = []

        from cortex_memory.embedding import embed_node

        for obs in observations:
            if obs.get("confidence", 0) < self.OBSERVATION_CONFIDENCE_THRESHOLD:
                continue

            node = CortexNode(
                id=uuid4(),
                tree_id=experience_tree.id,
                parent_id=obs_root,
                node_type=CortexNodeType.OBSERVATION,
                title=f"🔍 {obs.get('title', 'Observation')[:100]}",
                summary=obs.get("description", "")[:500],
                content=json.dumps(obs),
                status=CortexNodeStatus.COMPLETE,
                depth=2,
                sibling_order=await self._next_sibling_order(obs_root),
                metadata_extra={
                    "source_episodes": obs.get("source_episodes", []),
                    "confidence": obs.get("confidence", 0.5),
                    "first_observed": datetime.utcnow().isoformat(),
                    "observation_count": 1,
                },
                importance_score=obs.get("confidence", 0.5),
            )
            self.db.add(node)
            await self.db.flush()

            # Embed the observation
            await embed_node(self._embedding, node)
            created_ids.append(node.id)

        experience_tree.total_nodes = (experience_tree.total_nodes or 0) + len(created_ids)
        await self.db.flush()

        logger.info(f"Phase 1: {len(created_ids)} observations extracted for entity {entity_id}")
        return created_ids

    # ===================================================================
    # Pattern Recognition
    # ===================================================================

    async def _recognize_patterns(self, entity_id: UUID) -> List[UUID]:
        """
        Cluster observations by embedding similarity and synthesize patterns.
        """
        from cortex_memory.experience_tree import ExperienceTreeService
        experience_svc = ExperienceTreeService(self.db, self.company_id)

        observations = await experience_svc.get_observations(entity_id)
        if len(observations) < self.MIN_OBSERVATIONS_FOR_PATTERNS:
            logger.debug(f"Skipping pattern recognition: {len(observations)} observations")
            return []

        # Cluster by embedding similarity
        clusters = self._cluster_observations(observations)

        patterns_root = await experience_svc.get_patterns_root(entity_id)
        experience_tree = await experience_svc.get_or_create_experience_tree(entity_id)
        created_ids = []

        from cortex_memory.embedding import embed_node

        for cluster in clusters:
            if len(cluster) < 2:
                continue

            # LLM synthesis
            cluster_texts = [obs.summary for obs in cluster]
            try:
                llm = self._get_llm()
                response = await llm.call_llm(
                    task_type="text_generation",
                    system_prompt=PATTERN_RECOGNITION_PROMPT,
                    user_prompt=json.dumps(cluster_texts),
                    temperature=0.2,
                    max_tokens=500,
                )
                await self._log_dreaming_usage(response)
            except Exception as e:
                logger.warning(f"LLM call failed in pattern recognition: {e}")
                continue

            from cortex_memory._textutil import parse_json_object
            pattern = parse_json_object(response.output)
            if not pattern:
                continue

            node = CortexNode(
                id=uuid4(),
                tree_id=experience_tree.id,
                parent_id=patterns_root,
                node_type=CortexNodeType.PATTERN,
                title=f"🔄 {pattern.get('title', 'Pattern')[:100]}",
                summary=pattern.get("description", "")[:500],
                content=json.dumps(pattern),
                status=CortexNodeStatus.COMPLETE,
                depth=2,
                sibling_order=await self._next_sibling_order(patterns_root),
                metadata_extra={
                    "source_observations": [str(obs.id) for obs in cluster],
                    "pattern_strength": pattern.get("strength", 0.5),
                    "recurrence_count": len(cluster),
                    "success_correlation": pattern.get("success_correlation", 0.5),
                },
            )
            self.db.add(node)
            await self.db.flush()

            # Embed the pattern
            await embed_node(self._embedding, node)

            # Create cortex_edges linking pattern → source observations
            for obs in cluster:
                edge = CortexEdge(
                    source_node_id=node.id,
                    target_node_id=obs.id,
                    edge_type="derived_from",
                    weight=1.0 / len(cluster),
                    created_by="dreaming_engine",
                )
                self.db.add(edge)

            created_ids.append(node.id)

        experience_tree.total_nodes = (experience_tree.total_nodes or 0) + len(created_ids)
        await self.db.flush()

        logger.info(f"Phase 2: {len(created_ids)} patterns recognized for entity {entity_id}")
        return created_ids

    # ===================================================================
    # Intelligence Distillation
    # ===================================================================

    async def _distill_intelligence(self, entity_id: UUID) -> List[UUID]:
        """
        Distill validated patterns into actionable Intelligence rules.
        """
        from cortex_memory.experience_tree import ExperienceTreeService
        from cortex_memory.intelligence_tree import IntelligenceTreeService

        experience_svc = ExperienceTreeService(self.db, self.company_id)
        intelligence_svc = IntelligenceTreeService(self.db, self.company_id, embedding=self._embedding)

        # Get strong patterns
        patterns = await experience_svc.get_strong_patterns(
            entity_id,
            min_strength=self.PATTERN_STRENGTH_THRESHOLD,
            min_recurrence=self.MIN_PATTERNS_FOR_DISTILLATION,
        )

        if not patterns:
            logger.debug("Skipping distillation: no strong patterns")
            return []

        # Get existing rules to avoid duplicates
        existing_rules = await intelligence_svc.get_all_rules(entity_id)
        existing_summaries = [r.summary for r in existing_rules]

        try:
            llm = self._get_llm()
            response = await llm.call_llm(
                task_type="text_generation",
                system_prompt=INTELLIGENCE_DISTILLATION_PROMPT,
                user_prompt=json.dumps({
                    "patterns": [
                        {
                            "summary": p.summary,
                            "strength": (p.metadata_extra or {}).get("pattern_strength", 0.5),
                        }
                        for p in patterns
                    ],
                    "existing_rules": existing_summaries,
                }),
                temperature=0.1,
                max_tokens=2000,
            )
            await self._log_dreaming_usage(response)
        except Exception as e:
            logger.warning(f"LLM call failed in intelligence distillation: {e}")
            return []

        from cortex_memory._textutil import parse_json_array
        rules = parse_json_array(response.output)
        if not rules:
            return []

        intelligence_tree = await intelligence_svc.get_or_create_intelligence_tree(entity_id)
        created_ids = []

        from cortex_memory.embedding import embed_node

        NODE_TYPE_MAP = {
            "instruction": CortexNodeType.INSTRUCTION,
            "strategy": CortexNodeType.STRATEGY,
            "preference": CortexNodeType.PREFERENCE,
        }
        EMOJI_MAP = {
            "instruction": "📏",
            "strategy": "🎯",
            "preference": "❤️",
        }

        for rule in rules:
            rule_type = rule.get("type", "instruction")
            node_type = NODE_TYPE_MAP.get(rule_type, CortexNodeType.INSTRUCTION)
            emoji = EMOJI_MAP.get(rule_type, "📏")

            parent_id = await intelligence_svc.get_section_root(entity_id, rule_type)

            node = CortexNode(
                id=uuid4(),
                tree_id=intelligence_tree.id,
                parent_id=parent_id,
                node_type=node_type,
                title=f"{emoji} {rule.get('title', 'Rule')[:100]}",
                summary=rule.get("description", "")[:500],
                content=json.dumps(rule),
                status=CortexNodeStatus.COMPLETE,
                depth=2,
                sibling_order=await self._next_sibling_order(parent_id),
                metadata_extra={
                    "rule_type": rule_type,
                    "source_patterns": rule.get("source_patterns", []),
                    "confidence": rule.get("confidence", 0.5),
                    "success_rate": rule.get("success_rate", 0.0),
                    "applicability_conditions": rule.get("applicability_conditions", []),
                    "generation": (intelligence_tree.consolidation_generation or 0) + 1,
                },
            )
            self.db.add(node)
            await self.db.flush()

            # Embed for semantic retrieval
            await embed_node(self._embedding, node)
            created_ids.append(node.id)

        # Update generation counter
        intelligence_tree.consolidation_generation = (
            (intelligence_tree.consolidation_generation or 0) + 1
        )
        intelligence_tree.last_consolidated_at = datetime.utcnow()
        intelligence_tree.total_nodes = (intelligence_tree.total_nodes or 0) + len(created_ids)
        await self.db.flush()

        logger.info(f"Phase 3: {len(created_ids)} rules distilled for entity {entity_id}")
        return created_ids

    # ===================================================================
    # Scheduling Helpers
    # ===================================================================

    async def _should_run(self, entity_id: UUID) -> bool:
        """Check if enough time has passed since the last consolidation."""
        from cortex_memory.experience_tree import ExperienceTreeService
        experience_svc = ExperienceTreeService(self.db, self.company_id)

        try:
            tree = await experience_svc.get_or_create_experience_tree(entity_id)
        except Exception:
            return True  # No tree yet — first run

        if not tree.last_consolidated_at:
            return True

        hours_since = (datetime.utcnow() - tree.last_consolidated_at).total_seconds() / 3600
        return hours_since >= self.CONSOLIDATION_INTERVAL_HOURS

    async def _update_consolidation_timestamp(self, entity_id: UUID) -> None:
        """Update the last consolidation timestamp on the Experience Tree."""
        from cortex_memory.experience_tree import ExperienceTreeService
        experience_svc = ExperienceTreeService(self.db, self.company_id)
        tree = await experience_svc.get_or_create_experience_tree(entity_id)
        tree.last_consolidated_at = datetime.utcnow()
        tree.consolidation_generation = (tree.consolidation_generation or 0) + 1
        await self.db.flush()

    # ===================================================================
    # Observation Clustering
    # ===================================================================

    def _cluster_observations(
        self, observations: List[CortexNode],
    ) -> List[List[CortexNode]]:
        """
        Simple greedy clustering by embedding cosine similarity.
        Groups observations with embeddings > 0.75 similarity.
        """
        if not observations:
            return []

        # Filter to observations with embeddings
        embedded = [o for o in observations if o.embedding is not None]
        if len(embedded) < 2:
            return [embedded] if embedded else []

        # Greedy clustering
        used = set()
        clusters: List[List[CortexNode]] = []

        for i, obs_a in enumerate(embedded):
            if i in used:
                continue
            cluster = [obs_a]
            used.add(i)

            for j, obs_b in enumerate(embedded):
                if j in used or j <= i:
                    continue
                sim = self._cosine_similarity(obs_a.embedding, obs_b.embedding)
                if sim > 0.75:
                    cluster.append(obs_b)
                    used.add(j)

            clusters.append(cluster)

        return clusters

    @staticmethod
    def _cosine_similarity(a: Any, b: Any) -> float:
        """Compute cosine similarity between two vectors.

        Accepts plain lists or numpy/pgvector arrays. We must avoid bare
        truthiness checks (``if not a``) because pgvector loads embeddings
        as numpy ndarrays, for which truthiness raises
        ``ValueError: The truth value of an array ... is ambiguous``.
        """
        if a is None or b is None or len(a) == 0 or len(b) == 0 or len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = sum(x * x for x in a) ** 0.5
        norm_b = sum(x * x for x in b) ** 0.5
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return float(dot / (norm_a * norm_b))

    async def _next_sibling_order(self, parent_id: UUID) -> int:
        """Get next sibling order for children of a node."""
        from sqlalchemy import func
        result = await self.db.execute(
            select(func.coalesce(func.max(CortexNode.sibling_order), -1))
            .where(CortexNode.parent_id == parent_id)
        )
        return int(result.scalar() or -1) + 1

