# 03 — Agentic Loop: Today, and a World-Class Redesign

This document compares what the engine does today against the loop topology
used by leading autonomous-agent systems (Anthropic Claude Code, Devin,
LangGraph, Voyager, Reflexion, ReAct/ReWOO research), then proposes a
concrete redesign: a real **AgentLoop** with the existing engines becoming
*executors* under it.

---

## 1. What the loop is today

```
                                 +---------------------+
                                 |  Arq enqueues run   |
                                 +----------+----------+
                                            |
                                            v
                     +---------------------------------------+
                     |  ExecutionEngine.execute_run (1186 L) |
                     |                                       |
                     |  1. fetch run + entity (snapshot)     |
                     |  2. credit gate                       |
                     |  3. CORTEX tree create / resume       |
                     |  4. memory assemble (v1/v2)           |
                     |  5. load context sources              |
                     |  6. engine_type ?                     |
                     |       RECURSIVE → RecursiveEngine     |
                     |       DAG → reconcile plan            |
                     |  7. for each step:                    |
                     |       _execute_step_wrapper           |
                     |       review (critic)                 |
                     |       GoalGuard (step-level)          |
                     |       cortex write step               |
                     |       cortex checkpoint every N       |
                     |       MetaReviewer every N (autonomous)|
                     |       GoalGuard (autonomous, periodic)|
                     |       _should_exit?                   |
                     |  8. finalize → episodic write          |
                     +---------------------------------------+
```

### Critical observations

* **The loop is a for-loop over a plan**, not a perceive-think-act cycle.
* The "thinking" happens *inside* a step (REACT, CoT, Reflection, ToT),
  never *between* steps. There is no "what should I do next given
  everything I now know" decision point besides the one-shot
  `MetaReviewer`.
* "Autonomous mode" is hooks: re-plan on failure, periodic GoalGuard, periodic
  MetaReviewer. None of them edits the *agent's view of the world*; they
  only push REPLAN / RETRY / EARLY_EXIT signals back into the same loop.
* `RecursiveReasoningEngine` is the closest thing to a true autonomous loop,
  but:
  - Its confidence assessment is a single low-temperature LLM call with
    no access to memory, tools, or even the entity's identity.
  - Its goal expansion ignores CORTEX's existing knowledge.
  - Its synthesis is a single concat-and-summarize.
  - It does not invoke critic, GoalGuard, or MetaReviewer at all.

This means: **on PROCESS+AUTONOMOUS+DAG you get good guardrails over a
linear plan. On AGENT+RECURSIVE you get goal decomposition but the
guardrails go silent.**

---

## 2. What a *world-class* autonomous loop looks like

Look at the patterns common to the strongest open implementations:

### Anthropic Claude Code / Computer Use
* A long-running loop that **interleaves** thinking, tool use, environment
  observation, and progress reflection.
* Bounded by **wallclock time + token budget + iteration cap**, not by a
  static plan.
* Carries *task state* in a structured scratchpad that survives across LLM
  calls.
* Critics ("did this step move us closer?") are **separate prompts** with
  smaller, faster models.

### Devin / Cognition
* Distinct **planner**, **executor**, **critic**, and **memory** processes.
* Planner can revise the plan on each iteration.
* Executor can decide to spawn sub-agents.
* All four read/write a shared "session graph."

### Reflexion
* Each iteration ends with a **structured reflection** (what went well,
  what didn't, what to change) written to memory.
* Next iteration starts with the past reflections injected.

### Voyager
* A **skill library** that grows over time. Each successful chain becomes
  a callable skill.
* Curriculum: the agent **proposes its own next task**.

### LangGraph / OpenAI Swarm
* The agent is an explicit **state machine** (graph) with typed transitions
  and conditional edges.
* The framework persists state automatically; recovery from any node is
  trivial.

### CORTEX / RLM / PageIndex (which is what we already have)
* Replace "context = dict" with "context = current viewport into a tree."
* Tree is the *cognitive workspace*, not just a memory store.

### Shared invariants of world-class loops

1. **Perceive → Think → Act → Observe → Reflect**, not a static plan
   walker. Each iteration explicitly *decides what to do next*.
2. **State is structured** (not "the last LLM output"). Open subgoals,
   hypotheses, attempted actions, blocked-on-X all live in typed fields.
3. **Budget is a first-class citizen**, exposed to the LLM and the
   scheduler.
4. **Critics are separate**, often with different (smaller, cheaper)
   models. They are **not** asked to re-do the work.
5. **Reflection persists**. Lessons learned in one iteration are surfaced
   on the next.
6. **The loop chooses its own executor**: DAG-walk, recursive-decompose,
   tool-call-burst, dialogue. The executor is *not* a property of the
   entity config.

This is the bar we should aim for.

---

## 3. Concrete redesign — the `AgentLoop`

```
┌────────────────────────────────────────────────────────────────────┐
│                          AgentLoop (NEW)                          │
│                                                                    │
│   ┌────────────┐    ┌────────────┐    ┌────────────┐              │
│   │ Perceiver  │───▶│ Strategist │───▶│  Actor     │              │
│   │            │    │ (Planner)  │    │ (Executor) │              │
│   │ tree view, │    │ chooses    │    │ DAG /      │              │
│   │ memory,    │    │ strategy + │    │ recursive /│              │
│   │ telemetry  │    │ next move  │    │ single step│              │
│   └─────▲──────┘    └─────┬──────┘    └─────┬──────┘              │
│         │                 │                  │                     │
│         │                 │                  ▼                     │
│         │            ┌────┴─────┐      ┌──────────┐               │
│         │            │ Critic   │◀─────│ Observer │               │
│         │            │ (Multi-  │      │ (Outcome │               │
│         │            │  pass)   │      │  reader) │               │
│         │            └────┬─────┘      └──────────┘               │
│         │                 │                                       │
│         │                 ▼                                       │
│         │            ┌──────────┐                                 │
│         └────────────┤Reflector │                                 │
│                      │(writes to│                                 │
│                      │CORTEX +  │                                 │
│                      │Intellig.)│                                 │
│                      └──────────┘                                 │
└────────────────────────────────────────────────────────────────────┘
```

### 3.1 AgentLoop responsibilities

```python
# core/agent_loop.py  (NEW)
class AgentLoop:
    """
    The single top-level autonomous loop.

    Owns:
      - Goal & subgoal stack
      - Iteration counter, budget tracker, wallclock
      - Strategy selection (DAG / RECURSIVE / DIALOG / SKILL_INVOCATION)
      - Per-iteration state envelope (AgentState dataclass)

    Delegates:
      - Execution → executors/DAGExecutor, RecursiveExecutor, etc.
      - Memory  → memory.MemoryAssemblyService + CORTEX
      - Planning → planning.Strategist
      - Critique → planning.CriticPipeline
      - Reflection → memory.Reflector
    """

    async def run(self, run_id: UUID) -> RunResult: ...
```

### 3.2 The state envelope (typed)

```python
@dataclass
class AgentState:
    run_id: UUID
    iteration: int
    budget: Budget                  # tokens, USD, wallclock
    open_subgoals: list[Subgoal]    # explicit, ordered stack
    achieved: list[Subgoal]
    blockers: list[Blocker]         # missing tool / data / approval
    hypotheses: list[Hypothesis]    # things the agent tentatively believes
    last_action: Action | None
    last_observation: Observation | None
    reflections: list[Reflection]   # this run only; episodic-tree gets longer-lived
    cortex_cursor: UUID             # current viewport node
    chosen_executor: str            # 'DAG' | 'RECURSIVE' | 'DIALOG' | 'TOOL_BURST'
```

This replaces the unstructured `context_state: dict` for *loop-level* state.
`context_state` continues to exist for prompt variable resolution
(`{{step_id}}`), but it stops being the source of truth for what the agent
believes/wants.

### 3.3 Per-iteration flow

```
while not done:
    state.iteration += 1
    if state.budget.exhausted(): break

    # 1) Perceive
    perception = await Perceiver.gather(state, db, cortex, memory)
        # → current viewport text
        # → relevant intelligence rules
        # → recent episodic similar runs
        # → outstanding HITL approvals
        # → fresh tool/credit availability

    # 2) Strategize (choose move + executor)
    move = await Strategist.next_move(state, perception)
        # → {goal_to_pursue, executor, plan_fragment, expected_value, expected_cost}

    # 3) Optional pre-action critic (catches "obvious bad moves" before spending)
    pre = await CriticPipeline.pre_action(move, state, perception)
    if pre.recommend == "BLOCK": continue   # skip move, re-plan

    # 4) Act via chosen executor
    action_result = await EXECUTORS[move.executor].execute(move, state)

    # 5) Observe
    observation = Observer.parse(action_result, state)
    state.apply(observation)

    # 6) Post-action critic
    post = await CriticPipeline.post_action(state, observation, perception)

    # 7) Reflect
    reflection = Reflector.produce(state, observation, post)
    await Reflector.persist(reflection, cortex, intelligence_tree)
    state.reflections.append(reflection)

    # 8) Decide: continue / replan / pause for HITL / done
    decision = await Strategist.decide_next(state, post, reflection)
    state = decision.update(state)
    if decision.done: break

return RunResult.from_state(state)
```

### 3.4 The executors (Adapter pattern)

```python
class Executor(Protocol):
    name: str
    async def execute(self, move: Move, state: AgentState) -> ActionResult: ...
```

| Executor | Wraps existing code | When chosen |
|----------|---------------------|-------------|
| `DAGExecutor` | Today's `_execute_steps_dag` + `_execute_step_wrapper` | Move has a structured plan fragment with ≥2 ready steps |
| `RecursiveExecutor` | Today's `RecursiveReasoningEngine.execute_tree` | Move is "decompose this goal further" |
| `SingleStepExecutor` | Today's `_execute_step` | Move is one specific step |
| `ChildEntityExecutor` | Today's `_execute_child_invocation` | Move delegates to a child entity |
| `DialogExecutor` | New: free-form REACT turn with current viewport | Move is "ask user / clarify" |
| `ToolBurstExecutor` | New: bounded parallel tool calls (e.g. 5 web_search queries) | Move is "gather evidence cheaply" |
| `SkillExecutor` | New: invoke a previously-learned skill (Voyager-style) | Move matches a skill in the library |

The crucial change: **the executor is selected per iteration**, not per
entity. A single run may use DAG once, then Recursive, then Single-Step, then
Dialog.

### 3.5 Why this is strictly better

| Today | After |
|------|-------|
| Engine type set on entity at design time | Strategist picks per-iteration |
| Plan is static; the loop is a `for` over it | Loop is a `while not done`; plan is rebuilt every iteration if needed |
| No bridging between RECURSIVE and DAG | Both are executors, freely interleaved |
| Critic re-runs the same model with feedback appended | CriticPipeline has separate pre-action / post-action passes with separate, often cheaper, model |
| No explicit "open subgoals" | First-class field on `AgentState` |
| No persistent reflections between iterations | `state.reflections` (run-local) + Intelligence Tree (cross-run) |
| Budget enforced by exception | Strategist *plans inside the budget*; surfaces budget pressure to the LLM |
| GoalGuard + MetaReview + Critic disjoint | Unified `CriticPipeline` with shared `StepHealthRecord` |

---

## 4. Per-iteration "Perceive" — what to inject and how

Today, every LLM call gets a *huge* sandwich prompt (`build_sandwich_prompt`)
that is mostly the same on every step. This is wasteful in tokens *and*
wastes the agent's attention.

**Proposed perception payload (≤4k tokens):**

```
## Iteration N of <budget.max_iterations>
## Budget: tokens=4,213/100k, USD=$0.07/$1.00, wallclock=12s/300s
## Cortex viewport
   <breadcrumb>
   <current_node>
   <child summaries — max 12>

## Open subgoals (oldest first)
  1. <S1> — blocked-on: <reason or None>
  2. <S2>

## Recent reflections (last 3, from this run)
  - …

## Active intelligence rules for this entity/task class (top 3)
  - …

## Last action + observation
  action: TOOL_CALL[web_search] args={…}
  observation: 8 results / first 3 summarised
  outcome: ✅ on-topic, novel info added to Knowledge Root

## Outstanding HITL / interrupts
  none
```

This is **dynamic and bounded** — never the same twice in a row.

---

## 5. Strategist — the "what next" decision

The Strategist is the **heart of autonomy**. Today this role is filled
implicitly by the static plan + occasional re-plan via `PlannerService.adapt_plan`.

```python
class Strategist:
    async def next_move(self, state, perception) -> Move:
        # 1) If there are unblocked open subgoals → pop one
        # 2) If most-recent reflection demands replan → call PlannerService
        # 3) If critic blocked twice in a row → escalate (HITL or downgrade goal)
        # 4) If budget tight → choose cheaper executor
        # 5) Default: REACT one step
```

Implementation hint: **let the LLM be the Strategist, but with a typed
output schema** and **calibration**. Force a JSON like:

```json
{
  "next_move": {
    "goal_id": "G2",
    "executor": "DAGExecutor",
    "plan_fragment": [...],
    "rationale": "…",
    "expected_value": "high",
    "expected_cost_usd": 0.04,
    "alternatives": [
      {"executor": "ToolBurstExecutor", "expected_cost_usd": 0.01, "rationale": "..."}
    ]
  }
}
```

Then a **bandit / value-of-information** layer can choose between the LLM's
top suggestion and the alternative based on past outcomes (logged into
Intelligence Tree).

---

## 6. Critic Pipeline — what to do instead of today's review

See §05 for the full design. Short version:

* **Pre-action critic** (cheap, ≤200 tokens): "is this the right move?"
  Stops obvious mistakes before money is spent.
* **Post-action critic** (the existing review_step_output upgraded):
  uses a *different* model than the actor.
* **Periodic alignment critic** (GoalGuard, but consuming the
  StepHealthRecord rather than re-prompting from scratch).
* **End-of-iteration supervisor** (MetaReviewer, but reading reflections
  + open subgoals + budget — not just the last step).

All four write to one **StepHealthRecord** persisted in CORTEX, so each
subsequent critic sees the earlier ones.

---

## 7. Reflection — closing the loop into memory

Each iteration's `Reflector.produce(...)` returns a typed `Reflection`:

```python
@dataclass
class Reflection:
    iteration: int
    what_worked: str
    what_didnt: str
    cause_hypothesis: str
    proposed_change: str
    scope: Literal["run", "entity", "task_class"]
    confidence: float
```

* `scope = "run"` reflections feed back into `state.reflections` for the
  next iteration only.
* `scope = "entity"` reflections become **observations** in the Episodic
  Tree (today's dreaming engine input).
* `scope = "task_class"` reflections jump straight to **Intelligence Tree
  rules** with `status = "candidate"`, and the dreaming engine validates
  them against future runs.

This is the **single missing piece** that turns the engine from "a really
good plan executor" into "an agent that gets better."

---

## 8. Budget — first-class, not a circuit breaker

Today: `governance.max_cost_usd`, `governance.timeout_ms`, hidden circuit
breakers, occasional `exec_constraints` mention in the prompt.

Proposed: `Budget` is a typed object passed to every layer.

```python
@dataclass
class Budget:
    tokens_max: int;    tokens_used: int
    usd_max: Decimal;   usd_used: Decimal
    wall_max_s: int;    wall_used_s: int
    iters_max: int;     iters: int

    @property
    def pressure(self) -> float:  # 0..1, where 1 = at limit
        ...

    def can_afford(self, expected_cost: Decimal, expected_secs: int) -> bool: ...
```

Surfaced to the LLM as part of perception (§4) and to the Strategist as a
hard input. When `pressure > 0.7`, the Strategist must prefer cheaper
executors and shorter plans.

This eliminates the all-too-common mode where an entity blows its budget on
the planner's last steps despite being 90% done.

---

## 9. Migration path (incremental, low-risk)

You can ship the AgentLoop *without* changing today's engines:

1. **Step 1 — wrap.** Implement `AgentLoop.run(run_id)` that, for the first
   pass, just calls `ExecutionEngine.execute_run(run_id)` and exposes the
   `AgentState` envelope as a *view* over today's `context_state`. New
   code paths can opt in via entity config.
2. **Step 2 — Perceive.** Replace the prompt sandwich with the
   §4 perception payload only for entities that opt in. Compare quality.
3. **Step 3 — extract executors.** Move `_execute_steps_dag` and
   `_execute_step` into `executors/dag.py` and `executors/single.py`.
   Refactor `RecursiveReasoningEngine` into `executors/recursive.py`.
4. **Step 4 — Strategist.** Begin with a *thin* Strategist that picks DAG
   for static plans, Recursive for goal-only entities, SingleStep for
   ACTION/SKILL. No LLM cost.
5. **Step 5 — Critic Pipeline.** Replace `_review_step_output` and the
   three GoalGuard / MetaReview hooks with one unified pipeline.
6. **Step 6 — Reflection persistence.** Add `Reflector` writing to
   `Intelligence Tree` as `status = "candidate"`.
7. **Step 7 — LLM-driven Strategist.** Promote Strategist to make a real
   "next move" LLM call. Roll out per entity tag.
8. **Step 8 — Skills.** Detect repeated tool-chains and promote to skills
   in a `SkillLibrary` under each entity's CORTEX tree.

Each step is independently shippable.

---

## 10. Specific defects in today's loop to fix during the migration

| Defect | Where | Fix |
|--------|-------|-----|
| Critic re-runs the *same* model with feedback appended; can converge to the wrong answer | `step_executor.py:1456-1484` | Critic must use a different model OR explicit "play devil's advocate" system prompt |
| Goal-validation score interpreted as boolean (`score > confidence_threshold * 100`) | `planning/goal_guard.py:101` | Use calibrated thresholds derived from historical pass-rates |
| `MetaReviewer.review_execution` only sees last 5 completed steps and first 5 remaining steps. No budget, no reflections, no critic history. | `core/meta_review.py:55-77` | Feed it `AgentState` |
| `RecursiveReasoningEngine._assess_confidence` returns 0.5 on any parse error → silent half-confidence | `core/recursive_engine.py:198-200` | Return None and treat as "must expand"; never fake a confidence |
| `RecursiveReasoningEngine._synthesize` truncates each child to 2000 chars *unconditionally* | `core/recursive_engine.py:281` | Use the CORTEX viewport, not in-prompt concatenation |
| `MAX_REACT_TURNS = 12` is a global constant; many entities need more | `constants.py:62`; `step_executor.py:999` | Move to `entity.reasoning_config.max_react_turns` (already exists for meta) and treat 12 as default |
| `step_executor._review_step_output` budget guard fires at 80% wallclock; nothing for token / USD budget | `step_executor.py:1387-1394` | Use `Budget.pressure` |
| No retry / replan for *infrastructure* errors (LLM 500, DB timeout); only handled for tool / format errors | `step_executor.py:413-500` | Retry-with-backoff middleware in LLMRouter |
| `_should_exit` checks only the literal string `"error"` in context (`step_executor.py:1488-1495`) | same | Drop; exit conditions should be structured |
| Parallel DAG opens isolated AsyncSessions but doesn't roll back the planner's `dynamic_plan` write if a step fails late | `execution_engine.py:201-256` | Single-writer guarantee; planner writes only after finalize |
| `process_gateway_event` (`arq_jobs.py:38-154`) creates an ExecutionRun *inline* in the same DB session it will mutate later — a self-loaded gun | `arq_jobs.py:121-142` | Two-phase: persist run, then `arq.enqueue_job('run_execution_recursive', run.id)` |

---

## 11. The "good loop" smell test

Once the AgentLoop is in place, the loop should pass these tests:

1. **Resumeable.** Crash the worker mid-iteration. New worker picks up the
   same `AgentState` from CORTEX and continues seamlessly.
2. **Observably autonomous.** SSE stream shows `iteration → perception
   summary → strategist decision → action → observation → reflection` for
   every cycle.
3. **Budget-disciplined.** A run with `usd_max = $0.10` should *never*
   exceed $0.11, even when REACT goes long.
4. **Skill-growing.** After ~5 successful runs of the same task class,
   the SkillLibrary contains at least one reusable chain.
5. **Reflective.** The Intelligence Tree gains ≥1 new candidate rule per
   long run.
6. **Critic-resistant.** A 5-step run where step 3 is *wrong but
   confident* must be caught by the post-action critic at least 4 out of
   5 times with a different-model critic.

These are the exit criteria for the autonomy work in the roadmap.
