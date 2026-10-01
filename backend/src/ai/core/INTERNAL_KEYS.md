# `INTERNAL_CONTEXT_KEYS` — the `context_state` bridge

`AgentLoop` reasons over a typed `AgentState`. The per-step executors, the
tool executor and the memory assembler still take a plain `context_state: dict`;
the loop copies state into it (`AgentState.materialise_context_dict`) and back
(`absorb_context_dict`) around every executor call. `INTERNAL_CONTEXT_KEYS` is
the set of keys in that dict that are loop plumbing, not task data: the step
executor leaves them out of the "Available Context from Previous Steps" block it
appends to a step's prompt, and out of a tool's fallback input.

Source of truth: `backend/src/ai/constants.py::INTERNAL_CONTEXT_KEYS`. Replacing
the dict with typed state is AK-21 in the
[consolidated plan](../../../../docs/current/defect-register/CONSOLIDATED-KERNEL-TOOLS-PLAN.md).

## Inventory

Re-checked against the code on 2026-10-01. **No writer** means nothing in
`src/` puts the key into a context today — readers always see it absent.

| Key | Writer | Reader | Notes |
|-----|--------|--------|-------|
| `input` | the caller that triggered the run (HTTP route, cron, gateway, parent run) | every step type | The run's request. Seeded into `AgentState.context_state` from `run.input_data` at bootstrap |
| `cortex_tree_id` | the caller (a parent's child dispatch, retry, refine) | `run_memory.open_run_tree` | Resume this CORTEX tree instead of creating one |
| `subtree_root_id` | the CORTEX `RECURSE` factory | `CortexService(scoped_subtree_root_id=...)` | Pins a RECURSE child's writes to a subtree |
| `__memory__` | `run_memory.assemble_run_memory` | `step_executor.prompt_context_block` (sandwich layer 9) | Rendered memory block, assembled once per run |
| `__episodic_memory__` | `memory.assembler` | `RunMemory.similar_runs` (Perceiver) | Past-episode dicts |
| `__intelligence_rules__` | `run_memory.assemble_run_memory` | `RunMemory` (Perceiver, supervisor critic), `PlannerService` | Rule dicts (`title`, `rule`, `type`, `confidence`) |
| `__cortex_viewport__` | `CortexBridge` | CORTEX step prompts | Rendered viewport text |
| `__alignment_correction__` | `StepEngine`'s GoalGuard check | the re-executed step | Correction hint from a failed goal check |
| `__goal_check_counter__` | `StepEngine`'s GoalGuard check | the same | How many goal checks have run |
| `tool_call_counts` | `StepExecutorService` (reset per step) | `ToolExecutor` | Per-tool call counts (TL-11: reset per step, not per run) |
| `company_id`, `user_id` | the step executor's tool context | tools | Tenant scoping |
| `__cortex_tree_id__` | `AgentLoop._compose` (when it opens the run's tree), and `_persist_final` onto `run.context_state` | child dispatch, retry, refine, `agent_reflect`, `CortexBridge` | Had no writer until EP-29, so a child never shared its parent's tree and a retry never resumed it |
| `__cortex_cursor__` | **no writer** | `agent_introspect`, `agent_reflect`, `CortexBridge` | `AgentState.cortex_cursor` is never set either — AK-05 |
| `__context_sources__` | **no writer** | `prompt_context_block` | Design-time context sources never reach this key |
| `__completed_steps__` | **no writer** | — | Step completion lives in `AgentState.completed_step_ids` (EP-16) |
| `__execution_metadata__`, `__intelligence__` | **no writer** | `agent_introspect` | |
| `__semantic_context__`, `__memory_context__`, `__cortex_knowledge__`, `__experience__`, `__episodic__`, `__knowledge_refs__` | **no writer** | — | Names reserved by earlier memory designs |

`__agent_state__` — the loop's `{iteration, budget_pressure, open_subgoals}`
echo, written by `materialise_context_dict` — is in the set (EP-25), so it is
no longer rendered into step prompts as if it were a previous step's output.

## Invariants

1. **These keys are plumbing.** They never belong in a prompt's task data or in
   a billing log. There is no shared scrub helper: the step executor filters by
   `INTERNAL_CONTEXT_KEYS` inline where it builds the context block and a tool's
   fallback input (`prompt_utils._scrub_internal_keys`, cited by older docs, never
   existed — LP-16).
2. **Adding a key** means adding it to `constants.py` and to this table.
3. **Readers must tolerate absence** and use sensible defaults, never `KeyError`.

## See also

- `backend/src/ai/constants.py` — the source of truth.
- `backend/src/ai/step_executor.py` — where the filtering happens.
- `docs/current/05-agent-kernel.md` — the typed `AgentState` envelope.
