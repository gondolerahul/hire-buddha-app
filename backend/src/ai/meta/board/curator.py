"""
ai.meta.board.curator — Role 2: REUSE / ADAPT / COMPOSE / CREATE decision.

Wraps :class:`RegistrySearchService` + :class:`AntiSprawlGuard` so the
Meta-Agent never blindly creates a near-duplicate. Outputs a typed
:class:`CuratorDecision` which the Architect consumes.

Side effects:
  * Records the decision in the company's MetaIntelligenceTree so the
    Promoter can later annotate it with the eventual outcome (whether
    the produced entity ended up promoted to ACTIVE or rejected).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional, cast
from uuid import UUID

logger = logging.getLogger(__name__)


@dataclass
class CuratorDecision:
    decision: str                                  # REUSE / ADAPT / COMPOSE / CREATE
    rationale: str = ""
    candidates: list[dict[str, Any]] = field(default_factory=list)
    top_candidate_id: Optional[str] = None
    decision_node_id: Optional[str] = None         # MetaIntelligenceTree audit row

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "rationale": self.rationale,
            "candidates": list(self.candidates),
            "top_candidate_id": self.top_candidate_id,
            "decision_node_id": self.decision_node_id,
        }


class Curator:
    """Glues RegistrySearch + AntiSprawl + MetaIntelligenceTree audit."""

    def __init__(self, db: Any, company_id: UUID):
        self.db = db
        self.company_id = company_id

    async def decide(self, spec: Any) -> CuratorDecision:
        spec_dict = self._normalise_spec(spec)

        from src.ai.meta.registry_search_service import (
            RegistrySearchService,
            SearchRequest,
        )
        from src.ai.meta.anti_sprawl import AntiSprawlGuard
        from src.ai.meta.meta_intelligence_tree import MetaIntelligenceTree

        search = RegistrySearchService(self.db, self.company_id)
        sprawl = AntiSprawlGuard(self.db, self.company_id)
        meta = MetaIntelligenceTree(self.db, self.company_id)

        rec: dict[str, Any] = {}
        try:
            rec = await search.recommend(SearchRequest(
                intent=spec_dict.get("description", ""),
                required_tools=list(spec_dict.get("required_tools") or []),
                preferred_type=spec_dict.get("preferred_type"),
                tags=list(spec_dict.get("tags") or []),
            ))
        except Exception as exc:                                            # noqa: BLE001
            logger.warning("RegistrySearch failed; defaulting to CREATE: %s", exc)
            rec = {"decision": "CREATE", "candidates": [], "rationale": str(exc)}

        decision = str(rec.get("decision", "CREATE")).upper()
        candidates = list(rec.get("candidates") or [])
        rationale = str(rec.get("rationale", ""))

        # Anti-sprawl gate: only on CREATE.
        if decision == "CREATE":
            try:
                # Daily-creation hard gate (company-scoped). AntiSprawlGuard
                # owns the semantic/limit split: check_creation_allowed is the
                # per-day count gate; the semantic near-duplicate check is the
                # sibling call below.
                allow = await sprawl.check_creation_allowed()
                if isinstance(allow, dict) and not allow.get("allowed", True):
                    if candidates:
                        decision = "ADAPT"
                        rationale = (
                            f"AntiSprawl declined CREATE ({allow.get('message','')}); "
                            f"adapting top candidate instead."
                        )
            except Exception:                                               # pragma: no cover
                pass
            try:
                dup = await sprawl.check_semantic_duplicate(
                    description=spec_dict.get("description", ""),
                    required_tools=list(spec_dict.get("required_tools") or []),
                    preferred_type=spec_dict.get("preferred_type"),
                )
                if isinstance(dup, dict) and dup.get("is_duplicate"):
                    decision = "ADAPT" if candidates else decision
                    rationale = (
                        f"Semantic duplicate found: {dup.get('similar_id','?')}; "
                        f"adapting."
                    )
            except Exception:                                               # pragma: no cover
                pass

        top_candidate_id = None
        if candidates:
            head = candidates[0]
            if isinstance(head, dict):
                top_candidate_id = str(head.get("entity_id") or head.get("id") or "") or None

        decision_node_id = None
        try:
            decision_node_id = await meta.record_curator_decision(
                decision=decision,
                candidates=candidates[:3],
                rationale=rationale,
                outcome=None,
            )
        except Exception:                                                   # pragma: no cover
            logger.debug("MetaIntelligenceTree audit write failed; continuing")

        return CuratorDecision(
            decision=decision,
            rationale=rationale,
            candidates=candidates,
            top_candidate_id=top_candidate_id,
            decision_node_id=str(decision_node_id) if decision_node_id else None,
        )

    @staticmethod
    def _normalise_spec(spec: Any) -> dict[str, Any]:
        if isinstance(spec, dict):
            return spec
        # Spec dataclass support
        if hasattr(spec, "to_dict"):
            return cast("dict[str, Any]", spec.to_dict())
        return {"description": str(spec)}


__all__ = ["Curator", "CuratorDecision"]
