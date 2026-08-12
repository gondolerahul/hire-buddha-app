"""
cortex_memory — the CORTEX hierarchical-memory engine, extracted as a
host-independent package (Phase 12 track `04`).

Boundary rule (the whole point of the extraction): **this package never
imports the host** (`src.ai.*`). The host depends on the package and injects
its concerns — LLM calls, embeddings, usage metering, run lookups — through the
Protocols in :mod:`cortex_memory.providers`. A host adapter (the thin
``cortex_bridge`` that stays in ``src/ai/memory``) implements those Protocols.

Stage-B status: the data layer (own ``Base`` + ORM models + enums + DTOs) and
the provider boundary live here. The CORTEX services move in next; see
``README.md``.
"""
from __future__ import annotations

from cortex_memory.db import Base, metadata
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
from cortex_memory.enums import (
    CortexNodeStatus,
    CortexNodeType,
    CortexTreeStatus,
    MemoryDomain,
    ScopeLevel,
)
from cortex_memory.assembly import MemoryAssemblyResult, MemoryAssemblyService
from cortex_memory.dreaming import DreamingEngine
from cortex_memory.episodic_tree import EpisodicTreeService
from cortex_memory.experience_tree import ExperienceTreeService
from cortex_memory.graph import SemanticGraphService
from cortex_memory.intelligence_tree import IntelligenceTreeService
from cortex_memory.knowledge_tree import KnowledgeTreeService
from cortex_memory.models import CortexEdge, CortexNode, CortexTree
from cortex_memory.prompts import CORTEX_OPS_HELP
from cortex_memory.service import (
    CheckpointData,
    CortexService,
    NodeContent,
    NodeSummaryDTO,
    Viewport,
)
from cortex_memory.providers import (
    EmbeddingProvider,
    EmbeddingResult,
    LLMProvider,
    LLMResult,
    RunfRef,
    RunRef,
    RunRegistry,
    UsageReporter,
)
from cortex_memory.scope_policy import ScopePolicy, ScopeViolation

__version__ = "0.1.0"

__all__ = [
    # data layer
    "Base",
    "metadata",
    "CortexTree",
    "CortexNode",
    "CortexEdge",
    "CortexTreeStatus",
    "CortexNodeType",
    "CortexNodeStatus",
    "MemoryDomain",
    "ScopeLevel",
    # DTOs
    "Provenance",
    "SourceType",
    "DEFAULT_TRUST_BY_SOURCE",
    "GoalNode",
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
    # providers
    "LLMProvider",
    "LLMResult",
    "EmbeddingProvider",
    "EmbeddingResult",
    "UsageReporter",
    "RunRegistry",
    "RunRef",
    "RunfRef",
    # service
    "CortexService",
    "SemanticGraphService",
    "KnowledgeTreeService",
    "EpisodicTreeService",
    "ExperienceTreeService",
    "IntelligenceTreeService",
    "DreamingEngine",
    "MemoryAssemblyService",
    "MemoryAssemblyResult",
    "Viewport",
    "NodeSummaryDTO",
    "NodeContent",
    "CheckpointData",
    "CORTEX_OPS_HELP",
    # tree primitives
    "ScopePolicy",
    "ScopeViolation",
    "__version__",
]
