"""Phase 11 Track 2 — executor registry + reasoning registry shape."""
from __future__ import annotations

import pytest

from src.ai.core.executors import (
    EXECUTOR_REGISTRY,
    get_executor,
    registered_executor_names,
)
from src.ai.core.reasoning import (
    REASONING_REGISTRY,
    get_reasoning,
    registered_reasoning_modes,
)
from src.ai.schemas.enums import ReasoningMode


# Every registered executor is a real one; the Dialog/ToolBurst/Skill stubs
# that raised NotImplementedError were deleted (AK-10).
EXPECTED_EXECUTORS = {
    "SingleStep", "DAG", "Recursive", "ChildEntity", "Debate",
}

# D-3: REFLECTION and TREE_OF_THOUGHTS are retired as per-step reasoning
# modes (Reflector / DebateExecutor replace them); only these two remain.
EXPECTED_REASONING_MODES = {
    ReasoningMode.REACT,
    ReasoningMode.CHAIN_OF_THOUGHT,
}

# Retired modes that must NOT be registered any more.
RETIRED_REASONING_MODES = {
    ReasoningMode.REFLECTION,
    ReasoningMode.TREE_OF_THOUGHTS,
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


def test_reasoning_registry_complete() -> None:
    modes = registered_reasoning_modes()
    assert modes >= EXPECTED_REASONING_MODES
    # Retired modes must no longer be registered (D-3).
    assert not (modes & RETIRED_REASONING_MODES), (
        f"retired modes still registered: {modes & RETIRED_REASONING_MODES}"
    )


def test_get_reasoning_resolves_each_mode() -> None:
    for mode in EXPECTED_REASONING_MODES:
        strategy = get_reasoning(mode)
        assert strategy.name == mode


def test_retired_reasoning_modes_not_resolvable() -> None:
    import pytest as _pytest
    for mode in RETIRED_REASONING_MODES:
        with _pytest.raises(LookupError):
            get_reasoning(mode)


def test_get_reasoning_unknown_raises() -> None:
    class _Fake:
        value = "FAKE_MODE"
    with pytest.raises(LookupError):
        get_reasoning(_Fake())  # type: ignore[arg-type]
