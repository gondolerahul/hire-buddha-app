# 01 — Phase 11 Consolidation: De-prefix, Legacy Removal, Restructure

> Scope item 1. Turns the canary build into the GA build: strip the
> `p11`/`P11`/`phase11` labels, delete the flag-gated legacy paths, finish the
> structural moves Phase 11 deferred, and lock the layout with CI.

This file assumes the cross-cutting decisions **D-1…D-4** in `00_README.md` and
the inventory in `05_pending_and_gaps.md`. It is sequenced so every step is an
independently revertable PR.

---

## 1. Guiding principle

Phase 11 shipped *additively and reversibly* on purpose. Phase 12 consolidation
is the **inverse operation, done once the bet has paid off**: we remove the
optionality, commit to the v2 paths, and make the directory tree tell the truth.

Three rules:

1. **No deletion before Stage 0.** The two master switches must be ON in prod
   with ≥30 days clean telemetry first (see `05` §4). This is non-negotiable.
2. **De-prefix and delete in the same cut per subsystem.** Renaming `p11` while
   the v1 body still exists creates a worse mess. Cut subsystem-by-subsystem:
   each PR removes the legacy body *and* drops the canary prefix for that
   subsystem together.
3. **Public surfaces keep a redirect shim for one release.** HTTP routes and the
   frontend route table get alias/redirect shims so external callers and
   bookmarks don't 404 on the rename; the shims carry a removal date.

---

## 2. The naming surfaces to neutralize

A full scan found the canary label in five surfaces:

| Surface | Current | Target |
|---------|---------|--------|
| Backend router | `backend/src/ai/phase11_router.py` (`/api/v1/ai/phase11/admin/*`) | `ai/api/admin.py` → `/api/v1/ai/admin/*` (kernel admin) |
| Migrations | `p11t02_*.py … p11t10_*.py`, `p11_*.py` (10 files) | **leave as-is** (renaming applied migrations is dangerous; see §2.1) |
| Frontend components | 14 × `frontend/src/components/agent/P11*.{tsx,css}` | drop `P11` prefix (`AgentKernel.tsx`, …) |
| Frontend types/services | `frontend/src/types/phase11.ts`, refs in `meta.service.ts`, `kpi.service.ts`, `router/index.tsx`, `MainLayout.tsx` | `types/agentKernel.ts`; update imports |
| Feature-flag keys | already neutral (`agent_loop.enabled`, `critic_pipeline.v2_enabled`, …) | **no change** — keys are fine; only *defaults* flip (§4) |

> **Note:** the *feature-flag keys* were named well during Phase 11 (no `p11`
> prefix), so the consolidation there is purely default-flips and dead-flag
> removal, not renaming.

### 2.1 Why migrations stay named `p11t*`

Alembic revision identifiers are content-addressable history. Renaming an
*applied* migration file does not rename the `version_num` already written to
the DB; it only confuses `alembic history`. The `p11t*` filenames are harmless
historical artifacts. **Do not rename them.** (Memory note:
`[[alembic-revision-id-32-char-limit]]` — keep any *new* P12 revision strings
≤32 chars.) New P12 migrations use a neutral prefix, e.g. `p12_*` or a plain
descriptive slug.

---

## 3. Cut 0 — Comment-narration & layout lint to error (P-M2)

The kernel is full of `# Phase 10D:`, `# Fix B:`, `# RACE-2 fix:` narration
(139 hits, currently *warn* in `backend/scripts/lint_ai_layout.py`).

* Sweep all 139 hits. Anything load-bearing becomes a one-line **invariant**
  comment ("children must resolve before dispatch"); the rest is deleted (git
  history is the changelog).
* Promote the narration rule and the file-layout rules from **warn → error** in
  `lint_ai_layout.py`, and remove the transitional allow-list.
* Add the new hard rule: `no identifier or filename may contain p11|P11|phase11`
  outside `docs/` and `migrations/versions/`.

**Exit:** `lint_ai_layout.py` is green with zero allow-list entries; CI fails on
any reintroduced narration or canary label.

---

## 4. Cut 1 — Delete flag-gated legacy bodies (P-D1…P-D4)

**Precondition: Stage 0 complete.** For each, confirm the v1 flag has shown
zero production traffic for ≥30 days via the telemetry envelope, then delete the
body *and* the flag in the same PR.

| Subsystem | Delete | Keep | Flag to retire |
|-----------|--------|------|----------------|
| Critic | `step_executor._review_step_output` body + its retry-with-same-model path | `RealCriticPipeline` | `critic_pipeline.v1_compat` |
| Memory | `MemoryRouter` retrieval body; the `memory_pipeline="v1"` branch in `memory/assembler.py` | `LegacyEpisodicReader` (first-run top-up — **permanent**) | `memory.v2_canonical` (becomes unconditional) |
| Meta-review | `core/meta_review.MetaReviewer` 5-line shim | `SupervisorCritic` | `meta_review.v2_enabled` |
| CORTEX naming | `CortexRouter` alias / `as CortexService` re-export | `CortexService` (the class) | — |
| Engine type | the `engine_type == "RECURSIVE"` behavior branch in the legacy `ExecutionEngine.execute_run` | the `RecursiveExecutor` (loop chooses it) | implied by `agent_loop.enabled` ON |

After this cut, `core/feature_flags.py::DEFAULTS` is pruned of every retired
key, and the stub/compat executors (`dialog`, `tool_burst`, `skill`) are either
implemented (see `06`) or explicitly removed from `DEFAULTS` to avoid dead
flags.

> The legacy `ExecutionEngine.execute_run` monolith is the biggest single
> deletion. Once `agent_loop.enabled` is unconditional, the loop is the only
> entry point and the old plan-walker body (the ~600-line branching method the
> review flagged as F-14) is dead. Delete it; the executors it spawned now live
> under `core/executors/` and are owned by the loop.

**Exit:** `grep -rn "v1_compat\|memory_pipeline.*v1\|MetaReviewer\|execute_run"
backend/src/ai` returns only the loop's own references; flag count drops by ~6.

---

## 5. Cut 2 — Finish the structural moves (P-M3, P-M4)

Phase 11 split `schemas.py` and `models.py` into packages and built
`core/`, `planning/`, `memory/domains/`, `meta/board/`. The one structural
move it deferred is the **tools subgrouping**. Apply the layout from the review
(`docs/phase11/review/07_folder_restructure.md` §2), now that the dust has
settled:

```
tools/
├── __init__.py            ← registrations
├── base.py
├── resilience.py
├── core/                  ← calculator, search, batch_search, scraper, file_writer, text_extractor
├── documents/            ← pdf_generator, docx_tool, pptx_tool, excel, xlsx_engine, document_save
├── media/                ← image_generation, video/ (see file 03)
├── sandbox/              ← sandbox_executor, sandbox_provision, terminal_tool, browser_tool (see file 02)
├── email/                ← email_tool
├── crm/                  ← crm_tools
├── integrations/
│   ├── social/           ← the 15 platform tools (audit ACTIVE/EXPERIMENTAL/DEAD first)
│   └── ads/
├── meta/                 ← platform_introspect, registry_search, schema_validator, entity_creator, entity_executor, spec_critic (+ tool_synthesis — file 06)
└── management/           ← tool admin router/service
```

* Pure `git mv` + update `tools/__init__.py` registrations (~30 import lines).
* **Audit the 15 social tools first** (review F-21): tag each ACTIVE /
  EXPERIMENTAL / DEAD; EXPERIMENTAL gate behind `tools.experimental.<id>`
  (mechanism already exists from T8); delete confirmed DEAD ones (flag via
  `spawn_task` if any are ambiguous).
* Refresh the per-subdomain `README.md` after the move.

**Exit:** `tools/` has the subgroup layout; `lint_ai_layout.py` enforces "no
loose tool files at `tools/` root except `__init__.py`, `base.py`,
`resilience.py`."

---

## 6. Cut 3 — Finish the deferred functional swaps (P-F3, P-F4, P-F5, P-F6)

These are the "one-line-each but real" items that complete Phase 11's intent.

### 6.1 `PlannerService.reconcile` → v2 (P-F5, ties to **D-2**)

Phase 11 flipped `adapt_plan` to v2 but left `reconcile` on v1. Finish it, and
fold in **D-2** (static plan as prior, not backbone):

* `reconcile()` no longer "repairs the LLM plan against the static plan."
  Instead `static_plan`, when present, is passed to `PlanGenerator.generate()`
  as a **named candidate** (`source="authored"`).
* Add a plan invariant `authored_steps_covered` that fires only when
  `static_plan.binding == true` (new optional field) — for compliance PROCESSes.
* Delete the v1 reconcile body and its `child_resolver` duplicate (the executor
  already uses the shared `child_resolver.resolve_child_entity_id`).

### 6.2 REACT-AFC inner closure adopts `ToolResilience.run` (P-F4)

The flag is ON; the inner `_execute_thought` closure still calls tools directly.
Refactor the closure to route through `ToolResilience.run(...)` so reformat-retry
and fallback heal tool failures inside REACT exactly as in direct TOOL_CALL.
This removes the last "REACT silently degrades, direct heals" asymmetry.

### 6.3 CostLedger everywhere (P-F3 → unblocks P-F6)

Thread `CostAttribution` into every non-tool LLM cost site:

```
planner → CostAttribution.PLANNER
pre/post/align/supervisor critic → CostAttribution.CRITIC
dreaming → CostAttribution.DREAMING
embedding → CostAttribution.EMBEDDING
meta_spec_critic / board roles → CostAttribution.META
test_driver → CostAttribution.META_TEST
```

Each is a one-line `CostLedger.add(..., attribution=...)` at the existing log
site. Once every site is attributed, flip `tools.cost_attribution_required` →
**ON** (the last canary flag), making un-attributed cost a hard error in tests.

### 6.4 `mypy --strict` kernel sweep (P-M1)

Ship as a tracked PR series, one package per PR (`core/`, then `planning/`,
`memory/`, `meta/`, `governance/`). ~100 small annotations. Add
`mypy --strict` on those five packages to CI as a required check at the end.

---

## 7. Cut 4 — Frontend de-canary (P-D5, P-O3, P-O4)

* Rename the 14 `P11*` components to neutral names (`AgentKernel`,
  `AgentStatePanel`, `IterationCard`, `PlanCandidatesCompare`, `SpanTree`,
  `SupervisorAndBandit`, `AgentLoopExecutionDetail`); update imports in
  `router/index.tsx`, `MainLayout.tsx`, `meta.service.ts`, `kpi.service.ts`.
* `types/phase11.ts` → `types/agentKernel.ts`.
* Route shim: keep `/admin/phase11/*` redirecting to `/admin/agent-kernel/*`
  for one release (bookmark safety), with a removal date in a comment.
* Confirm the SSE stream publishes the **iteration narrative**, not just status
  transitions (review gap; `05` §3). Add the typed `services/events.ts` reducer
  with exhaustiveness checking (P-O4).
* Polish wave (can trail): Storybook per `components/agent/*`, Lighthouse CI,
  Playwright nightly (P-O3).

---

## 8. The design decisions, made concrete in code

This section turns the cross-cutting decisions from `00` into specific edits, so
the consolidation actually *simplifies* rather than just renames.

### 8.1 D-1 (keep hierarchy, decouple type from execution)

* Remove `engine_type` as a *behavior* switch. Keep the field for one release as
  an accepted-but-ignored input (logged as deprecated), then drop from the
  schema in a minor version. The Strategist owns executor choice.
* Document in `schemas/entity.py` and `ai/README.md` the new meaning of the four
  types: **capability surface + governance scope + reuse granularity + the
  per-level meta-cognition matrix** (the matrix lives in `06` §1). Type no
  longer implies an engine.
* Keep `CHILD_ENTITY_INVOCATION` and the hierarchy index — they are how PROCESS
  composes AGENT/SKILL. The org chart stays.

### 8.2 D-2 (static plan → prior) — implemented in §6.1 above.

### 8.3 D-3 (reasoning modes)

* `core/reasoning/react.py`, `chain_of_thought.py` — **keep**.
* `core/reasoning/reflection.py` — **retire as a selectable per-entity mode.**
  Its logic is superseded by the loop's `Reflector`. Delete the per-entity
  `reasoning_mode="REFLECTION"` branch; migrate any entity configured that way to
  plain ReAct + the loop's reflection (a tiny data migration, `p12_*`).
* `core/reasoning/tree_of_thoughts.py` — **move/reframe** to
  `core/executors/debate.py` (a real `DebateExecutor`: spawns 2 persona child
  nodes in a CORTEX `debate` subtree, a third LLM judges). The Strategist
  selects it when step uncertainty/stakes are high; it is *not* a per-entity
  setting. This also delivers the review's "multi-agent debate" gap (`05` §3).
* **Per-step reasoning selection (F-16):** the Strategist's `Move` already
  carries an executor; extend it to carry a `reasoning_hint` so a cheap
  TOOL_CALL never pays for heavy reasoning and a synthesis step can opt into
  debate. Reasoning mode leaves the entity config entirely (kept only as an
  optional default hint).

### 8.4 D-4 (selective legacy removal) — implemented in §4 above.

---

## 9. PR sequence (each independently revertable)

| PR | Title | Depends on | Risk |
|----|-------|-----------|------|
| C0 | Narration sweep + lint→error + canary-label rule | Stage 0 | low |
| C1 | Delete critic v1 body + retire `v1_compat` | Stage 0 telemetry | med |
| C2 | Delete MemoryRouter body; assembler v2-only; keep LegacyEpisodicReader | Stage 0 | med |
| C3 | Delete MetaReviewer shim + CortexRouter alias | Stage 0 | low |
| C4 | Delete legacy `ExecutionEngine.execute_run`; loop is sole entry | Stage 0; C1–C3 | **high** |
| C5 | `reconcile`→v2 + static-plan-as-prior (D-2) | C4 | med |
| C6 | REACT-AFC `ToolResilience` inner closure (P-F4) | — | med |
| C7 | CostLedger attribution everywhere → `cost_attribution_required` ON | — | low |
| C8 | tools/ subgrouping git mv + social audit + READMEs | — | low |
| C9 | reasoning-mode consolidation (D-3) + DebateExecutor scaffold | C4 | med |
| C10 | backend router de-prefix (`phase11_router`→`api/admin`) + route shim | C1–C7 | low |
| C11 | frontend de-prefix + route shim + events reducer | C10 | low |
| C12 | mypy --strict series (5 PRs) | C1–C9 | low |
| C13 | drop deprecated `engine_type` & `reasoning_mode` fields (minor ver) | C5, C9 | med |

**C4 is the keystone and the highest risk** — it removes the legacy executor.
Gate it behind a staging soak and a one-click rollback (re-enable
`agent_loop.enabled=false` restores the legacy path *only if C4 has not yet
merged*; after C4 there is no legacy path, so C4 must not merge until the canary
is genuinely complete).

---

## 10. Exit criteria

* `grep -rn 'p11\|P11\|phase11' backend/src frontend/src` → empty (docs &
  applied migrations excluded).
* `core/feature_flags.py::DEFAULTS` contains no retired/legacy keys; both former
  master switches are gone (behavior is unconditional).
* No file > 600 LoC in `core/ planning/ memory/ meta/ governance/`; `tools/` is
  subgrouped; `lint_ai_layout.py` green with no allow-list.
* `mypy --strict` passes on the five kernel packages in CI.
* `tools.cost_attribution_required` ON; cost dashboard breaks down by
  attribution with no `UNATTRIBUTED` rows.
* All KPIs hold at or beat Phase 11 canary targets across the cutover (`08`).
