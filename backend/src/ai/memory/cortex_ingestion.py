"""
ai.memory.cortex_ingestion — host re-export + auto-injection shim.

``CortexIngestionPipeline`` (document → CORTEX knowledge subtree) moved into the
``cortex_memory`` package (Phase 12 `04` Stage B). The package class takes a
``cortex_memory.LLMProvider`` (for navigation-quality summaries) and a
``CortexService`` via injection. This shim subclasses it and auto-injects the
host adapters so ``CortexIngestionPipeline(db, company_id)`` is unchanged.
"""
from __future__ import annotations

from typing import Any, Optional
from uuid import UUID

from cortex_memory.ingestion import CortexIngestionPipeline as _PackageCortexIngestionPipeline


class CortexIngestionPipeline(_PackageCortexIngestionPipeline):
    def __init__(
        self,
        db: Any,
        company_id: UUID,
        *,
        llm: Optional[Any] = None,
        cortex: Optional[Any] = None,
    ) -> None:
        if llm is None:
            from src.ai.memory.cortex_providers import HostLLMProvider

            llm = HostLLMProvider(db, company_id)
        if cortex is None:
            from src.ai.memory.cortex_service import CortexService

            cortex = CortexService(db, company_id)
        super().__init__(db, company_id, llm=llm, cortex=cortex)


__all__ = ["CortexIngestionPipeline"]
