"""
ai.core.agent_state — Typed envelope for the AgentLoop (Phase 11 Track 2).

The state types here are the *vocabulary* of the new loop. Tracks 3-9
extend them but cannot rename or replace them. Their canonical
signatures are pinned in the agent kernel overview, §4.

The legacy ``context_state: dict`` survives only for prompt-variable
substitution and is bridged via ``materialise_context_dict`` /
``absorb_context_dict`` on AgentState. New code reads
``state.perception`` instead.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Literal, Optional

if TYPE_CHECKING:
    from src.ai.core.strategist import Decision
from uuid import UUID, uuid4

from src.ai.core.budget import Budget
from src.ai.planning.failure_tags import FailureTag
from src.ai.schemas.enums import EntityType

__all__ = [
    "ExecutorName",
    "Subgoal",
    "Hypothesis",
    "Blocker",
    "Action",
    "Observation",
    "Reflection",
    "PreCriticVerdict",
    "PostCriticVerdict",
    "AlignmentVerdict",
    "SupervisorVerdict",
    "Verdicts",
    "AgentState",
]


ExecutorName = Literal[
    "DAG",
    "Recursive",
    "SingleStep",
    "ChildEntity",
    "Debate",
    "Dialog",
    "ToolBurst",
    "Skill",
]


# ---------------------------------------------------------------------------
# Vocabulary types
# ---------------------------------------------------------------------------


@dataclass
class Subgoal:
    id: str
    description: str
    parent_id: Optional[str] = None
    priority: int = 0
    blocked_on: Optional[str] = None
    achieved: bool = False


@dataclass
class Hypothesis:
    id: str
    claim: str
    evidence_node_ids: list[str] = field(default_factory=list)   # CORTEX node UUIDs as strings
    confidence: float = 0.5


@dataclass
class Blocker:
    kind: Literal[
        "missing_tool",
        "missing_data",
        "awaiting_hitl",
        "budget",
        "error",
    ]
    detail: str
    related_subgoal_id: Optional[str] = None


@dataclass
class Action:
    iteration: int
    executor: ExecutorName
    move_id: str
    payload: dict[str, Any] = field(default_factory=dict)        # plan fragment OR step descriptor


@dataclass
class Observation:
    iteration: int
    outcome: Literal["success", "partial", "fail", "blocked"]
    novelty_score: float                                          # 0..1
    goal_delta_estimate: float                                    # -1..1
    cortex_node_ids_written: list[str] = field(default_factory=list)
    summary: str = ""


@dataclass
class Reflection:
    iteration: int
    scope: Literal["run", "entity", "task_class"]
    what_worked: str = ""
    what_didnt: str = ""
    cause_hypothesis: str = ""
    proposed_change: str = ""
    confidence: float = 0.5


# ---------------------------------------------------------------------------
# Critic interfaces (Track 2 defines; Track 3 implements)
# ---------------------------------------------------------------------------


@dataclass
class PreCriticVerdict:
    kind: Literal["PASS", "BLOCK", "REVISE"] = "PASS"
    concerns: list[str] = field(default_factory=list)
    cost_usd: Decimal = field(default_factory=lambda: Decimal("0"))


@dataclass
class PostCriticVerdict:
    kind: Literal["PASS", "REVISE", "REJECT"] = "PASS"
    tags: list[FailureTag] = field(default_factory=list)
    suggestion: str = ""
    cost_usd: Decimal = field(default_factory=lambda: Decimal("0"))


@dataclass
class AlignmentVerdict:
    aligned: bool = True
    drift: float = 0.0
    correction_hint: str = ""


@dataclass
class SupervisorVerdict:
    recommendation: Literal["CONTINUE", "REPLAN", "ABORT", "PAUSE"] = "CONTINUE"
    reasoning: str = ""
    confidence: float = 0.5
    # Supervisor may propose new subgoals when
    # recommending REPLAN. List is empty for any other recommendation.
    proposed_subgoals: list["Subgoal"] = field(default_factory=list)


@dataclass
class Verdicts:
    """Bundle of every critic verdict for one iteration."""
    pre: Optional[PreCriticVerdict] = None
    post: Optional[PostCriticVerdict] = None
    align: Optional[AlignmentVerdict] = None
    supervise: Optional[SupervisorVerdict] = None


# ---------------------------------------------------------------------------
# AgentState — the loop's envelope
# ---------------------------------------------------------------------------


@dataclass
class AgentState:
    """Typed envelope for one execution-run's worth of agent state.

    ``perception`` is current-iteration-only and is NOT snapshotted —
    it is rebuilt by ``Perceiver.gather`` at the top of every iteration.
    """
    run_id: UUID
    entity_id: UUID
    company_id: Optional[UUID]
    entity_type: EntityType
    iteration: int = 0
    budget: Budget = field(default_factory=Budget)

    open_subgoals: list[Subgoal] = field(default_factory=list)
    achieved: list[Subgoal] = field(default_factory=list)
    blockers: list[Blocker] = field(default_factory=list)
    hypotheses: list[Hypothesis] = field(default_factory=list)

    last_action: Optional[Action] = None
    last_observation: Optional[Observation] = None

    reflections: list[Reflection] = field(default_factory=list)

    cortex_cursor: Optional[UUID] = None
    cortex_tree_id: Optional[UUID] = None
    cortex_working_root_id: Optional[UUID] = None

    chosen_executor: Optional[ExecutorName] = None

    # Plan state cached on bootstrap from ExecutionRun.dynamic_plan.
    plan_steps: list[dict[str, Any]] = field(default_factory=list)
    completed_step_ids: set[str] = field(default_factory=set)

    # Per-step result summary, mirroring the legacy engine's
    # ``result_data["steps"]``. Each entry is ``{"step", "step_id", "type",
    # "output"[, "child_run_id"]}``. Snapshotted so it survives suspend/resume
    # (a PROCESS folds child results across resumes). The refine flow
    # (``service.py``) reads this back to reuse unchanged steps' outputs.
    step_results: list[dict[str, Any]] = field(default_factory=list)

    # Async child dispatch: child runs spawned this run that the loop is waiting
    # on. Each entry is ``{"run_id": str, "step_id": str, "status": str}``.
    # Snapshotted, so a resumed parent knows which children to fold. ``status``
    # is updated to the child's terminal status on resume.
    awaiting_children: list[dict[str, Any]] = field(default_factory=list)

    # Transient: set during an iteration when the executor dispatched children
    # asynchronously, signalling the loop to SUSPEND (snapshot + WAITING) rather
    # than finalize. NOT snapshotted — recomputed each run from awaiting_children.
    suspend_requested: bool = field(default=False, repr=False, compare=False)

    # Legacy bridge — only used to ferry data into adapter executors.
    context_state: dict[str, Any] = field(default_factory=dict)

    # Live Redis client for adapter executors (e.g. ChildEntity spawning a
    # sub-run). Kept as a transient attribute — NOT in ``context_state`` —
    # because ``context_state`` is JSON-serialised into ``input_data``,
    # snapshots, and ``run.context_state``; a raw Redis handle there raises
    # "Object of type Redis is not JSON serializable" and poisons the session.
    # Excluded from ``snapshot()``/``from_snapshot`` so it never persists.
    redis_client: Any = field(default=None, repr=False, compare=False)

    # Loop-level termination
    done: bool = False
    next_decision: Literal["CONTINUE", "DONE", "PAUSE_HITL", "ABORT"] = "CONTINUE"

    # Count of *consecutive* iterations whose chosen move was rejected by the
    # pre-critic (``PreCriticVerdict.kind == "BLOCK"``). Reset to 0 the moment a
    # move clears the pre-critic. AgentLoop trips a circuit breaker (ABORT) once
    # this crosses a threshold, so a Strategist that keeps proposing a move the
    # critic will always block can no longer livelock the loop.
    consecutive_pre_critic_blocks: int = 0

    # Total corrective retries QUEUED across the whole run (monotonic). The
    # per-step ``RetryExecutor.is_exhausted`` cap can't bound moves with no
    # stable step_id (e.g. a CHILD_ENTITY invocation), so without this global
    # cap a perpetually-REVISE critic makes the loop re-queue a retry every
    # iteration — re-spawning an expensive child each time until budget/iter
    # cap (the doc-factory runaway). The Strategist stops honouring the queue
    # past ``MAX_CORRECTIVE_RETRIES_PER_RUN`` and lets the run finish.
    corrective_retries_used: int = 0

    # Terminal status observed out-of-band (e.g. an operator cancelled the run
    # via the /cancel endpoint, flipping ExecutionRun.status away from RUNNING).
    # When set, AgentLoop._final_status preserves it instead of mapping the
    # ABORT decision to a generic FAILED. Transient — not snapshotted.
    external_status: Optional[str] = None

    # Pipeline-owned StepHealthRecords for this run.
    # Capped to last 20 for prompt-bloat hygiene by CriticPipeline.
    health_records: list[Any] = field(default_factory=list)

    # Retry queue. The Strategist consumes one entry
    # per iteration before generating a fresh move. Entries are
    # ``(strategy_name, move_dict)`` tuples; the Strategist hydrates
    # back into Move on consumption.
    retry_queue: list[dict[str, Any]] = field(default_factory=list)

    # Task class identifier (e.g. "research_topic").
    # Populated by AgentLoop bootstrap via TaskClassifier; consumed by
    # SupervisorCritic, PlanStyleBandit, and calibration grouping.
    task_class: str = "general"

    # Every PlanStyleBandit arm pulled this run.
    # AgentLoop._finalize replays this list into bandit.update_arm
    # once the run terminates.
    chosen_arms_by_iteration: list[str] = field(default_factory=list)

    # Current-iteration only (not snapshotted).
    perception: Optional[Any] = None    # tests/ai.core.perceiver.Perception (forward ref dodge)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def add_subgoal(self, description: str, *, priority: int = 0, parent_id: Optional[str] = None) -> Subgoal:
        sg = Subgoal(id=str(uuid4()), description=description, priority=priority, parent_id=parent_id)
        self.open_subgoals.append(sg)
        return sg

    def achieve_subgoal(self, subgoal_id: str) -> bool:
        for i, sg in enumerate(self.open_subgoals):
            if sg.id == subgoal_id:
                sg.achieved = True
                self.achieved.append(sg)
                self.open_subgoals.pop(i)
                return True
        return False

    def all_subgoals_achieved(self) -> bool:
        return not self.open_subgoals

    def current_goal_id(self) -> Optional[str]:
        if self.open_subgoals:
            return self.open_subgoals[0].id
        return None

    def has_plan(self) -> bool:
        return bool(self.plan_steps)

    def plan_ready_steps(self) -> list[dict[str, Any]]:
        """Steps not yet completed and with all dependencies satisfied."""
        ready: list[dict[str, Any]] = []
        for step in self.plan_steps:
            sid = str(step.get("step_id") or step.get("id") or "")
            if not sid or sid in self.completed_step_ids:
                continue
            deps = []
            target = step.get("target") or {}
            if isinstance(target, dict):
                deps = list(target.get("input_dependencies") or [])
            if all(d in self.completed_step_ids for d in deps):
                ready.append(step)
        return ready

    def plan_has_unblocked_steps(self) -> bool:
        return bool(self.plan_ready_steps())

    def mark_step_complete(self, step_id: str) -> None:
        if step_id:
            self.completed_step_ids.add(step_id)

    def next_step_is_child_invocation(self) -> bool:
        ready = self.plan_ready_steps()
        if not ready:
            return False
        first = ready[0]
        return str(first.get("type", "")).upper() == "CHILD_ENTITY_INVOCATION"

    def apply_observation(self, observation: Observation) -> None:
        self.last_observation = observation
        if observation.outcome == "blocked":
            self.blockers.append(Blocker(
                kind="missing_data",
                detail=observation.summary or "observation reported blocked",
            ))

    def apply_decision(self, decision: "Decision") -> None:  # noqa: F821 — fwd ref
        self.next_decision = decision.next
        if decision.next in ("DONE", "ABORT"):
            self.done = True

    # ------------------------------------------------------------------
    # Legacy context bridge
    # ------------------------------------------------------------------

    async def materialise_context_dict(self) -> dict[str, Any]:
        """Build a dict suitable for the legacy ``context_state`` parameter.

        Adapter executors pass this into legacy code so the AgentLoop
        can drive existing per-step execution without rewriting it.
        """
        ctx = dict(self.context_state)
        # Surface a few high-leverage signals so legacy code can read them.
        ctx.setdefault("__agent_state__", {
            "iteration": self.iteration,
            "budget_pressure": self.budget.pressure,
            "open_subgoals": [sg.description for sg in self.open_subgoals],
        })
        return ctx

    async def absorb_context_dict(self, ctx: dict[str, Any]) -> None:
        """Copy back into ``self.context_state`` after a legacy call.

        Drops the inner ``__agent_state__`` echo (we own that key) so
        repeated round-trips don't accumulate noise.
        """
        for k, v in ctx.items():
            if k == "__agent_state__":
                continue
            self.context_state[k] = v

    # ------------------------------------------------------------------
    # Snapshot
    # ------------------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        return {
            "run_id": str(self.run_id),
            "entity_id": str(self.entity_id),
            "company_id": str(self.company_id) if self.company_id else None,
            "entity_type": self.entity_type.value if self.entity_type else None,
            "iteration": self.iteration,
            "budget": self.budget.snapshot(),
            "open_subgoals": [asdict(g) for g in self.open_subgoals],
            "achieved": [asdict(g) for g in self.achieved],
            "blockers": [asdict(b) for b in self.blockers],
            "hypotheses": [asdict(h) for h in self.hypotheses],
            "last_action": asdict(self.last_action) if self.last_action else None,
            "last_observation": asdict(self.last_observation) if self.last_observation else None,
            "reflections": [asdict(r) for r in self.reflections[-20:]],
            "cortex_cursor": str(self.cortex_cursor) if self.cortex_cursor else None,
            "cortex_tree_id": str(self.cortex_tree_id) if self.cortex_tree_id else None,
            "cortex_working_root_id": (
                str(self.cortex_working_root_id) if self.cortex_working_root_id else None
            ),
            "chosen_executor": self.chosen_executor,
            "plan_steps": list(self.plan_steps),
            "completed_step_ids": sorted(self.completed_step_ids),
            "step_results": list(self.step_results),
            "awaiting_children": list(self.awaiting_children),
            "context_state": dict(self.context_state),
            "done": self.done,
            "next_decision": self.next_decision,
            "consecutive_pre_critic_blocks": self.consecutive_pre_critic_blocks,
            "corrective_retries_used": self.corrective_retries_used,
            "retry_queue": list(self.retry_queue),
            "task_class": self.task_class,
            "chosen_arms_by_iteration": list(self.chosen_arms_by_iteration),
        }

    @classmethod
    def restore(cls, snapshot: dict[str, Any]) -> "AgentState":
        entity_type = EntityType(snapshot["entity_type"]) if snapshot.get("entity_type") else EntityType.ACTION
        state = cls(
            run_id=UUID(snapshot["run_id"]),
            entity_id=UUID(snapshot["entity_id"]),
            company_id=UUID(snapshot["company_id"]) if snapshot.get("company_id") else None,
            entity_type=entity_type,
            iteration=int(snapshot.get("iteration", 0)),
            budget=Budget.restore(snapshot.get("budget", {})),
            open_subgoals=[Subgoal(**s) for s in snapshot.get("open_subgoals", [])],
            achieved=[Subgoal(**s) for s in snapshot.get("achieved", [])],
            blockers=[Blocker(**b) for b in snapshot.get("blockers", [])],
            hypotheses=[Hypothesis(**h) for h in snapshot.get("hypotheses", [])],
            reflections=[Reflection(**r) for r in snapshot.get("reflections", [])],
            cortex_cursor=UUID(snapshot["cortex_cursor"]) if snapshot.get("cortex_cursor") else None,
            cortex_tree_id=UUID(snapshot["cortex_tree_id"]) if snapshot.get("cortex_tree_id") else None,
            cortex_working_root_id=(
                UUID(snapshot["cortex_working_root_id"])
                if snapshot.get("cortex_working_root_id") else None
            ),
            chosen_executor=snapshot.get("chosen_executor"),
            plan_steps=list(snapshot.get("plan_steps", [])),
            completed_step_ids=set(snapshot.get("completed_step_ids", [])),
            step_results=list(snapshot.get("step_results", [])),
            awaiting_children=list(snapshot.get("awaiting_children", [])),
            context_state=dict(snapshot.get("context_state", {})),
            done=bool(snapshot.get("done", False)),
            next_decision=snapshot.get("next_decision", "CONTINUE"),
            consecutive_pre_critic_blocks=int(snapshot.get("consecutive_pre_critic_blocks", 0)),
            corrective_retries_used=int(snapshot.get("corrective_retries_used", 0)),
            retry_queue=list(snapshot.get("retry_queue", [])),
            task_class=str(snapshot.get("task_class", "general")),
            chosen_arms_by_iteration=list(snapshot.get("chosen_arms_by_iteration", [])),
        )
        la = snapshot.get("last_action")
        if la:
            state.last_action = Action(**la)
        lo = snapshot.get("last_observation")
        if lo:
            state.last_observation = Observation(**lo)
        return state

    def snapshot_json(self) -> str:
        return json.dumps(self.snapshot(), default=str)
