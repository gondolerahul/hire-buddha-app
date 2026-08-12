"""Version-aware Meta-Agent reseed — Phase 12 `06` §6.3.

Hermetic: the pure reconcile_template logic. Locks in idempotency (no-op when
current), the version-gate, and that an evolved system_prompt survives a reseed.
"""
from __future__ import annotations

from src.ai.meta.reseed_meta_agent import reconcile_template, version_tuple


def _template(version="3.1.0", prompt="DEFAULT PROMPT v3.1"):
    return {
        "version": version,
        "identity": {"system_prompt": prompt, "role": "Agent Architect"},
        "logic_gate": {"x": 1},
        "planning": {"static_plan": {}},
        "governance": {},
        "metadata_extensions": {"is_meta_agent": True, "meta_agent_version": version},
    }


def test_version_tuple_parses() -> None:
    assert version_tuple("3.1.0") == (3, 1, 0)
    assert version_tuple("v3") == (3,)
    assert version_tuple("") == (0,)


def test_noop_when_already_current() -> None:
    existing = {"version": "3.1.0", "identity": {"system_prompt": "x"},
                "metadata_extensions": {"meta_agent_version": "3.1.0"}}
    assert reconcile_template(existing, _template("3.1.0")) is None


def test_noop_when_existing_newer() -> None:
    existing = {"version": "4.0.0", "identity": {"system_prompt": "x"},
                "metadata_extensions": {"meta_agent_version": "4.0.0"}}
    assert reconcile_template(existing, _template("3.1.0")) is None


def test_upgrade_preserves_evolved_prompt() -> None:
    existing = {
        "version": "3.0.0",
        "identity": {"system_prompt": "EVOLVED company-specific prompt"},
        "metadata_extensions": {"meta_agent_version": "3.0.0"},
    }
    merged = reconcile_template(existing, _template("3.1.0"))
    assert merged is not None
    # Plan/logic refreshed from the new template…
    assert merged["logic_gate"] == {"x": 1}
    assert merged["version"] == "3.1.0"
    # …but the evolved prompt is preserved, and flagged.
    assert merged["identity"]["system_prompt"] == "EVOLVED company-specific prompt"
    assert merged["metadata_extensions"]["prompt_preserved_on_reseed"] is True


def test_upgrade_uses_template_prompt_when_not_evolved() -> None:
    existing = {
        "version": "3.0.0",
        "identity": {"system_prompt": "DEFAULT PROMPT v3.1"},  # same as new default
        "metadata_extensions": {"meta_agent_version": "3.0.0"},
    }
    merged = reconcile_template(existing, _template("3.1.0", prompt="DEFAULT PROMPT v3.1"))
    assert merged is not None
    assert merged["identity"]["system_prompt"] == "DEFAULT PROMPT v3.1"
    assert "prompt_preserved_on_reseed" not in (merged.get("metadata_extensions") or {})
