"""Phase 11 Track 6 — embedding-model resolver fallback path."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from src.ai.constants import EMBEDDING_MODEL_FALLBACK
from src.ai.memory.embedding_service import resolve_embedding_model


@pytest.mark.asyncio
async def test_falls_back_to_constant_when_no_integration() -> None:
    """Resolver returns ``(EMBEDDING_MODEL_FALLBACK, None)`` when nothing
    is configured for the company AND there is no DB session that can
    answer the registry lookup."""
    # Patch the inner resolver to short-circuit straight to the fallback
    # so we don't need a live DB.
    with patch(
        "src.ai.memory.embedding_service.EmbeddingService._resolve_embedding_model",
        AsyncMock(return_value=EMBEDDING_MODEL_FALLBACK),
    ):
        # db.execute will be called for the api-key probe; make it raise
        # so the resolver hits the bare-except branch and returns None.
        bad_db = AsyncMock()
        bad_db.execute.side_effect = RuntimeError("no registry table")
        model, api_key = await resolve_embedding_model(bad_db, uuid4())
        assert model == EMBEDDING_MODEL_FALLBACK
        assert api_key is None


@pytest.mark.asyncio
async def test_uses_registry_model_when_resolver_returns_one() -> None:
    """When the in-class resolver returns a specific model, the standalone
    helper passes it through unchanged."""
    with patch(
        "src.ai.memory.embedding_service.EmbeddingService._resolve_embedding_model",
        AsyncMock(return_value="custom-embed-1"),
    ):
        bad_db = AsyncMock()
        bad_db.execute.side_effect = RuntimeError("registry probe stubbed")
        model, _api_key = await resolve_embedding_model(bad_db, uuid4())
        assert model == "custom-embed-1"
