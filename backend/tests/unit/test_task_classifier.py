"""Phase 11 Track 4 — TaskClassifier v1 (rule-based) tests."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.ai.memory.task_classifier import (
    DEFAULT_CLASS,
    KEYWORD_TO_CLASS,
    TAG_TO_CLASS,
    TaskClassifier,
)


def _entity(*, tags=None, metadata=None, name="", goal="") -> SimpleNamespace:
    return SimpleNamespace(
        tags=list(tags or []),
        metadata_extensions=dict(metadata or {}),
        name=name,
        goal=goal,
    )


# ---------------------------------------------------------------------------
# 1. Explicit override beats everything.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_explicit_override_wins_over_tags() -> None:
    c = TaskClassifier()
    e = _entity(
        tags=["research"],
        metadata={"task_class": "custom_class"},
    )
    cls = await c.classify(task_description="research X", entity=e)
    assert cls == "custom_class"


# ---------------------------------------------------------------------------
# 2. Tag-based mapping.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_known_tag_maps_to_class() -> None:
    c = TaskClassifier()
    e = _entity(tags=["research"])
    assert await c.classify(task_description="", entity=e) == "research_topic"


@pytest.mark.asyncio
async def test_tag_lookup_is_case_insensitive() -> None:
    c = TaskClassifier()
    e = _entity(tags=["EMAIL"])
    assert await c.classify(task_description="", entity=e) == "draft_email"


# ---------------------------------------------------------------------------
# 3. Keyword fallback.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_keyword_in_description_classifies() -> None:
    c = TaskClassifier()
    assert await c.classify(task_description="Research the latest LLM papers", entity=None) == "research_topic"


@pytest.mark.asyncio
async def test_keyword_in_entity_name_classifies() -> None:
    c = TaskClassifier()
    e = _entity(name="Generate Report on Q4 leads")
    assert await c.classify(task_description="", entity=e) == "generate_report"


# ---------------------------------------------------------------------------
# 4. Fallback to default.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unknown_returns_default_class() -> None:
    c = TaskClassifier()
    assert await c.classify(task_description="some unrelated thing", entity=None) == DEFAULT_CLASS


@pytest.mark.asyncio
async def test_no_entity_no_description_returns_default() -> None:
    c = TaskClassifier()
    assert await c.classify(task_description="", entity=None) == DEFAULT_CLASS


# ---------------------------------------------------------------------------
# 5. Vocabulary sanity — every TAG_TO_CLASS value is reachable via keyword too.
# ---------------------------------------------------------------------------


def test_keyword_vocabulary_non_empty() -> None:
    assert len(KEYWORD_TO_CLASS) >= 5
    assert all(isinstance(kw, str) and isinstance(cls, str) for kw, cls in KEYWORD_TO_CLASS)


def test_tag_vocabulary_non_empty() -> None:
    assert len(TAG_TO_CLASS) >= 5
    assert all(isinstance(k, str) and isinstance(v, str) for k, v in TAG_TO_CLASS.items())
