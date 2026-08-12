# Phase 11 — Programme Progress Report

> **Author:** Codebase audit (automated)
> **Date:** 2026-05-29
> **Scope:** `backend/src/ai/`, `frontend/src/`, `docs/phase11/`
> **Cross-referenced against:** `STATUS.md`, `STATUS_FRONTEND.md`,
> `RETROSPECTIVE.md`, `DECISIONS.md`, `docs/phase11/plan/*`,
> `docs/phase11/review/*`.
> **Programme state:** `in-canary` (Tracks 0–9 + 12–15 shipped on both
> backend and frontend; selected items deferred to Phase 12).

---

## 1. Executive summary

Phase 11 was a 12-week programme to turn the platform from a
"plan-first, mostly-linear" execution engine into a **world-class
autonomous agent loop** with a real Meta-Agent, four-domain CORTEX
memory v2, a critic pipeline with calibration, a planner that proposes
and judges alternatives, and a tool/cost layer with attribution. The
12-week roadmap in `docs/phase11/review/08_roadmap.md` was executed
**in full for Tracks 0–9** and extended with **infrastructure Tracks
12–15** (data model, observability, test strategy, risk register).

Both backend and frontend are now in **canary**: every new code path
is reachable through a feature flag, all legacy paths are gated and
reachable for rollback, and the kernel exposes a complete admin
surface — KPI dashboards, feature-flag CRUD, risk indicators,
exit-checklist, and a decision log — at `/api/v1/ai/phase11/admin/*`
and `/admin/phase11/*` in the SPA.

Headline outcomes (validated against the code in this audit):

* **Loop redesign shipped.** `core/agent_loop.py` implements the
  perceive → strategize → pre-critic → act → observe → post-critic →
  reflect → decide cycle, with seven executor adapters under
  `core/executors/` and four reasoning modes under `core/reasoning/`.
* **Critic pipeline v2 shipped, default ON.** `planning/critic_pipeline.py`
  with `RealCriticPipeline`, `SupervisorCritic`, `PlanStyleBandit`,
  `critic_calibration.py`, and `step_health_record.py`. Legacy
  `_review_step_output` retained behind `critic_pipeline.v1_compat`
  (default OFF).
* **Meta-Agent Board shipped.** Seven roles under `meta/board/`
  (`requirement_chat`, `curator`, `architect`, `critic`, `validator`,
  `test_driver`, `promoter`) with `meta_intelligence_tree.py`,
  `skill_library.py`, `anti_sprawl.py`. Default routing OFF behind
  `meta_agent.board_routing` until per-company canary completes.
* **Memory v2 canonical.** `memory.v2_canonical` default ON; four
  domain trees (`episodic`, `experience`, `intelligence`, `knowledge`),
  `domains/base.py` with weighted retrieval, `scope_policy.py`,
  `legacy_episodic_reader.py` for first-run top-up,
  `dreaming_engine.py` with outcome trigger.
* **Planner v2 shipped, default ON.** `plan_generator.py`,
  `plan_invariants.py`, `plan_judge.py`, `plan_style_bandit.py`,
  `cost_estimator.py`, `child_resolver.py`, `retry_strategies.py`.
* **Tool + cost consolidation shipped.** `governance/tool_cost_resolver.py`,
  `tools/resilience.py`, `services/cost_attribution.py`,
  `services/attributed_usage.py`. Both v2 paths default ON.
* **KPI + risk telemetry live.** `kpi_daily_rollup` materialized view +
  hourly refresh cron; six SQL panels under
  `infra/dashboards/phase11/`. Admin endpoints `admin/risks` and
  `admin/exit_checklist` surface programme health.
* **Test posture.** ~420+ unit tests at the time of the retrospective.
  Audit-time count: **112 test files** under `backend/tests/`
  (`tests/ai/{core,planning,memory}` + `tests/integration`,
  `tests/parity`, `tests/chaos`, `tests/regression`, `tests/e2e`).
* **Frontend.** Twelve frontend tracks (FE-0..FE-15) shipped; admin
  pages live under `frontend/src/pages/admin/` (FeatureFlagsPage,
  CostAttributionDashboard, MetaIntelligencePage, RiskAndExitPage);
  agent kernel under `frontend/src/components/agent/P11*.tsx`.

What is **not** shipped is captured in §5 — mostly mechanical
follow-ups (lint promotions, `git mv` of tool subdomains, deletions
of legacy code paths that need ≥30 days of telemetry first), plus a
small set of items the canary explicitly held back.

---

## 2. Backend — track-by-track status

Verified against `backend/src/ai/` source.

| Track | Plan doc | State | Evidence in code |
|------:|----------|:-----:|-----------------|
| **T0 — Pre-flight** | `02_track_0_preflight.md` | ✅ done | `backend/scripts/lint_ai_layout.py` (transitional allow-list; comment-narration patterns in warn mode); per-package READMEs (`core/README.md`, `planning/README.md`, `memory/README.md`, `meta/README.md`, `governance/README.md`, `tools/README.md`). |
| **T1 — Schemas + ORM split** | `03_track_1_schemas_and_orm.md` | ✅ done | `backend/src/ai/schemas/{cortex,document,entity,enums,execution,governance,io_contract,persona,planning,prompts,reasoning,tools,capabilities}.py`; `backend/src/ai/orm/{document,entity,execution,memory,tools,usage}.py`; re-export shims in `models.py`. `FailureTag` closed enum in `schemas/enums.py`. |
| **T2 — AgentLoop** | `04_track_2_agent_loop.md` | ✅ done (flag default **OFF**) | `core/agent_loop.py`; `core/agent_state.py`; `core/budget.py`; `core/perceiver.py`; `core/strategist.py`; `core/observer.py`; `core/reflector.py`; `core/executors/{dag,recursive,single_step,child_entity,stubs}.py`; `core/reasoning/{chain_of_thought,react,reflection,tree_of_thoughts}.py`; `core/feature_flags.py`; parity tests under `tests/parity`. |
| **T3 — Critic Pipeline v2** | `05_track_3_critic_pipeline.md` | ✅ done (flag default **ON**) | `planning/critic_pipeline.py`; `planning/critic_calibration.py` (weekly Arq cron); `planning/critic_prompts.py`; `planning/failure_tags.py`; `planning/retry_strategies.py`; `planning/step_health_record.py`; `planning/goal_guard.py` (shimmed). |
| **T4 — Meta-Review + Bandit** | `06_track_4_meta_review_goalguard.md` | ✅ done (flag default **ON**) | `planning/supervisor_critic.py`; `planning/plan_style_bandit.py`; `memory/task_classifier.py`; `meta_review.v2_enabled` flag; legacy `core/meta_review.py` reduced to shim. |
| **T5 — Meta-Agent Board** | `07_track_5_meta_agent_board.md` | ✅ done (flag default **OFF**) | `meta/board/{requirement_chat,curator,architect,critic,validator,test_driver,promoter}.py`; `meta/meta_intelligence_tree.py`; `meta/skill_library.py`; `meta/meta_cognition_migration.py`; `meta/anti_sprawl.py`; cron jobs in `core/arq_jobs.py` (`skill_promotion_scan`, `meta_agent_prompt_evolution`). |
| **T6 — Memory v2 canonical** | `08_track_6_memory_v2.md` | ✅ done (default v2) | `memory/cortex_service.py`; `memory/legacy_episodic_reader.py`; `memory/scope_policy.py`; `memory/dreaming_engine.py` + `dreaming_prompts.py`; `memory/domains/base.py`; per-domain services (`{episodic,experience,intelligence,knowledge}_tree_service.py`); `memory/embedding_service.py` with `resolve_embedding_model`; `Provenance` schema in `schemas/cortex.py`. |
| **T7 — Planner v2 + Invariants** | `09_track_7_planner_priors.md` | ✅ done (flag default **ON**) | `planning/plan_generator.py`; `planning/plan_invariants.py` (8 deterministic checks); `planning/plan_judge.py`; `planning/cost_estimator.py`; `planning/child_resolver.py`; `planner_service.adapt_plan` flipped to v2. (`reconcile` still on v1 path — see §5.) |
| **T8 — Tool + Cost** | `10_track_8_tool_and_cost.md` | ✅ done | `governance/tool_cost_resolver.py`; `tools/resilience.py` (`ToolResilience`, `FailureKind`, `classify_tool_failure`); `services/cost_attribution.py`; `services/attributed_usage.py`; `usage_logs.attribution` column; `ToolStatus` + `ToolRegistry.get_visible_tools_for_company`. **Deferred item shipped during canary:** unified REACT/AFC path under `tools.resilience_v2_enabled` (see `DECISIONS.md` 2026-05-29). |
| **T9 — Hardening + KPI** | `11_track_9_hardening_and_kpi.md` | ✅ done | `core/INTERNAL_KEYS.md`; `backend/src/ai/ONBOARDING.md`; `infra/dashboards/phase11/{01_run_health,02_cost,03_critic_pipeline,04_meta_agent,05_memory,06_loop_telemetry}.sql`; `kpi_rollup_refresh` cron; `kpi_daily_rollup` materialized view via migration `p11t09_kpi_daily_rollup.py`. |
| **T12 — Data model** | `12_data_model_and_migrations.md` | ✅ done | Migrations applied: `p11t02_feature_flags.py`, `p11t05_preserve_meta_cognition.py`, `p11t06_backfill_intelligence_status.py`, `p11t08_usage_logs_attribution.py`, `p11t09_drop_unused_feature_flags.py`, `p11t09_kpi_daily_rollup.py`, plus `p11_merge_heads.py`. |
| **T13 — Observability + FF + Rollout** | `13_observability_feature_flags_rollout.md` | ✅ done | `TelemetryEvent` envelope; `feature_flags/admin` CRUD endpoints (`phase11_router.py` GET/PUT/DELETE/me). Decision log API live (`admin/decisions` GET+POST). |
| **T14 — Test strategy** | `14_test_strategy.md` | ✅ done | `tests/integration/`, `tests/chaos/`, `tests/parity/`, `tests/regression/`, `tests/e2e/`, `tests/harness/` directories present; ~112 test files. |
| **T15 — Risk register + acceptance** | `15_risk_register_and_acceptance.md` | ✅ done | `phase11_router.py` exposes `GET /admin/risks` (R-PRG-* indicators), `GET /admin/exit_checklist` (machine-readable). |

### Feature-flag default summary (`core/feature_flags.py`)

| Flag | Default | Purpose |
|------|:-------:|---------|
| `agent_loop.enabled` | **OFF** | Master switch — per-company canary opt-in. |
| `agent_loop.perception_bounded_viewport` | ON | |
| `agent_loop.snapshot_every_iteration` | ON | (Decision 2026-05-28.) |
| `agent_loop.executor_{dialog,skill,tool_burst}_enabled` | OFF | Stub executors, not for canary. |
| `critic_pipeline.v2_enabled` | ON | |
| `critic_pipeline.different_model_critic` | ON | (Decision 2026-05-28.) |
| `critic_pipeline.pre_critic_enabled` | ON | |
| `critic_pipeline.v1_compat` | OFF | Legacy `_review_step_output` reachable only with this. |
| `critic_pipeline.calibration_enabled` | ON | |
| `meta_review.v2_enabled` | ON | Supervisor + Bandit path. |
| `meta_review.fast_path_enabled` | ON | |
| `bandit.enabled` | ON | |
| `task_classifier.v2_enabled` | OFF | Embedding NN — v1 rules default. |
| `meta_agent.board_routing` | **OFF** | Per-company canary opt-in. |
| `meta_agent.{spec_critic_required,draft_lifecycle,testdriver_suite_enabled,skill_promotion_cron,prompt_evolution_cron}` | ON | Downstream gates ready for board flip. |
| `meta_agent.curator_consolidation_enabled` | OFF | LLM curator deferred. |
| `tools.cost_resolver_v2_enabled` | ON | |
| `tools.resilience_v2_enabled` | ON | |
| `tools.cost_attribution_required` | OFF | Hard-fail mode held back. |
| `planner.{v2_enabled,invariants_enforced,judge_enabled,priors_enabled}` | ON | |
| `memory.{v2_canonical,viewport_compact,scope_policy_enforced,dreaming_outcome_trigger,embedding_resolver_v2}` | ON | |
| `bandit.epsilon` | 0.10 | |
| `critic_pipeline.budget_share_cap` | 0.20 | |
| `meta_agent.testdriver_budget_usd` | 3.00 | |
| `planner.n_candidates` | 3.0 | |

The two master switches that remain **OFF** (`agent_loop.enabled`,
`meta_agent.board_routing`) are the explicit canary gates — both
codepaths run today against test fixtures, and per-company rollout is
the next step (see §6).

---

## 3. Frontend — track-by-track status

Verified against `frontend/src/`.

| FE Track | Plan doc | State | Evidence in code |
|---------:|----------|:-----:|-----------------|
| **FE-0 Preflight** | `02_track_0_preflight.md` | ✅ done | lint + bundle baselines. |
| **FE-1 Schemas + types** | `03_track_1_schemas_and_types.md` | ✅ done | `frontend/src/types/phase11.ts` mirrors backend enums. |
| **FE-2 AgentLoop UI** | `04_track_2_agent_loop_ui.md` | ✅ done | `components/agent/P11AgentLoopExecutionDetail.tsx`, `P11AgentKernel.tsx`, `P11AgentStatePanel.tsx`, `P11IterationCard.tsx`; ExecutionDetail revamped behind `agent_loop.enabled`. |
| **FE-3 Critic Pipeline UI** | `05_track_3_critic_pipeline_ui.md` | ✅ done | StepHealthStrip + FailureTag chip components (under `components/agent/`). |
| **FE-4 Meta-Review UI** | `06_track_4_meta_review_ui.md` | ✅ done | `P11SupervisorAndBandit.tsx` — verdict card + bandit panel. |
| **FE-5 Meta-Agent Board UI** | `07_track_5_meta_agent_ui.md` | ✅ done | `pages/admin/MetaIntelligencePage.tsx` — role timeline + skill / anti-pattern / prompt panels. |
| **FE-6 Memory v2 UI** | `08_track_6_memory_v2_ui.md` | ✅ done | Provenance ribbon + trust-score badges in CORTEX explorer. |
| **FE-7 Planner v2 UI** | `09_track_7_planner_priors_ui.md` | ✅ done | `P11PlanCandidatesCompare.tsx`. |
| **FE-8 Tool + Cost UI** | `10_track_8_tool_and_cost_ui.md` | ✅ done | `pages/admin/CostAttributionDashboard.tsx`. |
| **FE-9 KPI dashboard** | `11_track_9_kpi_dashboard_ui.md` | ✅ done | `pages/admin/FeatureFlagsPage.tsx` + KPI sub-pages (6). |
| **FE-13 Feature flag live refresh** | `13_feature_flags_and_rollout.md` | ✅ done | 60s polling + visibility-aware. |
| **FE-15 Risk / Exit dashboards** | `15_risk_and_acceptance.md` | ✅ done | `pages/admin/RiskAndExitPage.tsx`. |

The four Phase 11 admin pages (`FeatureFlagsPage`,
`CostAttributionDashboard`, `MetaIntelligencePage`,
`RiskAndExitPage`) are wired into the **Agent Kernel** sidebar group
and `allowedRoles`-locked at both the menu and the router layer to
`APP_ADMIN`, `PARTNER_ADMIN`, `TENANT_ADMIN`.

### Note on the `P11*` filename prefix

All Phase 11 components currently ship under the explicit `P11*`
filename prefix (`P11AgentKernel`, `P11AgentStatePanel`, etc.). This
is the canary-time naming convention so visual diffs and bundle
inspection can tell new components apart from legacy ones at a glance.
**Prefix removal + back-compat shims is the FE-T9 cleanup item
deferred to Phase 12** (see §5).

---

## 4. Cross-cutting infrastructure (live)

* **API surface (`backend/src/ai/phase11_router.py`, ~1500 lines, 25+
  endpoints):** execution-level (`executions/{run_id}/health_records`,
  `plan_candidates`, `cost_attribution`), entity-level
  (`entities/{entity_id}/bandit_state`), meta
  (`meta/skill_candidates`, `meta/intelligence/anti_patterns`,
  `meta/intelligence/prompt_candidates` + approve, `meta/skill_candidates/{id}/promote`,
  `meta/entities/{id}/promote`, `meta/spec_critic`), tools admin
  (`admin/tools/{id}/experimental`), company cost
  (`companies/{id}/cost_attribution`), KPI (`admin/kpi/{runs,cost,critic,meta_agent}`),
  risk (`admin/risks`, `admin/exit_checklist`), decision log
  (`admin/decisions` GET+POST), feature flags
  (`feature_flags/{admin,me,{key}}` GET/PUT/DELETE).
* **Cron / Arq jobs:** `critic_calibration_job` (weekly),
  `skill_promotion_scan` (weekly), `meta_agent_prompt_evolution`
  (HITL-gated), `kpi_rollup_refresh` (hourly),
  `dreaming_outcome_trigger` (from `AgentLoop._finalize`),
  `cost_estimator_refresh` (nightly — see §5 correction).
* **Migrations applied:** all `p11t*` migrations under
  `backend/migrations/versions/` (T2 feature_flags, T5 preserve
  meta_cognition, T6 intelligence_status backfill, T8 usage_logs
  attribution, T9 kpi_daily_rollup, T9 drop_unused_feature_flags,
  merge heads).
* **Observability:** SQL panels under `infra/dashboards/phase11/`
  cover run health, cost, critic pipeline, meta-agent, memory, and
  loop telemetry. Grafana / Metabase panel JSON deferred (§5).
* **Decision log:** `DECISIONS.md` carries four programme-level
  decisions (snapshot default ON; different-model critic default ON;
  LLM Strategist deferred; resilience_v2 default ON for REACT+direct).

---

## 5. What is pending (Phase 12 backlog)

Captured from `RETROSPECTIVE.md §3`, cross-checked against the code.
Items marked **(✱ correction)** are listed as deferred in the
retrospective but the audit found them actually implemented — the
retrospective doc is stale on these.

### 5.1 Mechanical follow-ups (no functional gap)

| Item | Track | Why deferred | Audit finding |
|------|-------|--------------|---------------|
| `mypy --strict` full kernel sweep | T9 | Time-boxed; ~100 small fixes planned as a PR series. | Open. |
| Comment-narration sweep to 0 hits + lint promotion to error | T9 | 139 hits in warn mode; mechanical follow-up. | Open. |
| Tool subdomain `git mv` (`core/`, `documents/`, `media/`, `sandbox/`, `email/`, `crm/`, `integrations/{social,ads}/`, `management/`) | T8 | Mechanical move; touches ~30 import lines. | Open — `backend/src/ai/tools/` still flat plus `tools/meta/`, `tools/social/`. |
| Subdomain README refresh after the `git mv` | T8 / T9 | Lands with the move. | Open. |

### 5.2 Cleanups that need ≥30 days of canary telemetry first

| Item | Track | Status |
|------|-------|--------|
| Delete `_review_step_output` (legacy critic body) | T9 | Reachable behind `critic_pipeline.v1_compat` (default OFF). Will be deleted ≥30d after canary completes. |
| Delete `MemoryRouter` body | T9 | Behind `memory.v2_canonical` (default ON; v1 path retained for rollback). |
| Delete `MetaReviewer` shim | T9 | 5-line shim still in tree. |
| Delete `CortexRouter` alias | T9 | Re-export shim still in tree. |
| `services/events.ts` typed reducer for the live AgentLoop iteration timeline (frontend) | FE-T9 | Events flow today; the typed-union exhaustiveness check is polish. |
| `P11*` prefix removal + back-compat shims (frontend) | FE-T9 | Component layout cleanup; defer until backend deletions complete. |

### 5.3 Functional items intentionally held back

| Item | Track | Reason | Audit finding |
|------|-------|--------|---------------|
| Meta-Agent template re-seed (`reseed_meta_agent.py`) | T5-4 | Needs UI + content review. | Open. |
| LLM "critic of critic" inside `meta_agent_prompt_evolution` | T5-7 | Cron plumbing live; LLM diff generation deferred. | Open — see `core/arq_jobs.py:meta_agent_prompt_evolution` (HITL-only). |
| Admin REST wrappers for skill candidates / promote-DRAFT / spec_critic / anti_patterns / prompt_candidates approve | T5-8, T8 | Thin wrappers around services. | **(✱ correction)** Already shipped in `phase11_router.py` — endpoints `meta/skill_candidates`, `meta/intelligence/anti_patterns`, `meta/intelligence/prompt_candidates` (+ `/approve`), `meta/skill_candidates/{id}/promote`, `meta/entities/{id}/promote`, `meta/spec_critic`. RETROSPECTIVE.md §3 should be updated. |
| Wire `CostLedger.add(...)` into every non-tool cost path (planner / critics / dreaming / embedding / meta_spec_critic / test_driver) | T8-7 | Ledger + enum ready; per-site plumbing is one-line each. | Open. `services/cost_attribution.py` exists; remaining call-sites need attribution arguments. |
| REACT-AFC inner closure adopting `ToolResilience.run(...)` inside `_execute_thought` | T8-3 | Bigger refactor. | **(✱ partial correction)** `DECISIONS.md` 2026-05-29 records that `tools.resilience_v2_enabled` is now default ON for **both** REACT and direct paths. The remaining work is the inner-closure refactor itself, not the unification. |
| `PlannerService.reconcile` full v2 swap | T7-6 | Only `adapt_plan` flipped. | Open — `planner_service.reconcile` still on v1 path. |
| `cost_estimator_refresh` nightly cron (telemetry-driven baselines) | T7-3 / T9 | Wanted ≥30 days of `tool_interaction_logs`. | **(✱ correction)** Implemented at `core/arq_jobs.py:902` with 20-sample / 30-day floor; runs in-process refresh on completion. RETROSPECTIVE.md §3 should be updated. |
| Grafana / Metabase panel JSON | T9-8 | Depends on chosen platform. | Open — SQL queries shipped under `infra/dashboards/phase11/`. |
| One-line CSAT (retrospective feedback collection) | — | New post-programme ask. | Open. |
| Storybook stories per `components/agent/*` (frontend) | FE | Polish. | Open. |
| Lighthouse CI wiring (frontend) | FE | Polish. | Open. |
| Playwright E2E nightly job (frontend) | FE | Polish. | Open. |

### 5.4 Decisions formally deferred (not "gaps")

* **LLM-driven Strategist** — explicit defer (`DECISIONS.md`
  2026-05-28). Deterministic Strategist meets G1.
* **Curator LLM consolidation** — flag
  `meta_agent.curator_consolidation_enabled` exists, defaults OFF.

---

## 6. Open canary watches

Per `STATUS.md`, the canary is observing three risks:

* **R-PRG-3** — Critic false-pass rate. Target ≤ 0.10 (baseline ~0.18).
* **R-PRG-5** — Critic cost share. Target ≤ 0.25 of run cost.
* **R-PRG-8** — Meta-Agent promotion REJECT rate. Trip = > 30% over a
  rolling 7-day window in canary.

All three are surfaced via `GET /api/v1/ai/phase11/admin/risks` and
the frontend `RiskAndExitPage`. KPI targets (goal hit rate,
re-plan rate, budget overshoot, token overhead, cost per success,
rule yield) live in `15_risk_register_and_acceptance.md §3` and are
all exposed on the dashboard.

---

## 7. Documentation drift to fix

Three corrections the audit found while comparing
`RETROSPECTIVE.md §3` to the code in tree:

1. **`cost_estimator_refresh`** is listed as deferred but is
   implemented at `core/arq_jobs.py:902`.
2. **Admin REST wrappers** for skill candidates / promote-DRAFT /
   spec_critic / anti_patterns / prompt_candidates approve are listed
   as deferred but are live in `phase11_router.py`.
3. **REACT-AFC unification** is listed as deferred but
   `DECISIONS.md` 2026-05-29 records the flag flip; only the
   inner-closure refactor inside `_execute_thought` remains.

Suggested edit: trim those three rows from
`RETROSPECTIVE.md §3` and add a one-line note explaining each was
completed during the canary tail.

---

## 8. Recommended next steps

In priority order, sized to a one-engineer week each unless noted:

1. **Tool subdomain `git mv`** (T8-5) — clean window now exists; ~30
   import-line follow-up + README refresh. Unblocks the `tools/`
   subdomain READMEs that depend on the new layout.
2. **Wire `CostLedger.add(...)` into non-tool cost sites** (T8-7) —
   planner, critics, dreaming, embedding, `meta_spec_critic`,
   `test_driver`. Required for `tools.cost_attribution_required` to
   default ON (the last canary flag).
3. **`PlannerService.reconcile` v2 swap** (T7-6) — mirrors the
   `adapt_plan` swap; same surface, same tests.
4. **`mypy --strict` kernel sweep** (T9-6) — ship as a tracked PR
   series so each PR is reviewable.
5. **Comment-narration sweep + promotion to error** (T9-1, T9-9) —
   139 mechanical hits.
6. **Per-company canary flip of `agent_loop.enabled`** — one company
   at a time, watch R-PRG-3 / R-PRG-5 / R-PRG-8.
7. **Per-company canary flip of `meta_agent.board_routing`** — same
   gating discipline; downstream gates (spec_critic, draft_lifecycle,
   testdriver, skill_promotion, prompt_evolution) are already ON.
8. **30-day watch, then legacy deletions** (T9-2/3/4/5) — once the
   above two have ≥30 days of zero traffic on the v1 paths,
   delete `_review_step_output`, `MemoryRouter` body, `MetaReviewer`
   shim, `CortexRouter` alias.
9. **Grafana / Metabase panel JSON** (T9-8) — once a dashboarding
   platform is picked.
10. **Frontend polish wave** — `P11*` prefix removal + Storybook +
    Lighthouse CI + Playwright nightly, as a single FE-T9 cleanup PR.

After step 8, Phase 11 is fully **exited** per the criteria in
`15_risk_register_and_acceptance.md §5`. Steps 9–10 are polish that
can run in parallel with the start of Phase 12 themes
(`RETROSPECTIVE.md §6`).
