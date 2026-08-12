"""ai.meta.spec_tiebreak — third-model tiebreak for high-stakes specs (`06` §4.3).

The board's spec-critic is already a *different* model from the Architect. For
**high-stakes** specs (a PROCESS with many children, or a cost projection near
the governance ceiling), Phase 12 adds an opt-in third-model adjudicator: when
the Architect and Critic disagree, a third model breaks the tie rather than
defaulting to REVISE. Default OFF (``meta_agent.spec_critic_tiebreak``); enabled
per company. The third model is injected so this is unit-testable.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

logger = logging.getLogger(__name__)

__all__ = ["is_high_stakes", "TiebreakResult", "SpecCriticTiebreaker"]


def is_high_stakes(
    spec: dict[str, Any],
    *,
    governance_ceiling_usd: float,
    max_children: int = 5,
    cost_proximity: float = 0.8,
) -> bool:
    """A spec is high-stakes if it is a wide PROCESS or projects near the ceiling."""
    spec_type = str(spec.get("type", "")).upper()
    children = spec.get("children") or spec.get("child_specs") or []
    if spec_type == "PROCESS" and len(children) > max_children:
        return True
    projected = float(spec.get("est_cost_usd", spec.get("cost_projection_usd", 0)) or 0)
    if governance_ceiling_usd > 0 and projected >= governance_ceiling_usd * cost_proximity:
        return True
    return False


@dataclass
class TiebreakResult:
    verdict: str            # PASS | REVISE | BLOCK
    invoked: bool = False   # whether the third model actually ran
    rationale: str = ""
    model_used: str = ""


def _disagree(architect_verdict: str, critic_verdict: str) -> bool:
    a = architect_verdict.upper()
    c = critic_verdict.upper()
    # Architect implicitly "votes" PASS by submitting; disagreement = critic
    # wants change (REVISE/BLOCK) while architect asserts ready (PASS).
    return a == "PASS" and c in {"REVISE", "BLOCK"}


class SpecCriticTiebreaker:
    """Adjudicates Architect↔Critic disagreement on high-stakes specs."""

    async def maybe_adjudicate(
        self,
        spec: dict[str, Any],
        architect_verdict: str,
        critic_verdict: str,
        *,
        llm: Any,
        governance_ceiling_usd: float,
        model_override: Optional[str] = None,
    ) -> TiebreakResult:
        if not _disagree(architect_verdict, critic_verdict):
            return TiebreakResult(verdict=critic_verdict.upper(), invoked=False,
                                  rationale="no disagreement")
        if not is_high_stakes(spec, governance_ceiling_usd=governance_ceiling_usd):
            # Not high-stakes: defer to the critic (the conservative default).
            return TiebreakResult(verdict=critic_verdict.upper(), invoked=False,
                                  rationale="not high-stakes; critic stands")

        from src.ai.shared.json_utils import parse_json_object

        system = (
            "You are a third independent reviewer breaking a tie on a HIGH-STAKES "
            "agent spec. The Architect says it is ready; the Critic wants changes. "
            "Decide who is right. Be decisive.\n"
            'Return JSON only: {"verdict":"PASS|REVISE|BLOCK","rationale":"..."}.'
        )
        user = (
            f"Spec: {str(spec)[:6000]}\n"
            f"Architect verdict: {architect_verdict}\nCritic verdict: {critic_verdict}\n"
            "Adjudicate."
        )
        try:
            response = await llm.call_llm(
                task_type="thinking", system_prompt=system, user_prompt=user,
                temperature=0.1, max_tokens=600, model_override=model_override,
            )
            output = getattr(response, "output", "") or ""
            model = getattr(response, "model_name", "") or (model_override or "")
        except Exception as exc:  # noqa: BLE001
            logger.warning("spec tiebreak LLM failed: %s", exc)
            return TiebreakResult(verdict=critic_verdict.upper(), invoked=False,
                                  rationale=f"tiebreak unavailable: {type(exc).__name__}")

        parsed = parse_json_object(output, warn_label="spec_tiebreak") or {}
        verdict = str(parsed.get("verdict", critic_verdict)).upper()
        if verdict not in {"PASS", "REVISE", "BLOCK"}:
            verdict = critic_verdict.upper()
        return TiebreakResult(verdict=verdict, invoked=True,
                              rationale=str(parsed.get("rationale", ""))[:400],
                              model_used=model)
