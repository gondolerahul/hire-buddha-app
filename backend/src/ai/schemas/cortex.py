"""
ai.schemas.cortex — host re-export shim.

The CORTEX DTOs (tree/node shapes, ``Provenance``, ``GoalNode``) moved into the
``cortex_memory`` package (Phase 12 `04` Stage B). This shim keeps the existing
``src.ai.schemas.cortex`` import path (and the ``from src.ai.schemas import *``
re-export) working; new code should import from ``cortex_memory`` directly.
"""
from __future__ import annotations

from cortex_memory.dtos import (
    DEFAULT_TRUST_BY_SOURCE,
    CortexCheckpointCreate,
    CortexNodeContentResponse,
    CortexNodeCreate,
    CortexNodeDetailResponse,
    CortexNodeSummary,
    CortexRecurseRequest,
    CortexTreeCreate,
    CortexTreeListResponse,
    CortexTreeResponse,
    CortexViewportResponse,
    GoalNode,
    Provenance,
    SourceType,
)

__all__ = [
    "CortexTreeCreate",
    "CortexTreeResponse",
    "CortexTreeListResponse",
    "CortexNodeSummary",
    "CortexViewportResponse",
    "CortexNodeContentResponse",
    "CortexNodeCreate",
    "CortexCheckpointCreate",
    "CortexRecurseRequest",
    "CortexNodeDetailResponse",
    "GoalNode",
    "Provenance",
    "SourceType",
    "DEFAULT_TRUST_BY_SOURCE",
]
