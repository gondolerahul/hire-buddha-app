"""
ai.core.reasoning — Reasoning-mode strategy registry.

Importing this package registers the two surviving per-step reasoning
modes (REACT, CHAIN_OF_THOUGHT). Per decision D-3 the former REFLECTION
and TREE_OF_THOUGHTS per-entity modes are retired: REFLECTION is
superseded by the AgentLoop's ``Reflector`` stage, and TREE_OF_THOUGHTS
by the Strategist-selected ``DebateExecutor``. The adapters delegate into
the existing ``llm.router`` calls.
"""
from src.ai.core.reasoning.base import (
    REASONING_REGISTRY,
    Reasoning,
    get_reasoning,
    register_reasoning,
    registered_reasoning_modes,
)
from src.ai.core.reasoning import react              # noqa: F401
from src.ai.core.reasoning import chain_of_thought   # noqa: F401

__all__ = [
    "REASONING_REGISTRY",
    "Reasoning",
    "get_reasoning",
    "register_reasoning",
    "registered_reasoning_modes",
]
