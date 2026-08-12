"""
ai.core.reasoning.base — Reasoning strategy protocol (Track 2).

Reasoning strategies wrap the four supported modes: REACT, CHAIN_OF_THOUGHT,
REFLECTION, TREE_OF_THOUGHTS. The Track 2 implementation registers thin
adapters that delegate to the existing call paths in
``llm/router.py`` and ``step_executor.py``. Track 9 finishes the
extraction so step_executor no longer owns the mode dispatch.
"""
from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable

from src.ai.schemas.enums import ReasoningMode

__all__ = [
    "Reasoning",
    "REASONING_REGISTRY",
    "register_reasoning",
    "get_reasoning",
    "registered_reasoning_modes",
]


@runtime_checkable
class Reasoning(Protocol):
    name: ReasoningMode

    async def run(
        self,
        *,
        llm_router: Any,
        system_prompt: str,
        user_prompt: str,
        task_type: str,
        config: dict[str, Any],
        tool_schemas: list[dict[str, Any]],
        execute_tool_fn: Any,
        model_override: Optional[str] = None,
    ) -> tuple[str, Any]: ...


REASONING_REGISTRY: dict[ReasoningMode, Reasoning] = {}


def register_reasoning(strategy: Reasoning) -> Reasoning:
    REASONING_REGISTRY[strategy.name] = strategy
    return strategy


def get_reasoning(mode: ReasoningMode) -> Reasoning:
    try:
        return REASONING_REGISTRY[mode]
    except KeyError as exc:
        raise LookupError(
            f"No reasoning strategy registered for {mode!r}. "
            f"Known: {sorted(m.value for m in REASONING_REGISTRY)}"
        ) from exc


def registered_reasoning_modes() -> set[ReasoningMode]:
    return set(REASONING_REGISTRY)
