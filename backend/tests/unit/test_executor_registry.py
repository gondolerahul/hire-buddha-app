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


EXPECTED_EXECUTORS = {
    "SingleStep", "DAG", "Recursive", "ChildEntity",
    "Dialog", "ToolBurst", "Skill",
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


def test_executor_registry_contains_seven_canonical_executors() -> None:
    names = registered_executor_names()
    assert EXPECTED_EXECUTORS.issubset(names), (
        f"missing: {EXPECTED_EXECUTORS - names}"
    )


def test_get_executor_resolves_each() -> None:
    for name in EXPECTED_EXECUTORS:
        ex = get_executor(name)
        assert ex.name == name


def test_get_executor_unknown_raises() -> None:
    with pytest.raises(LookupError):
        get_executor("NotARealExecutor")


@pytest.mark.asyncio
async def test_stub_executors_raise_not_implemented() -> None:
    from src.ai.core.strategist import Move
    from src.ai.core.agent_state import AgentState
    from src.ai.core.budget import Budget
    from src.ai.schemas.enums import EntityType
    from uuid import uuid4

    state = AgentState(
        run_id=uuid4(), entity_id=uuid4(), company_id=None,
        entity_type=EntityType.AGENT, budget=Budget(),
    )
    for name in ("Dialog", "ToolBurst", "Skill"):
        move = Move(move_id="x", goal_id=None, executor=name)
        with pytest.raises(NotImplementedError):
            await get_executor(name).execute(move, state, db=None)


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
