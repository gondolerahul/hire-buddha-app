# `INTERNAL_CONTEXT_KEYS` — the legacy `context_state` bridge

`AgentLoop` reasons over a typed `AgentState`. Legacy code paths
(`ExecutionEngine.execute_run`, the per-step executors, the
context-source ingestor) still pass a `context_state: dict` around.
`INTERNAL_CONTEXT_KEYS` is the canonical set of keys that MUST be
stripped before:

  * sending a payload to an LLM as the *user input*, and
  * persisting it back into `ExecutionRun.context`.

These are intra-loop plumbing values. They never belong in a prompt
or in a billing log.

Source of truth: `backend/src/ai/constants.py::INTERNAL_CONTEXT_KEYS`.

## Inventory

| Key | Writer | Reader | Lifecycle | Notes |
|-----|--------|--------|-----------|-------|
| `input` | the caller that triggered the run (HTTP route, cron, gateway, parent run) | every step type | entire run | The user-facing prompt; promoted into the typed `AgentState.context_state["input"]` for compatibility. |
| `cortex_tree_id` | `AgentLoop._bootstrap_state` / `ExecutionEngine.execute_run` | `step_executor`, `CortexService` | entire run | UUID of the run's CORTEX tree. |
| `subtree_root_id` | parent run when spawning a child via `RECURSE` | `CortexService(scoped_subtree_root_id=...)` | child run | Pins the child's CORTEX writes to a subtree. |
| `__memory__` | `MemoryAssemblyService` / legacy `MemoryRouter` | `prompt_utils.build_sandwich_prompt` | per iteration | Concatenated, ready-to-inject memory block. |
| `__cortex_viewport__` | `CortexService.get_viewport(...)` | `prompt_utils` | per CORTEX op | Rendered viewport text (now bounded by `max_chars`). |
| `__cortex_tree_id__` | `CortexService.create_tree` | CORTEX ops | run | Mirror of `cortex_tree_id` for older callers. |
| `__cortex_cursor__` | `CortexService.navigate` | CORTEX ops | per iteration | Where the agent's viewport currently sits. |
| `__cortex_knowledge__` | `cortex_bridge.ingest_tool_result` | CORTEX ops | run | Knowledge-subtree handle. |
| `__context_sources__` | design-time context-source upload | `MemoryAssemblyService` | run | List of `{type, id, page_range}`. |
| `__episodic_memory__` | `EpisodicTreeService.get_recent_episodes` / `LegacyEpisodicReader.read` | `prompt_utils` | per iteration | List of past-episode dicts. |
| `__semantic_context__` | `KnowledgeTreeService` semantic search | `prompt_utils` | per iteration | Top-K knowledge refs. |
| `__memory_context__` | unified memory rollup (v2 path) | `prompt_utils` | per iteration | Composite of the four domains. |
| `__completed_steps__` | `step_executor.store_step_output` | `step_executor`, planner adapt | run | Ordered list of completed-step dicts; consumed by `PlannerService.adapt_plan`. |
| `tool_call_counts` | `ToolExecutor` per-run budget | `ToolExecutor` | run | Mutates in place; rate-limits per (run, tool). |
| `company_id` | router / arq job | every layer | run | Tenant scoping. |
| `user_id` | router / arq job | every layer | run | Tenant scoping. |
| `__intelligence__` | `IntelligenceTreeService.get_applicable_rules` | `prompt_utils` | per iteration | List of rule dicts. |
| `__experience__` | `ExperienceTreeService.get_suggestions` | `prompt_utils` | per iteration | Learned execution patterns. |
| `__episodic__` | `EpisodicTreeService.get_recent_episodes` (v2 path) | `prompt_utils` | per iteration | Same shape as `__episodic_memory__`; v2 path uses this key. |
| `__knowledge_refs__` | `KnowledgeTreeService.search` | `prompt_utils` | per iteration | Top-K knowledge ref dicts. |
| `__execution_metadata__` | `AgentLoop._bootstrap_state` | meta-cognition prompts | run | `{iteration, budget_pressure, open_subgoals}` mirror so legacy prompts can introspect. |
| `__intelligence_rules__` | `MemoryAssemblyService` | `prompt_utils` (LLM Intelligence-Only mode) | per iteration | Formatted rule lines. |
| `__alignment_correction__` | GoalGuard shim / `CriticPipeline.alignment` | retry step | iteration N+1 | Correction hint from a failed alignment check. |
| `__goal_check_counter__` | GoalGuard shim | GoalGuard shim | run | Counts how many alignment checks have run; throttles cadence. |

## Invariants

1. **Keys here are mutually exclusive with prompt input.**
   `prompt_utils._scrub_internal_keys` MUST strip every member before
   concatenating user-facing fields.
2. **Adding a new key requires updating both `constants.py` AND this
   table** (enforced by Track 9 unit test `test_internal_keys_documented`).
3. **Removing a key requires a deprecation cycle** — at least one
   release of `pop(... , None)` with a warning before the underlying
   producer is removed.
4. The keys are *additive across releases* — readers MUST tolerate
   absence and use sensible defaults rather than KeyError.

## See also

- `backend/src/ai/constants.py` — the source of truth.
- `backend/src/ai/core/prompt_utils.py` — where the scrub happens.
- `docs/phase11/plan/01_overview_and_principles.md` §4 — the typed
  `AgentState` envelope replacing this dict for new code.
