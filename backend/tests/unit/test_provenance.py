"""Phase 11 Track 6 — Provenance schema tests."""
from __future__ import annotations

from datetime import datetime
from uuid import uuid4

import pytest

from src.ai.schemas.cortex import (
    DEFAULT_TRUST_BY_SOURCE,
    Provenance,
    SourceType,
)


def test_default_trust_for_user_upload_is_one() -> None:
    p = Provenance(source_type=SourceType.USER_UPLOAD)
    assert p.effective_trust_score() == 1.0


def test_default_trust_for_external_link_is_low() -> None:
    p = Provenance(source_type=SourceType.EXTERNAL_LINK)
    assert p.effective_trust_score() == DEFAULT_TRUST_BY_SOURCE["external_link"]


def test_explicit_trust_score_wins() -> None:
    p = Provenance(source_type=SourceType.TOOL, trust_score=0.95)
    assert p.effective_trust_score() == 0.95


def test_trust_score_clamped_to_unit_interval() -> None:
    p = Provenance(source_type=SourceType.TOOL, trust_score=1.5)
    assert p.effective_trust_score() == 1.0
    p2 = Provenance(source_type=SourceType.TOOL, trust_score=-0.5)
    assert p2.effective_trust_score() == 0.0


def test_round_trip_through_source_ref() -> None:
    run_id = uuid4()
    fetched = datetime(2026, 5, 27, 12, 30)
    p = Provenance(
        source_type=SourceType.TOOL,
        tool_id="web_search",
        url="https://example.com",
        fetched_at=fetched,
        run_id=run_id,
        step_id="s1",
        notes="for context",
    )
    blob = p.to_source_ref()
    back = Provenance.from_source_ref(blob)
    assert back is not None
    assert back.source_type == SourceType.TOOL
    assert back.tool_id == "web_search"
    assert back.url == "https://example.com"
    assert back.run_id == run_id
    assert back.step_id == "s1"
    assert back.fetched_at == fetched
    assert back.effective_trust_score() == DEFAULT_TRUST_BY_SOURCE["tool"]


def test_from_source_ref_returns_none_on_missing_type() -> None:
    assert Provenance.from_source_ref({}) is None
    assert Provenance.from_source_ref(None) is None
    assert Provenance.from_source_ref({"tool_id": "x"}) is None


def test_from_source_ref_returns_none_on_garbage() -> None:
    assert Provenance.from_source_ref({"source_type": "not_a_real_kind"}) is None


@pytest.mark.parametrize("kind,expected", [
    (SourceType.USER_UPLOAD, 1.0),
    (SourceType.MANUAL,      0.9),
    (SourceType.DREAMING,    0.8),
    (SourceType.TOOL,        0.7),
    (SourceType.REFLECTION,  0.6),
    (SourceType.EXTERNAL_LINK, 0.4),
])
def test_default_trust_table_constants(kind, expected) -> None:
    assert DEFAULT_TRUST_BY_SOURCE[kind.value] == expected
