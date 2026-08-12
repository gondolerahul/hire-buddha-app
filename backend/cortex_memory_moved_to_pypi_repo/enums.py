"""
cortex_memory.enums — CORTEX domain enums.

Moved out of the host (Phase 12 `04`). These are the canonical definitions; the
host re-exports ``CortexNodeType`` (and the others, via ``cortex_models``) for
backward compatibility.
"""
from __future__ import annotations

import enum


class CortexTreeStatus(str, enum.Enum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    COMPLETE = "complete"
    ARCHIVED = "archived"


class CortexNodeType(str, enum.Enum):
    # --- v1 types ---
    ROOT = "root"
    KNOWLEDGE = "knowledge"       # Ingested from a document (PageIndex-derived)
    FINDING = "finding"           # Written by the agent during execution
    TASK = "task"                 # A sub-task to be executed
    OUTPUT = "output"             # A section of the output document
    CHECKPOINT = "checkpoint"     # A compacted state snapshot
    # --- v2 types ---
    GROUP = "group"               # Re-clustering group container
    DOCUMENT = "document"         # Represents an ingested document
    SECTION = "section"           # A section/chapter within a document
    CHUNK = "chunk"               # Leaf-level text chunk with embedding
    OBSERVATION = "observation"   # Experience: specific observation
    PATTERN = "pattern"           # Experience: recurring pattern
    SUGGESTION = "suggestion"     # Experience: suggested approach
    INSTRUCTION = "instruction"   # Intelligence: distilled actionable rule
    STRATEGY = "strategy"         # Intelligence: high-level strategic approach
    PREFERENCE = "preference"     # Intelligence: user/entity preference
    EPISODE = "episode"           # Episodic: single execution episode record
    EPISODE_GROUP = "episode_group"  # Episodic: grouped episodes
    # --- agent-loop types ---
    SNAPSHOT = "snapshot"         # AgentState snapshot written each loop iteration
    HEALTH_RECORD = "health_record"  # Critic StepHealthRecord
    HEALTH_ROOT = "health_root"   # Container node for a run's health records


class CortexNodeStatus(str, enum.Enum):
    PENDING = "pending"
    ACTIVE = "active"
    COMPLETE = "complete"
    SUMMARISED = "summarised"


class MemoryDomain(str, enum.Enum):
    """Which memory domain a CORTEX tree belongs to."""
    KNOWLEDGE = "knowledge"
    EXPERIENCE = "experience"
    INTELLIGENCE = "intelligence"
    EPISODIC = "episodic"


class ScopeLevel(str, enum.Enum):
    """Hierarchical scope level for memory inheritance."""
    APP = "app"             # L0: Platform-wide
    PARTNER = "partner"     # L1: Partner organization
    TENANT = "tenant"       # L2: Company/tenant
    USER = "user"           # L3: End-user
    ENTITY = "entity"       # L4: Agent/entity
    RUNTIME = "runtime"     # L5: Single execution run


__all__ = [
    "CortexTreeStatus",
    "CortexNodeType",
    "CortexNodeStatus",
    "MemoryDomain",
    "ScopeLevel",
]
