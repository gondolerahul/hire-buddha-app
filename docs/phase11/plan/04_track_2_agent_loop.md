# Track 2 — AgentLoop Foundation (Weeks 3-4)

> **Owner:** Agent kernel engineer.
> **Duration:** 10 working days (≈2 calendar weeks).
> **Behaviour change:** New code path behind `agent_loop.enabled`
>   feature flag. Legacy path remains default.
> **Risk:** High. This is the central change of the programme.
> **Goal mapping:** G1 (true autonomous loop), G2 (foundation Meta-Agent
>   needs), G6 (kernel-layout), G8 (Budget + Reflection).

This Track is the **heart** of Phase 11. Everything else either depends
on or polishes the structures defined here.

---

## 1. Objectives (functional)

After Track 2:

1. A new top-level orchestrator `AgentLoop.run(run_id)` exists and is
   the entry point for any entity whose feature flag
   `agent_loop.enabled = true`.
2. The loop runs a real **perceive → strategize → pre-critic → act →
   observe → post-critic → reflect → decide** cycle (see
   [`01_overview_and_principles.md` §2](./01_overview_and_principles.md)).
3. `AgentState` is the typed state envelope; `Budget` is the typed
   budget; both are persisted to / restored from CORTEX so a crashed
   worker can resume.
4. The seven legacy execution responsibilities (DAG, Recursive,
   SingleStep, ChildEntity, Dialog (new), ToolBurst (new), Skill (new))
   are exposed as `Executor` adapters under `core/executors/`. Each one
   is a thin wrapper that delegates to existing code on day one.
5. The four reasoning modes (REACT, CHAIN_OF_THOUGHT, REFLECTION,
   TREE_OF_THOUGHTS) live under `core/reasoning/` as pluggable strategies
   instead of inline methods in `step_executor.py`.
6. Parity test: for at least one representative PROCESS entity and one
   AGENT entity, the new path produces semantically equivalent output
   to the old path within ±5% cost variance.
7. Telemetry events `agent.loop.iteration_start`,
   `agent.loop.iteration_end`, `agent.loop.budget_pressure`,
   `agent.loop.resume` flow into the central event bus.

---

## 2. Scope

### In scope

* New files: `core/agent_loop.py`, `core/agent_state.py`,
  `core/budget.py`, `core/perceiver.py`, `core/strategist.py`,
  `core/observer.py`, `core/reflector.py`.
* New package: `core/executors/` with seven adapter files.
* New package: `core/reasoning/` with four reasoning files extracted
  from `step_executor.py`.
* New feature flag `agent_loop.enabled` plumbed through `FeatureFlags`.
* Wiring: `core/arq_jobs.py::run_execution_recursive` consults the flag
  and dispatches to either `AgentLoop.run(run_id)` (new) or
  `ExecutionEngine.execute_run(run_id)` (legacy).
* A parity test harness (`backend/tests/parity/`) that runs the same
  fixture entity through both paths and diffs the result.
* Telemetry event emission via the central event bus from Track 13.

### Out of scope

* Replacing the legacy path. `ExecutionEngine.execute_run` continues to
  exist and to be reachable when the flag is off.
* Critic Pipeline implementation (Track 3 consumes the
  `Pre/PostCriticVerdict` *interfaces* defined here but does the actual
  work in Track 3).
* Strategist with LLM-driven move selection. The Track 2 Strategist is
  **deterministic**: it chooses the executor based on entity type and
  the current open subgoals.
* Skill detection / promotion (Track 5).
* `Dialog`, `ToolBurst`, `Skill` executors *function*. Track 2 lands
  them as **stubs** that raise `NotImplementedError` cleanly so the
  Strategist never picks them; full implementations come in later
  Tracks.

---

## 3. Architecture (technical)

### 3.1 Files added

```
backend/src/ai/core/
├── agent_loop.py             ← top-level loop (THE orchestrator)
├── agent_state.py            ← AgentState + helper types (Subgoal,
│                               Hypothesis, Blocker, Action, Observation,
│                               Reflection)
├── budget.py                 ← Budget tracker
├── perceiver.py              ← Perceiver + Perception
├── strategist.py             ← Strategist + Move + Decision
├── observer.py               ← Observer
├── reflector.py              ← Reflector
├── executors/
│   ├── __init__.py
│   ├── base.py               ← Executor protocol + registry
│   ├── single_step.py        ← wraps step_executor._execute_step
│   ├── dag.py                ← wraps execution_engine._execute_steps_dag
│   ├── recursive.py          ← wraps core/recursive_engine.py
│   ├── child_entity.py       ← wraps step_executor._execute_child_invocation
│   ├── dialog.py             ← stub for now (Track 5 fills)
│   ├── tool_burst.py         ← stub for now (Track 7/8)
│   └── skill.py              ← stub for now (Track 5)
├── reasoning/
│   ├── __init__.py
│   ├── base.py               ← Reasoning protocol
│   ├── react.py              ← extracted from step_executor.py
│   ├── chain_of_thought.py   ← extracted
│   ├── reflection.py         ← extracted
│   └── tree_of_thoughts.py   ← extracted
└── arq_jobs.py               ← extended to dispatch on feature flag
```

### 3.2 Sequence diagram for one iteration

```
AgentLoop.run(run_id)
│
├─ db_session = AsyncSessionLocal()
├─ state = await AgentState.bootstrap_from_db(run_id, db_session)
│    (loads ExecutionRun, entity, budget caps, opens CORTEX tree)
│
├─ event("agent.loop.run_start", run_id=run_id, entity_id=...)
│
├─ while not state.done:
│    │
│    │   await self._iteration(state)
│    │
│    ├─ event("agent.loop.iteration_start",
│    │         iteration=state.iteration, budget_pressure=...)
│    │
│    ├─ perception = await self.perceiver.gather(state)
│    │
│    ├─ move = await self.strategist.next_move(state, perception)
│    │
│    ├─ pre_verdict = await self.critic.pre_action(move, state)         # Track 3 fills
│    │   if pre_verdict.kind == "BLOCK":
│    │      state.reflections.append(Reflection.block(pre_verdict))
│    │      continue
│    │
│    ├─ executor = EXECUTOR_REGISTRY[move.executor]
│    ├─ action_result = await executor.execute(move, state, db_session)
│    │
│    ├─ observation = self.observer.parse(action_result, state)
│    ├─ state.apply_observation(observation)
│    │
│    ├─ post_verdict = await self.critic.post_action(state, observation)   # Track 3
│    ├─ align_verdict = await self.critic.alignment(state, observation)    # Track 3
│    ├─ super_verdict = await self.critic.supervisor(state)                # Track 3
│    │
│    ├─ reflection = self.reflector.produce(state, observation, verdicts)
│    ├─ await self.reflector.persist(reflection, state)
│    ├─ state.reflections.append(reflection)
│    │
│    ├─ decision = self.strategist.decide_next(state, super_verdict)
│    ├─ state.apply_decision(decision)
│    │
│    ├─ await state.snapshot_to_cortex()
│    │
│    ├─ event("agent.loop.iteration_end",
│    │         iteration=state.iteration, decision=decision.next, ...)
│    │
│    └─ if decision.next == "DONE": break
│
├─ event("agent.loop.run_end", outcome=..., total_cost_usd=..., iters=...)
└─ return RunResult.from_state(state)
```

### 3.3 Resume semantics

If the worker crashes mid-iteration, the next Arq pickup of the same
`run_id` calls `AgentLoop.run(run_id)` again. `AgentState.bootstrap_from_db`
detects an existing CORTEX snapshot and resumes from `iteration = N` with
the recorded `Budget` consumed so far.

```python
@classmethod
async def bootstrap_from_db(cls, run_id, db) -> "AgentState":
    snapshot = await CortexService(db, ...).read_latest_snapshot(run_id)
    if snapshot:
        event("agent.loop.resume", run_id=run_id, from_iter=snapshot.iteration)
        return cls.restore(snapshot)
    return cls.create_fresh(run_id, ...)
```

### 3.4 Executor protocol

```python
# core/executors/base.py
from typing import Protocol
from src.ai.core.agent_state import AgentState, Action
from src.ai.core.strategist import Move


class ActionResult:
    output: str                              # rendered for context propagation
    tools_used: list[str]
    children_run_ids: list[UUID]
    cost_usd: Decimal
    latency_ms: int
    cortex_nodes_written: list[UUID]
    success: bool
    error: str | None = None


class Executor(Protocol):
    name: str

    async def execute(self, move: Move, state: AgentState,
                      db) -> ActionResult: ...


EXECUTOR_REGISTRY: dict[str, Executor] = {}


def register(executor: Executor) -> Executor:
    EXECUTOR_REGISTRY[executor.name] = executor
    return executor
```

Day-1 executors are *thin adapters*:

```python
# core/executors/dag.py
@register
class DAGExecutor:
    name = "DAG"
    async def execute(self, move, state, db):
        # Call into existing _execute_steps_dag, marshalling AgentState
        # → context_state dict and back. Single-file, ~120 LoC.
        ...
```

The wrappers are deliberately mechanical. They let the new loop ship in
2 weeks without rewriting any executor logic.

### 3.5 Reasoning protocol

```python
# core/reasoning/base.py
class Reasoning(Protocol):
    name: ReasoningMode  # enum from schemas.enums

    async def run(self,
                  llm_router,
                  system_prompt: str,
                  user_prompt: str,
                  task_type: str,
                  config: dict,
                  tool_schemas: list[dict],
                  execute_tool_fn,
                  model_override: str | None = None,
                  ) -> tuple[str, LLMResponse]:
        ...
```

`step_executor.py` retains its public `_execute_thought` for now but
internally dispatches via the registered `Reasoning` strategies.

### 3.6 Critic interface (defined here, implemented in Track 3)

```python
# core/agent_state.py  (interfaces only — impl in planning/critic_pipeline.py)
@dataclass
class PreCriticVerdict:
    kind: Literal["PASS", "BLOCK", "REVISE"]
    concerns: list[str] = field(default_factory=list)
    cost_usd: Decimal = Decimal("0")

@dataclass
class PostCriticVerdict:
    kind: Literal["PASS", "REVISE", "REJECT"]
    tags: list[FailureTag] = field(default_factory=list)
    suggestion: str = ""
    cost_usd: Decimal = Decimal("0")

@dataclass
class AlignmentVerdict:
    aligned: bool
    drift: float                     # 0..1
    correction_hint: str = ""

@dataclass
class SupervisorVerdict:
    recommendation: Literal["CONTINUE", "REPLAN", "ABORT", "PAUSE"]
    reasoning: str = ""
    confidence: float = 0.5
```

Track 2 ships a **no-op CriticPipeline** that returns `PASS / PASS /
aligned / CONTINUE` always. Track 3 replaces it with the real
implementation. The loop's wiring never changes.

---

## 4. Detailed deliverables

### 4.1 T2-1 — `core/agent_state.py` and `core/budget.py` (Day 1)

Implement the dataclasses verbatim from
[`01_overview_and_principles.md` §4](./01_overview_and_principles.md).

Add `AgentState.snapshot_to_cortex(...)` and
`AgentState.restore_from_cortex(...)`:

```python
async def snapshot_to_cortex(self, cortex, working_root_id: UUID) -> UUID:
    """Write a snapshot node under the run's CORTEX tree.

    The snapshot is a JSON blob in `content` plus a one-line summary.
    Returns the new node id.
    """
    payload = {
        "iteration": self.iteration,
        "budget": asdict(self.budget),
        "open_subgoals": [asdict(g) for g in self.open_subgoals],
        "achieved": [asdict(g) for g in self.achieved],
        "blockers": [asdict(b) for b in self.blockers],
        "hypotheses": [asdict(h) for h in self.hypotheses],
        "reflections": [asdict(r) for r in self.reflections[-20:]],
        "cortex_cursor": str(self.cortex_cursor) if self.cortex_cursor else None,
        "chosen_executor": self.chosen_executor,
    }
    node = await cortex.write(
        parent_id=working_root_id,
        node_type="snapshot",
        title=f"🧠 Snapshot iter={self.iteration}",
        summary=f"{len(self.open_subgoals)} subgoals open, "
                f"budget_pressure={self.budget.pressure:.2f}",
        content=json.dumps(payload, default=str),
        status="complete",
        source_ref={"type": "agent_state_snapshot",
                    "iteration": self.iteration},
    )
    return node.id
```

`Budget.consume(...)` mutates in place; subtract from any cap.
`Budget.pressure` returns `max(usage_fraction across all dimensions)`.

### 4.2 T2-2 — `core/perceiver.py` (Day 2)

```python
class Perceiver:
    def __init__(self, db, cortex, memory_assembler):
        self.db = db
        self.cortex = cortex
        self.memory = memory_assembler

    async def gather(self, state: AgentState) -> Perception:
        # 1. Viewport (bounded)
        viewport = await self.cortex.navigate(state.cortex_cursor)
        viewport_text = viewport.to_prompt_text(
            include_ops_help=False,           # Track 6 will move this to system prompt
            max_chars=state.entity_context_budget_chars,
        )

        # 2. Intelligence rules (top K, scope-aware)
        intel = await self.memory.intelligence_rules(
            entity_id=state.entity_id,
            task_class=state.task_class,
            top_k=5,
        )

        # 3. Past similar runs (Episodic)
        episodic = await self.memory.recent_similar_runs(
            entity_id=state.entity_id,
            task_class=state.task_class,
            top_k=3,
        )

        # 4. Pending HITL
        pending = await self._load_pending_hitl(state.run_id)

        # 5. Build perception object
        return Perception(
            iteration=state.iteration,
            viewport_text=viewport_text,
            intelligence_rules=intel,
            recent_reflections=state.reflections[-3:],
            similar_past_runs=episodic,
            budget_pressure=state.budget.pressure,
            pending_hitl=pending,
            open_subgoals_text=render_subgoals(state.open_subgoals),
            last_action_summary=summarise_action(state.last_action),
            last_observation_summary=summarise_observation(state.last_observation),
        )
```

The perception payload is a *typed* object. Rendering to a prompt string
is a separate function `perception.to_prompt_block() -> str` so we can
unit-test the structure vs the rendering separately.

### 4.3 T2-3 — `core/strategist.py` (Day 3)

The Track 2 Strategist is **deterministic**. The LLM-driven version is
Track 4/7.

```python
class Strategist:
    """
    Deterministic strategist for Track 2.

    Picks an executor based on entity type and plan state.
    The LLM-driven version arrives in Track 4 + Track 7.
    """

    async def next_move(self, state, perception) -> Move:
        # Case A: there is a pending static plan with ready steps
        if state.has_plan() and state.plan_has_unblocked_steps():
            ready = state.plan_ready_steps()
            if len(ready) >= 2 and self._allow_parallel(state):
                return Move(
                    move_id=new_id(),
                    goal_id=state.current_goal_id(),
                    executor="DAG",
                    plan_fragment=ready,
                    rationale="≥2 ready steps; parallel DAG",
                    expected_value="med",
                    expected_cost_usd=self._estimate(ready),
                )
            return Move(
                move_id=new_id(),
                goal_id=state.current_goal_id(),
                executor="SingleStep",
                plan_fragment=ready[:1],
                rationale="One ready step; sequential",
                expected_value="med",
                expected_cost_usd=self._estimate(ready[:1]),
            )

        # Case B: child entity invocation
        if state.next_step_is_child_invocation():
            return Move(... executor="ChildEntity" ...)

        # Case C: no plan, entity is goal-only AGENT → recursive
        if state.entity_type == EntityType.AGENT and not state.has_plan():
            return Move(... executor="Recursive" ...)

        # Default: SingleStep on the current step
        return Move(... executor="SingleStep" ...)

    def decide_next(self, state, super_verdict) -> Decision:
        if state.budget.exhausted():
            return Decision(next="ABORT", reason="budget exhausted")
        if super_verdict and super_verdict.recommendation == "ABORT":
            return Decision(next="ABORT", reason=super_verdict.reasoning)
        if super_verdict and super_verdict.recommendation == "PAUSE":
            return Decision(next="PAUSE_HITL", reason=super_verdict.reasoning)
        if state.all_subgoals_achieved():
            return Decision(next="DONE", reason="all subgoals achieved")
        return Decision(next="CONTINUE", reason="more work")
```

### 4.4 T2-4 — `core/observer.py` + `core/reflector.py` (Day 4)

```python
class Observer:
    def parse(self, action_result, state) -> Observation:
        return Observation(
            iteration=state.iteration,
            outcome=("success" if action_result.success
                     else "fail" if action_result.error
                     else "partial"),
            novelty_score=self._novelty(action_result, state),
            goal_delta_estimate=self._goal_delta(action_result, state),
            cortex_node_ids_written=action_result.cortex_nodes_written,
            summary=self._summarise(action_result),
        )

    def _novelty(self, ar, state):
        # Simple v1: 1.0 if any new CORTEX node was written, else 0.5
        return 1.0 if ar.cortex_nodes_written else 0.5

    def _goal_delta(self, ar, state):
        # Track 2 stub: +0.1 on success, -0.1 on fail
        if ar.success: return 0.1
        if ar.error: return -0.1
        return 0.0
```

```python
class Reflector:
    def __init__(self, llm_router, intelligence_tree):
        self.llm = llm_router
        self.intel = intelligence_tree

    def produce(self, state, obs, verdicts) -> Reflection:
        """Deterministic v1: no LLM. Just summarise verdicts/observations.

        LLM-driven version arrives in Track 4."""
        what_worked = "step executed; output written" if obs.outcome == "success" else ""
        what_didnt  = "; ".join(t.value for t in (verdicts.post.tags if verdicts.post else []))
        return Reflection(
            iteration=state.iteration,
            scope="run",
            what_worked=what_worked,
            what_didnt=what_didnt,
            cause_hypothesis="",
            proposed_change="",
            confidence=0.5,
        )

    async def persist(self, reflection, state):
        # Run-scope reflections stay in state.reflections only;
        # nothing written to durable storage in Track 2.
        # Entity-scope and task_class-scope candidates land in Track 4.
        return
```

### 4.5 T2-5 — Executor adapters (Days 5-6)

#### 4.5.1 `DAGExecutor` (Day 5 AM)

Wraps `ExecutionEngine._execute_steps_dag`. Marshals state:

```python
@register
class DAGExecutor:
    name = "DAG"

    async def execute(self, move, state, db) -> ActionResult:
        from src.ai.core.execution_engine import ExecutionEngine
        engine = ExecutionEngine(db, state.redis, state.company_id)
        engine._ensure_services(state.company_id)
        run = await engine._reload_run(state.run_id)
        entity = run.entity
        context_state = await state.materialise_context_dict()

        all_results = await engine._execute_steps_dag(
            run, entity, move.plan_fragment, context_state,
        )
        await state.absorb_context_dict(context_state)
        cost = sum(Decimal(str(r.get("cost_usd", 0))) for r in all_results)
        return ActionResult(
            output=all_results[-1].get("output", "") if all_results else "",
            tools_used=[],
            children_run_ids=[],
            cost_usd=cost,
            latency_ms=0,
            cortex_nodes_written=[],
            success=all(not r.get("error") for r in all_results),
        )
```

Note: `materialise_context_dict` and `absorb_context_dict` are the
**boundary functions** between `AgentState` and the legacy `context_state`
dict. They live in `core/agent_state.py`.

#### 4.5.2 `SingleStepExecutor` (Day 5 PM)

Same pattern: call `step_executor._execute_step` with marshalled state.

#### 4.5.3 `RecursiveExecutor` (Day 6 AM)

Adapter around `RecursiveReasoningEngine.execute_tree`.

#### 4.5.4 `ChildEntityExecutor` (Day 6 PM)

Adapter around `step_executor._execute_child_invocation`.

#### 4.5.5 `Dialog/ToolBurst/Skill` stubs (Day 6 PM)

```python
@register
class DialogExecutor:
    name = "Dialog"
    async def execute(self, move, state, db):
        raise NotImplementedError("DialogExecutor — Track 5")
```

Strategist NEVER picks these in Track 2; the stubs exist so the
registry is complete.

### 4.6 T2-6 — Reasoning extraction (Day 7)

Move `_execute_chain_of_thought`, `_execute_reflection`,
`_execute_tree_of_thoughts` out of `step_executor.py` and into
`core/reasoning/`.

```python
# core/reasoning/base.py
class BaseReasoning:
    async def run(self, llm_router, system_prompt, user_prompt, task_type,
                  config, tool_schemas, execute_tool_fn,
                  model_override=None) -> tuple[str, LLMResponse]: ...
```

```python
# core/reasoning/react.py
class ReactReasoning(BaseReasoning):
    name = ReasoningMode.REACT
    async def run(self, ...):
        # Existing call_llm_react logic moves here (or stays where it is
        # in llm/router.py; this class just calls into it).
        ...
```

`step_executor.py::_execute_thought` shrinks; its reasoning-mode
dispatch becomes:

```python
strategy = REASONING_REGISTRY[reasoning_mode]
output, response = await strategy.run(...)
```

### 4.7 T2-7 — `AgentLoop` (Days 8-9)

```python
# core/agent_loop.py
class AgentLoop:
    def __init__(self, db, redis, company_id, feature_flags):
        self.db = db
        self.redis = redis
        self.company_id = company_id
        self.flags = feature_flags
        # Deps composed lazily once state is known
        self.cortex: CortexService | None = None
        self.memory_assembler = None
        self.perceiver = None
        self.strategist = None
        self.observer = None
        self.reflector = None
        self.critic_pipeline = None      # NoOpCriticPipeline in Track 2

    async def run(self, run_id: UUID) -> dict:
        async with AsyncSessionLocal() as db:
            state = await AgentState.bootstrap_from_db(run_id, db)
            self._compose(state, db)

            event("agent.loop.run_start", state=state)
            while not state.done:
                await self._iteration(state, db)
                if state.budget.exhausted():
                    event("agent.loop.budget_exhausted", state=state)
                    break
            event("agent.loop.run_end", state=state)
            return await self._finalize(state, db)

    async def _iteration(self, state, db):
        state.iteration += 1
        state.budget.consume(iter_step=True)
        event("agent.loop.iteration_start", state=state)

        perception = await self.perceiver.gather(state)
        state.perception = perception

        move = await self.strategist.next_move(state, perception)
        pre = await self.critic_pipeline.pre_action(move, state)
        if pre.kind == "BLOCK":
            event("agent.loop.pre_critic_block", state=state, concerns=pre.concerns)
            return

        executor = EXECUTOR_REGISTRY[move.executor]
        action_result = await executor.execute(move, state, db)
        state.last_action = Action(
            iteration=state.iteration, executor=move.executor,
            move_id=move.move_id, payload=...,
        )

        observation = self.observer.parse(action_result, state)
        state.apply_observation(observation)

        post = await self.critic_pipeline.post_action(state, observation)
        align = await self.critic_pipeline.alignment(state, observation)
        supervise = await self.critic_pipeline.supervisor(state)

        reflection = self.reflector.produce(state, observation,
                                            Verdicts(post=post, align=align, super=supervise))
        await self.reflector.persist(reflection, state)
        state.reflections.append(reflection)

        decision = self.strategist.decide_next(state, supervise)
        state.apply_decision(decision)
        state.budget.consume(usd=action_result.cost_usd,
                              wall_s=action_result.latency_ms // 1000)

        await state.snapshot_to_cortex(self.cortex, state.working_root_id)
        event("agent.loop.iteration_end", state=state, decision=decision.next)
```

### 4.8 T2-8 — Arq dispatch (Day 9 PM)

```python
# core/arq_jobs.py — updated
async def run_execution_recursive(ctx, run_id_str: str):
    run_id = UUID(run_id_str)
    import redis.asyncio as redis
    from src.common.config import settings
    from src.ai.core.feature_flags import FeatureFlags
    from src.ai.core.agent_loop import AgentLoop
    from src.ai.core.execution_engine import ExecutionEngine

    redis_pool = redis.from_url(settings.REDIS_URL or "redis://localhost:6379")
    async with AsyncSessionLocal() as db:
        flags = FeatureFlags(db, redis_pool)
        if await flags.is_on("agent_loop.enabled", run_id=run_id):
            loop = AgentLoop(db, redis_pool, company_id=None,
                             feature_flags=flags)
            await loop.run(run_id)
        else:
            engine = ExecutionEngine(db, redis_pool)
            await engine.execute_run(run_id)
    await redis_pool.close()
```

The feature flag is checked **per run** via the entity's company-id
override (see Track 13).

### 4.9 T2-9 — Parity test harness (Day 10)

`backend/tests/parity/test_agent_loop_parity.py`:

```python
@pytest.mark.parametrize("entity_fixture", [
    "fixtures/parity/simple_skill.json",
    "fixtures/parity/research_agent.json",
    "fixtures/parity/two_step_process.json",
])
async def test_parity_legacy_vs_loop(entity_fixture, db, redis):
    entity = load_entity(entity_fixture)
    input_data = load_input(entity_fixture)

    # Run on legacy path
    legacy_run = await run_with_flag(entity, input_data, flag=False, db=db)

    # Run on new path
    loop_run = await run_with_flag(entity, input_data, flag=True, db=db)

    assert legacy_run.status == loop_run.status
    assert abs(legacy_run.cost - loop_run.cost) / legacy_run.cost < 0.05
    assert similarity(legacy_run.output, loop_run.output) > 0.85
```

`similarity()` is a sentence-embedding cosine helper (not semantic
identity — outputs may differ in word choice).

---

## 5. Database / schema changes

### 5.1 New CORTEX node type: `snapshot`

The CORTEX schema already accepts a string `node_type`. To formalise:

* Add `"snapshot"` to the `CortexNodeType` enum (`schemas/enums.py`).
* No SQL change — column is already free-text.

### 5.2 Migration `p11t02_step_health_record.py`

Not in this Track — Track 3 owns it. Track 2 only writes snapshot nodes
which the existing CORTEX schema supports.

### 5.3 Feature flags table (if not already present)

If `feature_flags` table doesn't exist:

```python
# backend/migrations/versions/p11t02_feature_flags.py
def upgrade():
    op.create_table(
        "feature_flags",
        sa.Column("id", PGUUID, primary_key=True),
        sa.Column("company_id", PGUUID, nullable=True),     # null = global
        sa.Column("flag_key", sa.String(128), nullable=False),
        sa.Column("enabled", sa.Boolean, nullable=False, default=False),
        sa.Column("created_at", sa.DateTime, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime, server_default=sa.text("now()")),
    )
    op.create_index("ix_feature_flags_company_key",
                    "feature_flags", ["company_id", "flag_key"], unique=True)
```

See [`13_observability_feature_flags_rollout.md`](./13_observability_feature_flags_rollout.md)
§3 for the full FeatureFlags service spec.

---

## 6. API changes

### 6.1 SSE event additions

The `/api/v1/executions/{id}/stream` endpoint already publishes status
transitions. Track 2 adds new payload kinds (no path/route changes):

```jsonc
// event: agent.loop.iteration_start
{
  "type": "iteration_start",
  "iteration": 4,
  "executor": "DAG",
  "budget_pressure": 0.31,
  "open_subgoals": 2
}

// event: agent.loop.iteration_end
{
  "type": "iteration_end",
  "iteration": 4,
  "outcome": "success",
  "decision": "CONTINUE",
  "cost_iter_usd": 0.012
}

// event: agent.loop.resume
{
  "type": "resume",
  "from_iteration": 7
}
```

Existing UI clients ignore unknown event types — no breakage.

### 6.2 New read-only debug endpoint

```
GET /api/v1/executions/{id}/agent_state
```

Returns the latest `AgentState` snapshot if one exists. Useful for
debugging in dev/staging. Behind a `superadmin`-only auth check.

Schema:

```python
class AgentStateResponse(BaseModel):
    run_id: UUID
    iteration: int
    budget: dict
    open_subgoals: list[dict]
    achieved_subgoals: list[dict]
    blockers: list[dict]
    last_action_summary: str
    last_observation_summary: str
```

---

## 7. Telemetry events

| Event | Payload | Cardinality | Owner |
|-------|---------|-------------|-------|
| `agent.loop.run_start` | `{run_id, entity_id, company_id, budget_caps}` | 1 / run | AgentLoop |
| `agent.loop.run_end` | `{run_id, outcome, iters, total_cost_usd, total_tokens, latency_ms}` | 1 / run | AgentLoop |
| `agent.loop.iteration_start` | `{run_id, iteration, executor, budget_pressure}` | 1 / iter | AgentLoop |
| `agent.loop.iteration_end` | `{run_id, iteration, outcome, decision, cost_iter_usd, cortex_nodes_written}` | 1 / iter | AgentLoop |
| `agent.loop.budget_pressure` | `{run_id, iteration, pressure}` | only when >0.5 | Budget |
| `agent.loop.budget_exhausted` | `{run_id, iteration, dim}` (`dim` = which axis blew first) | rare | Budget |
| `agent.loop.resume` | `{run_id, from_iteration}` | 1 / resume | AgentLoop |
| `agent.loop.pre_critic_block` | `{run_id, iteration, concerns}` | rare | AgentLoop |
| `agent.executor.invoked` | `{run_id, iteration, executor, plan_size}` | 1 / iter | Executor base |
| `agent.executor.completed` | `{run_id, iteration, executor, success, cost_usd, latency_ms}` | 1 / iter | Executor base |

Event envelope is shared (see Track 13).

---

## 8. Feature flags

| Flag | Default | Resolution | Notes |
|------|---------|-----------|-------|
| `agent_loop.enabled` | OFF (global) | per-company OR per-entity override via `entity.metadata_extensions.feature_flags.agent_loop` | The master switch |
| `agent_loop.perception_bounded_viewport` | ON | global | Bounds CORTEX viewport rendering to `max_chars` (Track 6 will move ops-help out) |
| `agent_loop.snapshot_every_iteration` | ON | global | Can be OFF for cost-sensitive smoke tests |
| `agent_loop.executor_dialog_enabled` | OFF | global | Off until Track 5 |
| `agent_loop.executor_skill_enabled` | OFF | global | Off until Track 5 |
| `agent_loop.executor_tool_burst_enabled` | OFF | global | Off until Track 7/8 |

---

## 9. Tests

### 9.1 Unit

* `test_budget_pressure_axes` — token / USD / wall / iter pressure
  computed correctly; `exhausted` triggers when any axis at 100%.
* `test_agent_state_snapshot_restore` — round-trip `snapshot_to_cortex`
  / `restore_from_cortex` is lossless for every field.
* `test_subgoal_lifecycle` — `add → block → unblock → achieve` ordering
  correct.
* `test_strategist_deterministic_choices` — for each canonical input
  state, the executor picked is the one specified in §4.3.
* `test_observer_outcome_classification` — success/partial/fail mapping.
* `test_reflector_noop_when_no_obs` — does not crash on empty
  observation.
* `test_executor_registry_complete` — all seven names registered.
* `test_reasoning_registry_complete` — all four modes registered.

### 9.2 Integration

* `test_loop_iteration_end_to_end` — one full iteration on a stub
  executor produces all events, writes a snapshot, mutates state.
* `test_loop_resume_after_crash` — kill mid-iteration (simulate by
  raising), restart, confirm `from_iteration` is `prev+1`.
* `test_legacy_path_unchanged_when_flag_off` — every existing test
  passes with flag off.

### 9.3 Parity

The harness from §4.9 runs on three fixture entities. Acceptance:
status equal, cost within ±5%, output cosine similarity ≥ 0.85.

### 9.4 Load / chaos (optional, but recommended)

* `test_loop_cancelled_arq_job` — Arq cancellation between iterations
  → next pickup resumes.
* `test_loop_db_connection_drop_mid_iteration` — DB pool kills connection
  → loop reconnects on `bootstrap_from_db` retry.

---

## 10. Acceptance criteria

1. `AgentLoop.run(run_id)` is the entry point when
   `agent_loop.enabled = true`.
2. With the flag OFF, all existing tests pass unchanged.
3. With the flag ON for the three parity fixtures: status equal, cost
   within ±5%, output similarity ≥ 0.85.
4. SSE stream emits the new event types defined in §6.1 for new runs.
5. Crashing the worker mid-iteration and restarting it resumes from the
   last snapshot (`agent.loop.resume` event observed).
6. `mypy --strict` clean on `core/`.
7. All seven executors registered; the three stubs raise
   `NotImplementedError` and the Strategist never picks them.
8. All four reasoning modes pass their existing per-mode tests after
   extraction.
9. Layout lint clean.

---

## 11. Effort breakdown (10 working days)

| Day | Work |
|-----|------|
| 1 | T2-1: `agent_state.py`, `budget.py`, types + tests |
| 2 | T2-2: `perceiver.py` + tests |
| 3 | T2-3: `strategist.py` (deterministic) + tests |
| 4 | T2-4: `observer.py` + `reflector.py` + tests |
| 5 | T2-5a: `DAGExecutor` + `SingleStepExecutor` |
| 6 | T2-5b: `RecursiveExecutor` + `ChildEntityExecutor` + stubs |
| 7 | T2-6: reasoning extraction + per-mode tests pass |
| 8 | T2-7: `AgentLoop` skeleton + first end-to-end run on stub |
| 9 | T2-7 cont'd + T2-8: Arq dispatch + Feature flag wiring |
| 10 | T2-9: Parity harness + final QA + PR |

Buffer to add: a second engineer can shave 3-4 days by parallelising
T2-5/T2-6 (executor/reasoning extraction).

---

## 12. Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Adapter boundary drift: AgentState → context_state marshalling loses fields | H | Parity fails | Property-based test: round-trip `materialise` → `absorb` is identity for all `Subgoal/Action/Observation` fields |
| Recursive child runs (the existing pattern) don't fit the new loop cleanly | H | ChildEntityExecutor breaks on long children | Use async dispatch path (set `governance.async_child_dispatch = true` for test fixtures) |
| Snapshot writes inflate CORTEX tree size | M | Cost increase | Compact snapshots: keep last 20 reflections only; older roll up |
| Critic stub returning PASS hides regressions | M | False sense of parity | Mark Track 2 sign-off explicitly as "no critic"; Track 3 is the real validation |
| Strategist deterministic rules miss an edge case (entity with no plan + AGENT type + REACT-only) | M | Strategist returns no Move | Default-case fallback: SingleStep with the entity's primary step |
| Reasoning extraction breaks REFLECTION (3-pass) cost accounting | M | Token totals off | Cover with explicit test on aggregated `prompt_tokens` / `completion_tokens` |

---

## 13. Dependencies

* **Upstream:**
  * Track 0 (layout / re-export cleanup).
  * Track 1 (`FailureTag`, typed `PlanStep.type`, `HITLTriggerType`).
* **Downstream:**
  * Track 3 (CriticPipeline replaces the NoOpCriticPipeline used here).
  * Track 4 (Meta-Review v2 reads `AgentState`).
  * Track 5 (Skill / Dialog executors).
  * Track 7 (Planner with priors feeds `Strategist`).

---

## 14. Open questions

* Should the snapshot interval be every iteration or every K iterations?
  Default to every iteration; introduce K via
  `agent_loop.snapshot_every_n` flag in Track 9 if cost becomes a
  concern.
* Do we need a separate `LoopRunResult` ORM table, or is the existing
  `ExecutionRun` enough? Track 2 lands `ExecutionRun.result_data` + the
  CORTEX snapshot subtree only; a dedicated table is a Track 9 follow-up
  if KPI queries become awkward.
