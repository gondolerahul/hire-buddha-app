"""
models.py — DEPRECATED back-compat shim (Phase 11 Track 1).

The ORM classes formerly defined here have moved to ``src.ai.orm.*``.
This module re-exports everything so existing
``from src.ai.models import HierarchicalEntity`` calls continue to work.

New code should import from the canonical location, e.g.
``from src.ai.orm.entity import HierarchicalEntity``.
"""
from __future__ import annotations

from src.ai.orm import (  # noqa: F401
    Document,
    DocumentChunk,
    EntityType,
    EpisodicMemory,
    ExecutionRun,
    HierarchicalEntity,
    HumanApproval,
    LLMInteractionLog,
    RunStatus,
    ToolInteractionLog,
    ToolRegistryEntry,
    UsageLog,
)

__all__ = [
    "HierarchicalEntity",
    "ExecutionRun",
    "LLMInteractionLog",
    "ToolInteractionLog",
    "HumanApproval",
    "EpisodicMemory",
    "Document",
    "DocumentChunk",
    "UsageLog",
    "ToolRegistryEntry",
    "EntityType",
    "RunStatus",
]
