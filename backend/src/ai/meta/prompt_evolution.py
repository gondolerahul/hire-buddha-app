"""ai.meta.prompt_evolution — Meta-Agent prompt self-modification (`06` §6.1).

The cron ``meta_agent_prompt_evolution`` lays the plumbing (sample recent board
runs → write a ``prompt_update_candidate`` → HITL approve → prompt bump). This
module fills the previously-stubbed step: a *critic-of-critic* LLM reviews what
the **Meta-Agent's own board process** did wrong (not the agents it built) and
proposes a bounded prompt diff.

Safety: this is the "agent edits itself" capability, so it is deliberately
non-autonomous — the output is only ever a *candidate* requiring HITL approval
(``MetaIntelligenceTree.approve_prompt_candidate``). The LLM is injected so the
generator is unit-testable without live credentials.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, List, Optional

logger = logging.getLogger(__name__)

__all__ = ["RunSample", "PromptUpdateProposal", "PromptEvolutionCritic"]


@dataclass
class RunSample:
    """A compact, privacy-safe digest of one Meta-Agent board run."""

    run_id: str
    outcome: str = ""              # COMPLETED / FAILED / ...
    board_decision: str = ""       # REUSE / ADAPT / CREATE ...
    critic_verdict: str = ""       # PASS / REVISE / BLOCK
    cost_usd: float = 0.0
    notes: str = ""

    def to_line(self) -> str:
        return (
            f"- run {self.run_id[:8]}: outcome={self.outcome} "
            f"decision={self.board_decision} critic={self.critic_verdict} "
            f"cost=${self.cost_usd:.2f} {self.notes}".rstrip()
        )


@dataclass
class PromptUpdateProposal:
    prompt_diff: str = ""
    rationale: str = ""
    confidence: str = "low"        # low | med | high
    evidence_run_ids: List[str] = field(default_factory=list)
    model_used: str = ""

    @property
    def actionable(self) -> bool:
        return bool(self.prompt_diff.strip()) and bool(self.rationale.strip())


def _build_prompt(current_prompt: str, samples: List[RunSample]) -> tuple[str, str]:
    system = (
        "You are a critic-of-critic reviewing a Meta-Agent that DESIGNS other AI "
        "agents via a multi-role board (RequirementChat, Curator, Architect, "
        "Critic, Validator, TestDriver, Promoter). Review what the META-AGENT's "
        "own process did wrong across these runs — NOT the agents it built. Look "
        "for systemic issues: premature CREATE over REUSE, weak specs the Critic "
        "kept passing, cost blow-ups, missing validation. Propose ONE small, "
        "concrete prompt change.\n"
        'Return JSON only: {"prompt_diff":"<a short additive instruction or '
        'replacement to append/adjust in the template prompt>","rationale":'
        '"<why, citing the pattern>","confidence":"low|med|high"}. If the runs '
        'show no systemic problem, return prompt_diff="".'
    )
    sample_block = "\n".join(s.to_line() for s in samples[:20]) or "(no samples)"
    cur = (current_prompt or "")[:3000]
    user = (
        f"## Current Meta-Agent template prompt (excerpt):\n{cur}\n\n"
        f"## Recent board runs ({len(samples)}):\n{sample_block}\n\n"
        "Now produce the JSON proposal."
    )
    return system, user


class PromptEvolutionCritic:
    """Generates a HITL-gated Meta-Agent prompt-update proposal."""

    async def propose(
        self,
        current_prompt: str,
        samples: List[RunSample],
        *,
        llm: Any,
        model_override: Optional[str] = None,
        task_type: str = "thinking",
    ) -> PromptUpdateProposal:
        from src.ai.shared.json_utils import parse_json_object

        if not samples:
            return PromptUpdateProposal(rationale="no runs to review")
        system, user = _build_prompt(current_prompt, samples)
        try:
            response = await llm.call_llm(
                task_type=task_type,
                system_prompt=system,
                user_prompt=user,
                temperature=0.3,
                max_tokens=900,
                model_override=model_override,
            )
            output = getattr(response, "output", "") or ""
            model = getattr(response, "model_name", "") or (model_override or "")
        except Exception as exc:  # noqa: BLE001
            logger.warning("prompt-evolution LLM call failed: %s", exc)
            return PromptUpdateProposal(rationale=f"LLM unavailable: {type(exc).__name__}")

        parsed = parse_json_object(output, warn_label="prompt_evolution") or {}
        conf = str(parsed.get("confidence", "low")).lower()
        if conf not in {"low", "med", "high"}:
            conf = "low"
        return PromptUpdateProposal(
            prompt_diff=str(parsed.get("prompt_diff", ""))[:2000],
            rationale=str(parsed.get("rationale", ""))[:800],
            confidence=conf,
            evidence_run_ids=[s.run_id for s in samples[:5]],
            model_used=model,
        )
