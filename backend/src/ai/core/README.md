# `core/` — The agent kernel

The autonomous control loop and the typed state envelope it operates
on. Everything else in `backend/src/ai/` is a service the loop calls.

## What's in here

| File | Purpose |
|------|---------|
| `agent_loop.py` | The Phase 11 control loop — perceive → strategize → pre-critic → act → observe → post-critic → reflect → decide. Entry point: `AgentLoop.run(run_id)`. |
| `agent_state.py` | `AgentState` envelope + `Subgoal` / `Hypothesis` / `Blocker` / `Action` / `Observation` / `Reflection` / `Verdicts` / pre/post/alignment/supervisor critic verdict dataclasses. |
| `budget.py` | First-class `Budget` (tokens / USD / wall-clock / iterations) with `pressure`, `consume`, `exhausted`. |
| `perceiver.py` | Gathers `Perception` (viewport + intelligence rules + recent reflections + pending HITL + open subgoals). |
| `strategist.py` | Deterministic `next_move` + `decide_next`. Consults the `PlanStyleBandit` when ≥2 plan styles fit. |
| `observer.py` | Maps an `ActionResult` to an `Observation`. |
| `reflector.py` | Produces `Reflection`; escalates scope from `"run"` to `"entity"` on learnable signals; persists candidate Intelligence rules. |
| `executors/` | One adapter per executor name (`DAG`, `Recursive`, `SingleStep`, `ChildEntity`, stubs for `Dialog` / `ToolBurst` / `Skill`). |
| `reasoning/` | Pluggable reasoning strategies (`REACT`, `CHAIN_OF_THOUGHT`, `REFLECTION`, `TREE_OF_THOUGHTS`). |
| `feature_flags.py` | Async `FeatureFlags` service + `DEFAULTS` + `NUMERIC_DEFAULTS`. |
| `events.py` | Telemetry emission. |
| `meta_review.py` | **Deprecated shim** for the legacy `MetaReviewer.review_execution` API. Routes to `SupervisorCritic.assess`. Slated for deletion in Phase 12. |
| `execution_engine.py` | **Legacy** orchestrator. Still reachable when `agent_loop.enabled=false`. |
| `arq_jobs.py`, `recursive_engine.py`, `context_utils.py`, `prompt_utils.py`, `exceptions.py` | Supporting services. |

## Key types

- `AgentState` — the typed envelope shared by every loop layer.
- `Budget` — first-class cost / wall / iteration tracker.
- `Move`, `Decision` — what the Strategist returns.
- `Subgoal`, `Reflection`, `Observation`, `Blocker`, `Hypothesis`.
- `PreCriticVerdict`, `PostCriticVerdict`, `AlignmentVerdict`,
  `SupervisorVerdict`, `Verdicts`.

## Entry points

- **Arq dispatch** → `core/arq_jobs.run_execution_recursive` →
  `AgentLoop.run(run_id)` (new path, gated by `agent_loop.enabled`)
  OR `ExecutionEngine.execute_run(run_id)` (legacy).
- **AgentLoop** composes `Perceiver`, `Strategist`, `Observer`,
  `Reflector`, `CriticPipeline`, and the executor / reasoning
  registries.

## See also

- `docs/phase11/plan/01_overview_and_principles.md` — the canonical
  architecture picture + the eight load-bearing types.
- `docs/phase11/plan/04_track_2_agent_loop.md` — the loop.
- `docs/phase11/plan/05_track_3_critic_pipeline.md` — critic gates.
- `docs/phase11/plan/06_track_4_meta_review_goalguard.md` —
  SupervisorCritic + bandit.
- `core/INTERNAL_KEYS.md` — every key inside the legacy
  `context_state: dict` bridge.
