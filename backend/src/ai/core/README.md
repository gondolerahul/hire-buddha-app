# `core/` — The agent kernel

The autonomous control loop and the typed state envelope it operates on. Every
run of every entity goes through `AgentLoop`; there is no other engine (the
legacy `ExecutionEngine.execute_run` plan-walker and `recursive_engine.py` were
deleted in C4). Everything else in `backend/src/ai/` is a service the loop calls.

The full design is [`docs/current/05-agent-kernel.md`](../../../../docs/current/05-agent-kernel.md).

## What's in here

| File | Purpose |
|------|---------|
| `agent_loop.py` | The control loop — perceive → strategize → pre-critic → act → observe → post-critic → alignment → supervisor → reflect → decide. Entry points: `AgentLoop.run(run_id)` and `AgentLoop.resume(run_id)` (a parent suspended on its children). |
| `agent_loop_sse.py` | `event_async`: telemetry plus the per-run SSE frames (`_SSE_EVENT_TYPES`, checked by `tests/unit/test_sse_event_contract.py`). |
| `agent_state.py` | The `AgentState` envelope + `Subgoal` / `Blocker` / `Action` / `Observation` / `Reflection` and the four critic verdicts. |
| `budget.py` | First-class `Budget` (tokens / USD / wall-clock / iterations) with `pressure`, `consume`, `exhausted`. |
| `credit_guard.py` | The run's credit admission, in-run breaker and settlement (BC-05, BC-06). |
| `perceiver.py` | Gathers `Perception` (viewport, intelligence rules, similar runs, pending HITL, open subgoals). |
| `strategist.py` | Deterministic `next_move` + `decide_next`; consults the `PlanStyleBandit` when two plan styles fit. |
| `observer.py` | Maps an `ActionResult` to an `Observation`. |
| `reflector.py` | Produces a `Reflection`; escalates scope from `run` to `entity` on learnable signals. |
| `executors/` | One adapter per executor name: `SingleStep`, `DAG`, `Recursive`, `ChildEntity`, `Debate`. |
| `step_engine.py` | The per-step surface the executors delegate into: the DAG scheduler, the step wrapper (timeout, HITL, cost cap, goal check). |
| `step_results.py` | The per-step result summary kept on `AgentState.step_results`. |
| `feature_flags.py` | The `FeatureFlags` resolver + `DEFAULTS` + `NUMERIC_DEFAULTS`. Every declared flag is read somewhere (`tests/unit/test_feature_flag_census.py`). |
| `arq_jobs.py` | The worker's jobs: run dispatch, parent resume, documents, Dreaming, CORTEX, and the weekly/nightly crons. |
| `trace.py`, `events.py` | Execution trace spans and structured telemetry. |
| `meta_review.py` | **Deprecated shim** for the legacy `MetaReviewer.review_execution` API; routes to `SupervisorCritic`. |
| `context_utils.py`, `prompt_utils.py`, `exceptions.py` | Supporting helpers. |
| `INTERNAL_KEYS.md` | The plumbing keys of the `context_state` dict the executors still take. |

## Key types

- `AgentState` — the typed envelope shared by every loop layer.
- `Budget` — first-class cost / wall / iteration tracker.
- `Move`, `Decision` — what the Strategist returns.
- `Subgoal`, `Reflection`, `Observation`, `Blocker`.
- `PreCriticVerdict`, `PostCriticVerdict`, `AlignmentVerdict`,
  `SupervisorVerdict`, `Verdicts`.

## Entry points

- **Arq dispatch** → `arq_jobs.run_execution_recursive(run_id)` →
  `AgentLoop.run(run_id)`.
- **Parent resume** → `arq_jobs.resume_parent_run(parent_run_id)` →
  `AgentLoop.resume(parent_run_id)`, enqueued by a child run's finalisation.

## See also

- [`docs/current/05-agent-kernel.md`](../../../../docs/current/05-agent-kernel.md) — the kernel.
- [`docs/current/06-execution-pipeline.md`](../../../../docs/current/06-execution-pipeline.md) — entities, steps, child runs.
- [`docs/current/07-planning-and-critics.md`](../../../../docs/current/07-planning-and-critics.md) — the planner and the critic gates.
- [`docs/current/defect-register/CONSOLIDATED-KERNEL-TOOLS-PLAN.md`](../../../../docs/current/defect-register/CONSOLIDATED-KERNEL-TOOLS-PLAN.md) — what is being fixed in this area, in what order.
