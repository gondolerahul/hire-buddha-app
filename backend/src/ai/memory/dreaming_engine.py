"""
ai.memory.dreaming_engine — host re-export + auto-injection shim.

``DreamingEngine`` (the background observation→pattern→rule learning pipeline)
moved into the ``cortex_memory`` package (Phase 12 `04` Stage B). The package
class takes a ``cortex_memory.LLMProvider`` + ``EmbeddingProvider`` via
injection. This shim subclasses it and auto-injects the host adapters so
``DreamingEngine(db, company_id)`` works unchanged.
"""
from __future__ import annotations

from typing import Any, Optional
from uuid import UUID

from cortex_memory.dreaming import DreamingEngine as _PackageDreamingEngine


class DreamingEngine(_PackageDreamingEngine):
    def __init__(
        self,
        db: Any,
        company_id: UUID,
        *,
        llm: Optional[Any] = None,
        embedding: Optional[Any] = None,
    ) -> None:
        if llm is None or embedding is None:
            from src.ai.memory.cortex_providers import (
                HostEmbeddingProvider,
                HostLLMProvider,
            )

            if llm is None:
                llm = HostLLMProvider(db, company_id)
            if embedding is None:
                embedding = HostEmbeddingProvider(db, company_id)
        super().__init__(db, company_id, llm=llm, embedding=embedding)


__all__ = ["DreamingEngine"]
