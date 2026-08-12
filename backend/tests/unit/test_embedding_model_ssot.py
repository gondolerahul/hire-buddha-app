"""Embedding model single-source-of-truth — Phase 12 `07` §6 (review M10).

The embedding model must resolve exactly once per ``EmbeddingService`` instance
and be cached, so every node embedded by that service uses the same model. This
regression test locks in the one-resolution-per-process behavior before the
CORTEX extraction (`04`) moves the resolver.
"""
from __future__ import annotations

from uuid import uuid4

import pytest

import src.common.genai_factory as genai_factory
from src.ai.constants import EMBEDDING_MODEL
from src.ai.memory.embedding_service import EmbeddingService


@pytest.mark.asyncio
async def test_model_resolved_once_and_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = EmbeddingService(db=object(), company_id=uuid4())  # type: ignore[arg-type]

    calls = {"resolve": 0}

    async def fake_resolve() -> str:
        calls["resolve"] += 1
        return "text-embedding-005"

    async def fake_client(db, company_id):  # noqa: ANN001
        return object()

    monkeypatch.setattr(svc, "_resolve_embedding_model", fake_resolve)
    monkeypatch.setattr(genai_factory, "build_vertex_genai_client", fake_client)

    client1, model1 = await svc._get_client_and_model()
    client2, model2 = await svc._get_client_and_model()

    # Resolved exactly once; the cached client/model are reused.
    assert calls["resolve"] == 1
    assert model1 == model2 == "text-embedding-005"
    assert client1 is client2
    assert svc.get_model_name() == "text-embedding-005"


@pytest.mark.asyncio
async def test_get_model_name_falls_back_before_resolution() -> None:
    svc = EmbeddingService(db=object(), company_id=uuid4())  # type: ignore[arg-type]
    # Before any resolution the public accessor returns the constant, never None.
    assert svc.get_model_name() == EMBEDDING_MODEL
