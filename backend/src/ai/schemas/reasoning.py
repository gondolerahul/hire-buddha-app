"""schemas/reasoning.py — LogicGate and its constituent reasoning DTOs."""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel

from src.ai.schemas.enums import (
    BackoffStrategy,
    ReasoningMode,
    ValidationType,
)
from src.ai.schemas.prompts import DEFAULT_REVIEW_SYSTEM_PROMPT

__all__ = [
    "ReasoningConfig",
    "RetryPolicy",
    "SuccessCriterion",
    "ReviewMechanism",
    "ContextPolicy",
    "LogicGate",
]


class ReasoningConfig(BaseModel):
    task_type: str = "text_generation"
    model_provider: Optional[str] = None
    model_name: Optional[str] = None
    model_version: Optional[str] = None
    temperature: float = 0.7
    top_p: float = 1.0
    max_tokens: Optional[int] = None
    reasoning_mode: ReasoningMode = ReasoningMode.REACT
    # Autonomous loop configuration
    execution_mode: str = "STANDARD"  # STANDARD | AUTONOMOUS
    goal_validation_interval: int = 2       # Validate goal every N steps
    confidence_threshold: float = 0.85      # Early-exit if score > this * 100
    max_replanning_attempts: int = 3        # Max mid-execution re-plans
    self_reflection_enabled: bool = False   # Query CORTEX knowledge before acting


class RetryPolicy(BaseModel):
    max_retries: int = 3
    backoff_strategy: BackoffStrategy = BackoffStrategy.EXPONENTIAL
    backoff_multiplier: float = 2.0
    retry_on: List[str] = ["TOOL_FAILURE", "LLM_ERROR", "TIMEOUT"]


class SuccessCriterion(BaseModel):
    criterion: str
    validation_type: ValidationType
    validator: str


class ReviewMechanism(BaseModel):
    enabled: bool = False
    review_prompt: Optional[str] = None   # Additional review criteria (appended)
    review_system_prompt: str = DEFAULT_REVIEW_SYSTEM_PROMPT  # Base review prompt (overridable)
    success_criteria: List[SuccessCriterion] = []
    on_failure: str = "RETRY"  # RETRY | ESCALATE | ABORT


class ContextPolicy(BaseModel):
    """Context filtering policy for step execution."""
    type: str = "FULL"  # FULL | LAST_N | SLIDING_WINDOW | EXPLICIT
    n: Optional[int] = None  # For LAST_N: number of previous steps to include
    max_chars: Optional[int] = None  # For SLIDING_WINDOW: max characters
    summarize_threshold: Optional[int] = 8000  # Auto-summarize if context exceeds this
    explicit_keys: List[str] = []  # For EXPLICIT: specific context keys to include
    # P2.6: Domain-specific keys to always preserve verbatim during summarization.
    # Replaces hardcoded ["age_group", "style", "topic"] that were baked into worker.py.
    preserve_keys: List[str] = []  # e.g. ["customer_name", "product_id", "language"]


class LogicGate(BaseModel):
    reasoning_config: ReasoningConfig
    retry_policy: RetryPolicy = RetryPolicy()
    review_mechanism: ReviewMechanism = ReviewMechanism()
    context_policy: ContextPolicy = ContextPolicy()
