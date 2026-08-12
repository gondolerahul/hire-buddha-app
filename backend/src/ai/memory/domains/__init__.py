"""
ai.memory.domains — Phase 11 Track 6 domain-tree refactor.

Each memory domain (Knowledge, Episodic, Experience, Intelligence) is
a typed view over the CORTEX substrate. Track 6 extracts the 80%
boilerplate they share into :class:`DomainTreeBase` and codifies the
per-domain retrieval weights in one place.

The existing per-domain service classes (``KnowledgeTreeService``,
``EpisodicTreeService``, ``ExperienceTreeService``,
``IntelligenceTreeService``) continue to work unchanged; the base
class is **additive** — new code can subclass it for any future
domain, and the four legacy services can migrate incrementally
without breaking imports.
"""
from src.ai.memory.domains.base import (
    DEFAULT_DOMAIN_WEIGHTS,
    DomainItem,
    DomainTreeBase,
    KnowledgeWeights,
    EpisodicWeights,
    ExperienceWeights,
    IntelligenceWeights,
    score_signals,
)

__all__ = [
    "DomainTreeBase",
    "DomainItem",
    "DEFAULT_DOMAIN_WEIGHTS",
    "KnowledgeWeights",
    "EpisodicWeights",
    "ExperienceWeights",
    "IntelligenceWeights",
    "score_signals",
]
