"""
ai.planning.critic_pipeline — Unified four-stage critic pipeline (Phase 11 Track 3).

This module replaces the NoOp critic plumbed in Track 2 with a real
*Critic Pipeline* that runs four stages per iteration, all writing
into one shared ``StepHealthRecord``:

  * **pre_action**   — cheap "is this move sensible?" check
  * **post_action**  — different-model, structured-tag review
  * **alignment**    — periodic goal-alignment check (folds in GoalGuard)
  * **supervisor**   — periodic CONTINUE/REPLAN/ABORT/PAUSE verdict

Design notes:
  * The pipeline owns budget enforcement (``governance.critic_cost_share_pct``,
    default 0.20). When the critic share would push cost above the cap,
    it auto-degrades to PASS-only for pre + alignment.
  * Critic LLM calls SHOULD use a model distinct from the actor's. The
    resolver in ``resolve_critic_model`` falls back through entity
    override → company override → heuristic → same-model.
  * ``StepHealthRecord`` is persisted as a CORTEX node under a 🩺 Health
    subtree (created lazily). No SQL migration needed.
  * Retry is NOT the critic's job — the Strategist picks one of seven
    retry strategies based on the FailureTag set (see
    ``ai.planning.retry_strategies``).

Public surface kept stable so Track 2's AgentLoop wiring did not change:

    class CriticPipeline(Protocol):
        async def pre_action(move, state) -> PreCriticVerdict
        async def post_action(state, observation) -> PostCriticVerdict
        async def alignment(state, observation) -> AlignmentVerdict
        async def supervisor(state) -> SupervisorVerdict

The Track 2 NoOp implementation is preserved (``NoOpCriticPipeline``)
for tests and as a safe fallback when ``critic_pipeline.v2_enabled`` is
off.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Any, Iterable, Optional, Protocol, cast, runtime_checkable
from uuid import UUID

from src.ai.core.agent_state import (
    AgentState,
    AlignmentVerdict,
    Observation,
    PostCriticVerdict,
    PreCriticVerdict,
    SupervisorVerdict,
)
from src.ai.planning.critic_prompts import (
    POST_PROMPT_SYSTEM,
    POST_PROMPT_USER,
    PRE_PROMPT_SYSTEM,
    PRE_PROMPT_USER,
)
from src.ai.planning.failure_tags import FailureTag
from src.ai.planning.step_health_record import StepHealthRecord

logger = logging.getLogger(__name__)

__all__ = [
    "CriticPipeline",
    "NoOpCriticPipeline",
    "RealCriticPipeline",
    "StepHealthRecord",
    "CriticMode",
    "resolve_critic_model",
]


# ---------------------------------------------------------------------------
# StepHealthRecord
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Pipeline protocol + NoOp default (Track 2-compatible)
# ---------------------------------------------------------------------------


@runtime_checkable
class CriticPipeline(Protocol):
    async def pre_action(self, move: Any, state: AgentState) -> PreCriticVerdict: ...

    async def post_action(
        self, state: AgentState, observation: Observation
    ) -> PostCriticVerdict: ...

    async def alignment(
        self, state: AgentState, observation: Observation
    ) -> AlignmentVerdict: ...

    async def supervisor(self, state: AgentState) -> SupervisorVerdict: ...

    async def finalize_iteration(self, state: AgentState) -> Optional["StepHealthRecord"]:
        """Persist the iteration's StepHealthRecord and return it.

        AgentLoop calls this once after supervisor() at the end of every
        iteration. Default no-op implementations may return ``None``.
        """
        ...


class NoOpCriticPipeline:
    """Track-2 default — always passes.

    Retained as the safe fallback when ``critic_pipeline.v2_enabled`` is
    OFF or the real pipeline cannot be constructed.
    """

    async def pre_action(self, move: Any, state: AgentState) -> PreCriticVerdict:  # noqa: ARG002
        return PreCriticVerdict(kind="PASS")

    async def post_action(
        self, state: AgentState, observation: Observation  # noqa: ARG002
    ) -> PostCriticVerdict:
        return PostCriticVerdict(kind="PASS")

    async def alignment(
        self, state: AgentState, observation: Observation  # noqa: ARG002
    ) -> AlignmentVerdict:
        return AlignmentVerdict(aligned=True, drift=0.0)

    async def supervisor(self, state: AgentState) -> SupervisorVerdict:  # noqa: ARG002
        return SupervisorVerdict(recommendation="CONTINUE", confidence=0.5)

    async def finalize_iteration(self, state: AgentState) -> Optional[StepHealthRecord]:  # noqa: ARG002
        return None


# ---------------------------------------------------------------------------
# Mode + model resolver
# ---------------------------------------------------------------------------


class CriticMode(str, Enum):
    FULL = "FULL"
    DEGRADED = "DEGRADED"     # skip pre + align; minimal post


# Heuristic ladder. Keys are case-insensitive substring matches against
# the actor's model name. Values are the recommended critic model.
_CRITIC_LADDER: list[tuple[str, str]] = [
    ("flash", "gemini-2.5-pro"),
    ("haiku", "claude-sonnet-4-5"),
    ("mini",  "gpt-4o"),
    ("nano",  "gpt-4o"),
    ("sonnet","claude-opus-4-1"),
    ("opus",  "gpt-5"),
    ("gpt-4o","claude-sonnet-4-5"),
    ("gpt-5", "claude-opus-4-1"),
    ("gemini-2.5-pro", "claude-sonnet-4-5"),
]


def resolve_critic_model(
    *,
    entity_override: Optional[str] = None,
    company_override: Optional[str] = None,
    actor_model: Optional[str] = None,
) -> Optional[str]:
    """Pick the critic model. Returns ``None`` to mean "fall back to default".

    Priority:
      1. entity-level ``critic_model_override``
      2. company-level override
      3. heuristic ladder (different model from actor)
      4. ``None`` (caller uses same-model with hostile prompt)
    """
    if entity_override:
        return entity_override
    if company_override:
        return company_override
    if actor_model:
        actor_lower = actor_model.lower()
        for needle, suggested in _CRITIC_LADDER:
            if needle in actor_lower and needle not in (suggested.lower()):
                return suggested
    return None


# ---------------------------------------------------------------------------
# Real pipeline
# ---------------------------------------------------------------------------


@dataclass
class _PipelineConfig:
    critic_model_override: Optional[str] = None
    company_critic_override: Optional[str] = None
    actor_model_hint: Optional[str] = None
    critic_cost_share_pct: float = 0.20
    goal_validation_interval: int = 2
    meta_review_interval: int = 3
    entity_goal: str = ""
    task_description: str = ""
    enable_pre_critic: bool = True
    enable_different_model: bool = True
    # Supervisor v2 wiring.
    supervisor_v2_enabled: bool = True
    supervisor_fast_path_enabled: bool = True

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "_PipelineConfig":
        return cls(
            critic_model_override=raw.get("critic_model_override"),
            company_critic_override=raw.get("company_critic_override"),
            actor_model_hint=raw.get("actor_model_hint"),
            critic_cost_share_pct=float(raw.get("critic_cost_share_pct", 0.20)),
            goal_validation_interval=int(raw.get("goal_validation_interval", 2)),
            meta_review_interval=int(raw.get("meta_review_interval", 3)),
            entity_goal=str(raw.get("entity_goal", "") or ""),
            task_description=str(raw.get("task_description", "") or ""),
            enable_pre_critic=bool(raw.get("enable_pre_critic", True)),
            enable_different_model=bool(raw.get("enable_different_model", True)),
            supervisor_v2_enabled=bool(raw.get("supervisor_v2_enabled", True)),
            supervisor_fast_path_enabled=bool(raw.get("supervisor_fast_path_enabled", True)),
        )


class RealCriticPipeline:
    """The Phase 11 Track 3 implementation of CriticPipeline.

    A new ``StepHealthRecord`` is created on every ``pre_action`` call
    and finalised (persisted to CORTEX) by ``finalize_iteration``.
    """

    def __init__(
        self,
        *,
        db: Any,
        llm_router: Any,
        cortex_service: Any,
        intelligence_reader: Any = None,
        config: Optional[dict[str, Any]] = None,
    ):
        self.db = db
        self.llm = llm_router
        self.cortex = cortex_service
        self.intel = intelligence_reader
        self.config = _PipelineConfig.from_dict(config or {})

        self._cumulative_critic_cost: Decimal = Decimal("0")
        self._health_root_id: Optional[UUID] = None
        self._current_record: Optional[StepHealthRecord] = None
        self._iter_started_at: float = 0.0

        # Supervisor v2.
        self._supervisor_v2: Any = None
        if self.config.supervisor_v2_enabled:
            from src.ai.planning.supervisor_critic import (
                SupervisorCritic,
                SupervisorCriticConfig,
            )
            self._supervisor_v2 = SupervisorCritic(
                llm_router=self.llm,
                intelligence_reader=self.intel,
                config=SupervisorCriticConfig(
                    fast_path_enabled=self.config.supervisor_fast_path_enabled,
                    critic_model_override=self.config.critic_model_override,
                    entity_goal=self.config.entity_goal,
                ),
            )

    # ------------------------------------------------------------------
    # Stage 1 — pre-action
    # ------------------------------------------------------------------

    async def pre_action(self, move: Any, state: AgentState) -> PreCriticVerdict:
        # Start a fresh record for this iteration.
        self._current_record = StepHealthRecord(
            iteration=state.iteration,
            move_id=getattr(move, "move_id", "") or "",
            step_id=self._step_id_from_move(move),
        )
        self._iter_started_at = time.time()

        if (
            self._budget_mode(state) is CriticMode.DEGRADED
            or not self.config.enable_pre_critic
        ):
            verdict = PreCriticVerdict(kind="PASS")
            self._current_record.pre_critic_verdict = "PASS"
            return verdict

        try:
            response = await self.llm.call_llm(
                task_type="text_generation",
                system_prompt=PRE_PROMPT_SYSTEM,
                user_prompt=PRE_PROMPT_USER.format(
                    goal=self.config.entity_goal or "(unknown)",
                    subgoals=", ".join(sg.description for sg in state.open_subgoals[:5]) or "(none)",
                    executor=getattr(move, "executor", "?"),
                    rationale=getattr(move, "rationale", "")[:200],
                    plan_size=len(getattr(move, "plan_fragment", None) or []),
                    pressure=state.budget.pressure,
                ),
                temperature=0.1,
                max_tokens=200,
            )
            cost = self._extract_cost(response)
            payload = self._parse_json(response.output) or {}
            kind = str(payload.get("verdict", "PASS")).upper()
            if kind not in {"PASS", "BLOCK", "REVISE"}:
                kind = "PASS"
            concerns = [str(c) for c in (payload.get("concerns") or []) if c]
            verdict = PreCriticVerdict(kind=cast(Any, kind), concerns=concerns, cost_usd=cost)
            await self._log_critic_usage(
                state=state, response=response, attribution="critic_pre",
            )
        except Exception as exc:                                            # noqa: BLE001
            logger.warning("pre_critic LLM call failed: %s", exc)
            verdict = PreCriticVerdict(kind="PASS")
            cost = Decimal("0")

        self._cumulative_critic_cost += verdict.cost_usd
        self._current_record.pre_critic_verdict = verdict.kind
        self._current_record.pre_critic_concerns = list(verdict.concerns)
        self._current_record.pre_critic_cost_usd = verdict.cost_usd
        return verdict

    # ------------------------------------------------------------------
    # Stage 2 — post-action
    # ------------------------------------------------------------------

    async def post_action(
        self, state: AgentState, observation: Observation
    ) -> PostCriticVerdict:
        record = self._ensure_record(state)
        critic_model = (
            resolve_critic_model(
                entity_override=self.config.critic_model_override,
                company_override=self.config.company_critic_override,
                actor_model=self.config.actor_model_hint,
            )
            if self.config.enable_different_model
            else None
        )

        prior_history = self._render_prior_history(state)
        intel_rules = await self._render_intel_rules(state)

        try:
            response = await self.llm.call_llm(
                task_type="text_generation",
                system_prompt=POST_PROMPT_SYSTEM,
                user_prompt=POST_PROMPT_USER.format(
                    goal=self.config.entity_goal or "(unknown)",
                    task=self.config.task_description or "(none)",
                    step_desc=self._step_description(state),
                    outcome=observation.outcome,
                    output=(observation.summary or "")[:2000] or "(empty)",
                    prior_history=prior_history,
                    intel_rules=intel_rules,
                ),
                temperature=0.1,
                max_tokens=400,
                model_override=critic_model,
            )
            cost = self._extract_cost(response)
            payload = self._parse_json(response.output) or {}
            kind = str(payload.get("verdict", "PASS")).upper()
            if kind not in {"PASS", "REVISE", "REJECT"}:
                kind = "PASS"
            tags: list[FailureTag] = []
            for raw_tag in payload.get("tags") or []:
                tag = FailureTag.from_string(str(raw_tag))
                if tag is not None:
                    tags.append(tag)
            suggestion = str(payload.get("suggestion", ""))[:500]
            verdict = PostCriticVerdict(
                kind=cast(Any, kind), tags=tags, suggestion=suggestion, cost_usd=cost,
            )
            await self._log_critic_usage(
                state=state, response=response, attribution="critic_post",
            )
        except Exception as exc:                                            # noqa: BLE001
            logger.warning("post_critic LLM call failed: %s", exc)
            verdict = PostCriticVerdict(kind="PASS")

        self._cumulative_critic_cost += verdict.cost_usd
        record.post_critic_verdict = verdict.kind
        record.post_critic_tags = list(verdict.tags)
        record.post_critic_suggestion = verdict.suggestion
        record.post_critic_cost_usd = verdict.cost_usd
        record.post_critic_model = critic_model or "(actor-same)"
        return verdict

    # ------------------------------------------------------------------
    # Stage 3 — alignment
    # ------------------------------------------------------------------

    async def alignment(
        self, state: AgentState, observation: Observation
    ) -> AlignmentVerdict:
        record = self._ensure_record(state)

        interval = max(1, self.config.goal_validation_interval)
        if state.iteration % interval != 0:
            verdict = AlignmentVerdict(aligned=True, drift=0.0)
            record.alignment_aligned = True
            record.alignment_drift = 0.0
            return verdict

        if self._budget_mode(state) is CriticMode.DEGRADED:
            verdict = AlignmentVerdict(aligned=True, drift=0.0)
            record.alignment_aligned = True
            record.alignment_drift = 0.0
            return verdict

        if not (observation.summary and self.config.entity_goal):
            verdict = AlignmentVerdict(aligned=True, drift=0.0)
            record.alignment_aligned = True
            record.alignment_drift = 0.0
            return verdict

        try:
            from src.ai.planning.goal_alignment import GoalAlignmentVerifier
            verifier = GoalAlignmentVerifier(self.db, cast(UUID, state.company_id))
            result = await verifier.verify_step_alignment(
                entity_goal=self.config.entity_goal,
                task_desc=self.config.task_description,
                step_output=observation.summary,
                step_name=self._step_description(state),
            )
            aligned = bool(result.get("aligned", True))
            confidence = float(result.get("confidence", 0.5))
            drift = max(0.0, min(1.0, 1.0 - confidence if not aligned else 0.0))
            verdict = AlignmentVerdict(
                aligned=aligned,
                drift=drift,
                correction_hint=str(result.get("correction_hint", "")),
            )
        except Exception as exc:                                            # noqa: BLE001
            logger.warning("alignment critic failed: %s", exc)
            verdict = AlignmentVerdict(aligned=True, drift=0.0)

        record.alignment_aligned = verdict.aligned
        record.alignment_drift = verdict.drift
        return verdict

    # ------------------------------------------------------------------
    # Stage 4 — supervisor
    # ------------------------------------------------------------------

    async def supervisor(self, state: AgentState) -> SupervisorVerdict:
        record = self._ensure_record(state)
        interval = max(1, self.config.meta_review_interval)
        if state.iteration == 0 or state.iteration % interval != 0:
            verdict = SupervisorVerdict(recommendation="CONTINUE")
            record.supervisor_recommendation = "CONTINUE"
            record.supervisor_confidence = verdict.confidence
            return verdict

        if self._budget_mode(state) is CriticMode.DEGRADED:
            verdict = SupervisorVerdict(
                recommendation="CONTINUE",
                reasoning="Critic pipeline degraded; skipping supervisor.",
            )
            record.supervisor_recommendation = "CONTINUE"
            record.supervisor_confidence = verdict.confidence
            return verdict

        # Track 4 supervisor v2 (default).
        if self._supervisor_v2 is not None:
            verdict = await self._supervisor_v2.assess(state)
            cost = self._supervisor_v2.last_cost_usd
            self._cumulative_critic_cost += cost
            record.supervisor_recommendation = verdict.recommendation
            record.supervisor_reasoning = verdict.reasoning
            record.supervisor_confidence = verdict.confidence
            record.supervisor_cost_usd = cost
            response = getattr(self._supervisor_v2, "last_response", None)
            if response is not None:
                await self._log_critic_usage(
                    state=state, response=response, attribution="critic_super",
                )
            return cast(SupervisorVerdict, verdict)

        # Legacy fallback — used only when supervisor_v2_enabled = False.
        try:
            from src.ai.core.meta_review import MetaReviewer
            reviewer = MetaReviewer(self.db, cast(UUID, state.company_id))
            completed = self._completed_steps_for_review(state)
            remaining = self._remaining_steps_for_review(state)
            review = await reviewer.review_execution(
                entity_goal=self.config.entity_goal,
                completed_steps=completed,
                remaining_steps=remaining,
                total_cost_usd=float(state.budget.usd_used),
                context_summary="",
            )
            rec = str(review.get("recommendation", "CONTINUE")).upper()
            if rec not in {"CONTINUE", "REPLAN", "ABORT", "PAUSE"}:
                rec = "CONTINUE"
            verdict = SupervisorVerdict(
                recommendation=cast(Any, rec),
                reasoning=str(review.get("reasoning", "")),
                confidence=float(review.get("confidence", 0.5)),
            )
        except Exception as exc:                                            # noqa: BLE001
            logger.warning("legacy supervisor critic failed: %s", exc)
            verdict = SupervisorVerdict(recommendation="CONTINUE", confidence=0.5)

        record.supervisor_recommendation = verdict.recommendation
        record.supervisor_reasoning = verdict.reasoning
        record.supervisor_confidence = verdict.confidence
        return verdict

    # ------------------------------------------------------------------
    # Iteration finalisation
    # ------------------------------------------------------------------

    async def finalize_iteration(self, state: AgentState) -> Optional[StepHealthRecord]:
        record = self._current_record
        if record is None:
            return None
        record.total_latency_ms = int((time.time() - self._iter_started_at) * 1000)
        await self._persist_record(record, state)
        # Cap history in state to last 20 for prompt-bloat hygiene.
        getattr(state, "health_records", []).append(record)
        if len(getattr(state, "health_records", [])) > 20:
            state.health_records = state.health_records[-20:]
        # Reset for the next iteration.
        self._current_record = None
        return record

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_record(self, state: AgentState) -> StepHealthRecord:
        if self._current_record is None:
            # Defensive — should not happen if AgentLoop calls pre_action first.
            self._current_record = StepHealthRecord(iteration=state.iteration)
        return self._current_record

    def _budget_mode(self, state: AgentState) -> CriticMode:
        run_cost = float(state.budget.usd_used)
        critic_cost = float(self._cumulative_critic_cost)
        if run_cost <= 0:
            return CriticMode.FULL
        if critic_cost / run_cost > self.config.critic_cost_share_pct:
            return CriticMode.DEGRADED
        return CriticMode.FULL

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

    async def _log_critic_usage(
        self, *, state: AgentState, response: Any, attribution: str,
    ) -> None:
        from src.ai.services.attributed_usage import log_llm_response_usage
        await log_llm_response_usage(
            db=self.db, response=response, attribution=attribution,
            company_id=state.company_id, run_id=state.run_id,
        )

    @staticmethod
    def _parse_json(text: Optional[str]) -> Optional[dict[str, Any]]:
        if not text:
            return None
        from src.ai.shared.json_utils import parse_json_object
        return parse_json_object(text, warn_label="critic_pipeline")

    @staticmethod
    def _step_id_from_move(move: Any) -> str:
        plan = getattr(move, "plan_fragment", None)
        if isinstance(plan, list) and plan:
            head = plan[0] or {}
            if isinstance(head, dict):
                return str(head.get("step_id") or head.get("id") or "")
        return ""

    @staticmethod
    def _step_description(state: AgentState) -> str:
        if state.last_action:
            return f"executor={state.last_action.executor} move={state.last_action.move_id}"
        return "(initial step)"

    def _render_prior_history(self, state: AgentState) -> str:
        records: Iterable[StepHealthRecord] = getattr(state, "health_records", []) or []
        if not records:
            return "(none)"
        lines = []
        for r in list(records)[-3:]:
            tags = ",".join(t.value for t in r.post_critic_tags) or "-"
            lines.append(
                f"iter={r.iteration} post={r.post_critic_verdict} "
                f"tags=[{tags}] align={r.alignment_aligned}"
            )
        return "\n".join(lines)

    async def _render_intel_rules(self, state: AgentState) -> str:    # noqa: ARG002
        if self.intel is None:
            return "(none)"
        try:
            rules = await self.intel.top_rules(limit=3)
            if not rules:
                return "(none)"
            return "\n".join(f"- {getattr(r, 'summary', str(r))[:160]}" for r in rules)
        except Exception:                                                   # pragma: no cover
            return "(none)"

    def _completed_steps_for_review(self, state: AgentState) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for step in state.plan_steps[:50]:
            sid = str(step.get("step_id") or step.get("id") or "")
            if sid and sid in state.completed_step_ids:
                out.append({
                    "step_name": step.get("name") or sid,
                    "output": (step.get("output") or "")[:120],
                })
        return out

    def _remaining_steps_for_review(self, state: AgentState) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for step in state.plan_steps[:50]:
            sid = str(step.get("step_id") or step.get("id") or "")
            if sid and sid not in state.completed_step_ids:
                out.append({"name": step.get("name") or sid, "type": step.get("type", "?")})
        return out

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    async def _persist_record(self, record: StepHealthRecord, state: AgentState) -> None:
        if self.cortex is None or getattr(state, "cortex_working_root_id", None) is None:
            return
        try:
            health_root = await self._ensure_health_root(state)
            if health_root is None:
                return
            await self.cortex.write(
                parent_id=health_root,
                node_type="health_record",
                title=f"🩺 step={record.step_id or '?'} iter={record.iteration}",
                summary=(
                    f"post={record.post_critic_verdict or '-'} "
                    f"align={record.alignment_aligned} "
                    f"super={record.supervisor_recommendation or '-'}"
                ),
                content=record.to_json(),
                status="complete",
                source_ref={
                    "type": "step_health_record",
                    "record_id": record.record_id,
                    "tags": [t.value for t in record.post_critic_tags],
                },
            )
        except Exception:                                                   # pragma: no cover
            logger.exception("Failed to persist StepHealthRecord")

    async def _ensure_health_root(self, state: AgentState) -> Optional[UUID]:
        if self._health_root_id is not None:
            return self._health_root_id
        working_root = getattr(state, "cortex_working_root_id", None)
        if working_root is None:
            return None
        try:
            new_id = await self.cortex.write(
                parent_id=working_root,
                node_type="health_root",
                title="🩺 Health",
                summary="StepHealthRecord container for this run",
                content=None,
                status="complete",
                source_ref={"type": "health_root"},
            )
            self._health_root_id = new_id
            return cast(Optional[UUID], new_id)
        except Exception:                                                   # pragma: no cover
            logger.exception("Failed to create Health root node")
            return None
