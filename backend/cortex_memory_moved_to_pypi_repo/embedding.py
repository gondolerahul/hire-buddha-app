"""
cortex_memory.embedding — CORTEX node/query embedding helpers.

Thin CORTEX-specific wrappers over an injected ``EmbeddingProvider``: select the
text to embed for a node, run the provider, and store the vector. Keeping this
node-aware logic in the package (rather than in the host's ``EmbeddingService``)
is what lets the domain services be host-free — they call these with whatever
provider the host injected.
"""
from __future__ import annotations

from typing import Any, List, Optional


async def embed_query(provider: Any, text: str) -> Optional[List[float]]:
    """Embed a single query string; ``None`` if no provider or no result."""
    if provider is None or not text:
        return None
    res = await provider.embed([text])
    if res.vectors and res.vectors[0]:
        return list(res.vectors[0])
    return None


async def embed_texts(provider: Any, texts: List[str]) -> tuple[List[Optional[List[float]]], str]:
    """Embed a batch; returns (vectors, model_name). Missing → None entries."""
    if provider is None or not texts:
        return [None] * len(texts), ""
    res = await provider.embed(list(texts))
    vectors: List[Optional[List[float]]] = [
        list(v) if v else None for v in res.vectors
    ]
    return vectors, res.model


async def embed_node(provider: Any, node: Any) -> bool:
    """Generate + store an embedding for a CortexNode.

    Uses ``node.summary``, then ``node.title``, then ``node.content`` (truncated).
    Sets ``node.embedding`` / ``node.embedding_model``. Returns True on success.
    """
    if provider is None:
        return False
    text_to_embed = node.summary or node.title
    if not text_to_embed and node.content:
        text_to_embed = node.content[:2000]
    if not text_to_embed:
        return False
    res = await provider.embed([text_to_embed])
    vec = res.vectors[0] if res.vectors and res.vectors[0] else None
    if vec:
        node.embedding = list(vec)
        node.embedding_model = res.model or ""
        return True
    return False


__all__ = ["embed_query", "embed_texts", "embed_node"]
