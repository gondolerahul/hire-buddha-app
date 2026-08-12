"""tests/fixtures/llm_fixture.py — shared test doubles.

Phase 11 §14.10 spec: every Track that needs an LLM call in tests uses
``MockLLMRouter`` to keep tests deterministic (no live API key, no
network). Embeddings are similarly mocked via ``deterministic_embedding``
so the cosine-similarity assertions in the regression suite are stable.

Reusable from any test location::

    from tests.fixtures.llm_fixture import (
        MockLLMRouter, deterministic_embedding,
    )
"""
from __future__ import annotations

import hashlib
from typing import Any


__all__ = ["MockLLMRouter", "deterministic_embedding"]


class MockLLMRouter:
    """Deterministic stand-in for ``ai.llm.router.LLMRouter``.

    ``fixtures`` keys are ``(task_type, prompt_hash8)``. Any unmatched
    prompt falls back to ``default_output``.

    Records every call into ``self.calls`` so tests can assert on the
    prompt shape rather than the LLM response.
    """

    DEFAULT_OUTPUT = '{"verdict":"PASS","concerns":[]}'

    def __init__(
        self,
        fixtures: dict[tuple[str, str], Any] | None = None,
        default_output: str = DEFAULT_OUTPUT,
        model_name: str = "mock-model",
    ):
        self.fixtures = fixtures or {}
        self.default_output = default_output
        self.model_name = model_name
        self.calls: list[dict[str, Any]] = []

    @staticmethod
    def prompt_key(user_prompt: str) -> str:
        return hashlib.sha256((user_prompt or "").encode()).hexdigest()[:8]

    def _build_response(self, output: str) -> Any:
        from src.ai.llm.types import LLMResponse
        return LLMResponse(
            output=output,
            prompt_tokens=120, completion_tokens=80, latency_ms=10,
            model_name=self.model_name, provider="mock",
        )

    async def call_llm(
        self,
        *,
        task_type: str,
        system_prompt: str,
        user_prompt: str,
        **kwargs: Any,
    ) -> Any:
        key = (task_type, self.prompt_key(user_prompt))
        self.calls.append({
            "task_type": task_type, "key": key,
            "system_prompt": system_prompt[:200],
            "user_prompt": user_prompt[:500],
            "model_override": kwargs.get("model_override"),
        })
        if key in self.fixtures:
            fx = self.fixtures[key]
            if isinstance(fx, str):
                return self._build_response(fx)
            return fx
        return self._build_response(self.default_output)

    async def call_llm_react(self, **kwargs: Any) -> Any:                     # pragma: no cover
        return self._build_response(self.default_output)


def deterministic_embedding(text: str, dim: int = 768) -> list[float]:
    """Stable hash → fixed-dim vector. Useful for cosine-similarity asserts.

    Cosine similarity between two known fixture texts is computable in
    advance and never drifts between runs.
    """
    digest = hashlib.sha512((text or "").encode()).digest()
    seed = int.from_bytes(digest[:8], "big") or 1
    state = seed
    out: list[float] = []
    for _ in range(dim):
        state ^= (state << 13) & 0xFFFFFFFFFFFFFFFF
        state ^= state >> 7
        state ^= (state << 17) & 0xFFFFFFFFFFFFFFFF
        out.append(((state & 0xFFFF) / 32768.0) - 1.0)
    return out


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Stable cosine similarity for unit-norm comparison in tests."""
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)
