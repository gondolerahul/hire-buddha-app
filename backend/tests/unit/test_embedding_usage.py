"""Phase 12 — embed_batch attributed-usage metering (P-F3/P-F6).

Covers the billing chokepoint added to ``EmbeddingService.embed_batch``:
characters are tallied from Vertex's response, one usage row is written
per batch (not per text), and any billing failure is swallowed so it
never surfaces into retrieval.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from src.ai.memory.embedding_service import EmbeddingService


def _fake_embed_response(values, billable_chars, tokens):
    emb = SimpleNamespace(
        values=values,
        statistics=SimpleNamespace(token_count=tokens, truncated=False),
    )
    return SimpleNamespace(
        embeddings=[emb],
        metadata=SimpleNamespace(billable_character_count=billable_chars),
    )


def _fake_client(per_call_chars=11, per_call_tokens=3):
    models = SimpleNamespace(
        embed_content=lambda model, contents, config: _fake_embed_response(
            [0.1, 0.2, 0.3], per_call_chars, per_call_tokens
        )
    )
    return SimpleNamespace(models=models)


@pytest.mark.asyncio
async def test_embed_batch_writes_one_usage_row_per_batch() -> None:
    """Two texts → two Vertex calls → exactly ONE attributed usage row,
    carrying the summed billable characters and ingestion phase."""
    svc = EmbeddingService(db=AsyncMock(), company_id=uuid4())

    with patch.object(
        EmbeddingService, "_get_client_and_model",
        AsyncMock(return_value=(_fake_client(per_call_chars=11), "text-embedding-005")),
    ), patch.object(
        EmbeddingService, "_log_embedding_usage", AsyncMock()
    ) as log_mock:
        results = await svc.embed_batch(["hello world", "foo bar baz"])

    assert len(results) == 2 and all(r is not None for r in results)
    log_mock.assert_awaited_once()
    _model, task_type, chars, tokens, embedded = log_mock.await_args.args
    assert task_type == "RETRIEVAL_DOCUMENT"
    assert chars == 22          # 11 + 11 summed across the two calls
    assert tokens == 6          # 3 + 3
    assert embedded == 2


@pytest.mark.asyncio
async def test_query_phase_is_tagged_retrieval() -> None:
    """embed_query funnels through embed_batch with RETRIEVAL_QUERY so the
    dashboard can split retrieval from ingestion spend."""
    svc = EmbeddingService(db=AsyncMock(), company_id=uuid4())
    with patch.object(
        EmbeddingService, "_get_client_and_model",
        AsyncMock(return_value=(_fake_client(), "text-embedding-005")),
    ), patch.object(
        EmbeddingService, "_log_embedding_usage", AsyncMock()
    ) as log_mock:
        await svc.embed_query("what is the capital of france?")
    assert log_mock.await_args.args[1] == "RETRIEVAL_QUERY"


@pytest.mark.asyncio
async def test_billing_failure_never_breaks_retrieval() -> None:
    """A blowup inside the usage write must not propagate — embeddings
    are still returned to the caller."""
    svc = EmbeddingService(db=AsyncMock(), company_id=uuid4())
    with patch.object(
        EmbeddingService, "_get_client_and_model",
        AsyncMock(return_value=(_fake_client(), "text-embedding-005")),
    ), patch(
        "src.common.database.AsyncSessionLocal",
        side_effect=RuntimeError("db pool exhausted"),
    ):
        # Real _log_embedding_usage runs; its internal try/except must eat
        # the error rather than letting embed_batch raise.
        results = await svc.embed_batch(["alpha"])
    assert results and results[0] is not None


@pytest.mark.asyncio
async def test_no_usage_row_when_nothing_embedded() -> None:
    """Empty / whitespace-only inputs produce no billable work, so no
    usage write is attempted."""
    svc = EmbeddingService(db=AsyncMock(), company_id=uuid4())
    with patch.object(
        EmbeddingService, "_get_client_and_model",
        AsyncMock(return_value=(_fake_client(), "text-embedding-005")),
    ), patch.object(
        EmbeddingService, "_log_embedding_usage", AsyncMock()
    ) as log_mock:
        results = await svc.embed_batch(["", "   "])
    assert results == [None, None]
    # embed_batch hands the logger embedded_count == 0 / chars == 0; the
    # guard at the top of _log_embedding_usage turns that into a no-op.
    _model, _task, chars, tokens, embedded = log_mock.await_args.args
    assert embedded == 0 and chars == 0
