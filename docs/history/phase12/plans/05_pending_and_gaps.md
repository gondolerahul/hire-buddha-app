# 05 — Pending Phase 11 Items + Phase 12 Gaps

This file is the **inventory**. Everything Phase 11 deferred or left
half-done, cross-checked against the code in tree, plus the gaps the
pre-implementation review identified that were never closed. The cleanup
and capability plans (`01`, `06`) act on this list; this is the source of
truth for "what is actually unfinished."

Sources: `docs/phase11/STATUS.md` §"Deferred to Phase 12",
`docs/phase11/PROGRESS_REPORT.md` §5, `docs/phase11/RETROSPECTIVE.md` §3/§6,
`docs/phase11/DECISIONS.md`, and a fresh read of `backend/src/ai/`.

---

## 1. Carried-over Phase 11 backlog (must close in P12)

### 1.1 Mechanical follow-ups (no functional gap)

| ID | Item | Anchor / evidence | Owner area | Plan |
|----|------|-------------------|-----------|------|
| P-M1 | `mypy --strict` full kernel sweep | `core/`, `planning/`, `memory/`, `meta/`, `governance/` — ~100 small fixes | kernel | `01` §6 |
| P-M2 | Comment-narration sweep → 0 hits + promote lint to **error** | 139 hits in warn mode; `backend/scripts/lint_ai_layout.py` | kernel | `01` §3 |
| P-M3 | Tool subdomain `git mv` (`core/ documents/ media/ sandbox/ email/ crm/ integrations/{social,ads}/ management/`) | `tools/` still flat (+ `tools/meta/`, `tools/social/`) | tools | `01` §5 |
| P-M4 | Subdomain README refresh after the move | lands with P-M3 | tools | `01` §5 |

### 1.2 Cleanups gated on ≥30 days canary telemetry

| ID | Item | Flag / shim | Plan |
|----|------|-------------|------|
| P-D1 | Delete `_review_step_output` (legacy critic body) | `critic_pipeline.v1_compat` (OFF) | `01` §4 |
| P-D2 | Delete `MemoryRouter` body (keep `LegacyEpisodicReader`) | `memory.v2_canonical` (ON) | `01` §4 |
| P-D3 | Delete `MetaReviewer` 5-line shim | `meta_review.v2_enabled` (ON) | `01` §4 |
| P-D4 | Delete `CortexRouter` alias / re-export shim | rename done; alias remains | `01` §4 + `04` |
| P-D5 | Frontend `P11*` prefix removal + back-compat shims | 14 `P11*` components | `01` §7 |

### 1.3 Functional items intentionally held back

| ID | Item | State in code | Plan |
|----|------|---------------|------|
| P-F1 | Meta-Agent template **re-seed** (`reseed_meta_agent.py`) | needs UI + content review | `06` §7 |
| P-F2 | LLM "critic-of-critic" inside `meta_agent_prompt_evolution` | cron plumbing live (`core/arq_jobs.py`), LLM diff deferred | `06` §6 |
| ~~P-F3~~ ✅ | Wire `CostLedger.add(...)` into **every non-tool** cost site (planner / critics / dreaming / embedding / `meta_spec_critic` / `test_driver`) | **DONE** — embedding was the last site; metered in `memory/embedding_service.py::embed_batch` (one row/batch, `attribution="embedding"`, char-billed) | `01` §6, `07` §4 |
| P-F4 | REACT-AFC inner-closure adopting `ToolResilience.run(...)` inside `_execute_thought` | flag flipped ON (DECISIONS 2026-05-29); inner refactor remains | `01` §6 |
| P-F5 | `PlannerService.reconcile` full **v2 swap** (only `adapt_plan` flipped) | `reconcile` still on v1 path | `01` §6 (ties to **D-2**) |
| ~~P-F6~~ ✅ | `tools.cost_attribution_required` → default ON (last canary flag) | **DONE** — flipped ON in `feature_flags.py`; CI guard `test_no_usage_log_is_unattributed` asserts no UNATTRIBUTED row | `01` §6 |
| P-F7 | `task_classifier.v2_enabled` (embedding NN) evaluation → ON/keep-OFF decision | default OFF; v1 rules in use | `06` §5 |
| P-F8 | `meta_agent.curator_consolidation_enabled` (LLM merge proposals) → ON | default OFF | `06` §4 |

### 1.4 Observability / DX polish

| ID | Item | Plan |
|----|------|------|
| P-O1 | Grafana / Metabase panel JSON (SQL shipped under `infra/dashboards/phase11/`) | `08` §KPI |
| P-O2 | One-line CSAT (retro feedback collection) | `07` §6 |
| P-O3 | Frontend Storybook per `components/agent/*`, Lighthouse CI, Playwright nightly | `01` §7 |
| P-O4 | `services/events.ts` typed reducer / exhaustiveness for live iteration timeline | `01` §7 |

### 1.5 Documentation drift to fix (found by the P11 audit)

The PROGRESS_REPORT found `RETROSPECTIVE.md §3` stale on three items — they are
**implemented**, not deferred. Fix as part of P12 doc hygiene:

* `cost_estimator_refresh` nightly cron — **done** (`core/arq_jobs.py:902`).
* Admin REST wrappers (skill candidates / promote-DRAFT / spec_critic /
  anti_patterns / prompt_candidates approve) — **done** in `phase11_router.py`.
* REACT-AFC unification flag — **flipped** (only inner closure remains, see
  P-F4).

---

## 2. Phase 12 candidate themes named in the retrospective (§6)

These were sketched as "Phase 12 candidate themes." Disposition for *this*
phase:

| Theme | P12 disposition |
|-------|-----------------|
| `DomainTreeBase` migration of the four legacy memory services | **In scope** — folds into CORTEX extraction (`04`); each service drops to ~80 LoC. |
| LLM-driven Strategist (currently deterministic) | **Partial** — pilot behind a flag for high-value entities only (`06` §3); full rollout = P13. |
| Cross-tenant skill / intelligence sharing | **Design only** in P12 (`06` §8); product/privacy call required before build. |
| RL over plan-style selection | **Out** — needs ≥3 months telemetry; stays bandit. |
| Tool synthesis from natural language | **In scope** — the marquee Meta-Agent capability (`06` §2). |
| MCP / external tool integration | **In scope, scoped** — adopt MCP as the tool-plugin protocol (`07` §1); the environment already exposes MCP servers. |
| Multi-model critic ("third-model" tiebreak) | **Opt-in** for high-stakes (`06` §4); not default. |
| Per-iteration contextual bandit | **Out** — P13. |
| Auto-promotion of skill candidates under per-company trust level | **In scope** — gated promotion (`06` §2). |
| Provenance trust-score learning (currently constant) | **In scope, small** (`07` §3). |

---

## 3. Gaps from the pre-implementation review never fully closed

The `docs/phase11/review/` doc listed nine "real functionality missing" gaps
(02 §6). Status after implementation:

| Review gap | Closed by P11? | P12 action |
|------------|----------------|-----------|
| No persistent failure log per entity | Partial — `StepHealthRecord` + IntelligenceTree candidate rules | Verify rules actually surface in planner prompt (P-F5 / `06` §5). |
| No introspective tools for the agent itself | Partial — perception payload exists; no `agent_introspect`/`agent_reflect` *tools* | Build them (`06` §3, "meta-abilities"). |
| No A/B telemetry on prompt/mode changes | Partial — KPI rollup exists; no per-version A/B harness | `07` §5 (eval harness). |
| No graph of cross-entity reuse / composition outcomes | **Open** | `06` §4 (Curator composition graph). |
| No streaming of intermediate narrative to user | Partial — SSE + `P11SpanTree`/trace events | Confirm narrative (not just status) streams (`01` §7). |
| No skill library / tool synthesis | Skill library **done**; tool synthesis **open** | `06` §2. |
| No structured reflective write at end of run | **Done** — `Reflector` + `dreaming_outcome_trigger` | — |
| No multi-agent debate / consensus | **Open** (ToT is single-LLM) | `06` §4 + **D-3** `DebateExecutor`. |
| No cost/time budget *contract* enforced in REACT | Partial — `Budget` exists & surfaced; LLM not bound by it | `07` §2 (budget-aware REACT). |

---

## 4. The two master canary switches — the gating fact for everything

Almost every deletion in `01` is blocked behind the same precondition:

```
agent_loop.enabled          default OFF   ← per-company canary opt-in
meta_agent.board_routing     default OFF   ← per-company canary opt-in
```

Until these flip ON in production and accumulate ≥30 days of clean telemetry
(R-PRG-3 false-pass ≤0.10, R-PRG-5 critic-cost-share ≤0.25, R-PRG-8 promotion
REJECT ≤30%), the v1 bodies must stay reachable for rollback. **Stage 0 of the
roadmap is exactly this flip-and-watch.** Nothing in `01`'s deletion list may
land before Stage 0 completes. This is the single most important sequencing
constraint in Phase 12.
