"""
tests/harness/embeddings.py — Deterministic embedding stub for offline tests.

Real embedding cosine similarity needs a model. Test harness needs a
function that is:
  * Deterministic (same input → same vector).
  * Reasonably discriminative (different inputs → different vectors).
  * Self-consistent (similar inputs → similar vectors).

We use a hash-bucketed bag-of-tokens projection into a fixed-dim space.
Identical strings → cosine 1.0. Strings sharing tokens → cosine > 0.
Disjoint strings → cosine near 0.

This is NOT a substitute for real embeddings in production. It is
sufficient for offline parity/regression tests where the goal is to
catch *gross* output divergence (e.g. legacy returned an essay,
candidate returned an error string).
"""
from __future__ import annotations

import hashlib
import math
import re
from typing import Iterable


EMBEDDING_DIM = 256
_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")


def _tokens(text: str) -> Iterable[str]:
    return (m.group(0).lower() for m in _TOKEN_RE.finditer(text))


def deterministic_embedding(text: str, *, dim: int = EMBEDDING_DIM) -> list[float]:
    """Hash-bucketed bag-of-tokens embedding.

    Each token contributes ±1 (sign from hash) to two buckets (also
    from hash) — like a tiny TF-IDF count-min sketch.
    """
    vec = [0.0] * dim
    for tok in _tokens(text):
        h = hashlib.blake2b(tok.encode("utf-8"), digest_size=8).digest()
        # Two independent bucket+sign pairs per token for variance.
        for off in (0, 4):
            chunk = h[off:off + 4]
            ival = int.from_bytes(chunk, "big")
            idx = ival % dim
            sign = 1.0 if (ival >> 31) & 1 else -1.0
            vec[idx] += sign
    return vec


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Standard cosine; returns 0.0 if either vector is zero."""
    if len(a) != len(b):
        raise ValueError("vector length mismatch")
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (math.sqrt(na) * math.sqrt(nb))


def deterministic_cosine_similarity(text_a: str, text_b: str) -> float:
    """Convenience: embed both texts and return their cosine."""
    return cosine_similarity(
        deterministic_embedding(text_a),
        deterministic_embedding(text_b),
    )
