"""
ai.planning.supervisor_critic — Phase 11 Track 4 supervisor critic.

Replaces ``ai.core.meta_review.MetaReviewer.review_execution`` as the
"is this run on track?" decision-maker. Unlike the legacy one-shot
LLM call, ``SupervisorCritic.assess(state)``:

  * reads the full :class:`AgentState` (reflections, blockers,
    health_records, budget, open subgoals, task class);
  * short-circuits with a deterministic ABORT when budget pressure is
    catastrophic (≥0.95);
  * short-circuits with CONTINUE when the last N health records are
    clean (no LLM call);
  * only invokes the LLM when the fast paths are inconclusive;
  * returns a :class:`SupervisorVerdict` with optional
    ``proposed_subgoals`` populated on REPLAN.

The class is instantiated by :class:`RealCriticPipeline`; tests can
construct it directly with a stub LLM.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Optional, cast
from uuid import uuid4

from src.ai.core.agent_state import (
    AgentState,
    Subgoal,
    SupervisorVerdict,
)

logger = logging.getLogger(__name__)

__all__ = [
    "SupervisorCritic",
    "SupervisorCriticConfig",
]


_SYSTEM_PROMPT = (
    "You are the Supervisor of an autonomous AI agent. You review the "
    "current run's state — reflections, recent step health, open "
    "subgoals, and budget — and decide whether to CONTINUE, REPLAN, "
    "ABORT, or PAUSE. Be conservative: recommend ABORT only on clear "
    "failure or budget risk; recommend PAUSE only when human input is "
    "essential. When recommending REPLAN you may propose new subgoals "
    "that replace the current open subgoals."
)


@dataclass
class SupervisorCriticConfig:
    fast_path_enabled: bool = True
    fast_path_window: int = 3
    abort_pressure_threshold: float = 0.95
    max_tokens: int = 600
    temperature: float = 0.2
    critic_model_override: Optional[str] = None
    entity_goal: str = ""

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "SupervisorCriticConfig":
        if not raw:
            return cls()
        return cls(
            fast_path_enabled=bool(raw.get("fast_path_enabled", True)),
            fast_path_window=int(raw.get("fast_path_window", 3)),
            abort_pressure_threshold=float(raw.get("abort_pressure_threshold", 0.95)),
            max_tokens=int(raw.get("max_tokens", 600)),
            temperature=float(raw.get("temperature", 0.2)),
            critic_model_override=raw.get("critic_model_override"),
            entity_goal=str(raw.get("entity_goal", "") or ""),
        )


class SupervisorCritic:
    """Calibrated supervisor verdict producer."""

    def __init__(
        self,
        *,
        llm_router: Any = None,
        intelligence_reader: Any = None,
        config: Optional[SupervisorCriticConfig | dict[str, Any]] = None,
    ):
        self.llm = llm_router
        self.intel = intelligence_reader
        if isinstance(config, dict):
            self.config = SupervisorCriticConfig.from_dict(config)
        elif isinstance(config, SupervisorCriticConfig):
            self.config = config
        else:
            self.config = SupervisorCriticConfig()
        self._last_cost_usd: Decimal = Decimal("0")
        self._last_response: Any = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def assess(self, state: AgentState) -> SupervisorVerdict:
        self._last_cost_usd = Decimal("0")
        self._last_response = None

        # 1. Budget-pressure short-circuit.
        if state.budget.pressure >= self.config.abort_pressure_threshold:
            return SupervisorVerdict(
                recommendation="ABORT",
                confidence=0.95,
                reasoning=(
                    f"Budget pressure {state.budget.pressure:.2f} "
                    f"≥ {self.config.abort_pressure_threshold:.2f}"
                ),
            )

        # 2. Fast path — N consecutive clean health records.
        if self.config.fast_path_enabled and self._fast_path_continue(state):
            return SupervisorVerdict(
                recommendation="CONTINUE",
                confidence=0.85,
                reasoning=(
                    f"{self.config.fast_path_window} consecutive clean steps; "
                    "skipping supervisor LLM."
                ),
            )

        # 3. LLM-driven assessment.
        if self.llm is None:
            return SupervisorVerdict(
                recommendation="CONTINUE",
                confidence=0.5,
                reasoning="No LLM router available; defaulting to CONTINUE.",
            )

        try:
            prompt = self._build_prompt(state)
            response = await self.llm.call_llm(
                task_type="text_generation",
                system_prompt=_SYSTEM_PROMPT,
                user_prompt=prompt,
                temperature=self.config.temperature,
                max_tokens=self.config.max_tokens,
                model_override=self.config.critic_model_override,
            )
            self._last_cost_usd = self._extract_cost(response)
            self._last_response = response
            parsed = self._parse(response.output)
        except Exception as exc:                                            # noqa: BLE001
            logger.warning("SupervisorCritic LLM call failed: %s", exc)
            return SupervisorVerdict(
                recommendation="CONTINUE",
                confidence=0.4,
                reasoning=f"Supervisor LLM error: {type(exc).__name__}",
            )

        return self._build_verdict(parsed)

    @property
    def last_cost_usd(self) -> Decimal:
        return self._last_cost_usd

    @property
    def last_response(self) -> Any:
        return self._last_response

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _fast_path_continue(self, state: AgentState) -> bool:
        window = max(1, self.config.fast_path_window)
        recent = list(getattr(state, "health_records", []) or [])[-window:]
        if len(recent) < window:
            return False
        for h in recent:
            if getattr(h, "post_critic_verdict", None) != "PASS":
                return False
            aligned = getattr(h, "alignment_aligned", None)
            if aligned is False:
                return False
        return True

    def _build_prompt(self, state: AgentState) -> str:
        lines: list[str] = []
        b = state.budget
        lines.append(f"## Iteration: {state.iteration} / {b.iters_max}")
        lines.append(
            f"## Budget: USD ${b.usd_used} / ${b.usd_max}, "
            f"tokens {b.tokens_used}/{b.tokens_max}, "
            f"wall {b.wall_used_s}s/{b.wall_max_s}s, "
            f"pressure={b.pressure:.2f}"
        )
        if self.config.entity_goal:
            lines.append(f"## Goal: {self.config.entity_goal}")
        lines.append(f"## Task class: {state.task_class}")
        lines.append(f"## Open subgoals ({len(state.open_subgoals)}):")
        for g in state.open_subgoals[:10]:
            blocked = f" (blocked: {g.blocked_on})" if g.blocked_on else ""
            lines.append(f"  - {g.description}{blocked}")
        if state.blockers:
            lines.append(f"## Blockers ({len(state.blockers)}):")
            for blk in state.blockers[-5:]:
                lines.append(f"  - {blk.kind}: {blk.detail[:120]}")
        if state.reflections:
            lines.append("## Recent reflections (last 3):")
            for r in state.reflections[-3:]:
                lines.append(
                    f"  - worked={r.what_worked or '∅'} | "
                    f"didnt={r.what_didnt or '∅'}"
                )
        recent_h = list(getattr(state, "health_records", []) or [])[-5:]
        if recent_h:
            lines.append("## Recent step health (last 5):")
            for h in recent_h:
                tags = ",".join(t.value for t in getattr(h, "post_critic_tags", []))
                lines.append(
                    f"  - step={getattr(h, 'step_id', '?')} "
                    f"post={getattr(h, 'post_critic_verdict', '-')} "
                    f"tags=[{tags}]"
                )
        rules_block = self._render_rules(state)
        if rules_block:
            lines.append("## Intelligence rules (top 3):")
            lines.append(rules_block)
        lines.append("")
        lines.append("Respond with JSON only:")
        lines.append(
            '{"recommendation":"CONTINUE|REPLAN|ABORT|PAUSE",'
            '"confidence":0.0-1.0,'
            '"reasoning":"...",'
            '"proposed_subgoals":[{"description":"...","priority":1}]}'
        )
        return "\n".join(lines)

    @staticmethod
    def _render_rules(state: AgentState) -> str:
        perception = getattr(state, "perception", None)
        rules = getattr(perception, "intelligence_rules", None) if perception else None
        if not rules:
            return ""
        out: list[str] = []
        for r in list(rules)[:3]:
            if isinstance(r, dict):
                text = r.get("rule") or r.get("title") or r.get("text") or ""
            else:
                text = getattr(r, "text", None) or getattr(r, "rule", None) or str(r)
            if text:
                out.append(f"  - {str(text)[:160]}")
        return "\n".join(out)

    @staticmethod
    def _parse(output: Optional[str]) -> dict[str, Any]:
        if not output:
            return {"recommendation": "CONTINUE", "confidence": 0.4,
                    "reasoning": "Empty supervisor response."}
        from src.ai.shared.json_utils import parse_json_object
        obj = parse_json_object(output, warn_label="supervisor_critic")
        if not obj:
            return {"recommendation": "CONTINUE", "confidence": 0.4,
                    "reasoning": "Could not parse supervisor JSON."}
        return obj

    @staticmethod
    def _build_verdict(parsed: dict[str, Any]) -> SupervisorVerdict:
        rec = str(parsed.get("recommendation", "CONTINUE")).upper()
        if rec not in {"CONTINUE", "REPLAN", "ABORT", "PAUSE"}:
            rec = "CONTINUE"
        try:
            confidence = float(parsed.get("confidence", 0.5))
        except (TypeError, ValueError):
            confidence = 0.5
        confidence = max(0.0, min(1.0, confidence))
        reasoning = str(parsed.get("reasoning", ""))[:1000]
        proposed: list[Subgoal] = []
        if rec == "REPLAN":
            for s in parsed.get("proposed_subgoals") or []:
                if not isinstance(s, dict):
                    continue
                desc = str(s.get("description", "")).strip()
                if not desc:
                    continue
                try:
                    priority = int(s.get("priority", 0))
                except (TypeError, ValueError):
                    priority = 0
                proposed.append(Subgoal(
                    id=str(uuid4()),
                    description=desc[:200],
                    priority=priority,
                ))
        return SupervisorVerdict(
            recommendation=cast(Any, rec),
            confidence=confidence,
            reasoning=reasoning,
            proposed_subgoals=proposed,
        )

    @staticmethod
    def _extract_cost(response: Any) -> Decimal:
        for attr in ("cost_usd", "estimated_cost_usd", "cost"):
            val = getattr(response, attr, None)
            if val is not None:
                try:
                    return Decimal(str(val))
                except Exception:
                    pass
        return Decimal("0")
