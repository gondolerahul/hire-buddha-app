"""
ai.core.exceptions — Unified error taxonomy for the AI engine.

All agent-specific exceptions inherit from AgentError, enabling
structured error handling in the execution loop.

Extracted from worker.py during Phase 10A restructuring.
"""
from typing import Any, Optional


class AgentError(Exception):
    """Base exception for all agent-related errors."""
    pass


class UncertaintySignal(AgentError):
    """
    Raised when the LLM explicitly signals it cannot proceed without
    clarification.  The LLM must include the following JSON block anywhere
    in its response to trigger this path:

        {"needs_clarification": true, "question": "...", "confidence": 0.3}

    Attributes:
        question:      The clarifying question the agent wants to ask.
        confidence:    Estimated confidence in completing the task without input (0–1).
        alternatives:  Optional list of alternative interpretations the LLM suggests.
    """
    def __init__(self, question: str, confidence: float = 0.0, alternatives: Optional[list[Any]] = None) -> None:
        super().__init__(question)
        self.question = question
        self.confidence = confidence
        self.alternatives = alternatives or []


class GoalDriftError(AgentError):
    """Step output misaligned with entity goal."""
    pass


class CreditExhaustedError(AgentError):
    """Execution stopped due to insufficient credits."""
    pass


class BudgetExhaustedError(AgentError):
    """Execution stopped because the run reached the entity's
    ``governance.max_cost_usd`` ceiling.

    Distinct from ``CreditExhaustedError`` (company-wide credit balance): this is
    a *per-entity* cost cap enforced between steps on the legacy run loop, so a
    child entity can't blow many multiples past its own configured budget. The
    run finalises as ``PARTIAL_COMPLETE`` (not FAILED) — work done up to the cap
    is kept and billed; the cap simply stops further spend.
    """

    def __init__(self, message: str, spent_usd: float = 0.0, cap_usd: float = 0.0):
        self.spent_usd = spent_usd
        self.cap_usd = cap_usd
        super().__init__(message)


class ParallelStepError(AgentError):
    """One or more parallel steps failed."""
    def __init__(self, failures: list[Any]) -> None:
        self.failures = failures
        msgs = [f"{sid}: {err}" for sid, err in failures]
        super().__init__(f"{len(failures)} parallel step(s) failed: {'; '.join(msgs)}")


class MetaAgentAbort(AgentError):
    """Meta-agent recommended aborting execution."""
    pass


class StepTimeoutError(AgentError):
    """Step exceeded its configured timeout."""
    def __init__(self, step_name: str, timeout_ms: int):
        self.step_name = step_name
        self.timeout_ms = timeout_ms
        super().__init__(f"Step '{step_name}' exceeded {timeout_ms}ms timeout")


class EntityNotFoundError(AgentError):
    """Referenced entity does not exist or has been deleted."""
    def __init__(self, entity_id: Any, context: str = "") -> None:
        self.entity_id = entity_id
        super().__init__(f"Entity {entity_id} not found. {context}")


class PlanningError(AgentError):
    """Plan generation or reconciliation failed."""
    pass


class CortexError(AgentError):
    """CORTEX memory operation failed."""
    pass


class ToolExecutionError(AgentError):
    """Tool execution failed."""
    def __init__(self, tool_name: str, error: str):
        self.tool_name = tool_name
        super().__init__(f"Tool '{tool_name}' failed: {error}")
