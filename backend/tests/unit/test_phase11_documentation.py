"""Phase 11 Track 9 — documentation completeness + KPI cron presence."""
from __future__ import annotations

import importlib.util
import os
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
AI_ROOT = REPO_ROOT / "backend" / "src" / "ai"


# ---------------------------------------------------------------------------
# Per-package READMEs exist (Track 9 §3.2)
# ---------------------------------------------------------------------------


REQUIRED_README_PACKAGES = [
    "core", "planning", "memory", "meta", "governance", "tools",
]


@pytest.mark.parametrize("pkg", REQUIRED_README_PACKAGES)
def test_per_package_readme_exists(pkg: str) -> None:
    readme = AI_ROOT / pkg / "README.md"
    assert readme.exists(), f"Track 9 requires {readme.relative_to(REPO_ROOT)}"
    text = readme.read_text()
    # Templates ask for "What's in here / Key types / Entry points / See also".
    for required in ("What's in here", "Key types", "Entry points", "See also"):
        assert required in text, (
            f"{readme.relative_to(REPO_ROOT)} missing section: {required}"
        )


# ---------------------------------------------------------------------------
# Onboarding + INTERNAL_KEYS docs exist
# ---------------------------------------------------------------------------


def test_onboarding_doc_exists() -> None:
    assert (AI_ROOT / "ONBOARDING.md").exists()


def test_internal_keys_doc_exists() -> None:
    assert (AI_ROOT / "core" / "INTERNAL_KEYS.md").exists()


# ---------------------------------------------------------------------------
# Every key in INTERNAL_CONTEXT_KEYS is documented in INTERNAL_KEYS.md
# ---------------------------------------------------------------------------


def test_every_internal_key_documented() -> None:
    from src.ai.constants import INTERNAL_CONTEXT_KEYS
    doc = (AI_ROOT / "core" / "INTERNAL_KEYS.md").read_text()
    missing: list[str] = []
    for key in INTERNAL_CONTEXT_KEYS:
        # Keys appear in the table as `` `key` ``.
        pattern = f"`{re.escape(key)}`"
        if pattern not in doc:
            missing.append(key)
    assert not missing, (
        "INTERNAL_KEYS.md missing rows for: " + ", ".join(sorted(missing))
    )


# ---------------------------------------------------------------------------
# ...and the reverse: every key the table documents still exists in the
# constants set, so the doc can't rot by retaining a removed key
# (Phase 12 `07` §6 — INTERNAL_CONTEXT_KEYS doc enforcement, both directions).
# ---------------------------------------------------------------------------


def test_no_orphan_documented_internal_keys() -> None:
    from src.ai.constants import INTERNAL_CONTEXT_KEYS

    doc = (AI_ROOT / "core" / "INTERNAL_KEYS.md").read_text()
    # Inventory rows look like:  | `key` | writer | reader | ... |
    documented = set(re.findall(r"^\|\s*`([^`]+)`\s*\|", doc, flags=re.MULTILINE))
    assert documented, "could not parse any documented keys from INTERNAL_KEYS.md"
    orphans = sorted(k for k in documented if k not in INTERNAL_CONTEXT_KEYS)
    assert not orphans, (
        "INTERNAL_KEYS.md documents keys no longer in INTERNAL_CONTEXT_KEYS "
        "(remove the rows or restore the keys): " + ", ".join(orphans)
    )


# ---------------------------------------------------------------------------
# Phase 11 RETROSPECTIVE exists
# ---------------------------------------------------------------------------


def test_phase11_retrospective_exists() -> None:
    p = REPO_ROOT / "docs" / "phase11" / "RETROSPECTIVE.md"
    assert p.exists()
    text = p.read_text()
    for required in ("What landed", "What slipped", "KPI deltas",
                     "Recommended owners"):
        assert required in text, f"RETROSPECTIVE.md missing section: {required}"


# ---------------------------------------------------------------------------
# Dashboard SQL files exist
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("filename", [
    "01_run_health.sql",
    "02_cost.sql",
    "03_critic_pipeline.sql",
    "04_meta_agent.sql",
    "05_memory.sql",
    "06_loop_telemetry.sql",
])
def test_dashboard_query_exists(filename: str) -> None:
    p = REPO_ROOT / "infra" / "dashboards" / "phase11" / filename
    assert p.exists()
    # Sanity: SQL files should contain at least one SELECT.
    assert "SELECT" in p.read_text().upper()


# ---------------------------------------------------------------------------
# KPI migration + cron present
# ---------------------------------------------------------------------------


def test_kpi_migration_importable() -> None:
    mig = REPO_ROOT / "backend" / "migrations" / "versions" / "p11t09_kpi_daily_rollup.py"
    assert mig.exists()
    spec = importlib.util.spec_from_file_location("p11t09_kpi_daily_rollup", mig)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert hasattr(module, "upgrade") and hasattr(module, "downgrade")
    assert module.revision == "p11t09_kpi_rollup"
    assert module.down_revision == "p11t08_usage_attr"


def test_kpi_cron_registered() -> None:
    from src.ai.worker import WorkerSettings
    from src.ai.core.arq_jobs import kpi_rollup_refresh
    # The cron list contains the kpi refresh entry.
    assert any(
        getattr(cj, "coroutine", None) is kpi_rollup_refresh
        or getattr(cj, "name", "") == "kpi_rollup_refresh"
        for cj in WorkerSettings.cron_jobs
    ), "kpi_rollup_refresh cron must be registered in WorkerSettings"
