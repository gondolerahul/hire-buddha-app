"""
ai.core.executors.base — Executor protocol + ActionResult + registry.

An Executor is a thin adapter the AgentLoop calls per iteration. It
takes a ``Move`` (which encodes "what to do") and an ``AgentState``,
mutates state via legacy code if needed, and returns an
``ActionResult``.

Registry semantics:

  * One Executor per executor name.
  * The registry is module-global because all executors must be
    discoverable from the loop without dependency injection.
  * ``register_executor`` is idempotent; later registrations replace
    earlier ones (useful for tests).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Protocol, runtime_checkable
from uuid import UUID

from src.ai.core.agent_state import AgentState, ExecutorName
from src.ai.core.strategist import Move

__all__ = [
    "ActionResult",
    "Executor",
    "EXECUTOR_REGISTRY",
    "register_executor",
    "get_executor",
    "registered_executor_names",
]


@dataclass
class ActionResult:
    """Output of one Executor.execute call."""
    output: str = ""                                # rendered for context propagation
    tools_used: list[str] = field(default_factory=list)
    children_run_ids: list[UUID] = field(default_factory=list)
    cost_usd: Decimal = field(default_factory=lambda: Decimal("0"))
    latency_ms: int = 0
    cortex_nodes_written: list[UUID] = field(default_factory=list)
    success: bool = True
    error: str = ""
    completed_step_ids: list[str] = field(default_factory=list)
    context_state_delta: dict[str, Any] = field(default_factory=dict)
    # Async child dispatch: when non-empty, the executor dispatched child run(s)
    # as isolated jobs instead of running them inline, and the AgentLoop must
    # SUSPEND (snapshot + WAITING_ON_CHILDREN) rather than continue the
    # iteration. Each entry is ``{"run_id": str, "step_id": str}``. The step is
    # NOT in ``completed_step_ids`` yet — it completes on resume once the child
    # is terminal.
    awaiting_children: list[dict[str, Any]] = field(default_factory=list)


@runtime_checkable
class Executor(Protocol):
    name: ExecutorName

    async def execute(
        self,
        move: Move,
        state: AgentState,
        db: Any,
    ) -> ActionResult: ...


EXECUTOR_REGISTRY: dict[str, Executor] = {}


def register_executor(executor: Executor) -> Executor:
    """Add (or replace) an executor in the global registry."""
    EXECUTOR_REGISTRY[executor.name] = executor
    return executor


def get_executor(name: ExecutorName) -> Executor:
    try:
        return EXECUTOR_REGISTRY[name]
    except KeyError as exc:
        raise LookupError(
            f"No executor registered for {name!r}. "
            f"Known: {sorted(EXECUTOR_REGISTRY)}"
        ) from exc


def registered_executor_names() -> set[str]:
    return set(EXECUTOR_REGISTRY)
