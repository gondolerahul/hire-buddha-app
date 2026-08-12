"""Phase 11 Track 5 — resolve_meta_cognition default-flip tests."""
from __future__ import annotations

from types import SimpleNamespace

from src.ai.meta.platform_schema_compiler import resolve_meta_cognition


def _entity(
    *,
    type="AGENT",
    capabilities=None,
    metadata_extensions=None,
    planning=None,
    logic_gate=None,
) -> SimpleNamespace:
    return SimpleNamespace(
        type=type,
        capabilities=dict(capabilities or {}),
        metadata_extensions=dict(metadata_extensions or {}),
        planning=dict(planning or {}),
        logic_gate=dict(logic_gate or {}),
    )


def test_agent_defaults_to_opt_in_off() -> None:
    cfg = resolve_meta_cognition(_entity(type="AGENT"))
    assert cfg["registry_search"] is False
    assert cfg["self_modification"] is False


def test_process_defaults_to_opt_in_off() -> None:
    cfg = resolve_meta_cognition(_entity(type="PROCESS"))
    assert cfg["registry_search"] is False
    assert cfg["self_modification"] is False


def test_explicit_true_preserved() -> None:
    cfg = resolve_meta_cognition(_entity(
        capabilities={"meta_cognition": {
            "registry_search": True, "self_modification": True,
        }},
    ))
    assert cfg["registry_search"] is True
    assert cfg["self_modification"] is True


def test_meta_agent_auto_opt_in() -> None:
    cfg = resolve_meta_cognition(_entity(
        type="AGENT",
        metadata_extensions={"is_meta_agent": True},
    ))
    assert cfg["registry_search"] is True
    assert cfg["self_modification"] is True


def test_meta_agent_explicit_false_overridden_by_meta_flag() -> None:
    # If you say is_meta_agent=true, you must mean it; meta-agent always
    # gets the tiers regardless of what the explicit dict says.
    cfg = resolve_meta_cognition(_entity(
        type="AGENT",
        capabilities={"meta_cognition": {
            "registry_search": False, "self_modification": False,
        }},
        metadata_extensions={"is_meta_agent": True},
    ))
    assert cfg["registry_search"] is True
    assert cfg["self_modification"] is True


def test_platform_awareness_still_auto_for_react() -> None:
    cfg = resolve_meta_cognition(_entity(
        type="SKILL",
        logic_gate={"reasoning_config": {"reasoning_mode": "REACT"}},
    ))
    assert cfg["platform_awareness"] is True
