"""
registry_search_service.py — Four-phase reuse decision engine (V2).

Phase 1:   Structural contract matching (deterministic, fast)
             - Entity type filtering
             - Tool overlap scoring
             - Tag overlap, complexity match

Phase 1.5: IO Contract compatibility
             - Input/output schema property overlap

Phase 2:   Semantic intent matching (LLM-powered)
             - Description/goal similarity
             - System prompt behavioral alignment

Phase 2.5: Execution trace analysis
             - Historical success rate
             - Cost efficiency
             - Recency weighting

Returns ranked candidates with match classification:
  REUSE   — Direct execution, no modification needed
  ADAPT   — Minor modifications (add tools, tweak prompt)
  COMPOSE — Multiple agents combined into a new PROCESS
  CREATE  — No viable match, generate from scratch
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, cast
from uuid import UUID

from sqlalchemy import select, func, Text as _SAText
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class MatchType(str, Enum):
    REUSE = "REUSE"
    ADAPT = "ADAPT"
    COMPOSE = "COMPOSE"
    CREATE = "CREATE"


@dataclass
class MatchCandidate:
    """A scored candidate from the registry search."""
    entity_id: UUID
    entity_name: str
    entity_type: str
    match_type: MatchType
    structural_score: float  # 0.0 - 1.0 (Phase 1)
    io_score: float          # 0.0 - 1.0 (Phase 1.5)
    semantic_score: float    # 0.0 - 1.0 (Phase 2)
    execution_score: float   # 0.0 - 1.0 (Phase 2.5)
    combined_score: float    # Weighted combination
    tool_overlap: List[str] = field(default_factory=list)
    missing_tools: List[str] = field(default_factory=list)
    rationale: str = ""
    diff_spec: Optional[Dict[str, Any]] = None  # For ADAPT: what to change

    def to_dict(self) -> Dict[str, Any]:
        return {
            "entity_id": str(self.entity_id),
            "entity_name": self.entity_name,
            "entity_type": self.entity_type,
            "match_type": self.match_type.value,
            "structural_score": round(self.structural_score, 3),
            "io_score": round(self.io_score, 3),
            "semantic_score": round(self.semantic_score, 3),
            "execution_score": round(self.execution_score, 3),
            "combined_score": round(self.combined_score, 3),
            "tool_overlap": self.tool_overlap,
            "missing_tools": self.missing_tools,
            "rationale": self.rationale,
            "diff_spec": self.diff_spec,
        }


@dataclass
class SearchRequest:
    """Structured search request from the RequirementAnalyst."""
    intent: str                          # Natural language description
    required_tools: List[str] = field(default_factory=list)
    preferred_type: Optional[str] = None  # ACTION, SKILL, AGENT, PROCESS
    io_schema: Optional[Dict[str, Any]] = None     # Expected input/output shape
    complexity_class: str = "MEDIUM"     # LOW, MEDIUM, HIGH
    tags: List[str] = field(default_factory=list)


class RegistrySearchService:
    """Four-phase reuse decision engine for the Meta-Agent (V2)."""

    # Scoring thresholds
    REUSE_THRESHOLD = 0.85
    ADAPT_THRESHOLD = 0.60
    COMPOSE_THRESHOLD = 0.40

    # V2 four-factor weighting
    STRUCTURAL_WEIGHT = 0.25
    IO_CONTRACT_WEIGHT = 0.15
    SEMANTIC_WEIGHT = 0.35
    EXECUTION_WEIGHT = 0.25

    def __init__(self, db: AsyncSession, company_id: UUID):
        self.db = db
        self.company_id = company_id

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def search(
        self,
        request: SearchRequest,
        top_k: int = 5,
        include_templates: bool = True,
    ) -> List[MatchCandidate]:
        """Run the full four-phase search pipeline.

        Returns ranked candidates with match type classification.
        """
        # Structural filtering + scoring
        candidates = await self._phase1_structural(request, include_templates)

        if not candidates:
            return []

        # .5: IO Contract compatibility scoring
        await self._phase15_io_contract(request, candidates)

        # Semantic scoring (LLM-powered)
        scored = await self._phase2_semantic(request, candidates[:top_k * 2])

        # .5: Execution trace weighting
        await self._phase25_execution_traces(scored)

        # Recompute combined scores with all four factors
        for c in scored:
            c.combined_score = (
                c.structural_score * self.STRUCTURAL_WEIGHT +
                c.io_score * self.IO_CONTRACT_WEIGHT +
                c.semantic_score * self.SEMANTIC_WEIGHT +
                c.execution_score * self.EXECUTION_WEIGHT
            )

        # Classify and rank
        classified = self._classify_candidates(scored, request)

        # Return top K
        return sorted(classified, key=lambda c: c.combined_score, reverse=True)[:top_k]

    async def recommend(self, request: SearchRequest) -> Dict[str, Any]:
        """High-level recommendation: search + decision summary.

        Returns a dict with:
          - decision: REUSE | ADAPT | COMPOSE | CREATE
          - candidates: ranked list of candidates
          - rationale: explanation of the decision
        """
        candidates = await self.search(request, top_k=5)

        if not candidates:
            return {
                "decision": MatchType.CREATE.value,
                "candidates": [],
                "rationale": "No existing agents match the requirement. "
                             "A new agent should be created from scratch.",
            }

        best = candidates[0]

        if best.match_type == MatchType.REUSE:
            rationale = (
                f"Agent '{best.entity_name}' (score: {best.combined_score:.0%}) "
                f"matches all requirements. Direct execution recommended."
            )
        elif best.match_type == MatchType.ADAPT:
            missing = ", ".join(best.missing_tools[:5]) if best.missing_tools else "prompt adjustments"
            rationale = (
                f"Agent '{best.entity_name}' (score: {best.combined_score:.0%}) "
                f"is a near-match. Adaptation needed: {missing}."
            )
        elif best.match_type == MatchType.COMPOSE:
            agent_names = [c.entity_name for c in candidates if c.combined_score > self.COMPOSE_THRESHOLD]
            rationale = (
                f"No single agent covers the full requirement. "
                f"Recommend composing: {', '.join(agent_names[:3])} into a PROCESS entity."
            )
        else:
            rationale = "No viable match found. Create a new agent."

        return {
            "decision": best.match_type.value,
            "candidates": [c.to_dict() for c in candidates],
            "rationale": rationale,
        }

    # ------------------------------------------------------------------
    # Structural Contract Match
    # ------------------------------------------------------------------

    async def _phase1_structural(
        self,
        request: SearchRequest,
        include_templates: bool,
    ) -> List[MatchCandidate]:
        """Fast, deterministic structural matching."""
        from src.ai.models import HierarchicalEntity

        # Build base query: company-scoped + optionally templates
        query = select(HierarchicalEntity).where(
            HierarchicalEntity.status != "DELETED",
        )

        if include_templates:
            from sqlalchemy import or_
            query = query.where(
                or_(
                    HierarchicalEntity.company_id == self.company_id,
                    HierarchicalEntity.is_template == True,
                )
            )
        else:
            query = query.where(HierarchicalEntity.company_id == self.company_id)

        # Type filter (if specified)
        if request.preferred_type:
            query = query.where(HierarchicalEntity.type == request.preferred_type)

        # Exclude Meta-Agent entities from search results.
        # tags is a plain JSON column, not JSONB, so we cast to text for filtering.
        query = query.where(
            func.coalesce(
                func.cast(HierarchicalEntity.tags, _SAText).like('%meta_agent%'),
                False
            ) == False
        )

        result = await self.db.execute(query)
        entities = result.scalars().all()

        candidates = []
        for entity in entities:
            score = self._score_structural(entity, request)
            if score > 0.1:  # Min threshold to avoid noise
                entity_tools = self._extract_tools(entity)
                required_set = set(request.required_tools)
                entity_tool_set = set(entity_tools)

                candidates.append(MatchCandidate(
                    entity_id=entity.id,
                    entity_name=entity.name,
                    entity_type=entity.type if isinstance(entity.type, str) else entity.type.value,
                    match_type=MatchType.CREATE,  # Will be classified later
                    structural_score=score,
                    io_score=0.5,         # Neutral default
                    semantic_score=0.0,
                    execution_score=0.5,  # Neutral default
                    combined_score=score * self.STRUCTURAL_WEIGHT,
                    tool_overlap=list(required_set & entity_tool_set),
                    missing_tools=list(required_set - entity_tool_set),
                ))

        return sorted(candidates, key=lambda c: c.structural_score, reverse=True)

    def _score_structural(self, entity: Any, request: SearchRequest) -> float:
        """Score an entity based on structural contract matching."""
        score = 0.0
        weights_total = 0.0

        # 1. Tool overlap (weight: 0.5)
        if request.required_tools:
            entity_tools = set(self._extract_tools(entity))
            required = set(request.required_tools)
            if required:
                overlap = len(entity_tools & required) / len(required)
                score += overlap * 0.5
            weights_total += 0.5
        else:
            weights_total += 0.5
            score += 0.25  # Neutral if no tools specified

        # 2. Type match (weight: 0.2)
        if request.preferred_type:
            entity_type = entity.type if isinstance(entity.type, str) else entity.type.value
            if entity_type == request.preferred_type:
                score += 0.2
        else:
            score += 0.1  # Neutral
        weights_total += 0.2

        # 3. Tag overlap (weight: 0.15)
        if request.tags and entity.tags:
            entity_tags = set(entity.tags) if isinstance(entity.tags, list) else set()
            required_tags = set(request.tags)
            if required_tags:
                tag_overlap = len(entity_tags & required_tags) / len(required_tags)
                score += tag_overlap * 0.15
        weights_total += 0.15

        # 4. Complexity match (weight: 0.15)
        step_count = self._count_steps(entity)
        complexity_ranges = {
            "LOW": (1, 3),
            "MEDIUM": (3, 7),
            "HIGH": (7, 20),
        }
        low, high = complexity_ranges.get(request.complexity_class, (3, 7))
        if low <= step_count <= high:
            score += 0.15
        elif abs(step_count - (low + high) / 2) <= 3:
            score += 0.075
        weights_total += 0.15

        return score / weights_total if weights_total > 0 else 0.0

    # ------------------------------------------------------------------
    # .5: IO Contract Compatibility
    # ------------------------------------------------------------------

    async def _phase15_io_contract(
        self,
        request: SearchRequest,
        candidates: List[MatchCandidate],
    ) -> None:
        """Score IO contract compatibility between request and candidates.

        Mutates candidates in-place with updated io_score.
        """
        if not request.io_schema:
            # No IO schema in request — leave all at neutral 0.5
            return

        for c in candidates:
            c.io_score = await self._score_io_compatibility(c.entity_id, request)

    async def _score_io_compatibility(self, entity_id: UUID, request: SearchRequest) -> float:
        """Score how well an entity's IO contract matches the request."""
        if not request.io_schema:
            return 0.5  # Neutral

        # We need the entity's io_contract. On an AsyncSession, Session.get is a
        # coroutine and must be awaited (already-loaded rows resolve from the
        # identity map without a round-trip).
        try:
            from src.ai.models import HierarchicalEntity
            entity = await self.db.get(HierarchicalEntity, entity_id)
            if not entity:
                return 0.5
        except Exception:
            return 0.5

        entity_io = entity.io_contract or {}
        entity_input = entity_io.get("input_schema", {}).get("properties", {})
        entity_output = entity_io.get("output_schema", {}).get("properties", {})

        required_input = request.io_schema.get("input", {}).get("properties", {})
        required_output = request.io_schema.get("output", {}).get("properties", {})

        # Check if entity can accept the required input fields
        if required_input:
            input_coverage = len(
                set(required_input.keys()) & set(entity_input.keys())
            ) / len(required_input)
        else:
            input_coverage = 0.5  # Neutral

        # Check if entity produces the required output fields
        if required_output:
            output_coverage = len(
                set(required_output.keys()) & set(entity_output.keys())
            ) / len(required_output)
        else:
            output_coverage = 0.5  # Neutral

        return (input_coverage + output_coverage) / 2

    # ------------------------------------------------------------------
    # Semantic Intent Match (LLM-powered)
    # ------------------------------------------------------------------

    async def _phase2_semantic(
        self,
        request: SearchRequest,
        candidates: List[MatchCandidate],
    ) -> List[MatchCandidate]:
        """LLM-powered semantic scoring of structural candidates."""
        if not candidates:
            return []

        try:
            from src.ai.llm.router import LLMRouter

            llm = LLMRouter(db=self.db, company_id=self.company_id)

            # Build comparison prompt
            entity_summaries = []
            for i, c in enumerate(candidates):
                entity = await self._load_entity(c.entity_id)
                if not entity:
                    continue

                identity = entity.identity or {}
                system_prompt = identity.get("system_prompt", "")[:300] if isinstance(identity, dict) else ""

                entity_summaries.append({
                    "index": i,
                    "name": c.entity_name,
                    "type": c.entity_type,
                    "description": (entity.description or "")[:300],
                    "goal": (entity.goal or "")[:200],
                    "system_prompt_preview": system_prompt,
                    "tools": c.tool_overlap + c.missing_tools,
                    "structural_score": c.structural_score,
                })

            if not entity_summaries:
                return candidates

            prompt = (
                f"Score how well each existing agent matches this requirement.\n\n"
                f"REQUIREMENT:\n"
                f"  Intent: {request.intent}\n"
                f"  Required tools: {request.required_tools}\n"
                f"  Preferred type: {request.preferred_type or 'any'}\n"
                f"  Complexity: {request.complexity_class}\n\n"
                f"EXISTING AGENTS:\n"
                f"{json.dumps(entity_summaries, indent=2, default=str)}\n\n"
                f"For each agent, provide a semantic_score (0.0-1.0) and brief rationale.\n"
                f"Respond with JSON array: "
                f'[{{"index": 0, "semantic_score": 0.85, "rationale": "..."}}]'
            )

            result = await llm.call_llm(
                task_type="thinking",
                system_prompt=(
                    "You are an agent registry curator. Score how well existing agents "
                    "match a user's requirement. Focus on behavioral alignment, not just "
                    "surface-level description similarity. Be conservative — only score >0.8 "
                    "if the agent can handle the requirement with minimal or no modification."
                ),
                user_prompt=prompt,
                temperature=0.1,
                max_tokens=1000,
            )

            # Parse LLM scores
            scores = self._parse_semantic_scores(result.output)

            for score_entry in scores:
                idx = score_entry.get("index", -1)
                if 0 <= idx < len(candidates):
                    candidates[idx].semantic_score = score_entry.get("semantic_score", 0.0)
                    candidates[idx].rationale = score_entry.get("rationale", "")

        except Exception as e:
            logger.warning(f"Phase 2 semantic scoring failed: {e}. Using structural scores only.")

        return candidates

    # ------------------------------------------------------------------
    # .5: Execution Trace Analysis
    # ------------------------------------------------------------------

    async def _phase25_execution_traces(
        self,
        candidates: List[MatchCandidate],
    ) -> None:
        """Score candidates based on historical execution performance.

        Mutates candidates in-place with updated execution_score.
        Uses the existing get_execution_traces() method that was previously unused.
        """
        for c in candidates:
            try:
                c.execution_score = await self._score_execution_history(c.entity_id)
            except Exception as e:
                logger.debug(f"Execution trace scoring failed for {c.entity_id}: {e}")
                c.execution_score = 0.5  # Neutral on error

    async def _score_execution_history(self, entity_id: UUID) -> float:
        """Score an entity based on its execution history.

        Factors:
          - Success rate (60% weight): ratio of COMPLETED runs
          - Cost efficiency (20% weight): lower avg cost → higher score
          - Recency (20% weight): recent successful runs → higher score
        """
        traces = await self.get_execution_traces(entity_id, limit=10)
        if not traces:
            return 0.5  # No data — neutral

        # Success rate
        completed = sum(1 for t in traces if t["status"] in ("COMPLETED", "completed"))
        success_rate = completed / len(traces)

        # Cost efficiency (cap at $2.00 for normalization)
        avg_cost = sum(t["cost_usd"] for t in traces) / len(traces)
        cost_score = 1.0 - min(avg_cost / 2.0, 1.0)

        # Recency: weight recent executions higher
        # Score based on whether the most recent run was within the last 7 days
        recency_score = 0.5  # default
        try:
            if traces[0].get("created_at"):
                most_recent = datetime.fromisoformat(traces[0]["created_at"].replace("Z", "+00:00"))
                days_ago = (datetime.now(timezone.utc) - most_recent).days
                if days_ago <= 1:
                    recency_score = 1.0
                elif days_ago <= 7:
                    recency_score = 0.8
                elif days_ago <= 30:
                    recency_score = 0.6
                else:
                    recency_score = 0.3
        except Exception:
            pass

        return float(success_rate * 0.6 + cost_score * 0.2 + recency_score * 0.2)

    # ------------------------------------------------------------------
    # Classification
    # ------------------------------------------------------------------

    def _classify_candidates(
        self,
        candidates: List[MatchCandidate],
        request: SearchRequest,
    ) -> List[MatchCandidate]:
        """Classify each candidate as REUSE, ADAPT, COMPOSE, or CREATE."""
        for c in candidates:
            if c.combined_score >= self.REUSE_THRESHOLD:
                c.match_type = MatchType.REUSE
            elif c.combined_score >= self.ADAPT_THRESHOLD:
                c.match_type = MatchType.ADAPT
                # Generate diff spec for adaptation
                c.diff_spec = self._generate_diff_spec(c, request)
            elif c.combined_score >= self.COMPOSE_THRESHOLD:
                c.match_type = MatchType.COMPOSE
            else:
                c.match_type = MatchType.CREATE

        return candidates

    def _generate_diff_spec(
        self,
        candidate: MatchCandidate,
        request: SearchRequest,
    ) -> Dict[str, Any]:
        """Generate a diff spec for adapting an existing agent."""
        diff: dict[str, Any] = {}

        if candidate.missing_tools:
            diff["add_tools"] = candidate.missing_tools

        if request.preferred_type and candidate.entity_type != request.preferred_type:
            diff["change_type"] = request.preferred_type

        # Suggest prompt modification if semantic score is moderate
        if candidate.semantic_score < 0.7:
            diff["modify_system_prompt"] = True
            diff["prompt_hint"] = request.intent

        return diff

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _extract_tools(self, entity: Any) -> List[str]:
        """Extract tool_id list from entity capabilities."""
        caps = entity.capabilities
        if not caps or not isinstance(caps, dict):
            return []
        tools = caps.get("tools", [])
        return [
            str(t.get("tool_id") or t.get("name") or "")
            for t in tools
            if isinstance(t, dict)
        ]

    def _count_steps(self, entity: Any) -> int:
        """Count steps in entity's planning."""
        planning = entity.planning
        if not planning or not isinstance(planning, dict):
            return 1
        static_plan = planning.get("static_plan", {})
        if not static_plan or not isinstance(static_plan, dict):
            return 1
        return len(static_plan.get("steps", []))

    async def _load_entity(self, entity_id: UUID) -> Any:
        """Load a single entity by ID."""
        from src.ai.models import HierarchicalEntity
        result = await self.db.execute(
            select(HierarchicalEntity).where(HierarchicalEntity.id == entity_id)
        )
        return result.scalar_one_or_none()

    def _parse_semantic_scores(self, output: str) -> List[Dict[str, Any]]:
        """Parse LLM semantic scoring output."""
        try:
            text = output
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0]
            elif "[" in text:
                text = text[text.find("["):text.rfind("]") + 1]
            return cast("list[dict[str, Any]]", json.loads(text))
        except Exception:
            logger.debug(f"Failed to parse semantic scores: {output[:200]}")
            return []

    # ------------------------------------------------------------------
    # Execution Trace Analysis
    # ------------------------------------------------------------------

    async def get_execution_traces(
        self,
        entity_id: UUID,
        limit: int = 5,
    ) -> List[Dict[str, Any]]:
        """Load recent execution traces for an entity.

        Provides ground-truth behavioral data for the Meta-Agent's
        REUSE decision quality.
        """
        from src.ai.models import ExecutionRun

        result = await self.db.execute(
            select(ExecutionRun).where(
                ExecutionRun.entity_id == entity_id,
                ExecutionRun.company_id == self.company_id,
                ExecutionRun.parent_run_id.is_(None),  # Top-level only
            ).order_by(ExecutionRun.created_at.desc()).limit(limit)
        )
        runs = result.scalars().all()

        return [
            {
                "run_id": str(r.id),
                "status": r.status,
                "input_preview": str(r.input_data)[:300] if r.input_data else "",
                "output_preview": str(r.result_data)[:300] if r.result_data else "",
                "cost_usd": float(r.total_cost_usd or 0),
                "execution_time_ms": r.execution_time_ms,
                "created_at": r.created_at.isoformat() if r.created_at else "",
            }
            for r in runs
        ]
