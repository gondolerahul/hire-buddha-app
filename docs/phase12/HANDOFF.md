# Phase 12 — Implementation Handoff

> **Read this first.** It is the single entry point for continuing Phase 12 in a
> fresh session. It captures the current state, the non-obvious findings that
> change the plan, how to verify, and the exact remaining sequence. Pair it with
> [`WHATS_NEXT.md`](./WHATS_NEXT.md) (the prioritized checklist), the eight
> [`plans/`](./plans/) files (the original spec), and the two C4 design docs in
> [`designs/`](./designs/).
>
> **Last updated:** 2026-06-08 (Stage 1 COMPLETE; new-capability tracks —
> `02` S1–S6, `04` Stage A–C, **`03` video split DONE**, **`07` budget-aware
> REACT + eval harness + doc/embedding guards DONE**, **`06` §3.1 introspection
> tools DONE + §2 tool-synthesis safety core (ToolSpec + ToolValidator) landed**;
> next: `06` tool-synthesis LLM loop / board GA, `07` MCP adapter / trust-score)
> **Branch:** `phase12/stage1-consolidation`

> **Session addendum (2026-06-08, capability completion):** Phase 12 capability
> tracks finished out — ten more gate-green commits (unit 746 / parity 2 / lint 0
> / mypy --strict 0 over 113 files):
> - **`06` §2 tool synthesis (marquee) DONE** — ToolSmith → ToolValidator →
>   sandbox replay → red-team → DRAFT register; gated meta-tool + `ToolStatus.DRAFT`
>   + `meta_agent.tool_synthesis_enabled` kill switch (all OFF). See
>   [[phase12-06-tool-synthesis]].
> - **`07` §1 MCP adapter** (`tools/mcp/`), **`07` §3 trust-score learning**
>   (`memory/trust_learning.py` + `source_trust_scores` migration).
> - **`07` §6 smalls** — CSAT capture (`execution_runs.csat_score` + endpoint),
>   SSE iteration narrative, seed-hygiene verified.
> - **`06` §4** consolidation merge-plans + composition graph + spec tiebreak +
>   TestDriver goldens; **§5** rule lifecycle + confirmed-only planner gate;
>   **§6.1** prompt-evolution LLM diff (cron wired) + **§6.3** version-aware reseed.
> - **P-O1** `infra/dashboards/phase12/` + **`OPS_REMAINDER.md`** (the build-done/
>   ship-pending list: `02` S7 CVE+publish, `04` PyPI, GA canary flips, frontend).
> - New flags (all default OFF): `meta_agent.tool_synthesis_enabled`,
>   `meta_agent.spec_critic_tiebreak`, `memory.trust_score_learning`,
>   `memory.rule_lifecycle_confirmed_only`. New migrations:
>   `p12_source_trust_scores`, `p12_run_csat`.
>
> **Session addendum (2026-06-08, capability tracks):** six commits on top of the
> base branch, each gate-green (lint 0 / typecheck 0 / unit) and hermetic:
> - **`03` video split** — `video_generation` → `video_generate` / `video_edit` /
>   `video_add_sound` over `tools/media/video/_ffmpeg.py` (routes through
>   `run_sandbox_exec`); deprecated `video_generation` shim composes them.
> - **`07` §2 budget-aware REACT** — `budget_prompt_lines` injected into the step
>   prompt behind `agent_loop.budget_aware_react` (ON) + `..._threshold` (0.70).
> - **`07` §6 guards** — INTERNAL_KEYS reverse doc-rot test + embedding-SSOT test.
> - **`06` §3.1 introspection** — `agent_introspect` + `agent_reflect` meta-tools,
>   matrix-gated via `resolve_meta_cognition` (`self_introspection`/`reflection`).
> - **`07` §5 eval harness** — `tests/eval/` (pure metrics + delta report; DB-gated
>   replay runner).
> - **`06` §2 tool-synthesis safety core** — `ToolSpec` + `ToolValidator` AST gate.
>   The LLM ToolSmith loop + sandbox-test + red-team + DRAFT registration remain.
>   **Note:** `ToolStatus` still lacks a `DRAFT` value — add it when wiring DRAFT
>   registration.
> - **Track A: Vertex creds wired** — `GOOGLE_CLOUD_PROJECT`/`GOOGLE_CLOUD_LOCATION`
>   in `backend/.env` (local); real embedding + generation verified via the VM's
>   metadata SA. This VM is **not** keyless (see §1.7).
> - **Track B: egress proxy DONE** — `02` S7's network gate. `hb-egress-proxy`
>   image + `EgressProxyManager` (`--internal` net + dual-homed tinyproxy,
>   allow-list) + `TenantSandboxManager.ensure(egress=True)`. Backs
>   `NetworkPolicy.ALLOWLIST`. Docker-verified (allow/deny/no-direct-egress). The
>   `02` S7 remainder is now just CVE scan + registry publish.

---

## 0. TL;DR — where things stand

- Phase 12 plans live in `docs/phase12/plans/` (8 files, `00`–`08`). The
  prioritized status is in `WHATS_NEXT.md`.
- **Stage 1 consolidation is COMPLETE.** The repo is the GA shape and the
  keystone C4 deletion landed: the legacy `ExecutionEngine.execute_run`
  plan-walker and `execution_engine.py` are gone, the **AgentLoop is the sole
  run engine**, and async suspend/resume is the only child path.
- **C4 Phase B landed (newest work)** — see §3:
  - **PR-5** extract `StepEngine` (the step surface; `execution_engine.py` kept
    only `execute_run` on top of it).
  - **PR-6** async child dispatch is the loop's sole child path; the parity
    candidate is now drainer-driven (`worker_sim`) so multi-child PROCESS
    suspends + resumes like a real worker.
  - **PR-7** `RecursiveExecutor` maps a goal-only AGENT onto the planner (no
    `execute_run`); `RecursiveReasoningEngine` reparented to `StepEngine`.
  - **PR-8** every run entry point is loop-only (arq dispatch, gateway
    dispatcher, `process_gateway_event`, `resume_execution`; dead
    `enqueue_job("execute_run")` repointed).
  - **PR-9** delete `execute_run` + `execution_engine.py` + the child callback
    plumbing + the `agent_loop.enabled` switch.
  - **G4 flag soak dev-skipped by explicit decision** (same policy as the
    Stage-0 telemetry gate — no live canary in this keyless env).
- **Fallout also landed:** **C2** (MemoryRouter retrieval body deleted, memory
  v2 unconditional), **C3-finish** (engine MetaReviewer use gone; `MetaReviewer`
  kept as the critic-pipeline fallback), **C13** (`engine_type` +
  `RecursiveReasoningEngine` deleted; per-step reasoning via `reasoning_hint`).
- **`grep -rn 'execute_run\b' backend/src/ai`** → comments/history only. All
  gates green (unit, parity 2-passed, lint 0, typecheck 0 over 99 files).
- **Nothing is in production.** All commits are **local only** (no GitHub creds
  in this env) — the human pushes.

---

## 1. CRITICAL CONTEXT — read before writing any code

1. **C4 is DONE — the AgentLoop is the sole run engine.** `execute_run` /
   `execution_engine.py` are deleted; the loop's executors construct `StepEngine`
   (`core/step_engine.py`) for step execution and dispatch child entities
   asynchronously (suspend/resume). There is no engine switch. Full detail in §3
   and `designs/c4_replatforming_implementation_plan.md`. **Stage 1 is complete;**
   the remaining Phase-12 work is the new-capability tracks (`02`/`03`/`04`/`06`/`07`).

2. **The layout/canary lint is now `error` mode and green.** `CANARY_LABEL_MODE`
   in `backend/scripts/lint_ai_layout.py` is `error`; any reintroduced
   `p11/P11/phase11` identifier/filename under `backend/src/ai/**.py` fails CI.
   The `core/` size cap is **1500** (agent_loop.py is large from suspend/resume).
   Keep new files under their package cap or extract a module (as `step_results.py`
   did).

3. **Residual `phase11` strings are intentional and lint-permitted.** Only: the
   one-release redirect shims (`backend/src/main.py` and the frontend route table,
   both with a **2026-09-01 removal date**), immutable applied-migration names
   (`p11t02_*`, `p11_merge_2026_05_28`), and `docs/phase11/*` pointers in `*.md`
   READMEs (the lint scans only `*.py`). Don't "clean" these without a plan.

4. **The two master switches default ON in dev** (`agent_loop.enabled`,
   `meta_agent.board_routing`) — `backend/src/ai/core/feature_flags.py`. The
   feature-flag env-override prefix is now **`AI_FLAG_`** (was `PHASE11_FLAG_`).

5. **The parity gate is hermetic and is the C4 evidence gate.** `tests/parity/`
   runs legacy `ExecutionEngine` vs the new `AgentLoop` with a deterministic mock
   LLM + stubbed `web_search` (no API keys). It now has a **positive multi-child
   PROCESS** case and the **async-dispatch + chaos + cost** checks (§3). Embeddings
   are NOT stubbed — they hit the real Vertex endpoint (returns 200 here; cost $0
   with no SKU rows). This is parity-neutral (both engines embed).

6. **All real-DB parity checks run inside ONE event loop** (the aggregated
   `test_agent_loop_parity`). A standalone `@pytest.mark.asyncio` DB test **skips**
   with "attached to a different loop" — the global `AsyncSessionLocal` engine
   binds to the first loop it touches and asyncpg can't cross loops. **Add new
   real-DB parity checks as helper functions called from that one test**, not as
   new test functions. (PR-2/PR-3 follow this.)

7. **DB + Redis are live** (Postgres `localhost:5433`, Redis `localhost:6379`).
   There is no live arq worker; the async child path is exercised hermetically
   via the in-process drainer `tests/parity/worker_sim.py`. **LLM is NOT keyless
   on this VM** (correcting an earlier assumption): the box's attached service
   account `hirebuddha-vertex-ai@hirebuddha-production` gives Vertex AI access via
   ADC (metadata server, `cloud-platform` scope). Set `GOOGLE_CLOUD_PROJECT=`
   `hirebuddha-production` + `GOOGLE_CLOUD_LOCATION=us-central1` in `backend/.env`
   (done locally; `.env` is gitignored) and real Vertex embedding + `gemini-2.5-flash`
   generation work — verified. The test suites still use a deterministic mock LLM
   on purpose; real creds are only needed to run agents end-to-end.

8. **The comment-narration lint is `error` mode.** Don't write comments matching
   `# Phase 12`, `# Fix X:`, `# RACE-N`, etc. in `backend/src/ai/**.py`.

---

## 2. What's DONE (committed on the branch)

Oldest → newest (this branch is ahead of `origin/phase12/stage1-consolidation`;
all local). Earlier Phase-11/Stage-0 work (`1dd336a`..`deaabba`) is unchanged.

| Commit | What |
|--------|------|
| `7b946fb` | **C3-partial** — remove the deprecated `CortexRouter` alias. |
| `7379d92` | **C10** — backend de-prefix: `ai/phase11_router.py` → `ai/api/admin.py` (`/api/v1/ai/admin/*`) + 307 redirect shim in `main.py`; decision log → `docs/DECISIONS.md`. |
| `f9343b9` | **C11** — frontend de-prefix: 7 `P11*` component pairs + sub-components renamed; `types/phase11.ts`→`agentKernel.ts`; `Phase11KPI`→`KPIDashboard`; `p11-`→`agentk-` CSS; routes `/admin/agent-kernel/*` + redirect shim. |
| `98868d4` | **de-canary** — neutralize remaining `phase11` tokens in `ai/*.py` (incl. env prefix `AI_FLAG_`); flip `CANARY_LABEL_MODE`→`error`; raise `core/` cap to 1500. `test_layout_lint_passes` green. |
| `5aa0a25` | **C4 PR-1** — multi-child PROCESS positive parity (G1 inline) + the C4 implementation plan doc. |
| `dd16a35` | **C4 PR-1b** — loop emits `result_data["steps"]` (snapshotted `AgentState.step_results`); fixes a real refine-flow regression. |
| `4b762c5` | **C4 PR-2** — async suspend/resume parity (first E2E) via `worker_sim.py`; `max_concurrent_children` cap; `CHILD_RUN_QUEUE` config. |
| `4882886` | **C4 PR-3** — resumability chaos (G2) + cost amplification guard (G3). |
| `fbfbf00` | **docs** — C4 plan Progress section. |
| `b17c803` | **C12 scaffold** — `mypy --strict` per-package gate (`scripts/typecheck_ai.py` + allowlist + `test_typecheck_passes` + CI fast lane + `[tool.mypy]`); **`governance/` strict-clean** (first package). |
| `996053b` | **C12 — ORM→`Mapped[]` + planning clean** — `orm/*` migrated to SQLAlchemy 2.0 `Mapped[]` (DDL-identical), governance de-cast, **`planning/` strict-clean** (87→0); allowlist now governance + orm + planning. |
| `4f60690` | **C12 — meta strict-clean** — **`meta/` strict-clean** (74→0); allowlist now governance + orm + planning + meta (46 files). Surfaced 3 latent meta bugs (flagged). |
| `0c6aa5a` | **C12 — memory strict-clean + cortex_models→`Mapped[]`** — `memory/cortex_models.py` migrated to `Mapped[]` (DDL-neutral); **`memory/` strict-clean** (222→0); allowlist + memory (68 files). Fixed graph Decimal+float, `PlanStepTarget`, `_get_company_id` monkey-patch bugs. |
| `2c84a39` | **C12 — core strict-clean (DONE)** — **`core/` strict-clean** (234→0); allowlist now all 6 ai packages (**100 files**). Fixed a `child_entity` UnboundLocalError (caught by parity). Bundles the CriticCalibrator + 3 meta latent-bug fixes (coupled via arq_jobs). **C12 complete.** |
| `3e70a16` | **C4 PR-5** — extract `StepEngine` (`core/step_engine.py`); `ExecutionEngine(StepEngine)` keeps only `execute_run`; executors repointed. |
| `51fccc8` | **C4 PR-6** — async child dispatch is the loop's sole child path (no inline fallback); parity candidate drainer-driven via `worker_sim`. |
| `1c80ca1` | **C4 PR-7** — `RecursiveExecutor` maps a goal-only AGENT onto the planner; `RecursiveReasoningEngine` reparented to `StepEngine`. |
| `fb0d33a` | **C4 PR-8** — every run entry point loop-only (arq, gateway dispatcher, `process_gateway_event`, `resume_execution`); dead `execute_run` enqueues repointed. |
| `34eb457` | **C4 PR-9** — delete `execute_run` + `execution_engine.py` + child callback plumbing (`_execute_child_invocation`/`_dispatch_child_async`/`_run_child_full`) + the `agent_loop.enabled` switch. **Irreversible.** |
| `7107111` | **C2** — delete `MemoryRouter` retrieval body (`retrieve`/`_load_episodic`/`format_for_prompt`) + assembler v1; memory v2 unconditional; keep `write_episodic`/`search_semantic`/`LegacyEpisodicReader`. |
| `6872140` | **C3-finish** — engine `MetaReviewer` hook died with `execute_run`; `MetaReviewer` kept as `CriticPipeline.supervisor`'s `supervisor_v2_enabled=False` fallback; refresh stale docstrings. |
| `d7921d4` | **C13a** — drop `engine_type`: delete orphaned `RecursiveReasoningEngine` (`recursive_engine.py`) + tests; keep `GoalNode` DTO. |
| `781057b` | **C13b** — `step_executor` reads per-step `PlanStep.reasoning_hint` (default REACT), not entity `reasoning_mode`; PlanStep before-validator maps legacy per-step `reasoning_mode`→hint; run-telemetry `reasoning_mode` kept. |

**Push status:** local only.
```bash
git push origin phase12/stage1-consolidation
```

---

## 3. C4 — the keystone deletion (DONE)

**Status: COMPLETE.** Phase A (evidence gate) and the full Phase B deletion
chain (PR-5..PR-9) landed; the G4 flag soak was dev-skipped by explicit decision
(no live canary in this keyless env, same policy as the Stage-0 telemetry gate).
The AgentLoop is the sole run engine; `execute_run` and `execution_engine.py`
are deleted. Non-obvious findings from the cut, for future readers:

- **The parity candidate is now drainer-driven.** Async child dispatch is the
  loop's only child path, so a multi-child PROCESS suspends
  (WAITING_ON_CHILDREN) on a single `AgentLoop.run`; the parity `CandidateAdapter`
  drives it through `run_execution_recursive` + the in-process `worker_sim`
  drainer (and extracts on a fresh session). `record_golden_runs` records the
  same way — there is no legacy engine to record from.
- **`RecursiveExecutor` was a misnomer.** It handed the whole run to
  `execute_run` (engine_type defaulted to DAG, not recursion). For a goal-only
  AGENT whose planner yields nothing hermetically, the legacy engine completed
  with the sentinel output `"Success"` (0 steps). PR-7 reproduces this: map the
  goal onto the planner; on an empty plan, achieve the bootstrapped goal subgoal
  + stamp `result_data={"output":"Success"}` so the loop finalizes COMPLETED
  matching the golden. This path *is* parity-covered (research_agent_brief +
  the PROCESS's research_agent children both hit it) — the gate caught a first
  wrong attempt (driving `execute_tree`).

The full, code-grounded plan is
[`designs/c4_replatforming_implementation_plan.md`](./designs/c4_replatforming_implementation_plan.md)
(builds on [`designs/async_child_dispatch.md`](./designs/async_child_dispatch.md)).

**Why C4 is not a simple deletion** (still true): `execute_run` is load-bearing —
loop executors delegate into engine step methods, and child entities ran via the
`execute_run_fn` callback. Routing children through the loop inline was tried in
Phase 11 and reverted (~$11/child amplification + worker blocking,
`execution_engine.py:97-104`). The fix is async suspend/resume child dispatch.

**Expanded caller inventory (a finding beyond the original design's 3):**
`execute_run` is also called **directly, bypassing the loop and the
`agent_loop.enabled` flag**, by the gateway dispatcher (`gateway/dispatcher.py:272`)
and the gateway-event worker (`arq_jobs.py:290`), plus `resume_execution`
(`arq_jobs.py:719`). PR-8 must re-route these too. Also note the dead
`enqueue_job("execute_run", …)` calls (`cortex_bridge.py:357`, `arq_jobs.py:801`)
reference an unregistered job name — verify/clean.

**Phase A — DONE (the gate):**
- **G1** multi-child PROCESS parity, inline (PR-1) **and async suspend/resume,
  first E2E** (PR-2). ✅
- **G2** resumability chaos: crash before resume → durable `WAITING_ON_CHILDREN`
  → fresh-worker recovery → idempotency (PR-3). ✅
- **G3** cost amplification guard: async child-execution work == inline (PR-3). ✅

**Phase B — NOT started, gated:**
- **G4 flag soak (PR-4)** — operational: `governance.async_child_dispatch` ON for
  a live canary + real telemetry. Cannot run in the keyless dev env. The human
  runs it in prod, or it is dev-skipped by explicit decision (like the Stage-0
  telemetry gate this build skipped).
- Then the irreversible chain: **PR-5** extract `StepEngine` → **PR-6** drop the
  child callback → **PR-7** re-platform `RecursiveExecutor` (the hard one) →
  **PR-8** make every entry point loop-only → **PR-9** delete `execute_run`
  (irreversible — removes the rollback flag) → **PR-10** C2 (`MemoryRouter`
  delete) → **PR-11** C3 finish. All MemoryRouter/MetaReviewer engine uses live
  *inside* `execute_run`, so deleting it unblocks C2 and reduces C3.

> Do not start Phase B without confirming the soak decision. PR-9 is irreversible.

---

## 4. The async-child-dispatch mechanism (so you don't re-learn it)

Behind `governance.async_child_dispatch` (default OFF), now **proven E2E**:

- **Status** `WAITING_ON_CHILDREN`; **marker** `ActionResult.awaiting_children`;
  **state** `AgentState.awaiting_children` + `step_results` (both snapshotted) +
  transient `suspend_requested`.
- **Dispatch** `ChildEntityExecutor._dispatch_async` creates the child run,
  enqueues `run_execution_recursive`, returns the marker. Bounded by
  `governance.max_concurrent_children` (default 8; over it → run inline).
- **Loop** `_iteration` detects the marker → suspend; `_drive` persists
  `_persist_suspended` + returns; `resume()` rehydrates, `_fold_children` folds
  terminal children (records a `step_results` entry per child),
  `_maybe_resume_parent` enqueues `resume_parent_run` on a child's finalize.
- **Jobs** `resume_parent_run` (idempotent), registered in `worker.py`.
- **Tests** units in `tests/unit/test_async_child_dispatch.py`; E2E + chaos +
  cost in `tests/parity/` (driven by `worker_sim.py`).

---

## 5. How to verify (commands that work here)

```bash
cd backend
PY=.venv/bin/python

# Full unit suite (hermetic). Expect: all pass (layout-lint now green).
$PY -m pytest tests/unit -o addopts="" -q -p no:warnings

# The parity gate + all C4 Phase-A checks (needs DB+Redis; skips if absent).
# Expect: 2 passed (sanity + the aggregated parity test running G1/G2/G3).
$PY -m pytest tests/parity -o addopts="" -q -p no:warnings

# Re-record parity goldens (hermetic; needed if you change a fixture/case).
$PY -m scripts.record_golden_runs --output tests/parity/goldens

# The layout/canary lint (now exits 0).
$PY scripts/lint_ai_layout.py

# The C12 mypy --strict gate over the clean-package allowlist (exits 0).
$PY scripts/typecheck_ai.py
```

Notes: always pass `-o addopts=""`. Parity seeds throwaway `parity-*` tenants and
does not clean them up (FK chains) — use a disposable Postgres if that matters.

---

## 6. The remaining roadmap (prioritized)

Pull per-item detail from `WHATS_NEXT.md`.

### A. Stage 1 consolidation — nearly done
- ✅ C3-alias, C10, C11, lint→error (de-canary). `grep` of `backend/src
  frontend/src` for `p11|P11|phase11` is empty except the documented shims +
  migration names + `*.md` doc pointers.
- ✅ **C12 — `mypy --strict` per package as a CI gate — DONE.** All six `ai/`
  packages are strict-clean and gated (`b17c803`, `996053b`, `4f60690`,
  `0c6aa5a`, `2c84a39`): `scripts/typecheck_ai.py` runs `mypy --strict
  --follow-imports=silent` over `CLEAN_PACKAGES` = governance, orm, planning,
  meta, memory, core (**100 files**); `test_typecheck_passes` + `run_ci_matrix.sh`
  fast lane gate it; `pyproject [tool.mypy]` is the baseline. Start counts:
  governance 32, planning 87, meta 74, memory 222, core 234 (orm via migration).
  **The legacy-`Column` ORM cost is GONE:** both `orm/` AND
  `memory/cortex_models.py` were migrated to SQLAlchemy 2.0 `Mapped[]` (both
  DDL-identical, alembic-verified). **Conventions for future ai code:** real
  annotations + `cast()` for query-result/legacy reads; behaviour-preserving
  `# type: ignore` (NOT "fixes") on the C4-doomed legacy `ExecutionEngine` so the
  parity goldens hold (`retrieve(top_k=)`, `cortex.get_tree()`); lazily-built
  Optional services narrowed via `assert ... is not None` after `_ensure_services`
  / `_compose`. **Bugs fixed along the way:** `CriticCalibrator` missing
  `company_id`; meta `curator`/`registry_search`/`platform_schema_compiler` latent
  bugs; a self-inflicted `child_entity` `UnboundLocalError` (inline
  `from uuid import UUID` shadowing) — **caught by the parity gate**: always run
  `tests/parity` after touching `core`.
- 🚧 **C13 — drop deprecated `engine_type` / `reasoning_mode`** — **blocked, not a
  clean cut** (see §7). Needs per-step reasoning routed via the Strategist first,
  and the engine_type half is gated on C4.

### B. C4 (large; §3) — Phase A done
Run the **G4 soak**, then Phase B (PR-5..PR-11). This unblocks **C2** and the rest
of **C3** as fallout.

### C. The rest of Phase 12 (each its own track; see plans)
- `02` Sandbox runtime / per-tenant containers — **S1–S6 DONE** (all behind
  default-OFF flags). S1–S2: `SandboxRuntime` Protocol + `SubprocessRuntime`.
  S3: the `hb-sandbox` image (`backend/docker/sandbox/`) — **built (4.52GB) +
  smoke-validated**. S4: `ContainerRuntime` + `TenantSandboxManager` behind
  `sandbox.container_runtime_enabled`, bind-mounting the tenant dir at the
  identical path (tools unchanged); Docker-gated integration tests, CI Docker-free.
  **Per-company canary wiring**: `resolve_sandbox_runtime(context)`. S5:
  persistent browser profile (`sandbox.persistent_browser_enabled`). S6: `sandbox`
  cost attribution via `run_sandbox_exec` + the `sandbox-runtime` SKU
  (`scripts/seed_sandbox_sku.py`). **§6 security review** done
  (`security_review_02_sandbox.md`). **Remaining = prod/ops only:** egress proxy
  + image CVE scan + registry publish, then **S7** canary→default-ON. The `06`
  tool-synthesis substrate is ready.
- `03` Video tool split (0%).
- `04` CORTEX pip package — **DONE through Stage C** (Stage A Protocols, Stage B
  full code-move to a host-free `backend/cortex_memory/` package on injected
  providers, Stage C packaging: `mypy --strict` clean, 85% coverage, CI workflow,
  builds a `cortex_memory-0.1.0` wheel). `src/ai/memory/` is now thin shims + host
  adapters. **Remaining = publish** (public repo + `twine upload` to PyPI, then
  pin the version and drop the in-repo copy).
- `06` Meta-Agent v5 capabilities (v4 board exists; v5 = 0%).
- `07` MCP adapter, budget-aware REACT, trust-score learning, eval harness.

---

## 7. Landmines / gotchas (specific, learned the hard way)

- **C13 is DONE** (was blocked on C4). `engine_type` is gone — its only consumer
  was `execute_run`'s RECURSIVE branch, and the orphaned `RecursiveReasoningEngine`
  was deleted. `step_executor` now reads per-step `PlanStep.reasoning_hint`
  (default REACT) instead of the entity `reasoning_config.reasoning_mode`; a
  PlanStep before-validator maps a legacy per-step `reasoning_mode` onto the hint.
  The ORM/`schemas/execution.py` run-telemetry `reasoning_mode` is **kept** (it
  records what reasoning ran, written via `LLMInteractionLog.reasoning_mode`).
- **One-loop parity constraint** (see §1.6): add real-DB parity checks as helpers
  called from `test_agent_loop_parity`, never as standalone async tests.
- **Loop result_data shape:** the loop now emits `{"output", "steps":[...]}` to
  match legacy (`core/step_results.py` + `_persist_final`). The refine flow
  (`service.py:617`) reads `result_data["steps"]` — don't regress it.
- **Child resolver has no company filter** (`planning/child_resolver.py` Strategy 4
  name-hint lookup → `scalar_one_or_none`): seeding fixed-name children across
  runs trips `MultipleResultsFound`. Parity seeding wires `target.entity_id`
  directly (Strategy 1) to avoid this.
- **De-prefix shims carry a 2026-09-01 removal date** (`main.py` backend redirect,
  frontend route table). Don't delete early; don't forget to delete on schedule.
- **C10 left a double-`admin/` path** for the KPI/decisions/risks/tools endpoints
  (e.g. `/api/v1/ai/admin/admin/kpi/runs`) — functionally correct, cosmetic
  cleanup if desired.
- **`execute_run` / `execution_engine.py` are deleted (C4).** The AgentLoop is
  the sole engine. `MemoryRouter` keeps only `write_episodic` + `search_semantic`
  (retrieval body deleted, C2). `MetaReviewer` stays as the critic-pipeline
  `supervisor_v2_enabled=False` fallback (`critic_pipeline.py:489`).
  `RecursiveReasoningEngine` is deleted (C13a).
- **Alembic revision ids ≤ 32 chars**, `p12_*` prefix; don't rename `p11t*`.
- **pytest-asyncio here ignores `loop_scope`** (old version) — the one-loop
  pattern in §1.6 is the workaround.

---

## 8. File & doc index

**Phase 12 docs (`docs/phase12/`):**
- `plans/00..08` — original spec. `WHATS_NEXT.md` — prioritized status.
- `designs/async_child_dispatch.md` — the mechanism (implemented).
- `designs/c4_replatforming_implementation_plan.md` — the C4 PR-by-PR plan +
  Progress section (Phase A done).
- `HANDOFF.md` — this file.

**Key code:**
- `backend/src/ai/core/feature_flags.py` — flags (`AI_FLAG_` env prefix).
- `backend/src/ai/core/agent_loop.py` — the loop (+ suspend/resume, step_results).
- `backend/src/ai/core/step_results.py` — per-step `result_data["steps"]` helpers.
- `backend/src/ai/core/step_engine.py` — `StepEngine`, the step-execution surface
  the loop's executors construct (replaced the deleted `execution_engine.py`).
- `backend/src/ai/core/executors/child_entity.py` — async dispatch + concurrency cap.
- `backend/src/ai/api/admin.py` — the de-prefixed admin router (`/api/v1/ai/admin/*`).
- `backend/src/ai/core/arq_jobs.py` + `worker.py` — dispatch, `resume_parent_run`,
  `CHILD_RUN_QUEUE`.
- `backend/tests/parity/` — the gate: `worker_sim.py` (in-process drainer),
  `test_async_child_parity.py` (G1 async helper), `c4_resumability.py` (G2/G3),
  `hermetic.py` (seeding + `child_fixtures`/`governance_overrides`), `extract.py`,
  `test_agent_loop_parity.py` (the one aggregated test).
- `backend/scripts/lint_ai_layout.py` — layout + canary (`error`) + narration lint.

**Memory notes** worth re-reading: `phase12-c4-done` (the full C4/C2/C3/C13 cut),
`phase12-stage1-decanary`, the alembic 32-char limit, the AgentLoop
billing/planning notes.

---

## 9. Suggested first actions for the fresh session

1. Read this file, then `WHATS_NEXT.md`, then
   `designs/c4_replatforming_implementation_plan.md` (Progress + §3 + §5).
2. Run the two verify commands in §5; confirm green unit suite + 2 parity passed +
   lint exit 0.
3. Push the pending commits (or confirm the human did).
4. **Stage 1 is complete; `04` is done through Stage C and `02` S1–S2 landed.**
   Pick up / continue a new-capability track from §6.C / `WHATS_NEXT.md`:
   - **`02` S1–S6 DONE** (all behind default-OFF flags) — runtime + container +
     per-company canary wiring + persistent browser + cost attribution; image
     built + smoke-validated; §6 security review written. Remaining on `02` is
     **prod/ops only**: egress proxy + image CVE scan + registry publish, then
     **S7** canary→default-ON. Keep CI Docker-free; container/persistent-browser
     integration tests are Docker-/Chromium-gated.
   - **`03`** video tool split, or **`06`** board GA on the AgentLoop + tool
     synthesis (the `02` substrate is ready). These are the recommended next tracks.
   - **`04`** is feature-complete in-repo; the only remainder is **publish** (PyPI).
   - **Do NOT** re-open C13 or the deleted `execute_run` path.
