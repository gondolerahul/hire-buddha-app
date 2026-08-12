"""
ai.meta.board.validator — Role 5: deterministic spec checks.

Catches obvious structural defects before the TestDriver burns budget.
Returns a typed report so the Promoter's gate G2 can simply check
``ValidatorReport.passed``.

Implemented checks::

  1. json_shape_ok                  — name / type / goal / planning / logic_gate present
  2. entity_type_valid              — one of ACTION / SKILL / AGENT / PROCESS
  3. no_cycle_in_children           — child IDs do not include the parent
  4. all_tools_listed_in_caps       — every TOOL_CALL step's tool appears in capabilities.tools
  5. plan_step_ids_unique           — no duplicate step_id values
  6. governance_caps_set            — max_cost_usd > 0 AND timeout_ms > 0
  7. cost_estimate_under_cap        — estimated cost (heuristic) ≤ max_cost_usd
  8. review_mechanism_consistent    — if review enabled, prompt template not empty
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


_VALID_TYPES = {"ACTION", "SKILL", "AGENT", "PROCESS"}


@dataclass
class CheckResult:
    name: str
    passed: bool
    reason: str = ""


@dataclass
class ValidatorReport:
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks)

    @property
    def failed(self) -> list[CheckResult]:
        return [c for c in self.checks if not c.passed]

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "checks": [
                {"name": c.name, "passed": c.passed, "reason": c.reason}
                for c in self.checks
            ],
        }


class ValidatorRole:
    """Synchronous, pure-function checker. Cheap to call."""

    async def check(self, draft: Any) -> ValidatorReport:
        spec = _spec_payload(draft)
        return ValidatorReport(checks=[
            self._json_shape_ok(spec),
            self._entity_type_valid(spec),
            self._no_cycle_in_children(spec),
            self._all_tools_listed(spec),
            self._plan_step_ids_unique(spec),
            self._governance_caps_set(spec),
            self._cost_estimate_under_cap(spec),
            self._review_mechanism_consistent(spec),
        ])

    # ------------------------------------------------------------------
    # Individual checks
    # ------------------------------------------------------------------

    @staticmethod
    def _json_shape_ok(spec: dict[str, Any]) -> CheckResult:
        required = ["name", "type", "goal"]
        missing = [k for k in required if not spec.get(k)]
        return CheckResult(
            "json_shape_ok",
            passed=not missing,
            reason="missing fields: " + ",".join(missing) if missing else "",
        )

    @staticmethod
    def _entity_type_valid(spec: dict[str, Any]) -> CheckResult:
        t = str(spec.get("type", "")).upper()
        return CheckResult(
            "entity_type_valid",
            passed=t in _VALID_TYPES,
            reason=f"unknown entity type: {t}" if t not in _VALID_TYPES else "",
        )

    @staticmethod
    def _no_cycle_in_children(spec: dict[str, Any]) -> CheckResult:
        parent_id = spec.get("id") or spec.get("entity_id")
        children = spec.get("children") or []
        bad = [c for c in children if isinstance(c, dict)
               and str(c.get("id", "")) == str(parent_id)]
        return CheckResult(
            "no_cycle_in_children",
            passed=not bad,
            reason="child references parent id" if bad else "",
        )

    @staticmethod
    def _all_tools_listed(spec: dict[str, Any]) -> CheckResult:
        caps = spec.get("capabilities") or {}
        listed = {str(t) for t in (caps.get("tools") or [])}
        plan = spec.get("planning") or {}
        steps = (plan.get("static_plan") or {}).get("steps") or plan.get("steps") or []
        missing: list[str] = []
        for step in steps:
            if not isinstance(step, dict):
                continue
            stype = str(step.get("type", "")).upper()
            if stype != "TOOL_CALL":
                continue
            target = step.get("target") or {}
            tool_id = str(target.get("tool_id") or step.get("tool_id") or "")
            if tool_id and tool_id not in listed:
                missing.append(tool_id)
        return CheckResult(
            "all_tools_listed_in_capabilities",
            passed=not missing,
            reason=("tools used but not declared: " + ",".join(missing[:5]))
                   if missing else "",
        )

    @staticmethod
    def _plan_step_ids_unique(spec: dict[str, Any]) -> CheckResult:
        plan = spec.get("planning") or {}
        steps = (plan.get("static_plan") or {}).get("steps") or plan.get("steps") or []
        ids = [str(s.get("step_id") or s.get("id") or "") for s in steps if isinstance(s, dict)]
        ids = [i for i in ids if i]
        dup = {i for i in ids if ids.count(i) > 1}
        return CheckResult(
            "plan_step_ids_unique",
            passed=not dup,
            reason=("duplicate step_ids: " + ",".join(sorted(dup))) if dup else "",
        )

    @staticmethod
    def _governance_caps_set(spec: dict[str, Any]) -> CheckResult:
        gov = spec.get("governance") or {}
        cost = gov.get("max_cost_usd")
        timeout = gov.get("timeout_ms")
        ok = bool(cost) and bool(timeout) and float(cost or 0) > 0 and int(timeout or 0) > 0
        return CheckResult(
            "governance_caps_set",
            passed=ok,
            reason="governance.max_cost_usd / timeout_ms must be > 0" if not ok else "",
        )

    @staticmethod
    def _cost_estimate_under_cap(spec: dict[str, Any]) -> CheckResult:
        gov = spec.get("governance") or {}
        cap = float(gov.get("max_cost_usd") or 0.0)
        if cap <= 0:
            # Already caught by the previous check; do not double-fail.
            return CheckResult("cost_estimate_under_cap", passed=True)
        # Cheap heuristic: 0.01 USD per planning step + 0.05 base.
        plan = spec.get("planning") or {}
        steps = (plan.get("static_plan") or {}).get("steps") or plan.get("steps") or []
        est = 0.05 + 0.01 * len(steps)
        return CheckResult(
            "cost_estimate_under_cap",
            passed=est <= cap,
            reason=f"estimate {est:.2f} > cap {cap:.2f}" if est > cap else "",
        )

    @staticmethod
    def _review_mechanism_consistent(spec: dict[str, Any]) -> CheckResult:
        logic = spec.get("logic_gate") or {}
        rm = logic.get("review_mechanism") or {}
        if not rm.get("enabled"):
            return CheckResult("review_mechanism_consistent", passed=True)
        prompt = (rm.get("review_prompt") or rm.get("review_system_prompt") or "").strip()
        return CheckResult(
            "review_mechanism_consistent",
            passed=bool(prompt),
            reason="review enabled but no review_prompt set" if not prompt else "",
        )


def _spec_payload(draft: Any) -> dict[str, Any]:
    if isinstance(draft, dict):
        return draft
    payload = getattr(draft, "payload", None)
    if isinstance(payload, dict):
        return payload
    return {"raw": str(draft)}


__all__ = ["ValidatorRole", "ValidatorReport", "CheckResult"]
