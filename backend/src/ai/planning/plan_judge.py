"""
ai.planning.plan_judge — Phase 11 Track 7 best-of-N candidate selector.

The :class:`PlanJudge` picks one :class:`PlanCandidate` out of two
(occasionally three) via a single LLM call. The prompt highlights:

  * The original goal and (when present) the supervisor-proposed
    subgoals.
  * The intelligence rules + anti-patterns surfaced for the run's
    ``task_class``.
  * Each candidate's steps, estimated cost, and invariant report.

The judge returns ``{"winner": idx, "scores": [...], "reasoning": "…"}``.
We always tiebreak by lower estimated cost when scores are within 0.10
of each other.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

__all__ = ["PlanJudge"]


_SYSTEM = (
    "You evaluate AI agent plans. Pick the candidate most likely to "
    "achieve the goal at the lowest cost. Reply with JSON only."
)


def _render_candidate(idx: int, cand: Any) -> str:
    steps = getattr(cand, "steps", None) or cand.get("steps", []) if isinstance(cand, dict) else []
    lines: list[str] = [f"### Candidate {idx}"]
    style = getattr(cand, "style", None) or (cand.get("style") if isinstance(cand, dict) else "?")
    cost = getattr(cand, "estimated_cost_usd", None) or (cand.get("estimated_cost_usd") if isinstance(cand, dict) else "?")
    lines.append(f"style={style} cost≈${cost}")
    for i, s in enumerate(steps[:10]):
        if not isinstance(s, dict):
            try:
                s = s.model_dump()                                          # pydantic
            except Exception:
                s = {"name": str(s)}
        name = s.get("name") or s.get("step_id") or f"step_{i}"
        stype = s.get("type", "?")
        lines.append(f"  - {name} ({stype})")
    if len(steps) > 10:
        lines.append(f"  …({len(steps) - 10} more steps)")
    return "\n".join(lines)


class PlanJudge:
    def __init__(self, llm_router: Any, db: Any = None):
        self.llm = llm_router
        self.db = db

    async def pick(
        self,
        candidates: list[Any],
        *,
        goal: str = "",
        intelligence_rules: Optional[list[Any]] = None,
        anti_patterns: Optional[list[Any]] = None,
        company_id: Optional[Any] = None,
    ) -> tuple[Any, list[float], str]:
        """Return ``(chosen_candidate, scores, reasoning)``.

        If the LLM call fails, falls back to lowest estimated cost.
        """
        if len(candidates) == 1:
            return candidates[0], [1.0], "only candidate"

        prompt_parts: list[str] = []
        if goal:
            prompt_parts.append(f"## Goal\n{goal}")
        if intelligence_rules:
            rules_block = "\n".join(
                f"  - {self._render_rule(r)}" for r in list(intelligence_rules)[:5]
            )
            prompt_parts.append("## Intelligence rules\n" + rules_block)
        if anti_patterns:
            ap_block = "\n".join(
                f"  - {self._render_rule(r)}" for r in list(anti_patterns)[:5]
            )
            prompt_parts.append("## Anti-patterns\n" + ap_block)
        prompt_parts.append(
            "## Candidates\n" +
            "\n".join(_render_candidate(i, c) for i, c in enumerate(candidates))
        )
        prompt_parts.append(
            "Respond with JSON only:\n"
            '{"winner": <0-based index>, '
            '"scores": [<one per candidate, 0..1>], '
            '"reasoning": "..."}'
        )
        user = "\n\n".join(prompt_parts)

        try:
            response = await self.llm.call_llm(
                task_type="text_generation",
                system_prompt=_SYSTEM,
                user_prompt=user,
                temperature=0.1,
                max_tokens=400,
            )
            parsed = self._parse(response.output, n=len(candidates))
            await self._log_attributed_usage(company_id, response, "planner")
        except Exception as exc:                                            # noqa: BLE001
            logger.warning(f"PlanJudge LLM call failed: {exc}; using cost tiebreak")
            scores = [0.0] * len(candidates)
            cheapest_idx = self._cheapest(candidates)
            return candidates[cheapest_idx], scores, f"fallback: cost tiebreak ({exc})"

        winner_idx = self._tiebreak(parsed["scores"], candidates,
                                    initial=parsed["winner"])
        return candidates[winner_idx], parsed["scores"], parsed.get("reasoning", "")

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _render_rule(rule: Any) -> str:
        if isinstance(rule, str):
            return rule[:200]
        if isinstance(rule, dict):
            return str(rule.get("text") or rule.get("rule") or rule.get("title") or rule)[:200]
        for attr in ("text", "rule", "title"):
            v = getattr(rule, attr, None)
            if v:
                return str(v)[:200]
        return str(rule)[:200]

    @staticmethod
    def _parse(output: Optional[str], n: int) -> dict[str, Any]:
        from src.ai.shared.json_utils import parse_json_object
        parsed = parse_json_object(output or "", warn_label="plan_judge") or {}
        try:
            winner = int(parsed.get("winner", 0))
        except (TypeError, ValueError):
            winner = 0
        winner = max(0, min(winner, n - 1))
        scores = parsed.get("scores") or []
        out_scores: list[float] = []
        for i in range(n):
            try:
                out_scores.append(float(scores[i]) if i < len(scores) else 0.0)
            except (TypeError, ValueError):
                out_scores.append(0.0)
        return {
            "winner": winner,
            "scores": out_scores,
            "reasoning": str(parsed.get("reasoning", ""))[:500],
        }

    @staticmethod
    def _cheapest(candidates: list[Any]) -> int:
        from decimal import Decimal
        best_idx = 0
        best_cost = Decimal("1e9")
        for i, c in enumerate(candidates):
            cost = getattr(c, "estimated_cost_usd", None)
            if cost is None and isinstance(c, dict):
                cost = c.get("estimated_cost_usd")
            try:
                cost = Decimal(str(cost or 0))
            except Exception:
                cost = Decimal("1e9")
            if cost < best_cost:
                best_cost = cost
                best_idx = i
        return best_idx

    async def _log_attributed_usage(
        self, company_id: Any, resp: Any, attribution: str,
    ) -> None:
        from src.ai.services.attributed_usage import log_llm_response_usage
        await log_llm_response_usage(
            db=self.db, response=resp, attribution=attribution,
            company_id=company_id,
        )

    @staticmethod
    def _tiebreak(scores: list[float], candidates: list[Any], *, initial: int) -> int:
        if not scores or len(scores) < 2:
            return initial
        top_score = max(scores)
        contenders = [i for i, s in enumerate(scores) if top_score - s <= 0.10]
        if len(contenders) <= 1:
            return initial
        cheapest_idx = PlanJudge._cheapest([candidates[i] for i in contenders])
        return contenders[cheapest_idx]
