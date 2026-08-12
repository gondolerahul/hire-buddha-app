"""
ai.meta.board.promoter — Role 7: 6-gate promotion guard.

Reads the Board outputs (CriticReport / ValidatorReport / SuiteResult
+ Curator decision) and either flips the draft entity to ACTIVE, raises
a HITL request, or rejects with structured ``failed_gates``.

Gates:

  G1 — Critic verdict is PASS (no unresolved BLOCK)
  G2 — Validator report passed all deterministic checks
  G3 — TestDriver suite passed (smoke + every non-skipped case)
  G4 — TestDriver did not blow its budget
  G5 — Curator decision is recorded (any decision is allowed; missing → fail)
  G6 — Runtime cost cap is set (governance.max_cost_usd > 0)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Optional


@dataclass
class PromoterGateResult:
    name: str
    passed: bool
    reason: str = ""


@dataclass
class PromotionDecision:
    outcome: str                                   # PROMOTED / REJECT / PENDING_HITL
    failed_gates: list[str] = field(default_factory=list)
    reason: str = ""
    entity_id: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome,
            "failed_gates": list(self.failed_gates),
            "reason": self.reason,
            "entity_id": self.entity_id,
        }


class Promoter:
    """Run the 6 gates and apply the lifecycle flip when allowed."""

    def __init__(self, *, hitl_required: bool = False, flip_callback: Any = None) -> None:
        self.hitl_required = hitl_required
        # flip_callback(draft) -> str entity_id ; injectable so tests
        # don't need a live DB.
        self.flip_callback = flip_callback

    async def promote(
        self,
        *,
        draft: Any,
        critic_report: Any,
        validator_report: Any,
        suite_result: Any,
        curator_decision: Any,
    ) -> PromotionDecision:
        gates = [
            self._g1(critic_report),
            self._g2(validator_report),
            self._g3(suite_result),
            self._g4(suite_result),
            self._g5(curator_decision),
            self._g6(draft),
        ]
        failures = [g for g in gates if not g.passed]
        if failures:
            return PromotionDecision(
                outcome="REJECT",
                failed_gates=[g.name for g in failures],
                reason="; ".join(g.reason for g in failures if g.reason),
            )

        if self.hitl_required:
            return PromotionDecision(outcome="PENDING_HITL")

        entity_id = None
        if self.flip_callback is not None:
            try:
                entity_id = await self.flip_callback(draft)
            except Exception as exc:                                        # noqa: BLE001
                return PromotionDecision(
                    outcome="REJECT",
                    failed_gates=["FLIP"],
                    reason=f"flip-to-active failed: {type(exc).__name__}: {exc}",
                )
        return PromotionDecision(outcome="PROMOTED", entity_id=entity_id)

    # ------------------------------------------------------------------
    # Individual gates
    # ------------------------------------------------------------------

    @staticmethod
    def _g1(report: Any) -> PromoterGateResult:
        verdict = getattr(report, "verdict", "REVISE")
        ok = verdict == "PASS"
        return PromoterGateResult(
            "G1_critic_clean",
            passed=ok,
            reason=f"Critic verdict={verdict}" if not ok else "",
        )

    @staticmethod
    def _g2(report: Any) -> PromoterGateResult:
        passed = getattr(report, "passed", False)
        failed = list(getattr(report, "failed", []))
        return PromoterGateResult(
            "G2_validator_clean",
            passed=passed,
            reason=(
                "; ".join(f"{c.name}:{c.reason}" for c in failed[:3])
                if not passed else ""
            ),
        )

    @staticmethod
    def _g3(suite: Any) -> PromoterGateResult:
        passed = getattr(suite, "passed", False)
        return PromoterGateResult(
            "G3_test_suite_pass",
            passed=passed,
            reason="TestDriver suite failed" if not passed else "",
        )

    @staticmethod
    def _g4(suite: Any) -> PromoterGateResult:
        exhausted = bool(getattr(suite, "budget_exhausted", False))
        return PromoterGateResult(
            "G4_test_budget_ok",
            passed=not exhausted,
            reason="TestDriver budget exhausted" if exhausted else "",
        )

    @staticmethod
    def _g5(decision: Any) -> PromoterGateResult:
        d = getattr(decision, "decision", None)
        return PromoterGateResult(
            "G5_curator_recorded",
            passed=bool(d),
            reason="Curator decision missing" if not d else "",
        )

    @staticmethod
    def _g6(draft: Any) -> PromoterGateResult:
        spec = draft.payload if hasattr(draft, "payload") else draft
        if not isinstance(spec, dict):
            return PromoterGateResult(
                "G6_runtime_cost_cap_set", passed=False, reason="draft has no payload",
            )
        gov = spec.get("governance") or {}
        cap = gov.get("max_cost_usd") or 0
        try:
            ok = Decimal(str(cap)) > 0
        except Exception:
            ok = False
        return PromoterGateResult(
            "G6_runtime_cost_cap_set",
            passed=ok,
            reason="governance.max_cost_usd must be > 0" if not ok else "",
        )


__all__ = ["Promoter", "PromotionDecision", "PromoterGateResult"]
