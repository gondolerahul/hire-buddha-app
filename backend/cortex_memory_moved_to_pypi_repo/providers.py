"""
cortex_memory.providers — the host-injection boundary.

CORTEX needs four things from its host that are NOT memory concerns: to call an
LLM, to embed text, to meter usage/cost, and to look up the run a write belongs
to. Rather than import the host's ``LLMRouter`` / ``EmbeddingService`` /
``UsageService`` / ORM (which would invert the dependency and make the package
un-shippable), the package declares these as Protocols. The host implements
them in a thin adapter (``cortex_bridge``) and injects instances.

Reference, host-free implementations live in
:mod:`cortex_memory.providers_reference` (used by the package's own tests so it
runs with zero host dependencies).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Protocol, Sequence, runtime_checkable


# ---------------------------------------------------------------------------
# DTOs exchanged across the boundary
# ---------------------------------------------------------------------------


@dataclass
class LLMResult:
    """The outcome of an LLM completion, normalised for the package."""

    text: str
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    raw: Any = None


@dataclass
class EmbeddingResult:
    """One or more embedding vectors plus their billing metadata."""

    vectors: List[List[float]]
    model: str = ""
    char_count: int = 0
    cost_usd: float = 0.0

    @property
    def dimension(self) -> int:
        return len(self.vectors[0]) if self.vectors else 0


@dataclass
class RunfRef:
    """The slice of an execution run CORTEX needs for write attribution +
    scope. (Spelled ``RunfRef`` to avoid a clash with the host ORM ``RunRef``;
    re-exported under both names from the package root.)"""

    run_id: str
    company_id: Optional[str] = None
    user_id: Optional[str] = None
    parent_run_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


# Friendly alias — the package root also exports ``RunRef``.
RunRef = RunfRef


# ---------------------------------------------------------------------------
# Provider Protocols — the host injects implementations of these
# ---------------------------------------------------------------------------


@runtime_checkable
class LLMProvider(Protocol):
    """Completes a prompt. The host adapter wraps its ``LLMRouter``."""

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
        ...


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Embeds text. The host adapter wraps its ``EmbeddingService`` +
    ``resolve_embedding_model`` (seam S4)."""

    async def embed(
        self,
        texts: Sequence[str],
        *,
        model: Optional[str] = None,
    ) -> EmbeddingResult:
        ...

    def dimension(self) -> int:
        """Vector dimension of the configured model (for pgvector DDL)."""
        ...


@runtime_checkable
class UsageReporter(Protocol):
    """Meters LLM + embedding usage/cost. The host adapter wraps its
    ``UsageService`` / ``CostAttribution``. No-op implementations are valid."""

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
        ...

    async def report_embedding(
        self,
        *,
        model: str,
        char_count: int,
        cost_usd: float,
        attribution: str = "cortex",
        meta: Optional[Mapping[str, Any]] = None,
    ) -> None:
        ...


@runtime_checkable
class RunRegistry(Protocol):
    """Looks up the run a CORTEX write belongs to (attribution + scope). The
    host adapter reads its ``ExecutionRun`` table."""

    async def get_run(self, run_id: str) -> Optional[RunfRef]:
        ...


__all__ = [
    "LLMResult",
    "EmbeddingResult",
    "RunfRef",
    "RunRef",
    "LLMProvider",
    "EmbeddingProvider",
    "UsageReporter",
    "RunRegistry",
]
