# 08 — Roadmap

A prioritised, sized backlog. Built so that each lane is independently
shippable and each week ends with measurable lift.

> Effort signals: **S** = ≤2 days, **M** = 3-5 days, **L** = 1-2 weeks,
> **XL** = > 2 weeks.

---

## 0. Pre-flight (Week 1)

Goal: get the repo into a state where the rest of the work is mechanical.

| Item | Anchor | Effort | Exit |
|------|--------|--------|------|
| 0.1 `git rm` 20 ghost duplicate files | §02 / git status | S | `git status` clean, worker still boots |
| 0.2 Remove `worker.py` re-exports (`worker.py:48-67`) | `worker.py` | S | No `from src.ai.worker import …` anywhere |
| 0.3 Move `migrate_*.py` + `DeepResearchSetup/` + `SeedEntities/` to `backend/scripts/` | repo root | S | `src/ai/` has no migration scripts |
| 0.4 Rename `memory/cortex_service.py::CortexRouter` → `CortexService`, drop aliases | §02 / 2.3 | S | grep `as CortexService` → empty |
| 0.5 CI: file-layout linter (rules in §07/5) | new | S | CI red on layout violation |

**Exit**: branch passes CI; clean diff with no behavioural change.

---

## 1. Schema + ORM split (Week 2)

| Item | Effort | Notes |
|------|--------|-------|
| 1.1 Split `schemas.py` → `schemas/*.py` per §07 | M | All other imports unaffected via `schemas/__init__.py` |
| 1.2 Split `models.py` → `orm/*.py` | M | Same approach |
| 1.3 Introduce typed `HITLTrigger` (replace stringly-typed config) | S | `HITLTriggerType` already exists — wire it through |
| 1.4 Introduce typed `StepType` union for `PlanStep.type` (replace `Optional[str]`) | S | Validates LLM planner output earlier |
| 1.5 Add `failure_tags.py` enum in `planning/` | S | Pre-req for §05 critic work |

**Exit**: type-check pass on all touched modules.

---

## 2. AgentLoop foundation (Weeks 3-4)

Goal: introduce the new top-level loop *without* breaking today's
execution path. Existing entities use the legacy path; opt-in entities
use the new one.

| Item | Effort | Notes |
|------|--------|-------|
| 2.1 New `core/agent_state.py` (typed envelope) | S | dataclasses + asdict |
| 2.2 New `core/budget.py` | S | tracks tokens, USD, wallclock, iters |
| 2.3 New `core/agent_loop.py` skeleton | M | First version delegates to `ExecutionEngine.execute_run` |
| 2.4 Extract `core/executors/single_step.py` and `dag.py` | M | Lift verbatim from execution_engine + step_executor |
| 2.5 Extract `core/executors/recursive.py` | S | Lift recursive_engine |
| 2.6 Extract `core/executors/child_entity.py` | S | Lift from step_executor |
| 2.7 Extract `core/reasoning/{react,cot,reflection,tot}.py` | M | These live in step_executor today |
| 2.8 New `core/perceiver.py` (returns perception payload §03/4) | M | |
| 2.9 New `core/strategist.py` (thin: chooses executor by entity type) | S | LLM-driven version comes later |
| 2.10 New `core/observer.py` + `core/reflector.py` (skeletons) | S | |
| 2.11 Entity config: `execution.use_agent_loop = true` opt-in flag | S | Behind feature flag |
| 2.12 Smoke test: one PROCESS + one AGENT on agent_loop, parity vs legacy | M | Run side-by-side in staging |

**Exit**: Same input produces semantically equivalent output via either
path; cost within ±5%.

---

## 3. Critic Pipeline v2 (Week 5)

| Item | Effort | Notes |
|------|--------|-------|
| 3.1 New `planning/critic_pipeline.py` (pre/post/align/super) | M | Wire all four into AgentLoop |
| 3.2 `StepHealthRecord` dataclass + CORTEX persistence | S | New subtree per run |
| 3.3 Critic uses *different* model than actor (configurable) | S | Default to "stronger" model |
| 3.4 Structured `failure_tags` from critic JSON | S | uses §1.5 enum |
| 3.5 Replace `_review_step_output` retry path (eliminate same-model+feedback loop) | M | Use Strategist to pick retry strategy |
| 3.6 Critic budget cap (`governance.critic_cost_share_pct`) | S | |
| 3.7 Calibration job: weekly false-positive rate per task class | S | Cron + IntelligenceTree write |

**Exit**: Run a hard regression suite — expect higher catch rate at lower
total cost.

---

## 4. Meta-Review v2 + GoalGuard merge (Week 6)

| Item | Effort | Notes |
|------|--------|-------|
| 4.1 Rewrite `core/meta_review.py` to consume `AgentState` + reflections (no more last-5-steps prompt) | S | |
| 4.2 Fold step-level alignment into CriticPipeline.align stage (kill duplicate path) | S | Removes the dual GoalGuard sites |
| 4.3 Add `expected_value` / `expected_cost` fields to Strategist `Move` output | S | Used in Pre-Critic |
| 4.4 Bandit-style exploit/explore over plan styles per task class | M | uses Intelligence Tree priors |

**Exit**: A clearly drifting run is aborted within `goal_validation_interval`
± 1 step in ≥80% of synthetic test cases.

---

## 5. Meta-Agent board v4 (Weeks 7-8)

| Item | Effort | Notes |
|------|--------|-------|
| 5.1 New `tools/meta/spec_critic.py` + `MetaIntelligenceTree` model | M | The single sharpest one-week fix (§04/10) |
| 5.2 Update Meta-Agent system prompt to call `meta_spec_critic` between BUILD and TEST | S | |
| 5.3 New `meta/board/test_driver.py` — suite runner (smoke/comparative/boundary/regression/hostile) | L | replaces one-shot `meta_entity_executor` |
| 5.4 New `meta/board/curator.py` — REUSE/ADAPT/COMPOSE/CREATE + consolidation proposals | M | wraps existing RegistrySearchService + AntiSprawlGuard |
| 5.5 Split Architect role into its own prompt; Critic uses different model | M | uses §3.3 infra |
| 5.6 `meta/board/promoter.py` + DRAFT → ACTIVE workflow | M | gates + audit row |
| 5.7 Skill library: detect repeated chains in episodic memory; propose promotion | L | new background job |

**Exit**: New Meta-Agent runs end with ≥1 MetaIntelligence rule per run
in 80% of cases. Promotion gate active.

---

## 6. Memory v2 canonicalisation (Week 9)

| Item | Effort | Notes |
|------|--------|-------|
| 6.1 `memory/assembler.py` → v2-only; v1 = `legacy_episodic_reader.py` | S | |
| 6.2 Move `CORTEX_OPERATIONS_PROMPT` out of viewport; into system prompt once | S | Saves ~10% prompt tokens per step |
| 6.3 `DomainTreeBase` refactor; collapse 4 services | M | |
| 6.4 Typed `Provenance` on knowledge nodes | S | |
| 6.5 `ScopePolicy` on `CortexService` | S | |
| 6.6 Dreaming triggers from outcomes (not just cron) | S | |
| 6.7 Reflector → IntelligenceTree candidate-rule write path | S | hooks into §3 reflections |
| 6.8 Embedding model from IntegrationRegistry per company | M | finally close the F-04-era bug |

**Exit**: One memory pipeline; no `MemoryRouter.retrieve` calls outside
the legacy adapter; embedding model configurable.

---

## 7. Planner with priors (Week 10)

| Item | Effort | Notes |
|------|--------|-------|
| 7.1 `planning/plan_invariants.py` (cycle, dangling refs, cost feasibility) | S | |
| 7.2 Inject IntelligenceTree rules into dynamic-planner system prompt | S | |
| 7.3 Multi-candidate plan generation (N=3) + scoring | M | |
| 7.4 LLM-judge between top-2 candidates for ambiguous cases | S | |
| 7.5 Plan-style track record per task class (writes to IntelligenceTree) | S | |
| 7.6 `child_resolver.py` consolidation (one entity_id-resolution function) | S | |

**Exit**: avg cost per success drops ≥10% on the regression suite without
quality loss.

---

## 8. Tool + cost consolidation (Week 11)

| Item | Effort | Notes |
|------|--------|-------|
| 8.1 `governance/tool_cost_resolver.py` — single charge entry point | S | kills the verbatim duplicate in step_executor |
| 8.2 `tools/resilience.py` — reformat-retry + fallback in one place; used by both direct TOOL_CALL and REACT paths | M | |
| 8.3 Cost telemetry by attribution (planner / step / critic / reformat / meta-review / dreaming) | S | new column on UsageLog |
| 8.4 Tool registry audit: ACTIVE / EXPERIMENTAL / DEAD tags | S | gate EXPERIMENTAL with feature flag |
| 8.5 Reorganise `tools/` into subgroups per §07 | S | |

**Exit**: Cost dashboard breaks down cost per attribution; experimental
tools cannot be invoked without a flag.

---

## 9. Hardening + DX (Week 12)

| Item | Effort | Notes |
|------|--------|-------|
| 9.1 Type-check pass (`mypy --strict`) on `core/`, `planning/`, `memory/`, `meta/`, `governance/` | M | |
| 9.2 Remove "Phase N" / "Fix N" narration comments | S | |
| 9.3 Document all `INTERNAL_CONTEXT_KEYS` with purpose, lifecycle, who writes/reads | S | |
| 9.4 README per top-level package (`core/`, `planning/`, etc.) | M | |
| 9.5 KPI dashboard: goal-hit, plan-adherence, re-plan rate, critic catch rate, cost per success, budget overshoot, reflection persistence | M | Grafana or similar |
| 9.6 Public "agent loop tracing" view in UI (iteration / perception / decision / action / observation / reflection) | L | Optional but valuable |

**Exit**: Onboarding doc for a new contributor takes <90 minutes from
clone to first PR.

---

## P2 / P3 backlog (post Week 12)

| Item | Why later |
|------|-----------|
| Multi-agent debate (two-LLM consensus, jury) | Once Critic Pipeline data is in, decide if extra LLM is worth it |
| Tool synthesis (NL → new Tool subclass) | Higher infra burden; Voyager-grade; revisit after skills work |
| Cross-tenant skill marketplace | Product call |
| External-tool MCP integration | Strategic, depends on platform direction |
| Reinforcement-learning over Strategist | Needs ≥3 months of telemetry first |
| Adaptive context-window allocation per step | Nice-to-have; modest cost lift |

---

## How to track this

Open one parent issue per Week-N block above. Each item maps 1:1 to a
sub-issue with the exit criterion as the acceptance test. Each PR
references its sub-issue.

For weeks 0-6, the work is largely **structural / mechanical** — the wins
are clarity, not yet autonomy. Weeks 7-10 deliver the autonomy lift
(Meta-Agent v4 + Critic Pipeline + Planner priors). Weeks 11-12 lock in
the gains with cost/observability.

The full programme is ~12 calendar weeks for a focused 2-person crew, or
~16 weeks for one person working alongside other commitments.

---

## Where the biggest single weeks land

If you have only **6 focused weeks**, do these in order:

1. **Week 0** — pre-flight cleanup
2. **Week 5** — Critic Pipeline v2 (changes outcomes immediately)
3. **Week 7-8** — Meta-Agent board v4 (changes the trajectory of every
   future agent)
4. **Week 3-4** — AgentLoop foundation (changes the ceiling on what's
   possible)

These four weeks alone move the platform from "an opinionated DAG executor
with a prompt-engineered Meta-Agent" to "an autonomous agent platform that
learns and improves."

The rest is cleanup, calibration, and DX.
