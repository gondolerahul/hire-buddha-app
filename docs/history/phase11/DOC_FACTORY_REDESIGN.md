# Document Factory — Execution Analysis & `doc-factory-lite` Redesign

**Status:** Proposal · **Date:** 2026-06-02 · **Author:** engineering analysis
**Scope:** Root-cause of an expensive `doc-factory-process` run, a concrete
lean replacement entity (`doc-factory-lite`), and fixes for three platform
issues surfaced by the investigation.

> The existing `doc-factory-process` entity hierarchy is **left untouched**.
> `doc-factory-lite` is an additive A/B alternative.

---

## 1. Executive summary

A single user request — *"create an insurance company balance sheet template"* —
produced **15 artifact files**, cost **$15.57** (billed **$37.37**), made **34
LLM calls** consuming **~1.8M tokens**, and left the live "Agent State" panel
frozen on iteration 1. Investigation of run `965aa0a4` shows the cost and file
sprawl are **not normal** — they are symptoms of an architecture designed for
the pre-Phase-11 kernel running on top of the Phase-11 kernel, so the two layers
multiply work instead of cooperating.

The fix is structural, not parametric: **replace the ~50-entity, 4-level
hierarchy with a single flat agent** and let the Phase-11 loop (planner + critic
+ bandit) do the iterating it was built for, with a deterministic finish and a
single registered output.

---

## 2. Run anatomy (evidence)

Run `965aa0a4-49ce-4ca1-80ae-1c4a0dad7b4d`, entity `doc-factory-process`:

| Fact | Value |
|---|---|
| Top-level PROCESS plan | **1 step**: `CHILD_ENTITY_INVOCATION → doc-xlsx-agent` |
| Children invoked | **1** (`doc-xlsx-agent`); QA & Delivery agent **not** invoked |
| Child plan | **8 steps**: 4× `THOUGHT` + 4× `ACTION` |
| LLM calls (whole tree) | **34** = 18 ReAct + 16 Critic |
| Tokens | **1,798,896** (several ReAct prompts at **150k–175k** tokens) |
| Raw cost / billed | **$15.57 / $37.37** |
| Child's own budget cap | `max_cost_usd = 3.00` → **overspent 5×** |
| Artifacts written | **15** (~12 template versions + 3 throwaway `test.xlsx`) |
| PROCESS iterations | **1** (blocked ~11 min inside the single child call) |
| Agent-state snapshots in this run's window | **1** |

Per-call token growth (child `doc-xlsx-agent`): calls #9/#20/#23/#29 carried
155k / 170k / 152k / 175k prompt tokens — the validation/finalize steps read the
whole workbook back into the prompt. Steps "Design architecture", "Validate" and
"Finalize" each appear 2–3× (re-planning re-runs).

---

## 3. Root-cause of each observation

### 3.1 — 15 files, and no "final" one (observations #1, #4)
`SandboxCodeTool._register_new_artifacts()`
(`backend/src/ai/tools/sandbox_executor.py:217`) scans the sandbox after **every**
code execution and auto-registers **any new document file** as an artifact. The
8-step plan re-runs `sandbox_code` repeatedly (Build → Validate → Remediate →
Finalize, plus re-planning re-runs); each `wb.save()` mints a new artifact.
Three are `test.xlsx` — the agent probing whether `openpyxl` imports. There is
**no overwrite, no dedup, no "final" marker**. Because the **QA & Delivery agent
never ran** (§3.5), nothing consolidated a winner.

### 3.2 — $15 raw / $37 billed (observation #2)
Four compounding cost drivers, in order of impact:
1. **8-step plan for a 1-file task.** The 4 `THOUGHT` steps each make a paid LLM
   call but produce **no document** — reasoning the planner already did.
2. **Context bloat.** "Validate" and "Finalize" read the entire workbook into the
   prompt; ReAct turns accumulate all prior tool output → 150k–175k-token
   prompts. `context_policy.summarize_threshold` (30k) never compacted the child.
3. **A CRITIC pass per step** — 16 of 34 calls are critic calls.
4. **Re-planning re-runs** of Design/Validate/Finalize (2–3× each).

### 3.3 — Over-complex design (observation #3)
The hierarchy is `PROCESS → AGENT → SKILL → ACTION`, ~50 entities, authored for
the *static-plan* mental model. Phase 11 supplies dynamic planning + critic +
bandit **inside one agent loop**, so the deep skill/action tree is now redundant
scaffolding that multiplies LLM calls. See §4 for the replacement.

### 3.4 — Agent state never updated (observation #6)
Two causes:
- The **PROCESS ran exactly one iteration**: a single `CHILD_ENTITY_INVOCATION`
  that executed **synchronously and blocked ~11 minutes** while the child did
  everything. One iteration ⇒ one snapshot ⇒ the panel never changes.
- The **child** (`doc-xlsx-agent`), where all the work happened, ran on the
  **legacy `ExecutionEngine.execute_run` path** and wrote **0 snapshots**. The
  parent's `/agent_state` endpoint only reads the *PROCESS* entity's tree, so the
  child's work is invisible to it. (That tree holds 107 snapshots, but spread
  across **17** historical runs — CORTEX trees are per-entity, not per-run; only
  1 belongs to this run.)

### 3.5 — Only one child (observation #7)
Routing to **only** the xlsx agent is **correct** — the request needs only Excel.
**But** the PROCESS goal and system prompt mandate *"ALWAYS invoke QA Agent as
the final step"* (and declare a `SEQUENTIAL` link to it), yet the planner emitted
a **single-step plan and dropped QA**. So "one child" = right document agent +
**missing mandatory QA/consolidation step**, which is also why no final output is
designated (§3.1).

---

## 4. Proposal — `doc-factory-lite` (concrete seed)

**Principle:** one agent, one loop, deterministic finish. Let the Phase-11 loop
iterate; don't hand-build a skill tree that re-implements planning.

### 4.1 Shape
```
AGENT: doc-factory-lite
  reasoning: REACT, agent_loop.enabled
  tools: [sandbox_code, document_save]
  static 3-step plan: generate → validate(in-sandbox) → finalize(document_save)
  NO child agents, NO skills, NO action sub-entities
```
One level replaces fifty. Keyword routing ("xlsx"/"docx"/…) lives in the system
prompt; no TREE_OF_THOUGHTS PROCESS is needed to decide "this is a spreadsheet".

### 4.2 The five changes that kill cost & sprawl
1. **Collapse the hierarchy** to a single agent → removes a planning LLM call and
   a critic pass per removed level.
2. **Static 3-step plan, zero THOUGHT steps** (`generate → validate → finalize`).
   Dynamic planning OFF so the planner can't re-decompose into 8 steps.
3. **Deterministic finalize is the only artifact.** Generate to a scratch dir the
   artifact scanner ignores; only the explicit final `document_save` call
   registers **one** artifact with a real name + `purpose: "final"`.
4. **Cap context.** Validation runs **in the sandbox** (openpyxl loads the file,
   asserts no `#REF!`/`#DIV/0!`, returns a ~200-token verdict) — the LLM never
   sees the whole workbook. Lower `summarize_threshold`.
5. **Enforce budget + convergence.** `max_cost_usd ≈ 2.00` that *actually stops*
   the run (§5.1); "if validation passed → STOP" so a valid file isn't re-planned.

### 4.3 Phase-11 knobs (config-only)
- `goal_validation_interval` / `meta_review_interval` = 2–3 → critic runs
  occasionally, not per step (16 → ~3–4 critic calls).
- `review_mechanism.critic_model_override` → a cheaper/faster critic model.
- `review_mechanism.on_failure` bounded (the unbounded `RETRY` caused re-runs).

### 4.4 Expected effect
~34 → **~6–8 LLM calls**, ~1.8M → **~150–250k tokens**, **~$1–2 raw** (≈$3
billed) instead of $15/$37, and **one** clearly-final artifact.

### 4.5 Concrete seed payload
A single self-contained creation script
(`backend/scripts/seeds/default_entities/SeedDocFactoryLite/create_lite.py`),
reusing `phase11.enrich_payload` from the existing seed for flag/reasoning
parity. The entity body:

```python
DOC_FACTORY_LITE = {
    "name": "doc-factory-lite",
    "type": "AGENT",
    "display_name": "📄 Document Factory (Lite)",
    "goal": (
        "Produce ONE final, publication-quality document (xlsx/docx/pptx/pdf) "
        "from a single request, validated and saved exactly once. Then stop."
    ),
    "prompts": {
        "system_prompt": (
            "You are a single-pass document generator. Decide the format from the "
            "request (xlsx/docx/pptx/pdf). Write code to a SCRATCH path under "
            "/work/scratch/ (these are NOT user outputs). Validate IN-SANDBOX: load "
            "the file, assert zero formula/structural errors, and return a SHORT "
            "verdict only — never print file contents back. When (and only when) "
            "validation passes, call document_save ONCE on the final file with a "
            "descriptive filename and purpose='final'. Do not regenerate a file that "
            "already validates. Do not write probe/test files into outputs."
        ),
    },
    # 3 deterministic steps — no THOUGHT steps, no planner re-decomposition.
    "planning": {
        "static_plan": {
            "enabled": True,
            "fallback_behavior": "STRICT",
            "steps": [
                {"step_id": "generate", "order": 1, "name": "Generate document",
                 "type": "ACTION",
                 "target": {"tool_id": "sandbox_code",
                            "prompt_template": "Generate the requested document to "
                                               "/work/scratch/. Request:\n\n{{input}}"},
                 "required": True},
                {"step_id": "validate", "order": 2, "name": "Validate in-sandbox",
                 "type": "ACTION",
                 "target": {"tool_id": "sandbox_code",
                            "prompt_template": "Load /work/scratch output, assert no "
                                               "errors, return a SHORT pass/fail "
                                               "verdict only.",
                            "input_dependencies": ["generate"]},
                 "required": True},
                {"step_id": "finalize", "order": 3, "name": "Save final artifact",
                 "type": "ACTION",
                 "target": {"tool_id": "document_save",
                            "prompt_template": "Save the validated scratch file as the "
                                               "single final artifact (purpose=final).",
                            "input_dependencies": ["validate"]},
                 "required": True},
            ],
        },
        "dynamic_planning": {"enabled": False},
    },
    "capabilities": {
        "tools": [{"tool_id": "sandbox_code"}, {"tool_id": "document_save"}],
        "memory": {"enabled": True, "mode": "CORTEX",
                   "memory_scope": "INTELLIGENCE_ONLY",
                   "cortex_config": {"auto_checkpoint": True, "context_budget_pct": 25}},
    },
    "context_policy": {"type": "SUMMARIZE", "summarize_threshold": 8000,
                       "preserve_keys": ["request_type", "final_artifact"]},
    "logic_gate": {
        "reasoning_config": {"reasoning_mode": "REACT", "goal_validation_interval": 2},
        "review_mechanism": {
            "enabled": True,
            "review_prompt": "Does the saved file satisfy the request with zero errors?",
            "on_failure": "RETRY",
            "max_retries": 1,                       # bounded — no unbounded re-runs
            "meta_review_interval": 3,
        },
    },
    # max_cost_usd MUST be enforced on the run — see §5.1.
    "governance": {"timeout_ms": 300000, "max_cost_usd": 2.00,
                   "max_recursion_depth": 1,
                   "execution_limits": {"max_tool_calls": 10}},
    # Phase-11 flag/reasoning parity via the existing enrichment helper.
    "metadata_extensions": {"feature_flags": {"agent_loop.enabled": True},
                            "task_class": "document_authoring"},
    "observability": {"log_thoughts": True},
}
```

> One additional config knob is needed for change #3: a per-entity / per-call way
> to tell `SandboxCodeTool._register_new_artifacts` to ignore the scratch dir and
> only register the explicit `document_save` output. Proposed: skip
> auto-registration for paths under `/work/scratch/` (treat that prefix as
> non-artifact), so the existing tree stays unchanged while lite gets a single
> final artifact.

---

## 5. Platform issues surfaced by this investigation

Two are real bugs; the third turned out to be intended behaviour and is
reclassified honestly below.

### 5.1 BUG — per-entity `max_cost_usd` is not enforced on children
**Symptom:** the xlsx agent's `max_cost_usd = 3.00` was ignored; it ran to
$15.57 (5×).
**Root cause:** child-entity invocations execute on the **legacy
`ExecutionEngine.execute_run`** path, which only guards **company-level credits**
(`CreditExhaustedError`, `execution_engine.py:1054`) and **HITL `COST_THRESHOLD`**
checkpoints — it never treats `governance.max_cost_usd` as an automatic abort
between steps. The AgentLoop *does* enforce it (`Budget.exhausted()` in
`core/agent_loop.py:_loop`), but only top-level runs use the loop.
**Fix (recommended — architectural):** route child-entity invocations through the
AgentLoop as well, so `Budget.exhausted()` applies (this also fixes §3.4
snapshots/visibility). Dispatch already resolves `agent_loop.enabled` per entity
in `run_execution_recursive` (`arq_jobs.py:24`); the gap is the synchronous
in-process child path (`step_executor.py:_dispatch_child_async` fallback to
`_execute_run_fn`).
**Fix (quick guard):** in the legacy step/DAG loop
(`execution_engine.py:_execute_steps_dag`, after `_execute_step_wrapper` /
`_fold_cost`), compare `run.total_cost_usd` against the entity's
`governance.max_cost_usd` and abort the run (terminal `PARTIAL_COMPLETE` + a
`budget_exhausted` event) once exceeded.

### 5.2 BUG — parent run `total_tokens` is 0 despite millions of tokens
**Symptom:** `execution_runs.total_tokens = 0` on the PROCESS row; the child row
correctly shows 1,798,376. The screenshot's "tok 0 / 2,000,000" reflects this.
**Root cause:** the nested engine bills tokens onto the **child** run row
(`step_executor._fold_cost`, `step_executor.py:145-146` updates the child's
`total_tokens`). The parent AgentLoop reconciles **USD** from the run row
(`_sync_budget_cost`, `agent_loop.py:632`) but **never tokens**, and
`_persist_final` sets `total_tokens = state.budget.tokens_used` which stays 0
(`agent_loop.py:894`).
**Fix:** add a `_sync_budget_tokens` mirroring `_sync_budget_cost` that sums
`total_tokens` over the run + descendant child runs (or reads the run row), and in
`_persist_final` set `total_tokens = max(state.budget.tokens_used,
synced_tokens)`. Symmetric with the existing `max(...)` used for `total_cost_usd`.

### 5.3 RECLASSIFIED — billed > raw cost is **intended pricing**, not a bug
**Finding:** `billed_amount $37.37` vs `total_cost_usd $15.57` is exactly the TB
formula: `billing_config.multiplier_factor = 2.0`, `platform_fee_pct = 0.10`,
`sales_partner_fee_pct = 0.10` → 15.57 × 2.0 × 1.2 ≈ 37.37
(`governance_service.settle_billing`, `governance_service.py:154`). This is the
designed margin, **not** a defect.
**Recommendation (UX transparency):** surface **raw cost vs billed** side-by-side
in the Execution Detail header so users aren't surprised by the markup. No
pricing-logic change.

---

## 6. Rollout & verification

1. **Track A — config quick-wins on the existing entity** (reversible, no
   architecture change): lower critic interval, bound `on_failure` retries, set a
   cheaper critic model, and stop auto-registering scratch/probe files. Likely
   halves cost on its own.
2. **Track B — ship `doc-factory-lite`** per §4 and A/B it against
   `doc-factory-process` on the same prompt. Success = single final artifact,
   ≤8 LLM calls, ≤$2 raw, agent-state updating across ≥3 iterations.
3. **Platform fixes** §5.1 and §5.2 as separate PRs (enforcement + token
   roll-up); §5.3 as a UI transparency tweak.

**Verification queries** (mirror the analysis): for a lite run, assert exactly
**one** `artifacts` row, `count(llm_interaction_logs) ≤ 8`, parent
`total_tokens > 0`, and the run aborts if `total_cost_usd` reaches
`max_cost_usd`. Use the new execution-trace span tree
(`/ai/executions/{id}/trace`) to confirm the `generate → validate → finalize`
shape with no re-runs.
