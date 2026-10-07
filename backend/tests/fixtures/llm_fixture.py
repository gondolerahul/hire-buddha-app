"""tests/fixtures/llm_fixture.py — deterministic embedding doubles.

``deterministic_embedding`` keeps the cosine-similarity assertions in the
regression suite stable. The LLM double is ``tests.harness.MockLLMRouter``
(TS-13: it was defined here too, with a different interface).

Reusable from any test location::

    from tests.fixtures.llm_fixture import deterministic_embedding
"""
from __future__ import annotations

import hashlib


__all__ = ["deterministic_embedding", "cosine_similarity"]


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
