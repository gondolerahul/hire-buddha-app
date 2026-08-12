"""
cortex_memory.providers_reference — host-free reference providers.

Deterministic, dependency-free implementations of the provider Protocols so the
package can be exercised (and the host's adapters validated against the same
contract) without any LLM / DB / network. Not for production — the host injects
real adapters (``cortex_bridge``).
"""
from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Mapping, Optional, Sequence

from cortex_memory.providers import (
    EmbeddingResult,
    LLMResult,
    RunfRef,
)


class EchoLLMProvider:
    """Returns a deterministic echo of the prompt. Implements ``LLMProvider``."""

    def __init__(self, model: str = "echo-llm") -> None:
        self.model = model

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
        text = f"[echo] {user.strip()}"
        return LLMResult(
            text=text,
            model=model or self.model,
            input_tokens=len(system) + len(user),
            output_tokens=len(text),
            cost_usd=0.0,
        )


class HashEmbeddingProvider:
    """Deterministic hash-based embeddings of a fixed dimension. Implements
    ``EmbeddingProvider``."""

    def __init__(self, dim: int = 16, model: str = "hash-embed") -> None:
        self._dim = dim
        self.model = model

    def dimension(self) -> int:
        return self._dim

    async def embed(
        self, texts: Sequence[str], *, model: Optional[str] = None
    ) -> EmbeddingResult:
        vectors: List[List[float]] = []
        chars = 0
        for t in texts:
            chars += len(t)
            digest = hashlib.sha256(t.encode("utf-8")).digest()
            vec = [digest[i % len(digest)] / 255.0 for i in range(self._dim)]
            vectors.append(vec)
        return EmbeddingResult(
            vectors=vectors,
            model=model or self.model,
            char_count=chars,
            cost_usd=0.0,
        )


class NullUsageReporter:
    """Drops all usage reports. Implements ``UsageReporter``."""

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


class InMemoryRunRegistry:
    """Serves ``RunfRef``s from an in-memory dict. Implements ``RunRegistry``."""

    def __init__(self, runs: Optional[Dict[str, RunfRef]] = None) -> None:
        self._runs: Dict[str, RunfRef] = dict(runs or {})

    def add(self, ref: RunfRef) -> None:
        self._runs[ref.run_id] = ref

    async def get_run(self, run_id: str) -> Optional[RunfRef]:
        return self._runs.get(run_id)


__all__ = [
    "EchoLLMProvider",
    "HashEmbeddingProvider",
    "NullUsageReporter",
    "InMemoryRunRegistry",
]
