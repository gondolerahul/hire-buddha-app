"""tests/eval/config.py — named A/B configs for the eval harness (`07` §5).

An ``EvalConfig`` is a named bundle of feature-flag (bool) and numeric
overrides applied for the duration of a corpus replay. The harness runs the
same corpus under two configs and diffs the metrics. Concrete pairs the plan
names: deterministic-vs-LLM Strategist (`06` §3.2), task-classifier v1-vs-v2
(`06` §5), critic model A-vs-B.

The overrides are applied as global feature-flag rows for the run and removed
after — kept declarative here so the harness owns the apply/teardown.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict

__all__ = ["EvalConfig", "BASELINE"]


@dataclass(frozen=True)
class EvalConfig:
    name: str
    bool_flags: Dict[str, bool] = field(default_factory=dict)
    numeric_flags: Dict[str, float] = field(default_factory=dict)

    def describe(self) -> str:
        parts = [f"{k}={v}" for k, v in {**self.bool_flags, **self.numeric_flags}.items()]
        return f"{self.name}({', '.join(parts) or 'defaults'})"


# The no-override baseline: whatever the defaults resolve to.
BASELINE = EvalConfig(name="baseline")
