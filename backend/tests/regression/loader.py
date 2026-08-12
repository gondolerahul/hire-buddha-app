"""
tests/regression/loader.py — Discover + load YAML regression cases.

YAML choice: human-editable and PR-reviewable. ``PyYAML`` is already a
backend dependency.
"""
from __future__ import annotations

from pathlib import Path
from typing import List

import yaml

from tests.regression.case_schema import RegressionCase

CASES_DIR = Path(__file__).resolve().parent / "cases"


def discover_case_files() -> List[Path]:
    """Every ``*.yaml`` under ``cases/``, sorted for stable test order."""
    if not CASES_DIR.exists():
        return []
    return sorted(CASES_DIR.glob("*.yaml"))


def load_case(path: Path) -> RegressionCase:
    payload = yaml.safe_load(path.read_text())
    if not isinstance(payload, dict):
        raise ValueError(
            f"{path.name}: top-level must be a mapping, got {type(payload).__name__}"
        )
    return RegressionCase.model_validate(payload)


def load_all_cases() -> List[RegressionCase]:
    return [load_case(p) for p in discover_case_files()]
