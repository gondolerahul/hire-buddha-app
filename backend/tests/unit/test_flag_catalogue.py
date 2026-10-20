"""ON-16: the flag catalogue (docs/reference/feature-flags.md) is the code's.

The onboarding doc's "42 boolean + 5 numeric flags" was a count nothing kept
true, and the catalogue listed flags deleted months before. This keeps its
rows and its counts equal to ``DEFAULTS`` and ``NUMERIC_DEFAULTS``.
"""
from __future__ import annotations

import re
from pathlib import Path

from src.ai.core.feature_flags import DEFAULTS, NUMERIC_DEFAULTS

DOC = Path(__file__).resolve().parents[3] / "docs" / "reference" / "feature-flags.md"


def _catalogue() -> str:
    text = DOC.read_text(encoding="utf-8")
    return text[text.index("## Feature flags"):]


def _rows() -> dict[str, str]:
    """Flag -> default, for every catalogue row; a deleted flag's default is ``—``."""
    return {key: default.strip() for key, default in
            re.findall(r"^\| `([a-z_][a-z0-9_.]*)` \| ([^|]*)\|", _catalogue(), re.M)}


def test_every_declared_flag_has_a_row_and_every_row_is_declared() -> None:
    live = {key for key, default in _rows().items() if default != "—"}
    declared = set(DEFAULTS) | set(NUMERIC_DEFAULTS)
    assert sorted(declared - live) == [], "declared flags missing from the catalogue"
    assert sorted(live - declared) == [], "catalogue rows for flags the code no longer declares (mark them — or drop them)"


def test_the_catalogue_counts_are_the_codes() -> None:
    head = _catalogue()[:600]
    assert f"**{len(DEFAULTS)} boolean flags**" in head
    assert f"**{len(NUMERIC_DEFAULTS)} numeric flags**" in head
