"""
cortex_memory.domains — DomainTreeBase + retrieval-weight registry.

Each memory domain (Knowledge / Episodic / Experience / Intelligence) is a typed
view over the CORTEX substrate. This module captures three things:

  1. The *signal vector* every domain ranks against: ``semantic``, ``recency``,
     ``user_match``, ``success``.
  2. The per-domain **retrieval weights** (constants below).
  3. A pure ``score_signals`` helper that turns a signal dict into a single
     weighted score.

A self-contained tree primitive (no host dependency); moved out of the host
(Phase 12 `04`). The host re-exports it from ``ai.memory.domains``.
"""
from __future__ import annotations

import logging
from abc import ABC
from dataclasses import dataclass, field
from typing import Any, ClassVar, Optional
from uuid import UUID

logger = logging.getLogger(__name__)


_REQUIRED_SIGNALS = ("semantic", "recency", "user_match", "success")


# ---------------------------------------------------------------------------
# Canonical per-domain weights.
# ---------------------------------------------------------------------------


KnowledgeWeights: dict[str, float] = {
    "semantic": 1.0, "recency": 0.4, "user_match": 0.0, "success": 0.0,
}
ExperienceWeights: dict[str, float] = {
    "semantic": 0.7, "recency": 0.5, "user_match": 0.2, "success": 0.6,
}
IntelligenceWeights: dict[str, float] = {
    "semantic": 0.6, "recency": 0.3, "user_match": 0.0, "success": 0.0,
}
EpisodicWeights: dict[str, float] = {
    "semantic": 0.5, "recency": 0.7, "user_match": 0.6, "success": 0.5,
}

DEFAULT_DOMAIN_WEIGHTS: dict[str, dict[str, float]] = {
    "knowledge":    KnowledgeWeights,
    "experience":   ExperienceWeights,
    "intelligence": IntelligenceWeights,
    "episodic":     EpisodicWeights,
}


# ---------------------------------------------------------------------------
# Pure scoring helper
# ---------------------------------------------------------------------------


def score_signals(
    weights: dict[str, float],
    signals: dict[str, float],
) -> float:
    """Weighted average over the canonical signal vector.

    Missing signals are treated as 0; the denominator uses the declared weights
    (not the present signals) so domains that always want recency see
    partial-credit penalties when recency is missing. Returns 0.0 when the
    weight vector is all zero (defensive).
    """
    total_weight = sum(max(0.0, w) for w in weights.values())
    if total_weight <= 0:
        return 0.0
    accum = 0.0
    for key in _REQUIRED_SIGNALS:
        w = max(0.0, float(weights.get(key, 0.0)))
        s = max(0.0, float(signals.get(key, 0.0)))
        accum += w * s
    return accum / total_weight


# ---------------------------------------------------------------------------
# Typed retrieval result
# ---------------------------------------------------------------------------


@dataclass
class DomainItem:
    """One retrievable item from a domain tree (post-scoring)."""

    node_id: UUID
    title: str
    summary: Optional[str]
    domain: str
    score: float = 0.0
    signals: dict[str, float] = field(default_factory=dict)
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": str(self.node_id),
            "title": self.title,
            "summary": self.summary,
            "domain": self.domain,
            "score": self.score,
            "signals": dict(self.signals),
            "payload": dict(self.payload),
        }


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------


class DomainTreeBase(ABC):
    """Optional base for domain tree services. New domain code SHOULD subclass
    to inherit the retrieval-weight contract and the pure scorer."""

    DOMAIN: ClassVar[str] = "general"
    ROOT_TITLE: ClassVar[str] = "Tree"
    SECTIONS: ClassVar[dict[str, str]] = {}
    RETRIEVAL_WEIGHTS: ClassVar[dict[str, float]] = KnowledgeWeights

    def __init__(self, db: Any, company_id: UUID):
        self.db = db
        self.company_id = company_id

    async def ensure_tree(self, *, scope_id: UUID, scope_level: str) -> Any:    # pragma: no cover
        raise NotImplementedError

    async def ensure_section(self, tree: Any, section_type: str) -> Any:        # pragma: no cover
        raise NotImplementedError

    async def write_item(self, **kwargs: Any) -> Any:                           # pragma: no cover
        raise NotImplementedError

    async def find(
        self, *, tree: Any, query: str, top_k: int = 5,
        filters: Optional[dict[str, Any]] = None,
    ) -> list[DomainItem]:                                                      # pragma: no cover
        raise NotImplementedError

    def score(self, signals: dict[str, float]) -> float:
        return score_signals(self.RETRIEVAL_WEIGHTS, signals)


__all__ = [
    "DomainItem",
    "DomainTreeBase",
    "DEFAULT_DOMAIN_WEIGHTS",
    "KnowledgeWeights",
    "EpisodicWeights",
    "ExperienceWeights",
    "IntelligenceWeights",
    "score_signals",
]
