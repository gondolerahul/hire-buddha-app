"""
ai.memory.memory_assembly_service — host re-export + auto-injection shim.

``MemoryAssemblyService`` (the v2 4-domain runtime-memory assembler) moved into
the ``cortex_memory`` package (Phase 12 `04` Stage B). The package class takes
the providers it passes down to the graph / domain / CORTEX services via
injection. This shim subclasses it and auto-injects the host adapters so
``MemoryAssemblyService(db, company_id)`` works unchanged.
"""
from __future__ import annotations

import functools
from typing import Any, Optional
from uuid import UUID

from cortex_memory.assembly import (  # noqa: F401
    MemoryAssemblyResult,
    MemoryAssemblyService as _PackageMemoryAssemblyService,
)


class MemoryAssemblyService(_PackageMemoryAssemblyService):
    def __init__(
        self,
        db: Any,
        company_id: UUID,
        *,
        embedding: Optional[Any] = None,
        llm: Optional[Any] = None,
        child_run_factory: Optional[Any] = None,
    ) -> None:
        if embedding is None or llm is None or child_run_factory is None:
            from src.ai.memory.cortex_providers import (
                HostEmbeddingProvider,
                HostLLMProvider,
            )
            from src.ai.memory.cortex_service import _host_child_run_factory

            if embedding is None:
                embedding = HostEmbeddingProvider(db, company_id)
            if llm is None:
                llm = HostLLMProvider(db, company_id)
            if child_run_factory is None:
                child_run_factory = functools.partial(_host_child_run_factory, db, company_id)
        super().__init__(
            db, company_id,
            embedding=embedding, llm=llm, child_run_factory=child_run_factory,
        )


__all__ = ["MemoryAssemblyService", "MemoryAssemblyResult"]
