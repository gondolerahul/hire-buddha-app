"""
ai.memory.cortex_providers — host implementations of the cortex_memory Protocols.

This is the **host side of the CORTEX injection boundary** (plan `04`). The
``cortex_memory`` package declares what it needs from a host — LLM completion,
embeddings, usage metering, run lookups — as Protocols; these adapters satisfy
them by wrapping the host's ``LLMRouter`` / ``EmbeddingService`` /
``UsageService`` / ``ExecutionRun``. The CORTEX services (as they move into the
package) take these via injection, so the package never imports the host.

A ``build_cortex_providers(db, company_id)`` factory wires the full set.
"""
from __future__ import annotations

import logging
from typing import Any, List, Mapping, Optional, Sequence
from uuid import UUID

from cortex_memory.providers import (
    EmbeddingResult,
    LLMResult,
    RunfRef,
)

logger = logging.getLogger(__name__)

# CORTEX node embeddings are pgvector Vector(768).
_CORTEX_EMBEDDING_DIM = 768


class HostLLMProvider:
    """Implements ``cortex_memory.LLMProvider`` via the host ``LLMRouter``."""

    def __init__(self, db: Any, company_id: UUID) -> None:
        # Lazy: the host LLMRouter is built on first use (a CortexService is
        # constructed on every loop iteration but rarely calls the LLM).
        self._db = db
        self._company_id = company_id
        self._router: Any = None

    def _get_router(self) -> Any:
        if self._router is None:
            from src.ai.llm.router import LLMRouter

            self._router = LLMRouter(db=self._db, company_id=self._company_id)
        return self._router

    async def complete(
        self,
        *,
        system: str,
        user: str,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        task_type: Optional[str] = None,
    ) -> LLMResult:
        resp = await self._get_router().call_llm(
            task_type=task_type or "text_generation",
            system_prompt=system,
            user_prompt=user,
            temperature=temperature,
            max_tokens=max_tokens,
            model_override=model,
        )
        return LLMResult(
            text=getattr(resp, "output", "") or "",
            model=getattr(resp, "model_name", "") or "",
            input_tokens=int(getattr(resp, "prompt_tokens", 0) or 0),
            output_tokens=int(getattr(resp, "completion_tokens", 0) or 0),
            cost_usd=float(getattr(resp, "cost_usd", 0) or 0),
            raw=resp,
        )


class HostEmbeddingProvider:
    """Implements ``cortex_memory.EmbeddingProvider`` via the host
    ``EmbeddingService`` (which itself resolves the per-tenant model from the
    IntegrationRegistry — seam S4 — and self-reports embedding usage)."""

    def __init__(self, db: Any, company_id: UUID) -> None:
        from src.ai.memory.embedding_service import EmbeddingService

        self._svc = EmbeddingService(db, company_id)

    async def embed(
        self, texts: Sequence[str], *, model: Optional[str] = None
    ) -> EmbeddingResult:
        vecs = await self._svc.embed_batch(list(texts))
        # The package contract wants one vector per input; failed embeddings
        # (None from the host service) become empty vectors the caller can skip.
        vectors: List[List[float]] = [list(v) if v else [] for v in vecs]
        return EmbeddingResult(
            vectors=vectors,
            model=self._svc.get_model_name(),
            char_count=sum(len(t) for t in texts),
        )

    def dimension(self) -> int:
        return _CORTEX_EMBEDDING_DIM


class HostUsageReporter:
    """Implements ``cortex_memory.UsageReporter``.

    The host's ``LLMRouter`` / ``EmbeddingService`` already write attributed
    usage rows when they run, so this adapter is a no-op by default (extra
    package-side reporting would double-count). It exists so the package's
    injected reporter is never ``None`` and can be swapped for a real one."""

    async def report_llm(
        self,
        *,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float,
        attribution: str = "cortex",
        meta: Optional[Mapping[str, Any]] = None,
    ) -> None:
        return None

    async def report_embedding(
        self,
        *,
        model: str,
        char_count: int,
        cost_usd: float,
        attribution: str = "cortex",
        meta: Optional[Mapping[str, Any]] = None,
    ) -> None:
        return None


class HostRunRegistry:
    """Implements ``cortex_memory.RunRegistry`` via the host ``ExecutionRun``."""

    def __init__(self, db: Any) -> None:
        self.db = db

    async def get_run(self, run_id: str) -> Optional[RunfRef]:
        from sqlalchemy import select

        from src.ai.orm.execution import ExecutionRun

        try:
            rid = run_id if isinstance(run_id, UUID) else UUID(str(run_id))
        except (ValueError, TypeError):
            return None
        run = (await self.db.execute(
            select(ExecutionRun).where(ExecutionRun.id == rid)
        )).scalar_one_or_none()
        if run is None:
            return None
        return RunfRef(
            run_id=str(run.id),
            company_id=str(run.company_id) if run.company_id else None,
            user_id=str(run.user_id) if run.user_id else None,
            parent_run_id=str(run.parent_run_id) if getattr(run, "parent_run_id", None) else None,
        )


class CortexProviders:
    """The full injected provider set the CORTEX services will consume."""

    def __init__(
        self,
        *,
        llm: HostLLMProvider,
        embedding: HostEmbeddingProvider,
        usage: HostUsageReporter,
        runs: HostRunRegistry,
    ) -> None:
        self.llm = llm
        self.embedding = embedding
        self.usage = usage
        self.runs = runs


def build_cortex_providers(db: Any, company_id: UUID) -> CortexProviders:
    """Wire the host adapters for a (db, company) into one provider set."""
    return CortexProviders(
        llm=HostLLMProvider(db, company_id),
        embedding=HostEmbeddingProvider(db, company_id),
        usage=HostUsageReporter(),
        runs=HostRunRegistry(db),
    )


__all__ = [
    "HostLLMProvider",
    "HostEmbeddingProvider",
    "HostUsageReporter",
    "HostRunRegistry",
    "CortexProviders",
    "build_cortex_providers",
]
