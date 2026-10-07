# 01 — Overview, North-Star Architecture, and Principles

This document is the **single source of truth for the target architecture**.
Every Track that follows assumes the picture and the principles described here.

If a Track ever conflicts with this document, this document wins.

---

## 1. North-star architecture (one picture)

```
                      ┌─────────────────────────────────────┐
                      │           HTTP / SSE API            │
                      │   backend/src/ai/api/*              │
                      └──────────────┬──────────────────────┘
                                     │
                                     ▼
                      ┌─────────────────────────────────────┐
                      │      AIService (services/)          │ ◀── HTTP-only
                      │      CRUD, refine, retry            │
                      └──────────────┬──────────────────────┘
                                     │ creates/triggers
                                     ▼
                      ┌─────────────────────────────────────┐
                      │   Arq Queue (core/arq_jobs.py)      │
                      └──────────────┬──────────────────────┘
                                     │
                                     ▼
                      ┌─────────────────────────────────────┐
                      │            AgentLoop                │  ◀── THE LOOP
                      │     core/agent_loop.py              │
                      │                                     │
                      │   while not done:                   │
                      │     perceive → strategize           │
                      │     pre-critic → act                │
                      │     observe → post-critic           │
                      │     reflect → decide_next           │
                      └───┬──────────────────┬──────────────┘
                          │                  │
            ┌─────────────▼──────┐  ┌────────▼─────────────┐
            │     Executors      │  │   Critic Pipeline    │
            │  core/executors/*  │  │ planning/critic_*    │
            │  DAG/Recursive/    │  │ pre/post/align/super │
            │  ChildEntity/Dialog│  │ + StepHealthRecord   │
            │  /ToolBurst/Skill  │  │                      │
            └─────────────┬──────┘  └────────┬─────────────┘
                          │                  │
                          ▼                  ▼
            ┌────────────────────┐  ┌───────────────────────┐
            │  Reasoning Modes   │  │   Planning            │
            │ core/reasoning/*   │  │ planning/planner.py   │
            │ REACT/CoT/         │  │ planning/invariants.py│
            │ Reflection/ToT     │  │ planning/child_res.py │
            └─────────┬──────────┘  └──────────┬────────────┘
                      │                        │
                      ▼                        ▼
            ┌──────────────────────────────────────────┐
            │              LLM Router                  │
            │   llm/router.py + adapters               │
            └────────────┬─────────────────────────────┘
                         │
                         ▼
            ┌──────────────────────────────────────────┐
            │           Tools (registry)               │
            │   tools/* with Resilience + CostResolver │
            └──────────────────────────────────────────┘

            ╔══════════════════════════════════════════╗
            ║              Memory Layer                ║
            ║  memory/cortex_service.py  (CortexService)║
            ║  memory/domains/{knowledge,episodic,     ║
            ║                  experience,intelligence}║
            ║  memory/dreaming/engine.py               ║
            ║  memory/legacy_episodic_reader.py        ║
            ╚════════════╤═════════════════════════════╝
                         │ read/write
                         ▼
                  ╔════════════════╗
                  ║   CORTEX Tree   ║
                  ║  (per run)      ║
                  ╚═════════════════╝

            ╔══════════════════════════════════════════╗
            ║         Meta-Agent (Architecture Board)  ║
            ║  meta/board/{requirement_chat,architect, ║
            ║              critic,validator,           ║
            ║              test_driver,promoter,       ║
            ║              curator}                    ║
            ║  meta/meta_intelligence_tree.py          ║
            ║  meta/skill_library.py                   ║
            ╚══════════════════════════════════════════╝

            ╔══════════════════════════════════════════╗
            ║       Governance (cost + HITL)           ║
            ║  governance/{governance_service,         ║
            ║              tool_cost_resolver,         ║
            ║              rate_limiter}               ║
            ╚══════════════════════════════════════════╝
```

Three observations to internalise:

1. **The AgentLoop is the orchestrator.** Executors, Critics, Planner,
   Memory are *services* called by the loop. None of them call each
   other directly.
2. **CORTEX is the substrate.** Every long-lived piece of state lives in
   CORTEX. The four memory-domain services are *typed views* over CORTEX
   trees.
3. **Meta-Agent is a normal agent that uses the same loop.** It happens
   to have a Board of internal roles, but at the top level it runs
   through `AgentLoop.run(run_id)` like every other entity.

---

## 2. Per-iteration sequence (one picture)

```
ITER N
 │
 ├─► Perceiver.gather(state) ─────────────────────► perception
 │    - viewport snippet (bounded)                  (Perception object)
 │    - intelligence rules (top K)
 │    - reflections so far this run
 │    - recent episodic similar runs
 │    - budget pressure
 │    - outstanding HITL approvals
 │
 ├─► Strategist.next_move(state, perception) ─────► move
 │    - goal_id (or new sub-goal)                    (Move object:
 │    - executor (DAG/Recursive/SingleStep/…)         executor, plan_fragment,
 │    - plan_fragment (if any)                        expected_value,
 │    - expected_value / cost                         expected_cost, rationale)
 │    - alternatives (≥1)
 │
 ├─► CriticPipeline.pre_action(move, state) ──────► PreVerdict
 │    - cheap LLM call, ≤300 tokens                  ({PASS|BLOCK|REVISE})
 │    if BLOCK: continue (next iteration)
 │
 ├─► EXECUTORS[move.executor].execute(move,state) ► action_result
 │    - returns ActionResult with output,           (ActionResult:
 │      tools used, sub-runs, cost, latency          output, tools[], children[],
 │                                                   cost_usd, latency_ms)
 │
 ├─► Observer.parse(action_result, state) ────────► observation
 │                                                   (Observation:
 │                                                    outcome, novelty_score,
 │                                                    goal_delta_estimate)
 │
 ├─► CriticPipeline.post_action(state, obs) ──────► PostVerdict
 │    - DIFFERENT model from actor                   ({PASS|REVISE|REJECT},
 │    - reads StepHealthRecord history                tags:list[FailureTag])
 │    - writes new StepHealthRecord
 │
 ├─► CriticPipeline.alignment(state, obs)─────────► AlignVerdict
 │   (every goal_validation_interval iterations)     (drift score)
 │
 ├─► CriticPipeline.supervisor(state) ─────────────► SuperVerdict
 │   (every meta_review_interval iterations)         (CONTINUE/REPLAN/ABORT/PAUSE)
 │
 ├─► Reflector.produce(state, obs, verdicts) ─────► reflection
 │    - what worked / didn't                         (Reflection:
 │    - cause hypothesis                              scope, what_worked,
 │    - proposed change                               what_didnt, hypothesis,
 │    - scope=run|entity|task_class                   proposed_change)
 │
 ├─► Reflector.persist(reflection) ────────────────► (writes to CORTEX
 │                                                    + IntelligenceTree
 │                                                    candidates)
 │
 ├─► state.apply(observation, reflection, verdicts)
 │
 └─► Strategist.decide_next(state) ────────────────► Decision
      - done?                                       ({CONTINUE|DONE|PAUSE_HITL
      - replan?                                       |ABORT})
      - escalate?
```

---

## 3. The seven design principles

These are the principles every Track is held against. When in doubt,
re-read these.

### P1 — Loops over chains

The agent is a **while-loop with explicit state**, not a chain of static
steps. Even when a plan exists, the loop chooses each iteration whether
to follow it. A static plan is a *hint*, never a contract.

**Implication:** `for step in plan: ...` patterns die. New code uses
`while not state.done: ...`.

### P2 — Typed state, not dict bag

State that the loop reasons about (open subgoals, budget, reflections,
verdicts) MUST be in a typed dataclass (`AgentState`). The
`context_state: dict` survives only for *prompt-variable substitution*
(the `{{step_id}}` machinery).

**Implication:** new code passes `state: AgentState` everywhere; legacy
code that reads `context_state["__memory__"]` is migrated to read
`state.perception.memory_block`.

### P3 — Critics never re-do the work

A critic returns a *verdict and tags*; it does NOT regenerate the
output. The Strategist picks a *retry strategy* if needed.

**Implication:** `_review_step_output` retry loop dies. `CriticPipeline`
emits structured verdicts; `Strategist.retry(...)` chooses
`RETRY_AS_IS | RETRY_DIFFERENT_MODEL | RETRY_DIFFERENT_PROMPT |
RETRY_DIFFERENT_TOOL | ABANDON | ASK_USER`.

### P4 — Budget is a first-class object

Every layer reads `Budget`. The LLM sees it in perception. The Strategist
treats it as a hard input. The Critic skips itself when budget pressure
is high.

**Implication:** all "max_cost", "timeout_ms", "max_recursion_depth" are
read through `Budget`. No layer maintains its own copy.

### P5 — Different model for the Critic by default

Critic LLM calls SHOULD use `critic_model_override` distinct from the
actor's model. Same-model self-review is allowed only for cheap
pre-action critics. This is the **single biggest quality lever**.

**Implication:** new `CriticPipeline` resolves model via
`config.get("critic_model_override")` → falls back to
`{"stronger": stronger_default, "different_provider": ...}`.

### P6 — Reflections close the loop into memory

Every iteration MUST produce a `Reflection` (even if `scope="run"` and
trivial). `Reflector.persist` writes it. The next iteration sees it.
Long-scope reflections become candidate Intelligence rules.

**Implication:** Dreaming Engine becomes a *consolidator* of candidate
rules, not the only producer of rules.

### P7 — CORTEX is the only place state lives across iterations

The AgentState envelope is reconstructable from CORTEX + the
ExecutionRun row. A crash mid-iteration MUST be resumable.

**Implication:** every iteration's "tail" writes a CORTEX snapshot. The
old `auto_checkpoint_every_n` becomes "every iteration."

---

## 4. Glossary of the new types

These types appear repeatedly across Tracks. Their canonical home is
listed; the canonical signature is the **only** acceptable shape unless
a later Track explicitly evolves it.

### 4.1 `AgentState` (core/agent_state.py)

```python
@dataclass
class AgentState:
    run_id: UUID
    iteration: int
    budget: Budget
    open_subgoals: list[Subgoal] = field(default_factory=list)
    achieved: list[Subgoal] = field(default_factory=list)
    blockers: list[Blocker] = field(default_factory=list)
    hypotheses: list[Hypothesis] = field(default_factory=list)
    last_action: Action | None = None
    last_observation: Observation | None = None
    reflections: list[Reflection] = field(default_factory=list)
    cortex_cursor: UUID | None = None
    chosen_executor: ExecutorName | None = None
    health_records: list[StepHealthRecord] = field(default_factory=list)
    perception: Perception | None = None     # current iteration only

    def snapshot(self) -> dict: ...
    @classmethod
    def restore(cls, snapshot: dict) -> "AgentState": ...
```

### 4.2 `Budget` (core/budget.py)

```python
@dataclass
class Budget:
    tokens_max: int;    tokens_used: int = 0
    usd_max: Decimal;   usd_used: Decimal = Decimal("0")
    wall_max_s: int;    wall_used_s: int = 0
    iters_max: int;     iters: int = 0

    @property
    def pressure(self) -> float: ...        # 0..1
    def can_afford(self, expected_usd: Decimal, expected_s: int) -> bool: ...
    def consume(self, *, tokens: int = 0, usd: Decimal | None = None,
                wall_s: int = 0, iter_step: bool = False) -> None: ...
    def exhausted(self) -> bool: ...
```

### 4.3 `Subgoal`, `Hypothesis`, `Blocker`, `Action`, `Observation`,
`Reflection` (core/agent_state.py)

```python
@dataclass
class Subgoal:
    id: str
    description: str
    parent_id: str | None = None
    priority: int = 0
    blocked_on: str | None = None
    achieved: bool = False

@dataclass
class Hypothesis:
    id: str
    claim: str
    evidence_node_ids: list[UUID] = field(default_factory=list)
    confidence: float = 0.5

@dataclass
class Blocker:
    kind: Literal["missing_tool","missing_data","awaiting_hitl","budget","error"]
    detail: str
    related_subgoal_id: str | None = None

@dataclass
class Action:
    iteration: int
    executor: ExecutorName
    move_id: str
    payload: dict          # plan fragment OR step descriptor

@dataclass
class Observation:
    iteration: int
    outcome: Literal["success","partial","fail","blocked"]
    novelty_score: float                   # 0..1
    goal_delta_estimate: float             # -1..1, negative means moved away
    cortex_node_ids_written: list[UUID]
    summary: str

@dataclass
class Reflection:
    iteration: int
    scope: Literal["run","entity","task_class"]
    what_worked: str
    what_didnt: str
    cause_hypothesis: str
    proposed_change: str
    confidence: float
```

### 4.4 `Move` (core/strategist.py)

```python
ExecutorName = Literal[
    "DAG","Recursive","SingleStep","ChildEntity","Dialog","ToolBurst","Skill"
]

@dataclass
class Move:
    move_id: str
    goal_id: str
    executor: ExecutorName
    plan_fragment: list[PlanStep] | None
    rationale: str
    expected_value: Literal["low","med","high"]
    expected_cost_usd: Decimal
    alternatives: list["Move"] = field(default_factory=list)
```

### 4.5 `StepHealthRecord` (planning/critic_pipeline.py)

```python
@dataclass
class StepHealthRecord:
    step_id: str
    iteration: int
    move_id: str
    pre_critic_verdict: Literal["PASS","BLOCK","REVISE"] | None
    pre_critic_concerns: list[str] = field(default_factory=list)
    post_critic_verdict: Literal["PASS","REVISE","REJECT"] | None = None
    post_critic_tags: list[FailureTag] = field(default_factory=list)
    alignment_aligned: bool | None = None
    alignment_drift: float | None = None
    supervisor_recommendation: Literal["CONTINUE","REPLAN","ABORT","PAUSE"] | None = None
    cost_usd: Decimal = Decimal("0")
    latency_ms: int = 0
```

### 4.6 `FailureTag` (planning/failure_tags.py)

```python
class FailureTag(str, Enum):
    OFF_TOPIC = "OFF_TOPIC"
    HALLUCINATION = "HALLUCINATION"
    INCOMPLETE = "INCOMPLETE"
    WRONG_FORMAT = "WRONG_FORMAT"
    TOOL_FAILURE = "TOOL_FAILURE"
    CONTRADICTION = "CONTRADICTION"          # disagrees with prior step
    UNVERIFIABLE = "UNVERIFIABLE"
    POLICY_VIOLATION = "POLICY_VIOLATION"
    UNDER_BUDGET = "UNDER_BUDGET"
    OVER_BUDGET = "OVER_BUDGET"
    BLOCKED_DEPENDENCY = "BLOCKED_DEPENDENCY"
    NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"
```

### 4.7 `Perception` (core/perceiver.py)

```python
@dataclass
class Perception:
    iteration: int
    viewport_text: str                       # bounded, no ops-help
    intelligence_rules: list[IntelRule]      # top K
    recent_reflections: list[Reflection]
    similar_past_runs: list[EpisodicRef]
    budget_pressure: float
    pending_hitl: list[HumanApproval]
    open_subgoals_text: str                  # rendered list
    last_action_summary: str
    last_observation_summary: str
```

### 4.8 `Decision` (core/strategist.py)

```python
@dataclass
class Decision:
    next: Literal["CONTINUE","DONE","PAUSE_HITL","ABORT"]
    reason: str
    next_state_patch: dict = field(default_factory=dict)
```

These eight types are the **vocabulary of the new system**. Every Track
either uses them or extends them; no Track introduces a parallel
vocabulary.

---

## 5. Backwards-compatibility strategy

### 5.1 Feature flags as the master switch

Two top-level flags govern the whole programme:

| Flag | Default | Meaning |
|------|---------|---------|
| `agent_loop.enabled` | `False` | New `AgentLoop.run()` instead of `ExecutionEngine.execute_run()` |
| `meta_agent.board_routing` | `False` | Route Meta-Agent through the Board |

Per-entity overrides via `entity.metadata_extensions.feature_flags`
take precedence over global defaults.

### 5.2 Old code path remains *available* throughout

`ExecutionEngine.execute_run` and `step_executor._execute_step` continue
to work end-to-end until Track 4 exit. Tracks 2-4 introduce parallel
code paths; only Track 9 deletes the old paths.

### 5.3 Database additivity

Every Track that touches the database **only adds** columns / tables.
No destructive migrations during the 12 weeks. Deletes happen post-
programme once the data is confirmed unused for ≥30 days.

### 5.4 API additivity

Every API change is additive. Old query params / fields stay; new ones
get added. Renames are double-emitted for 30 days.

---

## 6. Branch / PR discipline

* One Track owner per Track. Owner submits PRs to a long-lived feature
  branch `phase11/track-{N}`.
* Feature branch merges to `main` only at Track exit, with all
  acceptance criteria green.
* Each PR is ≤ ~400 lines of diff, has a single clear theme, and
  references the Track + item ID (e.g. `T3/3.5 — kill same-model retry`).
* Every PR adds at least one test or explains why none is possible.
* `mypy` and the layout-lint script (Track 9) MUST be green on every PR
  inside this programme.

---

## 7. Layered responsibility map (who owns what)

| Layer | Owner type | What changes here |
|-------|-----------|-------------------|
| `api/`, `services/`, `orm/`, `schemas/` | App platform engineer | HTTP / DB shape |
| `core/`, `planning/` | Agent kernel engineer | The loop, critics, planner |
| `memory/`, `tools/`, `llm/` | Agent infra engineer | CORTEX, tools, providers |
| `meta/` | AI / ML engineer | Meta-Agent, intelligence, learning |
| `governance/` | Platform / cost engineer | Cost, HITL, rate limiting |

These are *roles*, not necessarily distinct people. The split exists
so PR review can be sharded.

---

## 8. Single-page "what to build, in what order" recap

```
TRACK 0 [Week 1]    Pre-flight cleanup. No behaviour change.
TRACK 1 [Week 2]    schemas/, orm/, typed enums. No behaviour change.
TRACK 2 [Weeks 3-4] AgentLoop skeleton + Executors + Reasoning extract.
                    Behind feature flag. Parity vs legacy ±5%.
TRACK 3 [Week 5]    CriticPipeline v2 + StepHealthRecord +
                    different-model critic + retry strategies.
                    Replaces _review_step_output.
TRACK 4 [Week 6]    Meta-Review v2 reads StepHealthRecord + reflections.
                    Plan-style bandit.
TRACK 5 [Weeks 7-8] Meta-Agent v4 Board: spec_critic tool first, then
                    Test Driver suite, Curator, Architect/Critic split,
                    Promoter, SkillLibrary.
TRACK 6 [Week 9]    Memory v2 canonical. Kill v1 pipeline.
                    DomainTreeBase + Provenance + ScopePolicy.
TRACK 7 [Week 10]   PlanGenerator v2 + PlanInvariants + ChildResolver.
TRACK 8 [Week 11]   ToolCostResolver + ToolResilience + tool registry
                    audit + cost-by-attribution.
TRACK 9 [Week 12]   Type-check, comment cleanup, READMEs, KPI dashboard.
                    Delete deprecated paths.
```

This is the order of dependency:

* Tracks 0–1 are pure cleanup; no Track depends on them functionally.
* Track 2 unlocks Tracks 3–4 (Critic and Meta-Review consume AgentState).
* Track 3 (CriticPipeline) is consumed by Track 4 (Meta-Review).
* Track 5 (Meta-Agent v4) depends on the MetaIntelligenceTree being live —
  which is Track 5's own first PR. So Track 5 is self-contained but its
  benefits compound with Track 4.
* Track 6 (Memory) can run in parallel to Tracks 5/7; it's mostly
  internal.
* Track 7 (Planner) depends on Track 4's bandit infra.
* Tracks 8–9 are cleanup; depend on all preceding.

A 2-engineer crew can run:

* Engineer A: Tracks 0 → 1 → 2 → 3 → 4 → 7 → 9
* Engineer B: parallel from Week 4 onward: Track 5 → 6 → 8

Total elapsed: ~12 calendar weeks.
