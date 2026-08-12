"""IntelligenceTree rule lifecycle — Phase 12 `06` §5.

Hermetic: the pure transition policy + prompt-eligibility filter. Locks in
candidate→confirmed→retired transitions and the no-regression default (legacy
rules without a lifecycle field stay eligible even under confirmed_only).
"""
from __future__ import annotations

from src.ai.memory.rule_lifecycle import (
    RuleLifecycle,
    filter_for_prompt,
    is_prompt_eligible,
    next_state,
)


def test_candidate_promotes_after_enough_validations() -> None:
    assert next_state("candidate", validations=3) is RuleLifecycle.CONFIRMED
    assert next_state("candidate", validations=2) is RuleLifecycle.CANDIDATE


def test_candidate_not_promoted_when_contradicted() -> None:
    assert next_state("candidate", validations=3, contradictions=2) is RuleLifecycle.CANDIDATE


def test_confirmed_retires_after_contradictions() -> None:
    assert next_state("confirmed", contradictions=3) is RuleLifecycle.RETIRED
    assert next_state("confirmed", contradictions=2) is RuleLifecycle.CONFIRMED


def test_retired_is_terminal() -> None:
    assert next_state("retired", validations=100) is RuleLifecycle.RETIRED


def test_unknown_state_treated_as_candidate() -> None:
    assert next_state("bogus", validations=3) is RuleLifecycle.CONFIRMED


def test_retired_never_prompt_eligible() -> None:
    assert not is_prompt_eligible({"lifecycle": "retired"}, confirmed_only=False)
    assert not is_prompt_eligible({"lifecycle": "retired"}, confirmed_only=True)


def test_confirmed_only_drops_explicit_candidates_keeps_legacy() -> None:
    rules = [
        {"rule": "a", "lifecycle": "confirmed"},
        {"rule": "b", "lifecycle": "candidate"},
        {"rule": "c"},  # legacy, no lifecycle field
        {"rule": "d", "lifecycle": "retired"},
    ]
    kept = filter_for_prompt(rules, confirmed_only=True)
    kept_rules = {r["rule"] for r in kept}
    assert kept_rules == {"a", "c"}  # confirmed + legacy; candidate + retired dropped


def test_permissive_keeps_all_but_retired() -> None:
    rules = [
        {"rule": "a", "lifecycle": "candidate"},
        {"rule": "b", "lifecycle": "confirmed"},
        {"rule": "c", "lifecycle": "retired"},
    ]
    kept = {r["rule"] for r in filter_for_prompt(rules, confirmed_only=False)}
    assert kept == {"a", "b"}
