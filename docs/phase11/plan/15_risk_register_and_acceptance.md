# 15 — Risk Register and Acceptance KPIs (Cross-Cutting)

This is the **programme-level** risk register (cross-Track risks live
here; intra-Track risks live in each Track's §12) and the catalogue
of acceptance KPIs.

If a Track exits without satisfying its acceptance KPIs, this document
says it has not exited.

---

## 1. Programme-level risks

### 1.1 R-PRG-1 — Scope creep

| Field | Value |
|-------|-------|
| Description | New "while we're in there" work bleeds into Tracks, eating buffer |
| Likelihood | High |
| Impact | Programme slip 2-4 weeks |
| Mitigation | Each Track's §2 lists scope tightly. PRs that touch out-of-scope code blocked by reviewer. Non-goals listed in [`00_README.md`](./00_README.md) §2. |
| Owner | Tech lead |

### 1.2 R-PRG-2 — Insufficient parity test fidelity

| Field | Value |
|-------|-------|
| Description | Parity tests pass but production regressions appear during canary |
| Likelihood | Medium |
| Impact | Trust loss; flag flipped off; Track effectively rolled back |
| Mitigation | Three fixture types (SKILL, AGENT, PROCESS) at minimum. LLM-judge in regression suite. 48h canary watch before ramp. |
| Owner | Agent kernel engineer |

### 1.3 R-PRG-3 — LLM provider variance

| Field | Value |
|-------|-------|
| Description | Critic / planner LLM behaves differently across provider versions; recently-deployed model becomes worse |
| Likelihood | Medium |
| Impact | False-pass rate rises, planner suggests bad plans |
| Mitigation | Critic calibration job (Track 3) writes false-pass rate; alert on rise. Model overrides per task type via `IntegrationRegistry`. Pin minor versions where supported. |
| Owner | AI/ML engineer |

### 1.4 R-PRG-4 — Backfill migration on huge tenants

| Field | Value |
|-------|-------|
| Description | `p11t05_preserve_meta_cognition` or `p11t06_backfill_intelligence_status` runs slowly on tenants with many entities/nodes |
| Likelihood | Medium |
| Impact | Maintenance window extends; some tenants offline briefly |
| Mitigation | Run migrations in batches (limit 1000 rows per batch + sleep). Off-hours window. Communication. |
| Owner | Platform engineer |

### 1.5 R-PRG-5 — Cost rises before quality lift lands

| Field | Value |
|-------|-------|
| Description | Track 3 (Critic Pipeline) adds cost; Track 7 (Planner v2) is what brings cost back down — gap of 5 weeks |
| Likelihood | High |
| Impact | Customer complaints during weeks 5-10 |
| Mitigation | Per-Track cost tolerance widening listed in Track 3 (≤15%). Budget enforcement (Track 2) prevents unbounded blow-up. Customer comms ahead of canary ramp. |
| Owner | Tech lead + Product |

### 1.6 R-PRG-6 — Team availability

| Field | Value |
|-------|-------|
| Description | 1-2 engineer team; sick leave, holidays, or interrupts derail schedule |
| Likelihood | High |
| Impact | Programme slip |
| Mitigation | Track boundaries shipped independently. Roadmap (`../08_roadmap.md`) explicitly orders Tracks so partial completion is still valuable. Critical-path = Tracks 2 → 3 → 5. |
| Owner | Tech lead |

### 1.7 R-PRG-7 — Hidden dependency on legacy module

| Field | Value |
|-------|-------|
| Description | Production code, voice pipeline, or campaign worker imports a soon-to-be-deleted symbol |
| Likelihood | Medium |
| Impact | Worker boot fails after a Track 9 deletion |
| Mitigation | Telemetry watches imports / calls (Track 13). Deletion only after ≥30 days of zero calls. Layout-lint catches forbidden imports. |
| Owner | Platform engineer |

### 1.8 R-PRG-8 — Meta-Agent quality regression

| Field | Value |
|-------|-------|
| Description | Track 5 ships Board → new entities are *worse* than v3-produced entities |
| Likelihood | Medium |
| Impact | Existing customers see degraded generated agents |
| Mitigation | Canary 10-day window for Meta-Agent specifically. `meta_agent.board_routing` flag flip per company. Side-by-side comparative test in TestDriver suite. |
| Owner | AI/ML engineer |

### 1.9 R-PRG-9 — Frontend / API consumer breaks

| Field | Value |
|-------|-------|
| Description | Schema split, new endpoints, SSE event shape — a downstream consumer breaks |
| Likelihood | Low (wildcard re-exports + additive APIs) |
| Impact | UI bug |
| Mitigation | Schema re-export shim (Track 1). API endpoint additivity (no renames). SSE events ignored by old clients. |
| Owner | App platform engineer |

### 1.10 R-PRG-10 — Telemetry / dashboard cost

| Field | Value |
|-------|-------|
| Description | New event volume causes telemetry pipeline cost spike |
| Likelihood | Low-Medium |
| Impact | Ops cost rises |
| Mitigation | Event cardinality discipline (§13/2.2). Per-iteration events capped at 10. Per-step at 5. Sampling at high traffic. |
| Owner | Platform engineer |

---

## 2. Acceptance KPIs

These are the **programme-level KPIs**. They are tracked in the Track 9
dashboard. The programme exits successfully when *all* of them are at
or better than baseline at canary tenants for ≥14 days, and at
production tenants for ≥7 days.

### 2.1 Run-health KPIs

| KPI | Definition | Baseline (pre-Track 2) | Phase 11 target |
|-----|------------|------------------------|-----------------|
| `goal_hit_rate` | runs marked COMPLETED AND no user refinement AND no `meta_promotion.outcome=REJECT` upstream / Σ runs | TBD measure in Track 0 | +5pp |
| `re_plan_rate` | runs with ≥1 `agent.plan.replan` event / runs | Today: not measured | < 25% (avoid replan churn) |
| `budget_overshoot_rate` | runs where `Budget.pressure > 1.0` at finalize / runs | Today: ~ rare | ≤ 1% |
| `iterations_per_run_p50` | median iterations | n/a | within 50% of static-plan step count |
| `iterations_per_run_p95` | 95th pctile | n/a | within 3× of p50 |
| `agent_loop_resume_count` | runs that resumed via snapshot / day | n/a | low; presence proves resume works |

### 2.2 Critic KPIs

| KPI | Definition | Target |
|-----|------------|--------|
| `critic_catch_rate` | Σ `post_critic_verdict ∈ {REVISE, REJECT}` / Σ steps | ≥ 5% (catches *something* on average) |
| `critic_false_pass_rate` | (PASS verdicts → run later refined / flagged bad) / PASS verdicts | ≤ 15% (Track 3 calibration drives down) |
| `critic_block_rate` | Σ `pre_critic_verdict = BLOCK` / Σ pre-critic calls | 1-5% (signal of useful filtering) |
| `critic_cost_share` | Σ critic_cost / Σ total_run_cost | ≤ 25% |

### 2.3 Cost KPIs

| KPI | Definition | Target |
|-----|------------|--------|
| `cost_per_success` | Σ cost / runs_completed | ↓ ≥10% by end of programme |
| `cost_share_planner` | Σ cost (attribution=planner) / total | < 10% |
| `cost_share_critic_total` | Σ cost (attribution ∈ critic_*) / total | < 25% |
| `cost_share_tool` | Σ cost (attribution=tool) / total | tracking only |
| `cost_share_meta_agent` | Σ cost during Meta-Agent runs / total | tracking only |
| `prompt_token_overhead_per_step` | sum of fixed prompt overhead / sum of total prompt tokens | ↓ ≥10% after Track 6 |

### 2.4 Meta-Agent KPIs

| KPI | Definition | Target |
|-----|------------|--------|
| `meta_promotion_success_rate` | promotions/PROMOTED outcomes / promotions total | ≥ 60% (Meta-Agent decides "ship it" most of the time) |
| `meta_critic_block_rate` | spec_critic BLOCK verdicts / runs | tracking |
| `promoted_entity_first_run_success` | First real run of promoted entity → COMPLETED | ≥ 80% |
| `meta_intelligence_rules_added_per_week` | distinct anti-pattern nodes added / week | growing (≥1/week post-Track 5) |
| `skill_candidate_propose_rate` | candidates proposed / scan | tracking |
| `prompt_update_candidates_proposed_per_week` | per company | low (1-3) |

### 2.5 Memory KPIs

| KPI | Definition | Target |
|-----|------------|--------|
| `memory_assembly_p50_ms` | median latency of `MemoryAssemblyService.assemble_runtime_memory` | < 200ms |
| `dreaming_runs_per_week` | per entity, average | ≥ 1 for active entities |
| `intelligence_candidates_promoted_per_week` | confirmed rules added / week | ≥ 1 for active entities |
| `cortex_node_count_p95` | 95th percentile of nodes per tree | <2000 (bounded by checkpointing) |
| `provenance_coverage` | knowledge nodes with `provenance` block / total | ≥ 95% post-Track 6 |

### 2.6 Bandit KPIs

| KPI | Definition | Target |
|-----|------------|--------|
| `bandit_exploration_rate` | exploration_pulls / total_pulls | ε ± 5pp |
| `bandit_arm_convergence` | best arm chosen / total | rises with pulls; ≥ 0.7 after 50 pulls |
| `bandit_cost_per_success_delta` | cost_per_success of chosen arm vs uniform random | improvement ≥ 10% after 100 pulls per arm |

### 2.7 Infra KPIs

| KPI | Definition | Target |
|-----|------------|--------|
| `kpi_view_refresh_p95_seconds` | how long materialised view refresh takes | < 60s |
| `mypy_strict_passes` | binary | true at Track 9 exit |
| `layout_lint_violations` | int | 0 |
| `phase_narration_count` | grep hits for legacy comments | 0 |
| `feature_flags_count_active` | rows in `feature_flags` | trending down post-Track 9 |

---

## 3. Per-Track acceptance recap

Each Track exits when **its own** acceptance criteria (in the Track's
§10) are met AND it does not regress any KPI from §2 beyond the
tolerance in Track 13's rollout policy.

| Track | Exit gates (summary) |
|------:|----------------------|
| 0 | git status clean; layout lint green; smoke runs |
| 1 | schemas/orm packages exist; back-compat works; mypy strict on schemas/orm; FailureTag enum live |
| 2 | AgentLoop runs the 3 parity fixtures within ±5% cost / ≥0.85 similarity; resume from crash works |
| 3 | CriticPipeline catches an injected hallucination; critic_cost_share ≤25%; v1 retry loop gated off |
| 4 | SupervisorCritic replaces MetaReviewer; bandit converges on fixture entities; replan path live |
| 5 | spec_critic gates Meta-Agent runs; TestDriver suite live; preserve-migration ran; MetaIntelligenceTree growing |
| 6 | v2 memory canonical; prompt token overhead -10%; Reflector writes candidate rules; embedding from registry |
| 7 | 3 candidates generated per dynamic plan; invariants enforced; cost_per_success -10% on regression |
| 8 | Cost attribution column populated; one ToolResilience used by both code paths; experimental gating works |
| 9 | All legacy paths deleted; mypy strict on full kernel; KPI dashboard live; ONBOARDING ≤90 min |

---

## 4. Decision log

Tracked as a section in `docs/phase11/DECISIONS.md` (one-line entries
per decision). Examples to be filled as the programme runs:

```
2026-05-26  decision  agent_loop.snapshot_every_iteration default ON
              rationale: resume reliability outweighs CORTEX write cost
2026-06-15  decision  critic_model_override defaults: actor=Sonnet → critic=Opus
              rationale: regression suite shows 12pp catch rate improvement
2026-07-02  decision  postpone tool_synthesis to Phase 12
              rationale: out of scope; doesn't block Goal G2
```

---

## 5. Programme exit checklist

Phase 11 is **done** when all of the following hold:

- [ ] All 10 Tracks (T0-T9) have entered the "exit" state per Track §10.
- [ ] All Track 9 deletions have shipped (`_review_step_output`,
      `MemoryRouter`, `MetaReviewer`, `CortexRouter` alias,
      `_schemas_legacy.py`).
- [ ] `mypy --strict` clean on `core/`, `planning/`, `memory/`,
      `meta/`, `governance/`, `schemas/`, `orm/`, `tools/base.py`.
- [ ] Layout-lint green with no exception list.
- [ ] All Phase-11 feature flags either still operational knobs or
      deleted; no zombie flags.
- [ ] KPI dashboard live; six pages green.
- [ ] All five §2.1 run-health KPIs at or better than baseline for
      ≥7 days on production.
- [ ] All four §2.2 critic KPIs within target.
- [ ] All §2.3 cost KPIs within target.
- [ ] All §2.5 memory KPIs within target.
- [ ] At least 80% of §2.4 Meta-Agent KPIs within target (canary
      tolerance: 60%).
- [ ] Onboarding doc tested with one new engineer; ≤90 minutes.
- [ ] Retrospective written; Phase 12 backlog filed.

When this list is complete, file the closing PR with one commit
`phase11: programme complete` updating `docs/phase11/STATUS.md`
to `done`.

---

## 6. Phase 12 candidates (out-of-scope, parking lot)

Items surfaced during Phase 11 but explicitly deferred:

* LLM-driven Strategist (`Strategist.next_move` uses an LLM to pick
  among Move alternatives).
* Tool synthesis: Meta-Agent can propose new `Tool` subclasses.
* Cross-tenant skill marketplace.
* Reinforcement-learning over Strategist arms.
* Adaptive context-window allocation per step.
* External-tool MCP integration.
* `EpisodicMemory` table drop (30 days post-Track 6).
* `usage_logs` partitioning by month.
* Bandit as contextual bandit (features from `Perception`).
* `Provenance.trust_score` learned, not constant.
* `DomainTreeBase` absorbing section logic generically.
* Frontend "agent loop tracing" UI.
* Two-LLM debate / consensus for high-stakes critics.
* Cost-estimator refresh from telemetry (Track 7 deferred).
