"""schemas/enums.py — All Pydantic str-Enums used across the AI kernel."""
from __future__ import annotations

import logging
from enum import Enum

__all__ = [
    "EntityType",
    "RunStatus",
    "EntityStatus",
    "RelationshipType",
    "ReasoningMode",
    "DEPRECATED_REASONING_MODES",
    "BackoffStrategy",
    "ValidationType",
    "HITLTriggerType",
    "StepType",
    "ExecutionMode",
    "ContextSourceType",
    "CortexTreeStatus",
    "CortexNodeType",
    "VALID_TRANSITIONS",
    "validate_transition",
]


class EntityType(str, Enum):
    ACTION = "ACTION"
    SKILL = "SKILL"
    AGENT = "AGENT"
    PROCESS = "PROCESS"


class RunStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"                      # Waiting for HITL approval
    RESUMING = "RESUMING"                  # Resuming from checkpoint
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    PARTIAL_COMPLETE = "PARTIAL_COMPLETE"  # Some steps OK, others failed
    REPAIRING = "REPAIRING"
    REFINING = "REFINING"                  # Selective re-execution with user feedback
    CANCELLED = "CANCELLED"                # Operator-cancelled mid-flight (terminal)
    WAITING_ON_CHILDREN = "WAITING_ON_CHILDREN"  # Suspended; child runs in flight


# Execution state machine — valid transitions
VALID_TRANSITIONS: dict[str, set[str]] = {
    "PENDING": {"RUNNING", "REFINING", "CANCELLED"},
    "RUNNING": {"PAUSED", "COMPLETED", "FAILED", "PARTIAL_COMPLETE",
                "CANCELLED", "WAITING_ON_CHILDREN"},
    "PAUSED": {"RUNNING", "RESUMING", "FAILED", "CANCELLED"},
    "RESUMING": {"RUNNING", "FAILED", "CANCELLED"},
    "PARTIAL_COMPLETE": {"RUNNING", "COMPLETED", "FAILED"},
    "REPAIRING": {"RUNNING", "FAILED"},
    "REFINING": {"RUNNING", "COMPLETED", "FAILED"},
    # Async child dispatch: a suspended parent resumes (RESUMING → RUNNING) once
    # its children are terminal, or fails/cancels out of the wait.
    "WAITING_ON_CHILDREN": {"RESUMING", "RUNNING", "FAILED", "CANCELLED"},
}


def validate_transition(current: str, target: str) -> bool:
    """Check if a status transition is valid. Logs a warning for invalid ones (lenient mode)."""
    allowed = VALID_TRANSITIONS.get(current, set())
    if target not in allowed:
        logging.getLogger(__name__).warning(
            f"Invalid state transition: {current} → {target} "
            f"(allowed: {allowed or 'none'})"
        )
        return False
    return True


class EntityStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    DEPRECATED = "DEPRECATED"
    ARCHIVED = "ARCHIVED"
    DELETED = "DELETED"  # Soft-deleted — hidden from UI, preserved for billing FK integrity


class RelationshipType(str, Enum):
    SEQUENTIAL = "SEQUENTIAL"
    PARALLEL = "PARALLEL"
    CONDITIONAL = "CONDITIONAL"


class ReasoningMode(str, Enum):
    """Per-entity reasoning mode for THOUGHT/ACTION steps.

    D-3 (Phase 12): REACT and CHAIN_OF_THOUGHT are the supported modes.

    * REFLECTION is **deprecated** — the AgentLoop's per-iteration
      ``Reflector`` (plus the post-critic + corrective-retry path) now
      covers in-loop self-correction, so a separate per-step reflection
      mode double-bills. Entities still set to REFLECTION keep working
      (with a deprecation warning) until the data migration runs.
    * TREE_OF_THOUGHTS is **deprecated** as a per-entity mode — its
      multi-candidate "debate" value is being reframed as a
      Strategist-selectable ``DebateExecutor`` (per-step, not per-entity).

    Use :data:`DEPRECATED_REASONING_MODES` to detect the deprecated set.
    """
    REACT = "REACT"
    CHAIN_OF_THOUGHT = "CHAIN_OF_THOUGHT"
    REFLECTION = "REFLECTION"            # deprecated — see class docstring (D-3)
    TREE_OF_THOUGHTS = "TREE_OF_THOUGHTS"  # deprecated — see class docstring (D-3)


# D-3: modes retained for backward compatibility but no longer recommended.
# The dispatch in step_executor emits a deprecation warning when these are
# used; new entities should use REACT (tool-using) or CHAIN_OF_THOUGHT.
DEPRECATED_REASONING_MODES: frozenset[str] = frozenset({
    ReasoningMode.REFLECTION.value,
    ReasoningMode.TREE_OF_THOUGHTS.value,
})


class BackoffStrategy(str, Enum):
    LINEAR = "LINEAR"
    EXPONENTIAL = "EXPONENTIAL"
    NONE = "NONE"


class ValidationType(str, Enum):
    REGEX = "REGEX"
    SCHEMA = "SCHEMA"
    LLM_JUDGE = "LLM_JUDGE"
    FUNCTION = "FUNCTION"


class HITLTriggerType(str, Enum):
    """Trigger types for Human-in-the-Loop checkpoints."""
    BEFORE_STEP = "BEFORE_STEP"          # Pause before a specific step executes
    AFTER_STEP = "AFTER_STEP"            # Pause after a specific step completes
    COST_THRESHOLD = "COST_THRESHOLD"    # Pause when execution cost exceeds threshold
    TOOL_CALL = "TOOL_CALL"              # Pause before a specific tool is called
    CUSTOM = "CUSTOM"                    # Custom expression-based trigger


class StepType(str, Enum):
    THOUGHT = "THOUGHT"
    ACTION = "ACTION"
    TOOL_CALL = "TOOL_CALL"
    CHILD_ENTITY_INVOCATION = "CHILD_ENTITY_INVOCATION"
    # CORTEX step types
    NAVIGATE = "NAVIGATE"
    READ = "READ"
    WRITE = "WRITE"
    RECURSE = "RECURSE"
    AWAIT_CHILDREN = "AWAIT_CHILDREN"


class ExecutionMode(str, Enum):
    """Phase 5: Execution strategy for entities."""
    STANDARD = "STANDARD"      # Static plan-execute
    AUTONOMOUS = "AUTONOMOUS"  # Goal-centric with self-reflection


class ContextSourceType(str, Enum):
    DOCUMENT = "DOCUMENT"              # Design-time uploaded document
    KNOWLEDGE_BASE = "KNOWLEDGE_BASE"  # Existing tenant document collection
    CORTEX_TREE = "CORTEX_TREE"        # Previous CORTEX tree from any entity
    DB_RECORDS = "DB_RECORDS"          # Database records query


class CortexTreeStatus(str, Enum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    COMPLETE = "complete"
    ARCHIVED = "archived"


# CortexNodeType is unified with the cortex_memory package's canonical enum
# (Phase 12 `04`). The host's previous reduced copy is replaced by a re-export
# so the ORM and the schemas layer share one type.
from cortex_memory.enums import CortexNodeType  # noqa: E402,F401
