"""Phase 11 Track 14 — integration suite smoke test.

Single asserts to prove the conftest fixtures wire up:
  * The DB session works and rolls back at teardown.
  * MockLLMRouter returns the default response when no fixture matches.
  * deterministic_embedding is stable across calls.
"""
from __future__ import annotations

import pytest


pytestmark = pytest.mark.needs_db


async def test_db_session_works(db) -> None:
    from sqlalchemy import text
    val = (await db.execute(text("SELECT 42"))).scalar()
    assert val == 42


async def test_mock_llm_returns_default(mock_llm) -> None:
    resp = await mock_llm.call_llm(
        task_type="text_generation",
        system_prompt="x",
        user_prompt="y",
    )
    assert resp.model_name == "mock-model"
    assert resp.provider == "mock"
    assert mock_llm.calls and mock_llm.calls[0]["task_type"] == "text_generation"


def test_deterministic_embedding_stable() -> None:
    from tests.fixtures.llm_fixture import (
        cosine_similarity, deterministic_embedding,
    )
    v1 = deterministic_embedding("hello")
    v2 = deterministic_embedding("hello")
    v3 = deterministic_embedding("world")
    assert v1 == v2
    assert v1 != v3
    assert len(v1) == 768
    assert all(-1.0 <= x <= 1.0 for x in v1)
    # Identical text → cosine sim = 1; distinct text → less than 1.
    assert cosine_similarity(v1, v2) == pytest.approx(1.0, abs=1e-9)
    assert cosine_similarity(v1, v3) < 0.99
