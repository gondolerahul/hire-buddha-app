"""
ai.memory.cortex_service — host re-export + auto-injection shim.

``CortexService`` (the 7 CORTEX tree ops) moved into the host-independent
``cortex_memory`` package (Phase 12 `04` Stage B). The package class takes its
host concerns — an LLM provider and an execution-run factory — via injection.

This shim subclasses the package ``CortexService`` and **auto-injects the host
adapters** (``HostLLMProvider`` + an ``ExecutionRun`` factory) so every existing
``CortexService(db, company_id, ...)`` call site keeps working unchanged. The
``Viewport`` / ``NodeSummaryDTO`` / ``NodeContent`` / ``CheckpointData`` DTOs and
the ops-help prompt are re-exported.
"""
from __future__ import annotations

import functools
from typing import Any, Optional
from uuid import UUID

from cortex_memory.prompts import CORTEX_OPS_HELP as CORTEX_OPERATIONS_PROMPT  # noqa: F401
from cortex_memory.service import (  # noqa: F401
    CheckpointData,
    CortexService as _PackageCortexService,
    NodeContent,
    NodeSummaryDTO,
    Viewport,
)


async def _host_child_run_factory(
    db: Any,
    company_id: UUID,
    *,
    tree: Any,
    node_id: Any,
    task: str,
    task_node_id: Any,
    result_slot: str,
    execution_run_id: Any,
) -> Any:
    """Create the host ExecutionRun a RECURSE op spawns for a scoped subtree."""
    from src.ai.models import ExecutionRun

    child_run = ExecutionRun(
        entity_id=tree.entity_id,
        company_id=company_id,
        parent_run_id=execution_run_id,
        user_id=tree.user_id,
        input_data={
            "cortex_tree_id": str(tree.id),
            "subtree_root_id": str(node_id),
            "task": task,
            "task_node_id": str(task_node_id),
            "result_slot": result_slot,
        },
        status="PENDING",
    )
    db.add(child_run)
    await db.flush()
    return child_run.id


class CortexService(_PackageCortexService):
    """Host-configured CORTEX service: injects the host LLM provider + run
    factory so callers construct it exactly as before."""

    def __init__(
        self,
        db: Any,
        company_id: UUID,
        scoped_subtree_root_id: Optional[UUID] = None,
        scope_policy: Optional[Any] = None,
        *,
        llm: Optional[Any] = None,
        child_run_factory: Optional[Any] = None,
    ) -> None:
        if llm is None:
            from src.ai.memory.cortex_providers import HostLLMProvider

            llm = HostLLMProvider(db, company_id)
        if child_run_factory is None:
            child_run_factory = functools.partial(_host_child_run_factory, db, company_id)
        super().__init__(
            db,
            company_id,
            scoped_subtree_root_id,
            scope_policy,
            llm=llm,
            child_run_factory=child_run_factory,
        )


__all__ = [
    "CortexService",
    "Viewport",
    "NodeSummaryDTO",
    "NodeContent",
    "CheckpointData",
    "CORTEX_OPERATIONS_PROMPT",
]
