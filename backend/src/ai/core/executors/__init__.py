"""
ai.core.executors — Executor adapters used by AgentLoop (Track 2).

Importing this package registers every executor in
``EXECUTOR_REGISTRY``. Order matters only for "last write wins"; the
real executors register first so a stub never accidentally shadows a
working adapter.
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
from src.ai.core.executors import stubs        # noqa: F401  (registers Dialog/ToolBurst/Skill)

__all__ = [
    "ActionResult",
    "EXECUTOR_REGISTRY",
    "Executor",
    "get_executor",
    "register_executor",
    "registered_executor_names",
]
