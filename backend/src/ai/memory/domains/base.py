"""
ai.memory.domains.base — host re-export shim.

``DomainTreeBase`` + the retrieval-weight registry moved into the
host-independent ``cortex_memory`` package (Phase 12 `04`). This shim keeps the
``src.ai.memory.domains.base`` import path working.
"""
from __future__ import annotations

from cortex_memory.domains import (
    DEFAULT_DOMAIN_WEIGHTS,
    DomainItem,
    DomainTreeBase,
    EpisodicWeights,
    ExperienceWeights,
    IntelligenceWeights,
    KnowledgeWeights,
    score_signals,
)

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
