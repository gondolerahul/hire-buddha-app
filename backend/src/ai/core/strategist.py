"""
ai.core.strategist — Deterministic move/decision selector (Track 2).

The strategist owns two questions:

  * "What should I do next?"   → ``next_move(state, perception) -> Move``
  * "Should I keep going?"     → ``decide_next(state, super_verdict) -> Decision``

Track 2 ships a *deterministic* strategist driven entirely by entity
type and plan state. The LLM-driven version is Track 4 / Track 7.

The strategist NEVER picks executors that are stubs (Dialog,
ToolBurst, Skill) — those are guarded by feature flags but the
strategist also checks the registry.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Literal, Optional
from uuid import uuid4

if TYPE_CHECKING:
    from src.ai.planning.plan_style_bandit import PlanStyleBandit

from src.ai.core.agent_state import (
    AgentState,
    ExecutorName,
    SupervisorVerdict,
)
from src.ai.schemas.enums import EntityType

__all__ = ["Move", "Decision", "Strategist", "MAX_CORRECTIVE_RETRIES_PER_RUN"]

# Hard ceiling on corrective retries honoured per run, across all steps. Caps
# the cost of a perpetually-REVISE critic when the per-step exhaustion check
# can't apply (moves with no stable step_id, e.g. CHILD_ENTITY invocations).
MAX_CORRECTIVE_RETRIES_PER_RUN: int = 2


@dataclass
class Move:
    move_id: str
    goal_id: Optional[str]
    executor: ExecutorName
    plan_fragment: Optional[list[dict[str, Any]]] = None
    rationale: str = ""
    expected_value: Literal["low", "med", "high"] = "med"
    expected_cost_usd: Decimal = field(default_factory=lambda: Decimal("0"))
    alternatives: list["Move"] = field(default_factory=list)
    # F-16: reasoning is chosen per-step, not per-entity. The Strategist sets a
    # hint on the move (e.g. the cheap default vs. "DEBATE" for a high-stakes
    # synthesis step) so a TOOL_CALL never pays for heavy reasoning. ``None``
    # means "use the entity's configured default".
    reasoning_hint: Optional[str] = None


@dataclass
class Decision:
    next: Literal["CONTINUE", "DONE", "PAUSE_HITL", "ABORT"]
    reason: str = ""
    next_state_patch: dict[str, Any] = field(default_factory=dict)


class Strategist:
    """Deterministic v1. LLM-driven version arrives in Track 7.

    Phase 11 Track 4: when more than one plan style fits the current
    state, the Strategist consults the optional ``PlanStyleBandit`` to
    pick between candidates. The bandit's chosen arm is recorded on
    ``state.chosen_arms_by_iteration`` so ``AgentLoop._finalize`` can
    update the arm's stats after the run completes.
    """

    def __init__(
        self,
        *,
        allow_parallel_dag: bool = True,
        bandit: Optional["PlanStyleBandit"] = None,    # noqa: F821 — forward ref
    ):
        self.allow_parallel_dag = allow_parallel_dag
        self.bandit = bandit

    # ------------------------------------------------------------------
    # Pick the next move
    # ------------------------------------------------------------------

    async def next_move(self, state: AgentState, perception: Any) -> Move:  # noqa: ARG002
        # Case A: a static plan exists and has ready steps.
        if state.has_plan() and state.plan_has_unblocked_steps():
            ready = state.plan_ready_steps()

            # CHILD_ENTITY_INVOCATION dominates parallel DAG dispatch —
            # child runs need their own scoped CORTEX subtree.
            if str(ready[0].get("type", "")).upper() == "CHILD_ENTITY_INVOCATION":
                await self._record_arm(state, "CHILD_ENTITY")
                return self._move(
                    state, executor="ChildEntity",
                    plan_fragment=ready[:1],
                    rationale="next plan step is CHILD_ENTITY_INVOCATION",
                )

            # High-uncertainty / high-stakes step → multi-agent Debate. This is
            # the reframed Tree-of-Thoughts (D-3): reasoning is picked PER STEP,
            # never per entity. Conservative by construction — ``_should_debate``
            # defaults to False, so a step must explicitly opt in (a debate hint
            # or a governance high-stakes flag) and the executor must be
            # registered. A plain TOOL_CALL/synthesis step is never escalated.
            if self._should_debate(state, ready[0]):
                await self._record_arm(state, "DEBATE")
                return self._move(
                    state, executor="Debate",
                    plan_fragment=ready[:1],
                    rationale="high-stakes step → multi-agent debate",
                    reasoning_hint="DEBATE",
                )

            if len(ready) >= 2 and self.allow_parallel_dag:
                # Bandit chooses between parallel DAG and sequential.
                arm = await self._consult_bandit(
                    state, ["DAG_PARALLEL", "DAG_SEQUENTIAL"],
                )
                if arm == "DAG_SEQUENTIAL":
                    return self._move(
                        state, executor="SingleStep",
                        plan_fragment=ready[:1],
                        rationale="bandit picked DAG_SEQUENTIAL",
                        reasoning_hint=self._step_reasoning_hint(ready[0]),
                    )
                return self._move(
                    state, executor="DAG",
                    plan_fragment=ready,
                    rationale=f"{len(ready)} ready steps; bandit picked DAG_PARALLEL",
                )

            await self._record_arm(state, "DAG_SEQUENTIAL")
            return self._move(
                state, executor="SingleStep",
                plan_fragment=ready[:1],
                rationale="one ready plan step; sequential",
                reasoning_hint=self._step_reasoning_hint(ready[0]),
            )

        # Case B: goal-only AGENT with no plan → recursive expansion.
        if state.entity_type == EntityType.AGENT and not state.has_plan():
            await self._record_arm(state, "RECURSIVE")
            return self._move(
                state, executor="Recursive",
                plan_fragment=None,
                rationale="AGENT without plan; recursive goal expansion",
            )

        # Case C: PROCESS with no ready steps but blocked steps remain.
        if state.has_plan() and not state.plan_has_unblocked_steps():
            # The legacy SingleStep path will skip-and-record; let it run
            # so the loop makes progress rather than spinning.
            await self._record_arm(state, "DAG_SEQUENTIAL")
            return self._move(
                state, executor="SingleStep",
                plan_fragment=None,
                rationale="plan present but no ready steps; sequential progress",
            )

        # Default: single-step on whatever the entity exposes.
        await self._record_arm(state, "SINGLE_TOOL")
        return self._move(
            state, executor="SingleStep",
            plan_fragment=None,
            rationale="default fallback",
        )

    # ------------------------------------------------------------------
    # Bandit helpers
    # ------------------------------------------------------------------

    async def _consult_bandit(
        self, state: AgentState, candidates: list[str],
    ) -> str:
        """Pick one arm via the bandit or return the first candidate."""
        if self.bandit is None or len(candidates) == 1:
            arm = candidates[0]
        else:
            try:
                arm, _exploring = await self.bandit.select_arm(
                    entity_id=state.entity_id,
                    task_class=state.task_class,
                    candidates=candidates,
                )
            except Exception:                                               # pragma: no cover
                arm = candidates[0]
        state.chosen_arms_by_iteration.append(arm)
        return arm

    async def _record_arm(self, state: AgentState, arm: str) -> None:
        state.chosen_arms_by_iteration.append(arm)

    # ------------------------------------------------------------------
    # Termination / replan / pause decision
    # ------------------------------------------------------------------

    def decide_next(
        self,
        state: AgentState,
        super_verdict: Optional[SupervisorVerdict] = None,
    ) -> Decision:
        if state.budget.exhausted():
            axis = state.budget.which_exhausted()
            return Decision(
                next="ABORT",
                reason=f"budget exhausted on axis {axis}",
            )

        if super_verdict is not None:
            if super_verdict.recommendation == "ABORT":
                return Decision(next="ABORT", reason=super_verdict.reasoning or "supervisor abort")
            if super_verdict.recommendation == "PAUSE":
                return Decision(next="PAUSE_HITL", reason=super_verdict.reasoning or "supervisor pause")
            if super_verdict.recommendation == "REPLAN":
                # Replace open subgoals with proposed ones (if any); the
                # AgentLoop will invoke PlannerService.replan separately.
                if super_verdict.proposed_subgoals:
                    state.open_subgoals = list(super_verdict.proposed_subgoals)
                    state.achieved = []  # fresh start for the new plan
                return Decision(
                    next="CONTINUE",
                    reason="supervisor REPLAN",
                    next_state_patch={"replan_requested": True},
                )

        # A queued corrective retry must run before we can call the run done.
        # The post-critic stage enqueues a follow-up move when it returns
        # REVISE/REJECT with actionable tags (e.g. INCOMPLETE, WRONG_FORMAT);
        # the loop drains state.retry_queue at the top of the next iteration.
        # Without this guard the strategist returned DONE the moment the plan
        # steps were marked complete, silently dropping the queued retry and
        # accepting output the critic had flagged as defective.
        #
        # BUT honour the queue only up to a hard per-run cap. ``is_exhausted``
        # bounds retries per step_id, but a move with no stable step_id (a
        # CHILD_ENTITY invocation) is never counted, so a perpetually-REVISE
        # critic would re-queue forever — re-running an expensive child every
        # iteration until budget/iteration cap (the doc-factory runaway).
        # Past the cap we stop honouring the queue and let the run finish on
        # best-effort output rather than burning the budget and FAILING.
        if state.retry_queue and state.corrective_retries_used <= MAX_CORRECTIVE_RETRIES_PER_RUN:
            return Decision(next="CONTINUE", reason="pending corrective retry queued")

        if state.all_subgoals_achieved() and not state.has_plan():
            return Decision(next="DONE", reason="all subgoals achieved; no plan remaining")

        if state.has_plan() and not state.plan_ready_steps() and self._plan_fully_complete(state):
            return Decision(next="DONE", reason="all plan steps completed")

        return Decision(next="CONTINUE", reason="more work")

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _move(
        self,
        state: AgentState,
        *,
        executor: ExecutorName,
        plan_fragment: Optional[list[dict[str, Any]]],
        rationale: str,
        reasoning_hint: Optional[str] = None,
    ) -> Move:
        return Move(
            move_id=str(uuid4()),
            goal_id=state.current_goal_id(),
            executor=executor,
            plan_fragment=plan_fragment,
            rationale=rationale,
            expected_value="med",
            expected_cost_usd=Decimal("0"),
            reasoning_hint=reasoning_hint,
        )

    # ------------------------------------------------------------------
    # Per-step reasoning selection (F-16 / D-3)
    # ------------------------------------------------------------------

    # A step opts into multi-agent debate via either an explicit per-step
    # ``reasoning_hint``/legacy ``reasoning_mode`` of one of these values …
    _DEBATE_HINTS: frozenset[str] = frozenset({"DEBATE", "TREE_OF_THOUGHTS"})

    @classmethod
    def _step_reasoning_hint(cls, step: dict[str, Any]) -> Optional[str]:
        """Per-step reasoning hint, normalised to upper-case, or ``None``.

        Reads the step's explicit ``reasoning_hint`` first, then falls back to a
        pre-D-3 plan's per-step ``reasoning_mode`` (so authored plans that still
        carry a step-level mode keep steering reasoning per step rather than per
        entity). ``None`` lets the executor use the entity default.
        """
        if not isinstance(step, dict):
            return None
        hint = step.get("reasoning_hint") or step.get("reasoning_mode")
        return str(hint).upper() if hint else None

    @classmethod
    def _should_debate(cls, state: AgentState, step: dict[str, Any]) -> bool:  # noqa: ARG003
        """Deterministic, conservative gate for the Debate executor.

        Returns ``True`` only when a step explicitly signals high
        uncertainty/stakes — never by default. Two signals:

        * an explicit debate ``reasoning_hint`` (or a legacy
          ``reasoning_mode="TREE_OF_THOUGHTS"`` carried on the step), or
        * a governance high-stakes flag on the step
          (``step["governance"]["high_stakes"]`` / ``["debate"]``, or a
          top-level ``step["high_stakes"]``).

        The Debate executor must also be registered; if it is not (e.g. a
        partial import), we fall through to the normal executor rather than
        emitting a move for a missing executor.
        """
        if not isinstance(step, dict):
            return False
        if cls._step_reasoning_hint(step) in cls._DEBATE_HINTS:
            signalled = True
        else:
            gov = step.get("governance")
            gov_flag = bool(gov.get("high_stakes") or gov.get("debate")) if isinstance(gov, dict) else False
            signalled = bool(step.get("high_stakes")) or gov_flag
        if not signalled:
            return False
        # Mirror the stub-executor precedent: the Strategist also checks the
        # registry so it never proposes a move for an unregistered executor.
        try:
            from src.ai.core.executors.base import registered_executor_names
            return "Debate" in registered_executor_names()
        except Exception:                                                   # pragma: no cover
            return False

    @staticmethod
    def _plan_fully_complete(state: AgentState) -> bool:
        if not state.plan_steps:
            return True
        plan_ids = {
            str(s.get("step_id") or s.get("id") or "")
            for s in state.plan_steps
            if s.get("step_id") or s.get("id")
        }
        plan_ids.discard("")
        return plan_ids.issubset(state.completed_step_ids)
