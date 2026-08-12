"""schemas/capabilities.py — Tools, memory, context, meta-cognition.

Covers every "what the agent can do" config: tool refs/defs, the memory
configuration (CORTEX vs legacy), context engineering, and the three-tier
meta-cognition toggles.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from src.ai.schemas.enums import ContextSourceType

__all__ = [
    "ToolAuth",
    "ToolDefinition",
    "ToolReference",
    "CortexMemoryConfig",
    "MemoryConfig",
    "ContextSource",
    "ContextEngineering",
    "MetaCognitionConfig",
    "Capabilities",
]


class ToolAuth(BaseModel):
    type: str  # NONE | API_KEY | OAUTH2 | SERVICE_ACCOUNT
    credentials_ref: Optional[str] = None


class ToolDefinition(BaseModel):
    tool_id: str
    name: Optional[str] = None
    description: Optional[str] = None
    provider: Optional[str] = None
    authentication: Optional[ToolAuth] = None
    function_schema: Optional[Dict[str, Any]] = None
    # P3.1 — Extended permission model (OpenCode-inspired)
    access_level: str = "READ"   # READ | WRITE | EXECUTE (legacy single-string, kept for compat)
    permissions: List[str] = []  # e.g. ["read", "write", "network", "storage", "execute"]
    sandbox_mode: bool = False
    max_execution_seconds: int = 30      # Per-call timeout enforcement
    rate_limit_per_run: Optional[int] = None  # Max calls per ExecutionRun (None = unlimited)


class ToolReference(BaseModel):
    """Simple tool reference (just tool_id)."""
    tool_id: str


class CortexMemoryConfig(BaseModel):
    """Configuration for CORTEX cognitive tree memory mode."""
    max_children: int = 12           # MAX_CHILDREN invariant per node
    page_size_tokens: int = 8000     # Max tokens per content page
    context_budget_pct: int = 40     # % of context window for root run budget
    auto_checkpoint: bool = True     # Auto-checkpoint when budget exceeded
    resume_enabled: bool = True      # Enable resume from cursor


class MemoryConfig(BaseModel):
    """Memory configuration aligned with CORTEX memory system."""
    enabled: bool = False
    mode: str = "STANDARD"  # STANDARD | CORTEX
    # Memory scope controls what gets injected into runtime prompts
    # FULL = episodic + semantic (legacy default)
    # RUN_SCOPED = only current run's episodic data
    # INTELLIGENCE_ONLY = only distilled intelligence/learnings + failure patterns
    # NONE = no memory injection at all
    memory_scope: str = "FULL"  # FULL | RUN_SCOPED | INTELLIGENCE_ONLY | NONE
    # STANDARD mode: episodic + semantic memory
    episodic_memory_count: int = 10  # How many past episodes to inject
    semantic_search_enabled: bool = True  # pgvector document search
    semantic_top_k: int = 5
    # CORTEX mode: cognitive tree for unbounded context
    cortex_config: Optional[CortexMemoryConfig] = None


class ContextSource(BaseModel):
    """A design-time or runtime context source attached to an entity."""
    source_type: ContextSourceType
    reference_id: Optional[str] = None   # Artifact ID, tree ID, etc.
    query: Optional[str] = None          # For KB/DB: semantic search query
    description: Optional[str] = None    # Human-readable label
    # Display metadata (populated by frontend for UI display, not used by worker)
    file_name: Optional[str] = None      # Original filename
    file_type: Optional[str] = None      # MIME type or extension
    file_size: Optional[int] = None      # Size in bytes
    tree_status: Optional[str] = None    # For CORTEX trees: active/complete/etc
    tree_node_count: Optional[int] = None  # For CORTEX trees: total nodes


class ContextEngineering(BaseModel):
    """Context engineering configuration — CORTEX-native."""
    context_sources: List[ContextSource] = []   # Design-time context attachments
    inject_episodic_memory: bool = True          # Include recent interaction history
    inject_semantic_context: bool = True         # Include relevant doc chunks
    inject_cortex_viewport: bool = True          # Include CORTEX tree viewport
    no_truncation: bool = True                   # CORTEX handles unbounded contexts


class MetaCognitionConfig(BaseModel):
    """Controls meta-cognitive capabilities for this entity.

    Three tiers of meta-cognition, gated by entity type and governance:
      - Tier 1 (platform_awareness): Injects platform manifest summary into
        system prompt. Auto-enabled when dynamic_planning.enabled or
        reasoning_mode=REACT. Cost: ~2-4K tokens extra per prompt.
      - Tier 2 (registry_search): Auto-injects meta_registry_search tool.
        Lets agents discover existing entities mid-execution.
        Auto-enabled for AGENT and PROCESS types.
      - Tier 3 (self_modification): Auto-injects meta_entity_creator and
        meta_entity_executor tools. Lets agents create/adapt children at
        runtime. Auto-enabled for AGENT and PROCESS types. Requires HITL
        approval unless the entity is the dedicated Meta-Agent.
    """
    platform_awareness: bool = True     # Tier 1 (auto: dynamic_planning or REACT)
    registry_search: bool = False       # Tier 2 (auto: AGENT/PROCESS)
    self_modification: bool = False     # Tier 3 (auto: AGENT/PROCESS, requires HITL)
    max_runtime_creations: int = 3      # Tier 3: max entities created per execution run
    max_registry_searches: int = 5      # Tier 2: max searches per execution run


class Capabilities(BaseModel):
    tools: List[ToolReference] = []  # Accept simple tool references
    memory: MemoryConfig = MemoryConfig()
    context_engineering: ContextEngineering = ContextEngineering()
    meta_cognition: MetaCognitionConfig = MetaCognitionConfig()
