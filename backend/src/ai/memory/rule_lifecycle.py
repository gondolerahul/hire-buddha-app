"""memory.rule_lifecycle — IntelligenceTree rule lifecycle (Phase 12 `06` §5).

The review noted the candidate→confirmed→retired lifecycle needs to be *explicit*
and that **only confirmed rules should enter planner/critic prompts by default**.
This module is the host-side policy:

  * :func:`next_state` — the pure transition policy. Dreaming validates a
    ``candidate`` against subsequent runs; enough corroboration promotes it to
    ``confirmed``; a ``confirmed`` rule that stops predicting is ``retired``.
  * :func:`filter_for_prompt` — keep only prompt-eligible rules. With
    ``confirmed_only`` (gated by ``memory.rule_lifecycle_confirmed_only``), a rule
    carrying an explicit non-confirmed lifecycle is dropped; rules with no
    lifecycle field (legacy) are kept so enabling the gate never blanks prompts.

Kept pure + host-side so it does not destabilise the published ``cortex_memory``
package; the package stamps the ``lifecycle`` field, the host enforces it.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, List

__all__ = [
    "RuleLifecycle",
    "PROMOTE_AFTER",
    "RETIRE_AFTER",
    "next_state",
    "is_prompt_eligible",
    "filter_for_prompt",
]


class RuleLifecycle(str, Enum):
    CANDIDATE = "candidate"
    CONFIRMED = "confirmed"
    RETIRED = "retired"


# A candidate needs this many net validations to be confirmed; a confirmed rule
# is retired after this many net contradictions.
PROMOTE_AFTER = 3
RETIRE_AFTER = 3


def next_state(
    current: str,
    *,
    validations: int = 0,
    contradictions: int = 0,
) -> RuleLifecycle:
    """Pure transition policy over accumulated validate/contradict evidence."""
    try:
        state = RuleLifecycle(str(current or "candidate").lower())
    except ValueError:
        state = RuleLifecycle.CANDIDATE

    net = validations - contradictions
    if state is RuleLifecycle.RETIRED:
        return RuleLifecycle.RETIRED
    if state is RuleLifecycle.CANDIDATE:
        if net >= PROMOTE_AFTER:
            return RuleLifecycle.CONFIRMED
        return RuleLifecycle.CANDIDATE
    # CONFIRMED
    if contradictions - validations >= RETIRE_AFTER:
        return RuleLifecycle.RETIRED
    return RuleLifecycle.CONFIRMED


def _lifecycle_of(rule: Any) -> str:
    if isinstance(rule, dict):
        return str(rule.get("lifecycle") or "").lower()
    return str(getattr(rule, "lifecycle", "") or "").lower()


def is_prompt_eligible(rule: Any, *, confirmed_only: bool) -> bool:
    """Whether a rule may be injected into a planner/critic prompt."""
    lifecycle = _lifecycle_of(rule)
    if lifecycle == RuleLifecycle.RETIRED.value:
        return False
    if confirmed_only:
        # Drop only rules with an explicit non-confirmed lifecycle; keep legacy
        # rules (no lifecycle field) so enabling the gate never blanks prompts.
        if lifecycle and lifecycle != RuleLifecycle.CONFIRMED.value:
            return False
    return True


def filter_for_prompt(rules: List[Any], *, confirmed_only: bool) -> List[Any]:
    return [r for r in rules if is_prompt_eligible(r, confirmed_only=confirmed_only)]
