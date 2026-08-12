# 02 — Redundancy, Duplication, and Conflicting Workflows

This file is the **fact sheet**. It catalogs every place where the codebase has
duplicate / conflicting / dead / orphaned code, so that the cleanup in
[07_folder_restructure.md](./07_folder_restructure.md) is mechanical, not
discretionary.

> 🔎 **All anchors are real**: `path/to/file.py:line` or `git ls-files | grep ...`.

---

## 1. Ghost duplicates still in the git index

`git status` reports the following files as **deleted on disk but tracked**:

| Legacy path (still in git index) | Active replacement |
|---|---|
| `backend/src/ai/cortex_bridge.py` | `backend/src/ai/memory/cortex_bridge.py` |
| `backend/src/ai/cortex_ingestion.py` | `backend/src/ai/memory/cortex_ingestion.py` |
| `backend/src/ai/cortex_models.py` | `backend/src/ai/memory/cortex_models.py` |
| `backend/src/ai/cortex_router.py` | `backend/src/ai/memory/cortex_router.py` |
| `backend/src/ai/cortex_service.py` | `backend/src/ai/memory/cortex_service.py` |
| `backend/src/ai/dreaming_engine.py` | `backend/src/ai/memory/dreaming_engine.py` |
| `backend/src/ai/dreaming_prompts.py` | `backend/src/ai/memory/dreaming_prompts.py` |
| `backend/src/ai/embedding_service.py` | `backend/src/ai/memory/embedding_service.py` |
| `backend/src/ai/episodic_tree_service.py` | `backend/src/ai/memory/episodic_tree_service.py` |
| `backend/src/ai/experience_tree_service.py` | `backend/src/ai/memory/experience_tree_service.py` |
| `backend/src/ai/goal_alignment.py` | `backend/src/ai/planning/goal_alignment.py` |
| `backend/src/ai/governance_service.py` | `backend/src/ai/governance/governance_service.py` |
| `backend/src/ai/graph_service.py` | `backend/src/ai/memory/graph_service.py` |
| `backend/src/ai/intelligence_tree_service.py` | `backend/src/ai/memory/intelligence_tree_service.py` |
| `backend/src/ai/knowledge_tree_service.py` | `backend/src/ai/memory/knowledge_tree_service.py` |
| `backend/src/ai/llm_router.py` | `backend/src/ai/llm/router.py` |
| `backend/src/ai/memory_assembly_service.py` | `backend/src/ai/memory/memory_assembly_service.py` |
| `backend/src/ai/memory_service.py` | `backend/src/ai/memory/memory_service.py` |
| `backend/src/ai/planner_service.py` | `backend/src/ai/planning/planner_service.py` |
| `backend/src/ai/rate_limiter.py` | `backend/src/ai/governance/rate_limiter.py` |

**Action:** one `git rm` commit covering all 20 paths, plus a smoke run of
the worker to confirm no import lands on a ghost path.

> 🚨 Until this commit happens, anyone doing `git reset --hard` or `git
> clean -fd` will resurrect the duplicates, and IDEs will index both copies.

---

## 2. Duplicate runtime logic (live code, both reachable)

### 2.1 Tool cost lookup — `IntegrationRegistry` query repeated verbatim

Two near-identical blocks (~60 lines each) in `step_executor.py`:

* Path A — direct TOOL_CALL: `step_executor.py:517-580` (after each tool exec)
* Path B — REACT loop (`call_llm_react`): `step_executor.py:912-957`

They share the same `_TOOL_SKU_MAP`, the same `_TOOL_FIXED_COST` table, the
same SQL, the same accumulation logic.

**Action:** extract `ai/billing/tool_cost_resolver.py` (or `ai/governance/
tool_cost_resolver.py`):

```python
class ToolCostResolver:
    async def charge(self, run, tool_id: str, latency_ms: int) -> Decimal: ...
```

Both call sites become a one-liner. Bonus: the resolver becomes the single
place to emit cost telemetry per attribution (see F-18).

### 2.2 Memory pipeline branching — v1 / v2 both wired

`memory/assembler.py:42-53` selects on `memory_pipeline = "v1" | "v2"` per
entity. Default per the schema is `"v1"`. The Meta-Agent uses `v2`. Both
implementations are independently maintained.

The v1 path (`_assemble_v1`) routes through `MemoryRouter` and synthesises a
flat episodic+semantic block. The v2 path routes through
`MemoryAssemblyService` which uses the **four-domain tree services**. The two
emit different keys (`__memory__` vs `__memory__` + `__intelligence_rules__` +
`__episodic_memory__`), which leak into prompts via `INTERNAL_CONTEXT_KEYS`
(`constants.py:31-60`).

**Action:** pick v2 canonical; v1 becomes `memory/legacy_router.py`
imported only by a single migration adapter (read-only fallback when an
entity has no Episodic Tree yet).

### 2.3 Two `CortexRouter` classes named almost identically

* `memory/cortex_service.py` defines a class `CortexRouter` (the *service*).
* `memory/cortex_router.py` defines a FastAPI **APIRouter** with prefix
  `/api/v1/cortex`.

They are imported with disambiguating aliases:

```python
from src.ai.memory.cortex_service import CortexRouter as CortexService
```

`memory/cortex_router.py:16` does exactly this alias dance.

**Action:** rename `memory/cortex_service.py::CortexRouter` → `CortexService`.
Remove every `as CortexService` alias. The HTTP router keeps its file name.

### 2.4 Plan reconciliation logic duplicated between planner + step executor

`planner_service._reconcile_child_invocations()` (`:456-522`) hand-rolls
fuzzy name-matching to repair `CHILD_ENTITY_INVOCATION.entity_id` lost by the
LLM planner. `step_executor._execute_child_invocation` (`:129-184`) **also**
performs three strategies to re-resolve missing entity_ids at execution time.

The two never share code; the rules drift. The planner's matching is more
sophisticated (it considers `entity_name_hint`, order, static plan); the
executor's fallback is more defensive (hierarchy children index + DB name
lookup).

**Action:** introduce `planning/child_resolver.py` with one
`resolve_child_entity_id(step, parent_entity, db) -> UUID` function used by
both the planner (post-LLM) and the executor (runtime).

### 2.5 Goal-checking happens in *three* places

| Site | What it checks | Cost | Trigger |
|------|----------------|------|---------|
| `step_executor._review_step_output` | Single-step output vs success_criteria via LLM critic | 1 LLM call/step | Always if `review_mechanism.enabled` |
| `execution_engine._execute_step_wrapper` → `GoalGuard` (step-level) | Single-step alignment with entity.goal via `GoalAlignmentVerifier` | 1 LLM call every `goal_validation_interval` steps | `reasoning_config.goal_validation_interval > 0` |
| `execution_engine.execute_run` → `GoalGuard` (run-level) + `MetaReviewer` | Overall progress, replan/abort recommendation | 1-2 LLM calls every N steps | AUTONOMOUS mode |

They overlap conceptually but neither **knows about the others**:

* A step can fail review (critic), pass goal alignment, and the
  MetaReviewer still wants to abort. There is no shared "step health" record.
* All three call LLMs with the *same* model (the entity's default) — no
  diversification.

**Action:** unify into a single `planning/critic_pipeline.py` with three
stages (per-step, periodic-alignment, supervisor-review) and a single
`StepHealthRecord` written to a dedicated CORTEX subtree.

### 2.6 Reformat-retry and Fallback-chain logic

`step_executor._execute_tool_call` (`:334-600`) embeds: failure
classification (`_FORMAT_ERROR_KEYWORDS`, `_IO_ERROR_KEYWORDS`,
`_EMPTY_KEYWORDS`, `_TIMEOUT_KEYWORDS`), LLM-guided reformat retry, and
fallback tool chain. This is a small *resilience policy engine* trapped in a
600-line method.

The duplicate is more subtle: the AFC (`call_llm_react`) path goes through a
different code path in the LLMRouter that does *no* reformat-retry and *no*
fallback. So a tool failing inside REACT silently produces a degraded
response, while the same tool failing in a direct TOOL_CALL step gets
healed.

**Action:** extract `tool_executor/resilience.py` (`ToolResilience.run(...)`)
and use it from both code paths. The reformat-retry should also surface in
REACT.

---

## 3. Conflicting workflows

### 3.1 Two recursion mechanisms compete

* **DAG path** — `_execute_steps_dag` parallelises by step-ids; each parallel
  branch opens its own AsyncSession; child entities are spawned via
  `CHILD_ENTITY_INVOCATION` and dispatched through `_dispatch_child_async`
  (Arq job) **or** via direct recursive call to
  `_execute_run_fn(child_run_id)`.
* **Recursive path** — `RecursiveReasoningEngine.execute_tree` does
  **goal-tree** recursion driven by LLM confidence and synthesis, not by the
  static plan. Leaf goals are executed as single `THOUGHT` steps via
  `StepExecutorService`.

In practice:

* The DAG path is the default. AUTONOMOUS execution on a static plan still
  uses the DAG path.
* The RECURSIVE path is **gated by `engine_type == "RECURSIVE"`**
  (`execution_engine.py:680-714`).
* If an entity is `PROCESS` + AUTONOMOUS + RECURSIVE engine, you get a
  surprising blend: outer recursive goal decomposition, leaves that
  themselves call into AUTONOMOUS DAG execution.

This is the **biggest architectural conflict** in the codebase. §03 redesigns
this so DAG-execute and recursive-decompose are *strategies* selected by the
top-level `AgentLoop`, not toggles on the entity config.

### 3.2 Two child-dispatch mechanisms

* **Async dispatch** — `step_executor._dispatch_child_async` uses Arq +
  pubsub. Gated by `entity.governance.async_child_dispatch`.
* **Recursive in-process** — same execution engine instance calls
  `_execute_run_fn(child_run.id)` (`step_executor.py:309`).

The semantics differ:

* Recursive: parent holds the open transaction; child run shares the same
  process; failures bubble; latency is low.
* Async: parent waits on pubsub, child re-binds its own engine; **MaxWait =
  2 × timeout_ms**; failures come as JSON.

The flag is rarely set, so almost everyone is on recursive — but the async
path is the only one safe for long children (>5 min).

**Action:** make async the default; keep recursive as a documented opt-in
for sub-second child runs.

### 3.3 Two "checkpoint" concepts

* CORTEX checkpoints: written every `checkpoint_every_n_steps` via
  `_cortex_bridge.write_checkpoint`. These are *cognitive* checkpoints
  describing progress/key facts/next steps.
* HITL checkpoints: `HITLCheckpoint` config triggers `HumanApproval` rows
  for HITL gates.

They share the word "checkpoint" and the same N-step heuristic, but are
completely different concerns.

**Action:** rename CORTEX checkpoints → "cognitive snapshots" (or just
`CortexBridge.snapshot_progress(...)`). Keep "checkpoint" reserved for HITL.

### 3.4 Three "review" mechanisms

| Name | Implementation | Returns |
|------|---------------|---------|
| Step critic | `step_executor._review_step_output` | `{"passed": bool, "reason": ...}` |
| Goal alignment | `planning/goal_alignment.GoalAlignmentVerifier.verify_step_alignment` | `{"aligned": bool, "issues": [...]}` |
| Meta-review | `core/meta_review.MetaReviewer.review_execution` | `{"recommendation": CONTINUE/REPLAN/ABORT}` |

They all happen at different cadences, all call LLMs, all have their own
JSON output shape, and none of them shares context. The Meta-Agent also has
**no review at all** for its generated specs (no critic between
`meta_schema_validator` and `meta_entity_creator` beyond syntactic
validation).

§05 unifies them into one `CriticPipeline` with a shared `StepHealthRecord`
and a calibrated multi-pass design.

---

## 4. Dead / orphaned / unfinished code

### 4.1 `worker.py` re-exports

`worker.py:48-67` is a deliberate backward-compat re-export shim. It was
required during 10A but is now load-bearing for nothing. Removing it would
force any leftover `from src.ai.worker import ExecutionEngine` import to
fail loudly and be fixed in place.

### 4.2 `migrate_*.py` scripts living in runtime package

`backend/src/ai/migrate_documents_to_knowledge_trees.py` and
`backend/src/ai/migrate_episodic_to_trees.py` are one-off migrations. They
shouldn't be `src/ai/...` — they're not part of the runtime surface.

**Action:** move to `backend/scripts/migrations/`.

### 4.3 `DeepResearchSetup/` (deleted on disk, still in index)

A research-pipeline bootstrap. `SeedEntities/` (also untracked, on disk)
appears to be the successor. Both are in the repo root rather than
`backend/scripts/`.

### 4.4 `tools/social/*` and `social_*` services partly disconnected

15 social-platform tools (Facebook, Instagram, X, YouTube, Pinterest,
TikTok, Reddit, Quora, LinkedIn, LinkedIn Sales Nav, LinkedIn Ads, X Ads,
Meta Ads, Snapchat Ads, YouTube Ads, Google Ads) — each 300-500 lines.
`ai/social_*` services exist alongside. Inspection of `tools/__init__.py`
shows that not all of them are registered with `ToolRegistry` at import
time. Several are **never referenced** by any entity in seed scripts.

**Action:** audit tag each as ACTIVE / EXPERIMENTAL / DEAD, gate
EXPERIMENTAL ones behind a feature flag, and move them under
`tools/integrations/social/`. Same for the ads ones.

### 4.5 `failure_pattern_service.py`

Referenced only by `memory/assembler.py:79-104` inside try/except blocks
that swallow errors. If the file is missing the whole pipeline still works.
Either fully wire it (so failures become Intelligence rules), or remove it.

### 4.6 Stale "Phase / Fix" narration

Searches in `step_executor.py` and `execution_engine.py` show **dozens** of
inline comments like `# Phase 10D: ...`, `# Fix B: ...`, `# RACE-2 fix: ...`,
`# Ph-A: ...`. These describe history, not behaviour. They will rot.

**Action:** sweep them out as part of the schema split in week 2-3 of the
roadmap. Replace anything still load-bearing with a one-line invariant
comment.

---

## 5. Mis-organised modules (right code, wrong file)

| What | Currently in | Belongs in |
|------|--------------|------------|
| `GoalNode` dataclass | `schemas.py:938` | `core/goal_node.py` (used only by RecursiveReasoningEngine) |
| `CORTEX *` schemas | `schemas.py:783-893` | `memory/schemas.py` |
| `PlanStep`, `StaticPlan`, etc. | `schemas.py:340-411` | `planning/schemas.py` |
| `MetaCognitionConfig`, `Capabilities` | `schemas.py:491-517` | `entities/schemas.py` |
| `ToolRegistryEntry*` | `schemas.py:894-941` | `tools/schemas.py` |
| `migrate_*.py` | `src/ai/` | `backend/scripts/migrations/` |
| `tool_management_*.py` | `src/ai/` root | `tools/management/` |
| `entity_clone_helpers.py` | `src/ai/` root | `meta/entity_lifecycle.py` or `service.py` |
| `text_extractor.py` | `src/ai/` root | `common/text_extraction.py` |
| Reasoning-mode impls (CoT, Reflection, ToT) | `step_executor.py:1053-1224` | `core/reasoning/` package |

§07 has the full proposed layout.

---

## 6. Gaps (real functionality missing, not just messy)

1. **No persistent failure log per entity.** Failures are scattered across
   `LLMInteractionLog`, `ToolInteractionLog`, episodic memory; there is no
   single "this entity has failed at X in the past, avoid it" surface for
   the next plan.
2. **No introspective tools for the agent itself.** The agent can't ask
   "how am I doing? what's my context size? what's my budget left? how many
   tool calls?" — only the engine knows.
3. **No A/B telemetry.** When you change the planner prompt or a reasoning
   mode, you have no rollup metric (avg cost, success rate, latency,
   user-rated quality) to compare against the prior version.
4. **No graph of cross-entity reuse.** Meta-Agent's `RegistrySearchService`
   can find candidates, but there is no "which agents have been *combined*
   into a PROCESS and what was the outcome" graph.
5. **No streaming of intermediate state to the user.** SSE on
   `/executions/{id}/stream` only publishes status transitions, not the
   actual progress narrative the LLM is producing.
6. **No skill library / tool synthesis.** The Meta-Agent can compose
   existing tools but cannot synthesise a new tool from a natural-language
   description. Voyager / Devin do this; we don't.
7. **No reflective memory write at end of run** other than episodic flat
   text. A "what did I learn" structured note never gets created unless
   the user runs the Dreaming engine on a schedule.
8. **No multi-agent debate / consensus.** TREE_OF_THOUGHTS exists but is a
   single-LLM technique. There is no two-LLM debate, no multi-perspective
   sampling, no jury.
9. **No cost / time budget *contract* exposed to the LLM in REACT.** The
   exec_constraints block does add "Cost budget" but it is not enforced by
   the LLM's choices, only by the engine.

These gaps are the bulk of §03 and §04.

---

## 7. Summary of cleanup actions (queued for §07 and §08)

1. `git rm` the 20 ghost duplicates → one commit.
2. Move `migrate_*.py`, `DeepResearchSetup/`, `SeedEntities/` → `backend/scripts/`.
3. Split `schemas.py` into per-domain Pydantic modules.
4. Extract `tool_cost_resolver`, `tool_resilience`, `child_resolver`,
   `critic_pipeline`, `reasoning/` package.
5. Rename `CortexRouter` (the service class) → `CortexService`.
6. Consolidate "checkpoint" terminology (cognitive snapshot vs HITL).
7. Pick memory v2 canonical, demote v1.
8. Strip "Phase N" / "Fix X" narration; keep only invariant comments.
