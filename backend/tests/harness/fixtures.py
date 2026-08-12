"""
tests/harness/fixtures.py — Loaders for entity / LLM / CORTEX fixtures.

The fixture tree lives at ``backend/tests/fixtures/``:

  entities/        canonical entity definitions (JSON, importable into the DB)
  llm/             pre-recorded LLM responses for hermetic runs
  cortex/          CORTEX tree seeds (JSON)
  meta_inputs/     Meta-Agent input fixtures
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.ai.schemas.entity import HierarchicalEntityCreate

FIXTURES_ROOT = Path(__file__).resolve().parent.parent / "fixtures"


def fixture_path(*parts: str) -> Path:
    return FIXTURES_ROOT.joinpath(*parts)


def load_entity_fixture(name: str) -> HierarchicalEntityCreate:
    """Read ``fixtures/entities/<name>.json`` and validate against the schema.

    Returns a ``HierarchicalEntityCreate``. Validation is the test that
    the fixture is well-formed for the current schemas package.
    """
    path = fixture_path("entities", f"{name}.json")
    payload = json.loads(path.read_text())
    return HierarchicalEntityCreate.model_validate(payload)


def load_entity_fixture_raw(name: str) -> dict[str, Any]:
    """Raw dict load — for tests that need to mutate the fixture."""
    path = fixture_path("entities", f"{name}.json")
    return json.loads(path.read_text())


def load_meta_input(name: str) -> dict[str, Any]:
    return json.loads(fixture_path("meta_inputs", f"{name}.json").read_text())


def list_entity_fixtures() -> list[str]:
    """Names (without extension) of every entity fixture on disk."""
    root = fixture_path("entities")
    if not root.exists():
        return []
    return sorted(p.stem for p in root.iterdir() if p.suffix == ".json")


def list_regression_cases() -> list[Path]:
    root = Path(__file__).resolve().parent.parent / "regression" / "cases"
    if not root.exists():
        return []
    return sorted(root.glob("*.yaml"))
