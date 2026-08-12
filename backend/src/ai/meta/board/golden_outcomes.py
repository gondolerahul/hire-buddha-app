"""ai.meta.board.golden_outcomes — TestDriver golden capture/compare (`06` §4.4).

When a human approves a DRAFT, its TestDriver outputs are snapshotted as
*goldens*. A future ADAPT of that entity is regression-tested against them so a
"improvement" that silently changes established behaviour is caught.

Pure functions over :class:`SuiteResult` so they are unit-testable and have no
storage opinion — the Promoter persists ``capture_goldens(...)`` onto the entity
(e.g. ``metadata_extensions.golden_outcomes``) on approval; the TestDriver calls
``regression_against_goldens(...)`` on the next ADAPT.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

__all__ = ["GoldenDiff", "capture_goldens", "regression_against_goldens", "goldens_passed"]


def capture_goldens(suite: Any) -> dict[str, str]:
    """Snapshot {case_name: output} for every passed, non-skipped case."""
    out: dict[str, str] = {}
    for case in getattr(suite, "cases", []):
        if getattr(case, "passed", False) and not getattr(case, "skipped", False):
            out[case.name] = (getattr(case, "output", "") or "")
    return out


@dataclass
class GoldenDiff:
    case: str
    kind: str            # "regressed" | "now_failing" | "missing"
    golden: str = ""
    actual: str = ""


@dataclass
class GoldenComparison:
    diffs: list[GoldenDiff] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.diffs


def regression_against_goldens(
    suite: Any,
    goldens: dict[str, str],
    *,
    normalize: bool = True,
) -> GoldenComparison:
    """Compare a fresh suite against stored goldens; report regressions.

    A case regresses if it now fails, its output diverged from the golden, or it
    is absent from the new run. Outputs are whitespace-normalised by default so
    cosmetic differences don't trip the gate.
    """
    def norm(s: str) -> str:
        return " ".join(s.split()) if normalize else s

    by_name = {c.name: c for c in getattr(suite, "cases", [])}
    diffs: list[GoldenDiff] = []
    for name, golden in goldens.items():
        case = by_name.get(name)
        if case is None or getattr(case, "skipped", False):
            diffs.append(GoldenDiff(case=name, kind="missing", golden=golden))
            continue
        if not getattr(case, "passed", False):
            diffs.append(GoldenDiff(case=name, kind="now_failing", golden=golden,
                                    actual=getattr(case, "output", "") or ""))
            continue
        actual = getattr(case, "output", "") or ""
        if norm(actual) != norm(golden):
            diffs.append(GoldenDiff(case=name, kind="regressed", golden=golden, actual=actual))
    return GoldenComparison(diffs=diffs)


def goldens_passed(suite: Any, goldens: dict[str, str], **kw: Any) -> bool:
    if not goldens:
        return True  # nothing to regress against
    return regression_against_goldens(suite, goldens, **kw).ok
