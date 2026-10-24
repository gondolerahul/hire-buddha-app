"""The money settings reference is current (Phase 15 T10-5): regenerate it with
``python scripts/settings_census.py --write`` after adding or changing a setting."""
from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "settings_census.py"


def test_the_reference_matches_the_catalogue():
    spec = importlib.util.spec_from_file_location("settings_census", SCRIPT)
    census = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(census)
    assert census.OUT.read_text(encoding="utf-8") == census.render(), "run scripts/settings_census.py --write"
