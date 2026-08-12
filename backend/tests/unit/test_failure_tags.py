"""Phase 11 Track 1 — FailureTag enum used by CriticPipeline + Strategist."""
from __future__ import annotations

import pytest

from src.ai.planning.failure_tags import FailureTag


def test_failure_tag_from_string_canonical() -> None:
    assert FailureTag.from_string("OFF_TOPIC") is FailureTag.OFF_TOPIC


def test_failure_tag_from_string_lowercase() -> None:
    assert FailureTag.from_string("off_topic") is FailureTag.OFF_TOPIC


def test_failure_tag_from_string_hyphenated() -> None:
    assert FailureTag.from_string("off-topic") is FailureTag.OFF_TOPIC


def test_failure_tag_from_string_spaced() -> None:
    assert FailureTag.from_string("wrong format") is FailureTag.WRONG_FORMAT


def test_failure_tag_from_string_unknown_returns_none() -> None:
    assert FailureTag.from_string("definitely-not-a-tag") is None


def test_failure_tag_from_string_empty_returns_none() -> None:
    assert FailureTag.from_string("") is None
    assert FailureTag.from_string(None) is None


@pytest.mark.parametrize("tag", list(FailureTag))
def test_failure_tag_severity_in_range(tag: FailureTag) -> None:
    assert 0 <= tag.severity <= 3


def test_failure_tag_re_exported_from_planning_package() -> None:
    from src.ai.planning import FailureTag as PackageFailureTag

    assert PackageFailureTag is FailureTag
