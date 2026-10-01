"""
ai.core.executors — Executor adapters used by AgentLoop (Track 2).

Importing this package registers every executor in
``EXECUTOR_REGISTRY``. Every registered executor is real: the Dialog,
ToolBurst and Skill stubs were deleted (AK-10) — under the six-level
hierarchy a SKILL runs through the same loop as every other level.
"""
from src.ai.core.executors.base import (
    ActionResult,
    EXECUTOR_REGISTRY,
    Executor,
    get_executor,
    register_executor,
    registered_executor_names,
)
# Side-effect imports — each module calls ``register_executor`` at import time.
from src.ai.core.executors import single_step  # noqa: F401  (registers SingleStep)
from src.ai.core.executors import dag          # noqa: F401  (registers DAG)
from src.ai.core.executors import recursive    # noqa: F401  (registers Recursive)
from src.ai.core.executors import child_entity # noqa: F401  (registers ChildEntity)
from src.ai.core.executors import debate        # noqa: F401  (registers Debate)

__all__ = [
    "ActionResult",
    "EXECUTOR_REGISTRY",
    "Executor",
    "get_executor",
    "register_executor",
    "registered_executor_names",
]
