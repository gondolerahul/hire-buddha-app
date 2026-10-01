"""Phase 11 Track 2 — executor registry shape."""
from __future__ import annotations

import pytest

from src.ai.core.executors import (
    EXECUTOR_REGISTRY,
    get_executor,
    registered_executor_names,
)


# Every registered executor is a real one; the Dialog/ToolBurst/Skill stubs
# that raised NotImplementedError were deleted (AK-10).
EXPECTED_EXECUTORS = {
    "SingleStep", "DAG", "Recursive", "ChildEntity", "Debate",
}


def test_executor_registry_holds_exactly_the_real_executors() -> None:
    assert registered_executor_names() == EXPECTED_EXECUTORS


def test_get_executor_resolves_each() -> None:
    for name in EXPECTED_EXECUTORS:
        ex = get_executor(name)
        assert ex.name == name


def test_get_executor_unknown_raises() -> None:
    with pytest.raises(LookupError):
        get_executor("NotARealExecutor")


def test_the_unused_reasoning_registry_is_gone() -> None:
    """LP-13: ``core/reasoning/`` registered REACT and CHAIN_OF_THOUGHT
    strategies nothing called; the step executor branches on the mode."""
    from pathlib import Path

    reasoning = Path(__file__).resolve().parents[2] / "src" / "ai" / "core" / "reasoning"
    assert not list(reasoning.glob("*.py"))
