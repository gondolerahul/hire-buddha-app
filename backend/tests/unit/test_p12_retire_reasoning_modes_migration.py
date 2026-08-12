"""Phase 12 (D-3) — data migration: REFLECTION/TREE_OF_THOUGHTS → REACT.

Tests the per-row rewrite helper (``rewrite_logic_gate``) in isolation plus the
revision-id hygiene the [[alembic-revision-id-32-char-limit]] note requires.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "migrations" / "versions" / "p12_retire_reasoning_modes.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("_p12_retire", _MIGRATION_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


mig = _load_migration()


def test_revision_id_within_32_char_cap() -> None:
    assert len(mig.revision) <= 32, f"revision id too long: {mig.revision!r}"
    assert mig.down_revision == "p11_execution_trace_events"


@pytest.mark.parametrize("mode", ["REFLECTION", "TREE_OF_THOUGHTS"])
def test_retired_modes_rewritten_to_react(mode) -> None:
    lg = {"reasoning_config": {"reasoning_mode": mode, "temperature": 0.5}}
    updated = mig.rewrite_logic_gate(lg)
    assert updated is not None
    assert updated["reasoning_config"]["reasoning_mode"] == "REACT"
    # Other config keys are preserved.
    assert updated["reasoning_config"]["temperature"] == 0.5
    # The original dict is not mutated in place.
    assert lg["reasoning_config"]["reasoning_mode"] == mode


@pytest.mark.parametrize("mode", ["REACT", "CHAIN_OF_THOUGHT"])
def test_supported_modes_untouched(mode) -> None:
    lg = {"reasoning_config": {"reasoning_mode": mode}}
    assert mig.rewrite_logic_gate(lg) is None


@pytest.mark.parametrize("lg", [
    None,
    {},
    {"reasoning_config": None},
    {"reasoning_config": {}},
    {"reasoning_config": {"reasoning_mode": None}},
    "not-a-dict",
])
def test_noop_shapes_return_none(lg) -> None:
    assert mig.rewrite_logic_gate(lg) is None


def test_case_insensitive_match() -> None:
    lg = {"reasoning_config": {"reasoning_mode": "reflection"}}
    updated = mig.rewrite_logic_gate(lg)
    assert updated is not None
    assert updated["reasoning_config"]["reasoning_mode"] == "REACT"
