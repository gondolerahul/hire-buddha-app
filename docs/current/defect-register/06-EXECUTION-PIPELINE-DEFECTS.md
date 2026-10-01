# 06. Entities & the Execution Pipeline — Defect Register

> **What this document is:** defects in how an entity is defined, dispatched, stepped and
> finished — the nine JSON config blocks, the step engine, the DAG scheduler, child runs
> and result handling — plus the improvements that would make a run cheaper and easier to
> debug.
> **Source document:** [`06-execution-pipeline.md`](../06-execution-pipeline.md)
> **Compiled:** 2026-09-01, against branch `fresh-main`.
> **Context:** the recurring theme here is **config that looks configurable and is not**.
> A tenant admin fills in a field in the builder, saves it, and nothing reads it.

> **2026-10-01 — consolidated.** This register is now worked through
> [`CONSOLIDATED-KERNEL-TOOLS-PLAN.md`](CONSOLIDATED-KERNEL-TOOLS-PLAN.md), which merges
> registers 05, 06, 07, 09, 10, 11, TOOL-LAYER and PO-06 into one deduplicated list,
> adds the six-level hierarchy (R1) and the skill-first tool stack (R2), and orders the
> fixes in phases. Use the canonical id from its merge map in commits; status lines here
> are still updated as fixes land.

---

## How to read this file

- **✅ Verified** — the code was read on 2026-09-01 and the claim held.
- **📄 Doc-reported** — from `06-execution-pipeline.md`, not independently re-checked.
- The entity builder shows six tabs of settings. A meaningful fraction of those settings
  have **no runtime reader**. [§3](#3-t1--config-that-does-nothing) is a complete list of
  the ones found so far, and it is the most useful section in this file.

---

## Contents

1. [Summary](#1-summary)
2. [T0 — Tenant boundary and correctness](#2-t0--tenant-boundary-and-correctness)
3. [T1 — Config that does nothing](#3-t1--config-that-does-nothing)
4. [T2 — Dead columns and dead docs](#4-t2--dead-columns-and-dead-docs)
5. [T3 — Traps in the step engine](#5-t3--traps-in-the-step-engine)
6. [Improvements](#6-improvements)
7. [Suggested order of work](#7-suggested-order-of-work)

---

## 1. Summary

| Tier | Theme | Count | When to do it |
|---|---|---|---|
| [T0](#2-t0--tenant-boundary-and-correctness) | Tenant boundary and correctness | 5 | Before the first paying tenant |
| [T1](#3-t1--config-that-does-nothing) | Config that does nothing | 8 | Each is a decision: wire it or remove it from the UI |
| [T2](#4-t2--dead-columns-and-dead-docs) | Dead columns and dead docs | 6 | **Now** — free |
| [T3](#5-t3--traps-in-the-step-engine) | Traps in the step engine | 10 | When the area is next touched |

**Total: 29 defects, 10 improvements.** (EP-26…EP-29 were found on 2026-10-01 while consolidating registers 05–11; see [`CONSOLIDATED-KERNEL-TOOLS-PLAN.md`](CONSOLIDATED-KERNEL-TOOLS-PLAN.md).)

The three to read first:

- **[EP-01](#ep-01--child-resolution-strategy-4-crosses-tenant-boundaries)** — a
  name-based lookup with no company filter can run another tenant's entity.
- **[EP-04](#ep-04--io_contractinput_schema-is-never-validated)** — the input contract the
  builder makes you define is never checked against the input.
- **[EP-05](#ep-05--eight-settings-in-the-builder-have-no-runtime-reader)** — the full
  list of controls that look real and are not.

---

## 2. T0 — Tenant boundary and correctness

### EP-01 — Child resolution Strategy 4 crosses tenant boundaries

**✅ Verified · Critical** · **Status: fixed (2026-10-01)** — Strategy 4 looks the
name up inside the parent's company only (and not at all for a parent with no
company), and `create_child_run` loads the child inside the parent entity's company,
so a UUID from a dynamic or stale plan cannot reach another tenant either
(`tests/integration/test_child_tenancy.py`, `test_child_resolver.py`).

`resolve_child_entity_id` tries four strategies in order. The fourth is a name lookup:

```python
row = (await db.execute(
    select(HierarchicalEntity).where(
        HierarchicalEntity.name == name_hint,
        HierarchicalEntity.status != "DELETED",
    )
)).scalar_one_or_none()
```

There is **no `company_id` filter**. If tenant A's plan names a child that A does not
own, but tenant B has an entity with that exact name, this resolves to B's entity — and
the parent then executes it.

`scalar_one_or_none()` raises when two companies both have the name, so the failure is
loud in the common case and silent in the dangerous one: exactly one other tenant owns
that name.

- [`ai/planning/child_resolver.py:114`](../../../backend/src/ai/planning/child_resolver.py:114) — Strategy 4
- Also recorded as **D-33** in the platform register

**Fix:** add `HierarchicalEntity.company_id == parent_entity.company_id`. One line.

---

### EP-02 — `ToolExecutor` never passes `company_id`, so tenant tools are invisible

**✅ Verified · High**

`get_tool_schemas` calls `ToolRegistry.get_all_schemas()` and
`execute_from_function_calls` calls `ToolRegistry.get_tool(name)` — both **without**
`company_id`, even though both registry methods accept one.

The `_tenant_tools` dict is therefore never consulted on any execution or advertisement
path. MCP adapters and synthesized DRAFT tools are neither offered to the model nor
resolvable if it names one.

- [`ai/tool_executor.py`](../../../backend/src/ai/tool_executor.py) — both call sites
- [`ai/tools/base.py:176`](../../../backend/src/ai/tools/base.py:176), [`:243`](../../../backend/src/ai/tools/base.py:243) — the methods that accept `company_id`
- Covered in depth as
  [TL-10](TOOL-LAYER-DEFECTS.md#tl-10--tenant-scoped-tools-are-unreachable-by-construction)

---

### EP-03 — `parent_run_id` means two different things

**📄 Doc-reported · High** · **Status: fixed (2026-10-01)** — `execution_runs.retry_of_run_id`
holds the retry/refine chain and `parent_run_id` means structure only; retry and refine
write the new column, so a retry is admitted, metered, settled and listed like any
top-level run. Migration `ep03_retry_of_run_id` moved the existing rows: refinements
(`__refinement_feedback__`) and same-entity rows without a RECURSE `subtree_root_id`
(`tests/integration/test_retry_is_not_a_child.py`).

The same column carries two unrelated relationships:

1. A **structural child run** — a `CHILD_ENTITY_INVOCATION` dispatched by a parent.
2. The **previous run in a retry or refine chain**.

Billing settlement skips any run with a `parent_run_id`
(`if run.parent_run_id: return Decimal("0")`). So a **retry** of a failed top-level run is
treated as a child and never settles — its cost accrues and is never charged.

Every report that walks the run tree also mixes the two relationships together.

- [`ai/orm/execution.py`](../../../backend/src/ai/orm/execution.py) — `parent_run_id`
- [`ai/governance/governance_service.py`](../../../backend/src/ai/governance/governance_service.py) — `settle_billing`

**Fix:** two columns. `parent_run_id` for structure, `retry_of_run_id` for chains.

---

### EP-04 — `io_contract.input_schema` is never validated

**✅ Verified · High**

The builder's Basics tab makes you define an input schema. The execution page reads it to
build the input form. Nothing ever validates `input_data` against it.

`_auto_generate_input_schema` populates the schema from the plan's prompt placeholders on
clone, which makes it look even more like a contract. It is a UI hint.

`output_schema` is weaker still — it is pasted into the prompt as an instruction and
nothing checks the result.

So an entity can be launched with completely wrong input, run its full plan, spend the
money, and fail at whatever step first tries to use the missing value.

- [`ai/service.py:1293`](../../../backend/src/ai/service.py:1293) — `_auto_generate_input_schema`
- No validator anywhere in the dispatch path

**Fix:** validate `input_data` against `input_schema` in `trigger_execution` and reject
with a 422 before the run row is created. This is the cheapest possible way to stop a
class of wasted runs.

---

### EP-26 — Behaviour forks on entity type, so a planless entity spins or claims success

**✅ Verified · High** · **Status: fixed (2026-10-01)** — found while consolidating registers
05–11 (see [`CONSOLIDATED-KERNEL-TOOLS-PLAN.md`](CONSOLIDATED-KERNEL-TOOLS-PLAN.md), R1).
One resolution for every level: `_ensure_plan` always reconciles; `reconcile` gives
static → dynamic → delegation (children and no tools) → one default step
(`planning/default_step.py`); the Strategist sends any planless run to `Recursive`, which
plans again or fails, and `decide_next` ends the run `FAILED` with the reason in
`error_message`. The `research_agent_brief` parity golden, which had recorded the
"Success"-with-no-work run, was re-recorded (1 step) (`test_uniform_execution.py`).

How an entity with no plan is handled depended on its `type`, in four places that disagree:

- `AgentLoop._ensure_plan` reconciles a plan only when a `static_plan` or
  `dynamic_planning` block is enabled.
- `PlannerService.reconcile` injects a default step only for `ACTION` and `SKILL`.
- `Strategist.next_move` plans a planless entity (`Recursive`) only when it is an `AGENT`.
- `RecursiveExecutor`, when it still finds no plan, achieves every subgoal and stamps
  `{"output": "Success", "steps": []}`.

So a `PROCESS` (or `SKILL`, or `ACTION`) whose planning blocks are off and whose children
are linked only through `parent_id` gets `SingleStep` no-ops until the 50-iteration cap,
and fails having done nothing. A goal-only `AGENT` with no children and no planning is
`COMPLETED` with output "Success" — billed and counted as a success with no work done.

- [`ai/core/agent_loop.py`](../../../backend/src/ai/core/agent_loop.py) — `_ensure_plan`
- [`ai/planning/planner_service.py`](../../../backend/src/ai/planning/planner_service.py) — `reconcile`
- [`ai/core/strategist.py`](../../../backend/src/ai/core/strategist.py) — Case B
- [`ai/core/executors/recursive.py`](../../../backend/src/ai/core/executors/recursive.py)

**Fix:** one rule for every level (R1): with no plan, reconcile one — static, else
dynamic, else delegate to children when the entity has children and no tools, else one
default step that carries `{{input}}`. A run that still has no plan fails with the reason.

---

## 3. T1 — Config that does nothing

Every item here is authored in the entity builder, saved to the database, shown back to
the user, and read by no runtime code. This is the section to act on first, because each
one is a promise the product is currently breaking.

### EP-05 — Eight settings in the builder have no runtime reader

**✅ Verified · High**

| Setting | Where it is authored | Runtime readers |
|---|---|---|
| `logic_gate.retry_policy` | Brain tab | **none** — grep finds it only in the schema |
| `planning.loop_control` | Planning tab | **none** — only `schemas/planning.py:177` |
| `governance.max_recursion_depth` | Safeguards tab | prompt text only, see [EP-06](#ep-06--max_recursion_depth-is-a-sentence-in-a-prompt) |
| `governance.execution_limits.max_tool_calls` | Safeguards tab | prompt text only |
| `capabilities.tools[].rate_limit_per_run` | not authorable at all | branch exists, never fires |
| `ToolDefinition.max_execution_seconds` | not authorable at all | **none** |
| `io_contract.input_schema` | Basics tab | UI form only, see [EP-04](#ep-04--io_contractinput_schema-is-never-validated) |
| `io_contract.output_schema` | Basics tab | prompt text only |

The real retry bound is the hard-coded `MAX_RETRIES_PER_STEP = 2` plus the tool healing
ladder. The real ceiling on a runaway agent is `MAX_REACT_TURNS = 12`, the step
`timeout_ms`, and `governance.max_cost_usd`.

- [`ai/schemas/planning.py:177`](../../../backend/src/ai/schemas/planning.py:177)
- [`ai/planning/retry_strategies.py`](../../../backend/src/ai/planning/retry_strategies.py) — `MAX_RETRIES_PER_STEP`
- [`ai/constants.py:63`](../../../backend/src/ai/constants.py:63) — `MAX_REACT_TURNS`

**Fix:** for each one, either wire it or remove the field from the builder. A greyed-out
"not yet implemented" control is honest; a working-looking one is not.

---

### EP-06 — `max_recursion_depth` is a sentence in a prompt

**✅ Verified · High** · **Status: fixed (2026-10-01)** — runs carry `depth` and
`max_depth`; `create_child_run` and the RECURSE factory refuse a child past the
tightest limit on the way down (`governance/composition.child_depth`, migration
`ep06_run_depth`; `test_run_depth.py`, `tests/integration/test_run_depth_db.py`).

The only use of the setting is:

```python
max_depth = governance.get("max_recursion_depth")
if max_depth:
    exec_constraints["Max recursion depth"] = str(max_depth)
```

It is rendered into the execution-constraints block of the prompt and the LLM is trusted
to respect it. Nothing counts actual depth and nothing refuses to go deeper.

In practice the only thing bounding a recursive fan-out is the credit balance and the
cost cap — both of which stop the run *after* the money is spent.

- [`ai/step_executor.py:681`](../../../backend/src/ai/step_executor.py:681)

---

### EP-07 — `rate_limit_per_run` cannot fire, in three separate ways

**✅ Verified · Medium**

The enforcement branch exists in `tool_executor.py` and reads
`call.get("rate_limit_per_run")`. It fails for three independent reasons:

1. The key must arrive **inside the function-call dict**. The only producer of those
   dicts is the LLM adapter, which emits `{"name", "args"}`. No call site injects it.
2. The field lives on `ToolDefinition`, but `Capabilities.tools` is typed
   `List[ToolReference]`, which has `tool_id` and nothing else. It cannot be authored.
3. The counter is wiped at the start of **every step**
   (`context['tool_call_counts'] = {}`), so even if 1 and 2 were fixed the limit would be
   per-step, not per-run.

- [`ai/tool_executor.py`](../../../backend/src/ai/tool_executor.py) — the read
- [`ai/step_executor.py:859`](../../../backend/src/ai/step_executor.py:859) — the per-step reset
- Covered in depth as
  [TL-11](TOOL-LAYER-DEFECTS.md#tl-11--the-only-enforced-rate-limit-is-never-populated)

---

### EP-08 — There is no per-tool timeout

**📄 Doc-reported · Medium**

`ToolDefinition.max_execution_seconds` defaults to 30 and is unreachable config. What
actually bounds a tool call is the enclosing step's
`asyncio.wait_for(..., timeout_ms/1000)` and whatever internal timeout the tool happens to
implement.

A tool with no internal timeout, inside a step with a generous `timeout_ms`, can hold a
worker for a long time.

---

### EP-09 — `entity.status` is not a state machine

**📄 Doc-reported · Medium** · **Status: fixed (2026-10-01)** — `update_entity` checks
status changes against `ENTITY_STATUS_TRANSITIONS` (DELETED only through DELETE); an
ARCHIVED entity does not run (400, and refused as a child); a DRAFT runs on its own or
inside a draft tree, never under a published parent; a DEPRECATED one runs with an
`agent.entity.deprecated_run` event (`tests/integration/test_entity_status.py`).

There is no transition validation on entity status, and a `DRAFT` or `ARCHIVED` entity
executes perfectly happily. Only `DELETED` is enforced, in the arq ghost-run guard.

So "flip status to ACTIVE when ready" — the documented workflow — is advisory. A half-built
`DRAFT` agent referenced by a `PROCESS` will run.

- [`ai/orm/entity.py`](../../../backend/src/ai/orm/entity.py)

---

### EP-10 — `version` is decorative

**📄 Doc-reported · Medium**

`hierarchical_entities.version` is a semantic version string that nothing resolves,
compares, pins or increments.

The practical consequence: **editing an entity changes behaviour for runs already in
flight**. A run that started against version 1.0.0 will pick up whatever the row says on
its next step. There is no way to pin a run to the definition it started with.

---

### EP-11 — Several settings the runtime reads cannot be authored through the API

**✅ Verified · Medium** · **Status: fixed (2026-09-29, `3fadd76`)** — with PO-09:
`critic_cost_share_pct`, `max_concurrent_children` and `critic_model_override` are declared
(with `goal_validation_interval` and `meta_review_interval`). `capabilities.tools[].usage`
turned out to have **no reader** in the backend — the builder sends it and nothing uses it —
so it is accepted and not stored rather than declared.

The entity create/update schema is a **closed** Pydantic model — unknown keys are dropped
without an error. Four keys the runtime *does* read are not declared fields, so they can
never be set through the API:

| Key | Read by |
|---|---|
| `governance.critic_cost_share_pct` | the critic pipeline's degrade rule |
| `governance.max_concurrent_children` | `within_child_dispatch_cap` |
| `logic_gate.review_mechanism.critic_model_override` | the kernel |
| `capabilities.tools[].usage` | `step_executor` |

They can only be set by editing the database directly. The seed authors documented this
as a trap.

**Fix:** declare them. Same change as
[PO-09](01-PRODUCT-OVERVIEW-DEFECTS.md#po-09--a-mistyped-config-key-in-the-entity-builder-disappears-silently)
— making the model reject unknown keys turns this whole class of problem into a 422.

---

### EP-12 — `input_dependencies` silently overrides `context_policy`

**📄 Doc-reported · Medium**

If a step declares `input_dependencies`, only `input` plus those dependencies reach it —
whatever the entity's `context_policy` says.

Two controls, one wins silently. A user who sets `context_policy: FULL` and also lists
dependencies on one step will find that step running with almost no context and no
explanation.

---

## 4. T2 — Dead columns and dead docs

| ID | Delete or fix | Notes | Status |
|---|---|---|---|
| **EP-13** | `ExecutionRun.idempotency_key` and `span_id` | Dead columns. Both have partial indexes maintained for them | ✅ Verified · **fixed (2026-10-01)** — dropped with the index (migration `ep13_run_row_hygiene`) |
| **EP-14** | `ToolInteractionLog.idempotency_key` | Same — dead column, indexed | 📄 Doc-reported |
| **EP-15** | `ExecutionRun.execution_time_ms` | Never written by the loop path. Derive from `completed_at - started_at`. Any dashboard reading it shows nulls | ✅ Verified · **fixed (2026-10-01)** — written at finalisation; finished runs backfilled by `ep13_run_row_hygiene` |
| **EP-16** | `__completed_steps__` in `INTERNAL_KEYS.md` | Documented and never written. The live mechanism is `AgentState.completed_step_ids`. The doc is stale and misleads anyone debugging step completion | ✅ Verified · **fixed (2026-10-01)** — `INTERNAL_KEYS.md` rewritten from the code; it now marks every key with no writer (eleven of them) |
| **EP-17** | The stale `core/README.md` | Documents `execution_engine.py` and `recursive_engine.py`, neither of which exists. Same entry as [AK-14](05-AGENT-KERNEL-DEFECTS.md#4-t2--delete-or-fix-the-name) | ✅ Verified · **fixed (2026-10-01)** with AK-14 |
| **EP-28** | `governance.execution_limits.max_recursion_depth` | A second copy of `governance.max_recursion_depth` with no reader at all (the first is read only into prompt text — [EP-06](#ep-06--max_recursion_depth-is-a-sentence-in-a-prompt)). Two settings for one limit, the same split as [PC-17](07-PLANNING-AND-CRITICS-DEFECTS.md#pc-17--two-different-goal_validation_interval-settings) | **✅ Verified · Medium** · **Status: fixed (2026-10-01)** — one setting: the schema folds the old spelling into `max_recursion_depth` (it wins: it is the builder's), the migration folds stored copies, and the builder edits the one setting |

---

## 5. T3 — Traps in the step engine

### EP-18 — Every step output is stored twice

**✅ Verified · Medium**

`store_step_output` writes the value under the step **name** and again under the step
**id**:

```python
context_state[step_name] = value
if step_id and step_id != step_name:
    context_state[step_id] = value
```

Two consequences:

1. **Context size doubles.** Full outputs are deliberately preserved for data integrity,
   so for a research step producing 40 KB of findings, the context carries 80 KB.
2. **Duplicate step names silently overwrite each other.** Nothing validates that step
   names are unique within a plan.

The context is then trimmed by `_maybe_summarize_context` when it grows too large — so the
duplication directly causes earlier and more aggressive trimming of real data.

- [`ai/core/context_utils.py:22`](../../../backend/src/ai/core/context_utils.py:22)

**Fix:** store once under the id, and resolve `{{name}}` references through a lookup.

---

### EP-19 — `convert_to_template` misses plan-only children

**📄 Doc-reported · Medium** · **Status: fixed (2026-10-01)** — both conversion and
cloning walk the tree with one helper over all three paths. Fixing it showed a worse
fault behind it: `remap_entity_refs` edited the stored JSON in place, so SQLAlchemy
saw no change and templates and clones kept pointing at the source's children in the
database (the in-memory objects looked right). It now works on deep copies
(`tests/integration/test_template_tree.py` reads the stored rows).

`clone_template` walks three discovery paths: the `parent_id` FK, `hierarchy.children`,
and `static_plan.steps[].target.entity_id`.

`convert_to_template` walks only the first two. An entity whose children are referenced
**only** from its static plan — which is how several seeds wire them — becomes a template
with missing children, and every clone of that template is broken.

- [`ai/service.py`](../../../backend/src/ai/service.py) — `convert_to_template` vs `clone_template`

---

### EP-20 — Parallel DAG steps run in isolated sessions

**📄 Doc-reported · Medium**

Each parallel branch gets its own session. That is correct and necessary — but it means
**never mutate a shared ORM object from a step**. Cost must be folded with the atomic
`_bump_run_cost` increment; a read-modify-write silently drops charges when two branches
finish together.

Nothing enforces this. It is a rule you have to know.

Related: two of the three executors still use the loop's shared session — see
[AK-18](05-AGENT-KERNEL-DEFECTS.md#ak-18--two-of-three-executors-share-the-loops-database-session).

---

### EP-21 — The Execution Detail page finds artifacts by regex

**📄 Doc-reported · Medium**

The UI locates a run's produced files by scanning the step output text for something that
looks like an artifact URL — not by querying `artifacts WHERE run_id = ...`.

So a tool that produces a real file but does not print its URL into its output produces an
**invisible artifact**: the row exists, the file exists, the user cannot see it.

`pdf_generator` makes this worse by leaving `run_id = NULL` on the artifact row and
writing the file twice.

- [`frontend/src/pages/ai/ExecutionDetail.tsx`](../../../frontend/src/pages/ai/ExecutionDetail.tsx)
- [`ai/tools/documents/pdf_generator.py`](../../../backend/src/ai/tools/documents/pdf_generator.py)

**Fix:** query by `run_id`. It is the column the table already has.

---

### EP-22 — With the resilience flag off, REACT tool calls get no healing at all

**📄 Doc-reported · Medium**

The failure-classification and self-healing ladder exists **twice**: inline in
`_execute_tool_call` for direct `TOOL_CALL` steps, and in `ToolResilience` for the
REACT/AFC path.

The REACT path is gated on `tools.resilience_v2_enabled`. With that flag off, REACT tool
calls go straight to `ToolExecutor.execute_from_function_calls` with no reformat-retry and
no fallback — a silently different reliability level depending on which reasoning mode the
entity uses.

- [`ai/step_executor.py:870`](../../../backend/src/ai/step_executor.py:870) — the flag check
- [`ai/tools/resilience.py`](../../../backend/src/ai/tools/resilience.py)

**Fix:** finish the migration and delete the inline copy. Two implementations of one
ladder will drift.

---

### EP-23 — The fallback chain is one hop only

**📄 Doc-reported · Low**

`get_fallback_tool` returns the **first** alternative and there is no chain walk. So
`web_search → headless_browser` is the whole recovery; if the browser also fails, the step
returns `[TOOL_EMPTY]`.

Given the pairs are mutually reciprocal (`scraper_tool → headless_browser` and
`headless_browser → scraper_tool`), a chain walk would need loop protection anyway. Listed
so the limit is known rather than assumed.

- [`ai/tool_fallback.py:26`](../../../backend/src/ai/tool_fallback.py:26)

---

### EP-24 — The reformat retry is billed and easy to miss

**📄 Doc-reported · Low**

Every reformat attempt writes an `LLMInteractionLog` with `reasoning_mode="REFORMAT"` and
logs usage. That is correct — the call really costs money.

The trap is that it does not appear in the plan, in the step list or in the trace as a
distinct step. A run that quietly reformatted twenty tool calls looks the same as one that
did not, except for the bill.

- [`ai/step_executor.py:597`](../../../backend/src/ai/step_executor.py:597)–610

---

### EP-25 — A step whose template omits `{{input}}` never sees the task

**✅ Verified · High** · **Status: fixed (2026-10-01)** — found 2026-09-29 on a live
deep-research run. `step_executor.compose_step_prompt` appends the run input as `## Task`
when the rendered template does not contain it, and `__agent_state__` is in
`INTERNAL_CONTEXT_KEYS`. Test: `tests/unit/test_step_prompt.py`.

`step_executor` builds the user prompt from `step.target.prompt_template` (default
`{{input}}`), then appends an "Available Context from Previous Steps" block built from
every context key **not** in `INTERNAL_CONTEXT_KEYS`. `input` is in that set. So when a
template does not reference `{{input}}`, the run's actual request reaches the model
nowhere.

Live: the research-gatherer (a `SKILL` whose static step's `prompt_template` is its
description) was invoked with `input` set to the user's question. Its LLM user prompt
was its description plus an `__agent_state__` dump. The question was missing, and it
answered "Please provide me with the research topic". The research-analyst did the
same. Seeds that write a description into `prompt_template` are common.

A second leak shows in the same block: `__agent_state__` is not in
`INTERNAL_CONTEXT_KEYS`, so loop bookkeeping (iteration, budget pressure, subgoals) is
rendered to the model as if it were a previous step's output.

- [`ai/step_executor.py:808`](../../../backend/src/ai/step_executor.py:808) — template → prompt
- [`ai/step_executor.py:831`](../../../backend/src/ai/step_executor.py:831) — context block excludes `input`
- [`ai/constants.py:31`](../../../backend/src/ai/constants.py:31) — `INTERNAL_CONTEXT_KEYS`

**Fix:** when the rendered template does not contain the run input, append it as a
`## Task` section. Add `__agent_state__` to `INTERNAL_CONTEXT_KEYS`.

---

### EP-27 — Reading an entity writes a "virtual" plan into its row

**✅ Verified · Medium** · **Status: fixed (2026-10-01)** — found while consolidating
registers 05–11. `get_entity` no longer touches the row; the read and update routes
(entities and templates) show the default step through `display_planning`, a copy, for
an entity of any level with no static steps — the same step the planner runs
(`tests/integration/test_entity_read_is_pure.py`).

`AIService.get_entity` gives an `ACTION` or `SKILL` with no static steps a virtual
one-step plan "for the UI" by assigning `entity.planning = virtual_planning` on the
**persistent** ORM instance. `update_entity` loads the entity through `get_entity`,
applies the update and commits — so an update that does not itself send `planning` (a
status change, a rename) writes the virtual plan into the database. The entity then has
a real static plan nobody authored.

- [`ai/service.py`](../../../backend/src/ai/service.py) — `get_entity`, `update_entity`

**Fix:** compute the display plan in the response, for any level, and never assign it to
the row.

---

### EP-29 — The CORTEX tree id is never put into the context, so children and retries never share the tree

**✅ Verified · High** · **Status: fixed (2026-10-01)** — found 2026-10-01 while rewriting
`INTERNAL_KEYS.md` (EP-16). `_compose` writes `__cortex_tree_id__` into the context when
it opens the tree, and `_persist_final` keeps it on `run.context_state`; a retry copies
the failed run's plan and passes its finished steps as `__reuse_outputs__`, which the
loop now pre-completes at bootstrap (`step_results.reuse_step_outputs`). Refine's
`__reuse_outputs__` had no reader either and is honoured the same way. Tests:
`tests/unit/test_run_resume_state.py`, `tests/integration/test_retry_resumes.py`.

`create_child_run` propagates the parent's tree to a child only
`if "__cortex_tree_id__" in context`; `retry_execution` and `refine_execution` carry
it forward the same way; `agent_reflect` and `CortexBridge` read it. **Nothing writes
that key.** The loop opens the run's tree into the typed `AgentState.cortex_tree_id`
and never mirrors it into the context dict the executors take. So every child run
opens a tree of its own (the manifest and `06-execution-pipeline.md` §8 say parent
and children share one), and a retry or refine starts a fresh tree instead of
resuming the failed run's.

Related, in the same retry path: `retry_execution` copies `failed_run.context_state`
"so completed step keys are skipped", but the loop never writes `context_state` at
finalisation (only `_persist_suspended` does, for its snapshot), and `_bootstrap_state`
seeds only `run.input_data` — so a retry re-runs every step.

- [`ai/step_executor.py`](../../../backend/src/ai/step_executor.py) — `create_child_run`
- [`ai/service.py`](../../../backend/src/ai/service.py) — `retry_execution`, `refine_execution`
- [`ai/core/agent_loop.py`](../../../backend/src/ai/core/agent_loop.py) — `_compose` (sets the typed field only), `_persist_final`

**Fix:** the loop writes `__cortex_tree_id__` into the context when it opens the run's
tree; a retry carries the tree id and pre-completes the steps the failed run finished,
from its `result_data["steps"]`.

---

## 6. Improvements

### EP-I1 — Validate input at dispatch

**Effect: large, cheap.** [EP-04](#ep-04--io_contractinput_schema-is-never-validated). One
`jsonschema.validate` in `trigger_execution` turns "the run failed at step 3 because a
variable was missing" into a 422 with a clear message and zero cost. The schema is already
there and already auto-generated.

### EP-I2 — Decide the fate of every dead setting in one pass

**Effect: large for trust.** [EP-05](#ep-05--eight-settings-in-the-builder-have-no-runtime-reader)
lists eight. Take them as one piece of work: for each, wire it or remove it from the
builder. Leaving them is the worst option, because a user who sets `max_recursion_depth: 2`
and watches a run go five deep loses confidence in every other control on the page.

### EP-I3 — Store step outputs once

**Effect: medium, immediate.** [EP-18](#ep-18--every-step-output-is-stored-twice). Halving
the context dict halves what is serialised into `run.context_state` on every snapshot,
halves what is copied by the loop's context bridge twice per iteration, and delays
context summarisation — which means less real data is trimmed away.

### EP-I4 — Pin a run to the entity version it started with

**Effect: medium.** [EP-10](#ep-10--version-is-decorative). Snapshot the entity's config
onto the run row at dispatch, and have the loop read from the snapshot. This makes runs
reproducible, makes `version` mean something, and removes a whole class of
"it worked yesterday" reports.

### EP-I5 — Query artifacts by `run_id`

**Effect: medium.** [EP-21](#ep-21--the-execution-detail-page-finds-artifacts-by-regex).
The `artifacts` table has `run_id`, `agent_id` and `generated_by`. Using them removes the
regex, makes every produced file visible, and fixes the `pdf_generator` case as a side
effect.

### EP-I6 — Enforce unique step names within a plan

**Effect: small, prevents silent data loss.** Two steps with the same name overwrite each
other's output in the context dict, and nothing warns. The graph editor already runs a
validation pass on every change — add the check there and in the API.

### EP-I7 — Make the retry chain visible

**Effect: medium.** [EP-03](#ep-03--parent_run_id-means-two-different-things). Splitting the
column also fixes billing for retries and lets the UI show "this is attempt 3 of a run
that first failed at 14:02", which is what a user actually wants to see.

### EP-I8 — One healing ladder

**Effect: medium.** [EP-22](#ep-22--with-the-resilience-flag-off-react-tool-calls-get-no-healing-at-all).
`ToolResilience` is the extracted, testable version with a proper `FailureKind` enum.
Finish the migration, delete the inline copy in `step_executor`, and remove the flag.
Definition of done for a migration is that the old path is gone.

### EP-I9 — Cost the plan before running it

**Effect: large for users.** `planning/cost_estimator.py` already has per-tool baseline
costs refreshed nightly from telemetry. Running it at dispatch and comparing against
`governance.max_cost_usd` and the wallet balance would let the platform refuse a run it
cannot finish, instead of stopping halfway with "Partial results saved."

Pairs with [PO-I7](01-PRODUCT-OVERVIEW-DEFECTS.md#po-i7--give-the-wallet-a-low-balance-warning-before-the-run-dies).

### EP-I10 — Show reformat retries in the trace

**Effect: small.** [EP-24](#ep-24--the-reformat-retry-is-billed-and-easy-to-miss). The
span machinery already exists. One extra span kind makes an invisible cost visible, and
makes "which tools keep needing reformatting" answerable — which is the signal that a tool
schema is wrong.

---

## 7. Suggested order of work

| Step | Work | Why here |
|---|---|---|
| **1** | EP-01 | One line, closes a cross-tenant execution path |
| **2** | EP-I1 / EP-04 | Input validation at dispatch. Cheapest way to stop wasted runs |
| **3** | EP-I3 / EP-18 | Store outputs once. Immediate reduction in context size everywhere |
| **4** | EP-I2 / EP-05 | The dead-config sweep. Do it as one piece of work, not eight |
| **5** | EP-I7 / EP-03 | Split `parent_run_id`. Fixes retry billing at the same time |
| **6** | EP-I5 / EP-21, EP-I6 | Artifacts by `run_id`, unique step names |
| **7** | EP-I8 / EP-22 | One healing ladder, flag deleted |
| **8** | EP-I4 / EP-10 | Version pinning. The largest piece, and what makes runs reproducible |

---

## Where to go next

- [06 — Execution pipeline](../06-execution-pipeline.md) — the source document.
- [`DEFECT-REGISTER.md`](../DEFECT-REGISTER.md) — EP-01 is D-33.
- [05 — Agent kernel](05-AGENT-KERNEL-DEFECTS.md) — the loop that drives these steps.
- [`TOOL-LAYER-DEFECTS.md`](TOOL-LAYER-DEFECTS.md) — for EP-02, EP-07, EP-08 in depth.
- [07 — Planning & critics](07-PLANNING-AND-CRITICS-DEFECTS.md) — for the retry strategy
  behind EP-05.
- [03 — Data model](03-DATA-MODEL-DEFECTS.md) — for the dead columns in T2.
