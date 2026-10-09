"""
memory_assembly_service.py — Unified Memory Assembly Pipeline (Phase F)

Central orchestrator that replaces MemoryRouter.retrieve() with a
comprehensive assembly that draws from all four memory domains:
  - Knowledge (reference nodes from persistent KB trees)
  - Experience (suggestions from learned patterns)
  - Intelligence (distilled rules and strategies)
  - Episodic (recent execution history)

Usage:
    assembler = MemoryAssemblyService(db, company_id)
    result = await assembler.assemble_runtime_memory(
        entity_id=entity_id,
        task_description="Analyze Q3 revenue trends",
    )
    prompt_text = result.formatted_prompt

A domain whose retrieval fails is named in ``result.failures`` (MC-06): its
empty list means "not read", not "nothing learned". Each domain reads in its
own savepoint, so one failed query does not abort the others.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable, Dict, List, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


@dataclass
class MemoryAssemblyResult:
    """Container for assembled memory from all four domains."""
    knowledge_refs: List[Dict[str, Any]] = field(default_factory=list)
    experience_suggestions: List[Dict[str, Any]] = field(default_factory=list)
    intelligence_rules: List[Dict[str, Any]] = field(default_factory=list)
    episodic_context: List[Dict[str, Any]] = field(default_factory=list)
    formatted_prompt: str = ""
    # Each retrieval that failed, by name -> "ErrorType: message": the four
    # domains, plus "knowledge_refs" (the runtime tree's reference nodes) and
    # "episodic_topic" (the semantic half of the episodic read).
    failures: Dict[str, str] = field(default_factory=dict)


class MemoryAssemblyService:
    """
    Unified Memory Assembly Pipeline for v2.

    Replaces MemoryRouter.retrieve() with a comprehensive assembly
    that draws from all four memory domains.
    """

    def __init__(
        self,
        db: AsyncSession,
        company_id: UUID,
        *,
        embedding: Any = None,
        llm: Any = None,
        child_run_factory: Any = None,
    ):
        self.db = db
        self.company_id = company_id
        # Injected cortex_memory providers, passed down to the graph / domain /
        # CORTEX services this assembler constructs.
        self._embedding = embedding
        self._llm = llm
        self._child_run_factory = child_run_factory

    async def assemble_runtime_memory(
        self,
        entity_id: UUID,
        user_id: Optional[UUID] = None,
        task_description: str = "",
        runtime_tree: Any = None,
        include_domains: Optional[List[str]] = None,
    ) -> MemoryAssemblyResult:
        """
        Assemble memory from all four domains for a new execution.

        Returns a MemoryAssemblyResult containing domain-specific data
        and a pre-formatted prompt string for system prompt injection.
        """
        domains = include_domains or ["knowledge", "experience", "intelligence", "episodic"]
        result = MemoryAssemblyResult()

        # 1. KNOWLEDGE ASSEMBLY
        if "knowledge" in domains:
            result.knowledge_refs = await self._read_domain(
                result, "knowledge", lambda: self._assemble_knowledge(entity_id, task_description),
            )
            if result.knowledge_refs and runtime_tree:
                await self._create_runtime_knowledge_refs(result, runtime_tree, result.knowledge_refs[:5])

        # 2. EXPERIENCE RETRIEVAL
        if "experience" in domains:
            result.experience_suggestions = await self._read_domain(
                result, "experience", lambda: self._retrieve_experience(entity_id, task_description),
            )

        # 3. INTELLIGENCE INJECTION
        if "intelligence" in domains:
            result.intelligence_rules = await self._read_domain(
                result, "intelligence", lambda: self._retrieve_intelligence(entity_id, task_description),
            )

        # 4. EPISODIC CONTEXT
        if "episodic" in domains:
            result.episodic_context = await self._read_domain(
                result, "episodic",
                lambda: self._retrieve_episodic(entity_id, user_id, task_description, result=result),
            )

        # 5. Format for prompt
        result.formatted_prompt = self._format_assembled_memory(result)
        return result

    # ===================================================================
    # Domain Assemblers
    # ===================================================================

    @staticmethod
    def _record_failure(result: MemoryAssemblyResult, name: str, exc: BaseException) -> None:
        result.failures[name] = f"{type(exc).__name__}: {exc}"[:500]
        logger.warning("CORTEX %s retrieval failed: %s", name, exc)

    async def _read_domain(
        self,
        result: MemoryAssemblyResult,
        name: str,
        read: Callable[[], Awaitable[List[Dict[str, Any]]]],
    ) -> List[Dict[str, Any]]:
        """One domain's read in its own savepoint. A failure is recorded in
        ``result.failures`` and reads as ``[]``; the savepoint keeps a failed
        query from aborting the transaction the other domains read in."""
        try:
            async with self.db.begin_nested():
                return await read()
        except Exception as exc:
            self._record_failure(result, name, exc)
            return []

    async def _assemble_knowledge(
        self,
        entity_id: UUID,
        task_description: str,
    ) -> List[Dict[str, Any]]:
        """Find relevant knowledge nodes via semantic graph search."""
        from cortex_memory.graph import SemanticGraphService
        graph = SemanticGraphService(self.db, self.company_id, embedding=self._embedding)

        results = await graph.semantic_graph_search(
            query=task_description,
            entity_id=entity_id,
            domains=["knowledge"],
            top_k=10,
            graph_expansion_depth=1,
        )
        return results or []

    async def _create_runtime_knowledge_refs(
        self, result: MemoryAssemblyResult, runtime_tree: Any, items: List[Dict[str, Any]],
    ) -> None:
        """Create reference nodes in the runtime tree's knowledge root.

        Each write has its own savepoint, so one bad reference costs only
        itself; the failures are recorded as ``knowledge_refs``.
        """
        failed: List[str] = []
        try:
            from cortex_memory.service import CortexService
            cortex = CortexService(self.db, self.company_id, llm=self._llm, child_run_factory=self._child_run_factory)
            async with self.db.begin_nested():
                knowledge_root = await cortex.get_knowledge_root(runtime_tree.id)
            if not knowledge_root:
                return

            for item in items:
                try:
                    async with self.db.begin_nested():
                        await cortex.write(
                            parent_id=knowledge_root.id,
                            node_type="knowledge",
                            title=f"📎 {item.get('title', 'Reference')[:100]}",
                            summary=item.get("summary", ""),
                            content=None,
                            source_ref={
                                "ref_type": "cortex_node",
                                "source_tree_id": item.get("tree_id"),
                                "source_node_id": item.get("node_id"),
                                "relevance_score": item.get("combined_score", 0),
                            },
                        )
                except Exception as exc:
                    failed.append(f"{type(exc).__name__}: {exc}")
        except Exception as exc:
            self._record_failure(result, "knowledge_refs", exc)
            return
        if failed:
            self._record_failure(
                result, "knowledge_refs",
                RuntimeError(f"{len(failed)} of {len(items)} reference writes failed; last: {failed[-1]}"),
            )

    async def _retrieve_experience(
        self,
        entity_id: UUID,
        task_description: str,
    ) -> List[Dict[str, Any]]:
        """Query Experience Tree for suggestions relevant to the current task."""
        from cortex_memory.graph import SemanticGraphService
        graph = SemanticGraphService(self.db, self.company_id, embedding=self._embedding)

        results = await graph.semantic_graph_search(
            query=task_description,
            entity_id=entity_id,
            domains=["experience"],
            top_k=5,
        )

        return [
            {
                "suggestion": r.get("summary", ""),
                "type": r.get("node_type"),
                "confidence": r.get("combined_score", 0),
            }
            for r in (results or [])
            if r.get("node_type") in ("suggestion", "pattern", "observation")
        ]

    async def _retrieve_intelligence(
        self,
        entity_id: UUID,
        task_description: str,
    ) -> List[Dict[str, Any]]:
        """Query Intelligence Tree for applicable rules."""
        from cortex_memory.intelligence_tree import IntelligenceTreeService
        intelligence_svc = IntelligenceTreeService(self.db, self.company_id, embedding=self._embedding)
        rules: List[Dict[str, Any]] = await intelligence_svc.get_applicable_rules(
            entity_id=entity_id,
            task_description=task_description,
            max_rules=10,
        )
        return rules

    async def _retrieve_episodic(
        self,
        entity_id: UUID,
        user_id: Optional[UUID] = None,
        task_description: str = "",
        *,
        result: Optional[MemoryAssemblyResult] = None,
    ) -> List[Dict[str, Any]]:
        """Retrieve recent and topically relevant episodes.

        The recent episodes stand on their own: if the semantic half fails it
        is recorded as ``episodic_topic`` and the recent ones are returned.
        """
        from cortex_memory.episodic_tree import EpisodicTreeService
        episodic_svc = EpisodicTreeService(self.db, self.company_id, embedding=self._embedding)

        # Recent episodes
        recent = await episodic_svc.get_recent_episodes(
            entity_id=entity_id, limit=5,
        )

        # Topic-relevant episodes (semantic)
        relevant = []
        if task_description:
            try:
                async with self.db.begin_nested():
                    relevant_raw = await episodic_svc.query_by_topic(
                        entity_id=entity_id,
                        query=task_description,
                        top_k=3,
                    )
                for ep in relevant_raw:
                    relevant.append({
                        "input": ep.get("content", ""),
                        "output": ep.get("summary", ""),
                        "status": (ep.get("metadata") or {}).get("status", ""),
                        "at": ep.get("created_at", ""),
                    })
            except Exception as exc:
                if result is None:
                    raise
                self._record_failure(result, "episodic_topic", exc)

        # Merge and deduplicate
        seen = set()
        episodes = []
        for ep in recent + relevant:
            key = ep.get("at", "") + ep.get("input", "")[:50]
            if key not in seen:
                episodes.append(ep)
                seen.add(key)

        return episodes[:10]

    # ===================================================================
    # Prompt Formatting
    # ===================================================================

    def _format_assembled_memory(self, result: MemoryAssemblyResult) -> str:
        """
        Format assembled memory into structured prompt text.

        Layout:
          [INTELLIGENCE] — Rules and strategies (highest priority)
          [KNOWLEDGE] — Relevant KB references
          [EXPERIENCE] — Suggestions from past patterns
          [EPISODIC] — Recent execution history
        """
        parts = []

        # Intelligence Rules (highest priority — goes first)
        if result.intelligence_rules:
            rule_lines = []
            for rule in result.intelligence_rules:
                confidence = rule.get("confidence", 0.5)
                emoji = {
                    "instruction": "📏",
                    "strategy": "🎯",
                    "preference": "❤️",
                }.get(rule.get("type", ""), "💡")
                rule_lines.append(
                    f"  {emoji} [{confidence:.0%}] {rule.get('rule', rule.get('title', ''))}"
                )
            parts.append(
                "## Learned Intelligence\n"
                "The following rules have been learned from past experience:\n"
                + "\n".join(rule_lines)
            )

        # Knowledge References
        if result.knowledge_refs:
            kb_lines = [
                f"  📎 [{r.get('combined_score', 0):.2f}] "
                f"{r.get('title', 'Untitled')}: {r.get('summary', '')[:200]}"
                for r in result.knowledge_refs[:5]
            ]
            parts.append("## Relevant Knowledge\n" + "\n".join(kb_lines))

        # Experience Suggestions
        if result.experience_suggestions:
            exp_lines = [
                f"  💡 [{s.get('confidence', 0):.2f}] {s.get('suggestion', '')[:200]}"
                for s in result.experience_suggestions
            ]
            parts.append("## Experience Suggestions\n" + "\n".join(exp_lines))

        # Episodic Context
        if result.episodic_context:
            ep_lines = []
            for ep in result.episodic_context[:5]:
                inp = (ep.get("input") or "")[:150]
                out = (ep.get("output") or "")[:150]
                at = ep.get("at", "")
                ep_lines.append(f"  [{at}] {inp!r} → {out!r}")
            parts.append("## Recent Execution History\n" + "\n".join(ep_lines))

        return "\n\n".join(parts)
