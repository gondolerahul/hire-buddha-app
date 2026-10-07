# Phase 11 — Retrospective

> **Programme dates:** Week 1 → Week 12 (12 elapsed weeks).
> **Author:** Phase 11 implementation team.
> **Status:** Tracks 0 – 9 landed; selected items intentionally
> deferred to Phase 12 (listed in §3).

---

## 1. What landed

### Track 0 — Pre-flight cleanup (Week 1)
* `lint_ai_layout.py` script enforcing file-size caps + transitional
  allow-list + forbidden imports / aliases (and, from Track 9,
  comment-narration patterns in warn mode).

### Track 1 — Schemas + ORM split (Week 2)
* `backend/src/ai/schemas/*` and `backend/src/ai/orm/*` packages.
* `FailureTag` closed enum.
* Typed `PlanStep.type` (`StepType` enum) with lenient string coercion.

### Track 2 — AgentLoop foundation (Weeks 3-4)
* `AgentLoop.run(run_id)` orchestrator + perceive → strategize →
  pre-critic → act → observe → post-critic → reflect → decide cycle.
* Typed `AgentState`, `Budget`, `Subgoal`, `Hypothesis`, `Blocker`,
  `Action`, `Observation`, `Reflection`, `Verdicts`.
* Seven executor adapters (`DAG`, `Recursive`, `SingleStep`,
  `ChildEntity`, stubs for `Dialog`, `ToolBurst`, `Skill`).
* Four reasoning modes extracted to `core/reasoning/`.
* `FeatureFlags` service + `agent_loop.enabled` master switch.
* Parity test harness against legacy `ExecutionEngine.execute_run`.

### Track 3 — Critic Pipeline v2 (Week 5)
* `RealCriticPipeline` with four stages (pre / post / alignment /
  supervisor) sharing one `StepHealthRecord`.
* Different-model resolver (`resolve_critic_model` heuristic ladder).
* Deterministic `pick_retry` (FailureTag → RetryStrategy).
* `🩺 Health` CORTEX subtree per run for audit.
* Weekly `critic_calibration_job` Arq cron.
* Legacy `_review_step_output` gated behind `critic_pipeline.v1_compat`.
* `GoalGuard` reduced to a shim into `AlignmentCritic`.

### Track 4 — Meta-Review v2 + Bandit (Week 6)
* `SupervisorCritic.assess(state)` with budget-pressure short-circuit
  and 3-clean-step fast path.
* `PlanStyleBandit` (ε-greedy, per-`(entity_id, task_class)` arm state
  persisted in IntelligenceTree under `🎯 Strategies`).
* `TaskClassifier` v1 rule-based + optional v2 embedding NN.
* REPLAN path: Strategist replaces open subgoals; AgentLoop kicks
  PlannerService.adapt_plan.
* `MetaReviewer` reduced to a 5-line shim.

### Track 5 — Meta-Agent Architecture Board (Weeks 7-8)
* `MetaIntelligenceTree` per company (6 sections, LRU-pruned).
* `meta_spec_critic` tool — different-model spec quality critic.
* Board roles: `RequirementChat` → `Curator` → `Architect` →
  `BoardCritic` → `ValidatorRole` → `TestDriver` → `Promoter`.
* `resolve_meta_cognition` opt-in flip + preserve-migration helper.
* `SkillLibrary` chain detector + weekly `skill_promotion_scan` cron.
* `meta_agent_prompt_evolution` cron (HITL-gated; LLM critic-of-critic
  itself deferred to Phase 12).

### Track 6 — Memory v2 canonicalisation (Week 9)
* `memory_pipeline="v2"` is the default; v1 is opt-in only.
* `LegacyEpisodicReader` for first-run top-up.
* Viewport `to_prompt_text(include_ops_help=False, max_chars=4000)`
  with sectioned rendering + truncation marker; ops-help moved into
  `build_sandwich_prompt(cortex_enabled=True)`.
* `DomainTreeBase` + per-domain retrieval weights
  (Knowledge / Episodic / Experience / Intelligence).
* `Provenance` schema + plumbed into `CortexService.write`.
* `ScopePolicy` + `ScopeViolation`; descendant cache.
* `Reflector` scope escalation (run → entity on learnable signal);
  persists candidate Strategy nodes.
* `dreaming_outcome_trigger` Arq job from `AgentLoop._finalize`.
* `resolve_embedding_model(db, company_id)` standalone helper.

### Track 7 — Planner v2 + Invariants (Week 10)
* `child_resolver.resolve_child_entity_id(...)` is the single source of
  truth for the four-strategy resolution (UUID, static-plan name match,
  hierarchy index, name-hint DB lookup).
* `plan_invariants.validate_plan(plan, entity, budget)` runs eight
  deterministic checks.
* `cost_estimator` baselines for tools + model factors.
* `PlanGenerator` (varied-temperature parallel candidates, invariant
  filter, repair fallback, judge-based selection).
* `PlanJudge` with cost-based tiebreak.
* `PlannerService.adapt_plan` → v2 shim.

### Track 8 — Tool & cost consolidation (Week 11)
* `usage_logs.attribution` column + `CostLedger` + `CostAttribution` enum.
* `ToolCostResolver` — one cached service replacing two duplicated
  60-line cost-lookup blocks in `step_executor.py`.
* `ToolResilience` + `FailureKind` + `classify_tool_failure` — shared
  reformat-retry + fallback chain.
* `ToolStatus` + `ToolRegistry.get_visible_tools_for_company(...)` —
  EXPERIMENTAL tools require `tools.experimental.{tool_id}` opt-in.
* `step_executor._execute_tool_call` refactored to delegate behind
  `tools.cost_resolver_v2_enabled` + `tools.resilience_v2_enabled`.

### Track 9 — Hardening + KPI dashboard (Week 12)
* `lint_ai_layout.py` extended with comment-narration patterns (warn
  mode; promotion to error deferred — see §3).
* Per-package READMEs (`core/`, `planning/`, `memory/`, `meta/`,
  `governance/`, `tools/`).
* `core/INTERNAL_KEYS.md` documents every key in `INTERNAL_CONTEXT_KEYS`.
* `backend/src/ai/ONBOARDING.md` walks a new engineer to a first PR.
* `kpi_daily_rollup` materialised view + hourly `kpi_rollup_refresh`
  cron.
* Six dashboard SQL query files under `infra/dashboards/phase11/`.

### Test posture

The unit suite grew from `185` tests at Track 2 baseline to **`420+`**
across Tracks 3-8 (43 + 35 + 37 + 43 + 51 + 34 net new in Tracks
3 / 4 / 5 / 6 / 7 / 8 respectively). 0 regressions through every track.

---

## 2. KPI deltas (expected; canary observation in progress)

The Track 9 dashboards will surface the real numbers once enough data
accumulates. Designed targets per `15_risk_register_and_acceptance.md`:

| KPI | Direction | Baseline (Track 2) | Target (Track 9) |
|-----|-----------|--------------------|------------------|
| `goal_hit_rate` | ↑ | ~0.72 | ≥ 0.78 |
| `re_plan_rate` | balanced | ~0.05 | 0.04–0.10 |
| `budget_overshoot_rate` | ↓ | ~0.12 | ≤ 0.06 |
| `false_pass_rate` | ↓ | ~0.18 | ≤ 0.10 |
| `prompt_token_overhead_per_step` | ↓ | 1.00 | ≤ 0.90 |
| `critic_cost_share` | bounded | n/a | ≤ 0.25 |
| `cost_per_success` | ↓ | 1.00 | ≤ 0.85 |
| `intelligence_rule_yield_per_run` | ↑ | 0 | ≥ 1 / 5 runs |

The dashboards expose every one of these directly.

---

## 3. What slipped (Phase 12 backlog)

| Item | Track | Reason for deferral |
|------|-------|---------------------|
| Meta-Agent template re-seed (`reseed_meta_agent.py`) | T5-4 | Requires UI coordination + content review. |
| Admin REST endpoints for skill candidates, promote-DRAFT, ad-hoc spec_critic, intelligence/anti_patterns, intelligence/prompt_candidates approve | T5-8, T8 | Thin route wrappers around already-implemented services. |
| LLM "critic of critic" inside `meta_agent_prompt_evolution` | T5-7 | The cron scaffolding lays the plumbing; LLM-driven diff generation deferred to focused P2 work. |
| Tool subdomain `git mv` (`core/`, `documents/`, `media/`, `sandbox/`, `email/`, `crm/`, `integrations/social,ads/`, `management/`) | T8-5 | Mechanical move that touches ~30 import lines; held until a clean window. |
| Wiring `CostLedger.add(...)` into every non-tool cost path (planner / critics / dreaming / embedding / meta_spec_critic / test_driver) | T8-7 | Ledger + attribution enum are ready; per-site plumbing is one-line each. |
| REACT-AFC inner closure inside `_execute_thought` adopting `ToolResilience.run(...)` | T8-3 | Bigger refactor to keep separate from T8-4. |
| `mypy --strict` full kernel sweep | T9-6 | Time-boxed in the plan; ~100 small fixes will produce a tracked PR series. |
| Comment-narration sweep to 0 hits + lint promotion to error | T9-1, T9-9 | 139 hits surfaced in warn mode; mechanical follow-up. |
| Deletion of `_review_step_output`, `MemoryRouter` body, `MetaReviewer` shim, `CortexRouter` alias | T9-2, T9-3, T9-4, T9-5 | Each requires ≥30 days of telemetry proving the flag is OFF in prod — defer to post-canary. |
| Subdomain README refresh after `git mv` | T8 / T9 | Together with the `git mv`. |
| `cost_estimator_refresh` nightly cron (telemetry-driven baseline updates) | T7-3 / T9 | Track 7 ships hardcoded baselines; the cron lands once we have ≥30 days of `tool_interaction_logs`. |
| `PlannerService.reconcile` full v2 swap | T7-6 | Only `adapt_plan` flips in Track 7; `reconcile` retained for the planner-usage logging path. |
| Grafana / Metabase panel JSON | T9-8 | SQL queries committed; panel JSON depends on the chosen platform. |
| One-line CSAT (RETROSPECTIVE feedback collection) | — | New ask, post-programme. |

None of the deferred items are load-bearing for the canary rollout —
the implemented surface is complete enough to ship Tracks 0-8 to
production under the existing feature-flag rollout discipline.

---

## 4. Recommended owners / on-call

| Module | Suggested owner |
|--------|-----------------|
| `core/agent_loop.py` + the loop primitives | Agent-kernel engineer (existing) |
| `planning/critic_pipeline.py` + `supervisor_critic.py` + `plan_*` | Agent-kernel engineer (existing) |
| `meta/board/*` + `meta_intelligence_tree.py` + `skill_library.py` | AI/ML engineer |
| `memory/*` + `cortex_service.py` + dreaming | Agent infra engineer |
| `governance/tool_cost_resolver.py` + `services/cost_attribution.py` | Platform / cost engineer |
| `tools/resilience.py` + `tools/base.py` + tool registry | Platform / cost engineer |
| KPI dashboards (`infra/dashboards/phase11/*.sql`) | Whoever owns observability |
| `lint_ai_layout.py` + per-package READMEs | Tech lead |

On-call rotation: the agent-kernel engineer is primary for the loop and
the critic pipeline (the two highest-impact modules); the platform
engineer is primary for cost and tool issues.

---

## 5. Programme-level lessons

* **Time-boxing legacy deletions paid off.** The Phase 11 programme
  shipped without removing a single load-bearing legacy code path.
  Every legacy path is gated behind a flag; deletions are scheduled
  for ≥30 days post-canary.
* **Additive base classes won over rewrites.** `DomainTreeBase`
  (Track 6) added a typed weight contract without forcing the four
  legacy domain services to subclass; new code can adopt incrementally.
* **Pure-function modules are testable.** `plan_invariants`,
  `cost_estimator`, `retry_strategies`, `child_resolver`,
  `classify_tool_failure`, `score_signals` all hit ≥90 % branch
  coverage trivially because they have no I/O.
* **Per-track unit-test density.** Tracks 3-8 averaged ~37 new tests
  each. The full suite ended at **`420+`** tests with 0 regressions.
* **Feature flags must default ON for new code.** The pattern that
  worked was: ship the new code path ON by default with the legacy
  branch reachable behind an opt-in flag for rollback safety. The
  inverse (new code OFF by default) creates a dead code path that
  drifts before it ever runs.

---

## 6. Phase 12 candidate themes (sketch)

* **DomainTreeBase migration** of the four legacy memory services.
* **LLM-driven Strategist** (currently deterministic).
* **Cross-tenant skill / intelligence sharing** (currently per-company).
* **Reinforcement learning over plan style selection** (currently bandit).
* **Tool synthesis from natural language**.
* **MCP / external tool integration**.
* **Multi-model critic pipeline ("third model" tiebreak)**.
* **Per-iteration contextual bandit** (currently per-run averaged).
* **Auto-promotion of skill candidates under per-company trust level**.
* **Provenance trust-score learning** (currently constant per source type).
