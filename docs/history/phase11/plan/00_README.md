# Phase 11 — Techno-Functional Implementation Plan

> **What this is:** the *executable* version of the Phase 11 review.
> Each document below is a sprint-ready implementation packet:
> functional goals, technical design, file-level deliverables, DB / API /
> telemetry changes, feature flags, tests, acceptance criteria, and a
> day-by-day breakdown.
>
> **What this is not:** the architectural review. For *why* we are doing
> any of this, read [`../00_README.md`](../00_README.md) and the eight
> review files it indexes.

---

## How to use this plan

* Each **Track** corresponds to a contiguous block of weeks in
  [`../08_roadmap.md`](../08_roadmap.md).
* Every Track file has the **same structure** (see §3 below) so anyone
  can pick up a Track without re-reading the whole plan.
* Cross-cutting topics (database, API, observability, tests, risk) live
  in the `12_…` to `15_…` files. Track files reference them via anchors
  rather than duplicating.
* Every file path in this plan is given **relative to the repo root**
  (e.g. `backend/src/ai/core/agent_loop.py`).
* Every function signature is given in **Python 3.11+ style** with full
  type hints. They are *design intent*, not literal source text — the
  implementer may rename or refactor inside the same shape.

---

## Document Index

| # | File | Track / Topic | Weeks |
|---|------|---------------|------:|
| 00 | [`00_README.md`](./00_README.md) | This index | — |
| 01 | [`01_overview_and_principles.md`](./01_overview_and_principles.md) | North-star architecture, principles, glossary, conventions | — |
| 02 | [`02_track_0_preflight.md`](./02_track_0_preflight.md) | **Track 0** — Pre-flight cleanup (ghost files, CI lint, renames) | 1 |
| 03 | [`03_track_1_schemas_and_orm.md`](./03_track_1_schemas_and_orm.md) | **Track 1** — `schemas.py` → `schemas/` package; `models.py` → `orm/`; typed enums | 2 |
| 04 | [`04_track_2_agent_loop.md`](./04_track_2_agent_loop.md) | **Track 2** — AgentLoop, AgentState, Budget, Executors, Reasoning extract | 3-4 |
| 05 | [`05_track_3_critic_pipeline.md`](./05_track_3_critic_pipeline.md) | **Track 3** — CriticPipeline v2, StepHealthRecord, retry strategies | 5 |
| 06 | [`06_track_4_meta_review_goalguard.md`](./06_track_4_meta_review_goalguard.md) | **Track 4** — Meta-Review v2 + GoalGuard merge + plan-style bandit | 6 |
| 07 | [`07_track_5_meta_agent_board.md`](./07_track_5_meta_agent_board.md) | **Track 5** — Meta-Agent v4 architecture board + MetaIntelligenceTree + SkillLibrary | 7-8 |
| 08 | [`08_track_6_memory_v2.md`](./08_track_6_memory_v2.md) | **Track 6** — Memory v2 canonical, DomainTreeBase, Provenance, ScopePolicy | 9 |
| 09 | [`09_track_7_planner_priors.md`](./09_track_7_planner_priors.md) | **Track 7** — PlanGenerator v2, PlanInvariants, ChildResolver, multi-candidate plans | 10 |
| 10 | [`10_track_8_tool_and_cost.md`](./10_track_8_tool_and_cost.md) | **Track 8** — ToolCostResolver, ToolResilience, registry audit, cost attribution | 11 |
| 11 | [`11_track_9_hardening_and_kpi.md`](./11_track_9_hardening_and_kpi.md) | **Track 9** — Type-check, comment cleanup, READMEs, KPI dashboard | 12 |
| 12 | [`12_data_model_and_migrations.md`](./12_data_model_and_migrations.md) | Cross-cutting — all DB migrations gathered in one place | all |
| 13 | [`13_observability_feature_flags_rollout.md`](./13_observability_feature_flags_rollout.md) | Cross-cutting — telemetry events, feature flags, rollout discipline | all |
| 14 | [`14_test_strategy.md`](./14_test_strategy.md) | Cross-cutting — unit / integration / regression / canary / chaos | all |
| 15 | [`15_risk_register_and_acceptance.md`](./15_risk_register_and_acceptance.md) | Cross-cutting — risks, mitigations, exit KPIs per track | all |
| FE | [`frontend/00_README.md`](./frontend/00_README.md) | **Frontend implementation plan** — mirrors every backend Track with corresponding UI work | all |

> **Reading order if you are the tech lead:** 01 → 02 → 04 → 05 → 07 →
> 13 → 15. The rest is owners' material.
>
> **If you own the frontend:** start at
> [`frontend/00_README.md`](./frontend/00_README.md). The frontend
> plan has its own per-Track structure mirroring the backend Tracks.

---

## 1. Goals of this programme (recap from review)

| # | Goal | Measured by |
|---|------|-------------|
| G1 | Turn the linear plan-executor into a **true autonomous loop** with explicit state, budget, perception, strategy, action, observation, reflection. | KPI: `goal_hit_rate`, `re_plan_rate`, `budget_overshoot_rate` — see §15 |
| G2 | Upgrade the Meta-Agent from "one prompt + 5 tools" to a **multi-role architecture board** that learns from its own outputs. | KPI: `meta_intelligence_rules_added`, `promoted_entity_first_run_success` |
| G3 | Make the **critic** non-trivially correct: separate-model, structured failure tags, calibrated, budget-bounded, cost-aware. | KPI: `critic_catch_rate`, `critic_false_pass_rate`, `critic_cost_share` |
| G4 | **Unify the four checking layers** (step critic, alignment, GoalGuard, MetaReview) into one CriticPipeline that shares a `StepHealthRecord`. | KPI: # of LLM calls per step in supervisor path drops; pass-rate consistency rises |
| G5 | Pick **memory v2** as canonical, retire v1, fix the viewport prompt bloat. | KPI: `prompt_token_overhead_per_step` drops ≥10% |
| G6 | Replace **hidden hierarchies of side files** with a single clean package layout (`core/`, `planning/`, `memory/`, `meta/`, `governance/`, `tools/`, `api/`, `schemas/`, `orm/`, `services/`). | KPI: `mypy --strict` passes on the agent kernel; layout CI lint green |
| G7 | **Per-hierarchy-level meta-cognition** that is opt-in for sprawl risks and on-by-default for awareness. | KPI: # of unsanctioned self-modifications → 0 |
| G8 | First-class **Budget** + **Reflection** so the agent learns and respects its own constraints. | KPI: `cost_per_success`, `intelligence_rule_yield_per_run` |

These are the only goals. Every Track maps to at least one. A task that
does not map to a Goal is out of scope.

---

## 2. Non-goals for this programme

Explicitly **not** in scope (do not let scope creep eat the plan):

1. New external integrations (no new social platforms, no new ad
   networks, no new LLM providers).
2. UI redesign. The "agent loop tracing" UI (item 9.6 in the roadmap) is
   optional and gated behind a separate engineering effort.
3. Voice / campaign pipelines. They sit in `services/`; we touch them
   only to keep imports working.
4. New tools (except a small number of *meta* tools listed in Track 5).
5. Reinforcement-learning over the Strategist. Too early.
6. Cross-tenant skill sharing. Product decision pending.
7. Tool synthesis from natural language. Listed as P3 — not in this 12-week
   window.

---

## 3. The Track-file template

Every Track file follows this exact structure:

```
1. Objectives (functional)         — what the user / operator gets
2. Scope                           — in scope / out of scope
3. Architecture (technical)        — picture + key types + sequence
4. Detailed deliverables           — file-by-file, with signatures
5. Database / schema changes       — alembic migrations referenced
6. API changes                     — new/changed endpoints + SSE events
7. Telemetry events                — new event names + payloads
8. Feature flags                   — name + default + rollout plan
9. Tests                           — unit / integration / regression
10. Acceptance criteria            — concrete pass/fail
11. Effort breakdown               — day-by-day for one engineer
12. Risks                          — what can blow up, mitigation
13. Dependencies                   — which Tracks/items must land first
```

Tracks that do not need a section (e.g. no DB change) write "N/A —
unaffected" rather than skipping it.

---

## 4. Conventions used throughout the plan

### 4.1 File path notation

* `backend/src/ai/core/agent_loop.py` — full path from repo root.
* `core/agent_loop.py` — same file, abbreviated inside a Track that has
  already established `backend/src/ai/` as the current working package.

### 4.2 Symbol notation

* `AgentLoop.run(...)` — class method.
* `assemble_memory(...)` — module-level function.
* `core/budget.py::Budget` — class lookup pattern when path matters.

### 4.3 Type-hint style

```python
async def run(self, run_id: UUID) -> RunResult: ...
```

Type hints are **load-bearing** in this plan. If a snippet says
`Optional[X]`, it means the caller MUST handle the `None` branch.

### 4.4 "MUST / SHOULD / MAY"

Capitalised modal verbs follow RFC 2119:

* **MUST** — non-negotiable, CI / tests enforce.
* **SHOULD** — strongly preferred default; deviations require comment.
* **MAY** — implementer's choice.

### 4.5 Feature-flag naming

`{track}.{feature}` with snake_case, e.g.:

* `agent_loop.enabled`
* `critic_pipeline.different_model_critic`
* `meta_agent.board_routing`

All flags are read through one central `FeatureFlags` service (defined
in [13_observability_feature_flags_rollout.md](./13_observability_feature_flags_rollout.md))
so they show up in one place in admin UI.

### 4.6 Migration naming

Alembic migrations are named with the Track prefix:

`backend/migrations/versions/p11t<NN>_<slug>.py`

e.g. `p11t02_schema_split_compat.py`, `p11t03_step_health_record.py`.

### 4.7 Telemetry event naming

`agent.{layer}.{verb}` with dot-separated segments, e.g.:

* `agent.loop.iteration_start`
* `agent.critic.post_action_verdict`
* `agent.memory.cortex_write`

All events use the same envelope defined in
[13_observability_feature_flags_rollout.md §2](./13_observability_feature_flags_rollout.md).

---

## 5. Definition of Done (programme-level)

The Phase 11 programme is done when **all** of the following hold:

1. The `git status` is clean of ghost duplicates (Track 0 exit).
2. `backend/src/ai/` matches the layout in
   [`../07_folder_restructure.md`](../07_folder_restructure.md).
3. The new `AgentLoop` runs in production for at least one PROCESS-type
   entity, behind a feature flag, with parity ±5% on the regression suite.
4. The Critic Pipeline is the only critic path in production. No
   call site of `_review_step_output` survives.
5. The Meta-Agent's `meta_spec_critic` runs on every Meta-Agent
   execution and writes to the MetaIntelligenceTree.
6. `memory_pipeline = "v2"` is the only value seen by any new entity.
   `MemoryRouter.retrieve` is unreachable except through
   `legacy_episodic_reader`.
7. The KPI dashboard (Track 9) shows ≥ baseline on every red KPI.
8. `mypy --strict` clean on `core/`, `planning/`, `memory/`, `meta/`,
   `governance/`.
9. Onboarding doc walks a new engineer from clone to first PR in
   ≤ 90 minutes (Track 9 deliverable).

Items 3-6 are the **functional** acceptance. Items 1-2 and 7-9 are the
**technical** acceptance.

---

## 6. Glossary (skim before diving in)

| Term | Meaning |
|------|---------|
| **AgentLoop** | The new top-level autonomous control loop. Replaces `ExecutionEngine.execute_run` as the orchestrator. |
| **AgentState** | Typed envelope: open subgoals, budget, hypotheses, reflections, cortex cursor. |
| **Budget** | First-class object: tokens / USD / wallclock / iterations remaining. |
| **Executor** | One of `DAG`, `Recursive`, `SingleStep`, `ChildEntity`, `Dialog`, `ToolBurst`, `Skill`. Strategist picks one per iteration. |
| **Strategist** | The "what next" decider. Today implicit; new module in Track 2. |
| **CriticPipeline** | Pre-action + post-action + alignment + supervisor critics sharing a `StepHealthRecord`. |
| **StepHealthRecord** | One row per executed step capturing every critic's verdict, structured tags, costs, latency. Persisted in CORTEX. |
| **MetaAgent Board** | Multi-role Meta-Agent v4: RequirementChat / Architect / Critic / Validator / Curator / TestDriver / Promoter. |
| **MetaIntelligenceTree** | Platform-scoped IntelligenceTree owned by the Meta-Agent. Holds anti-patterns, plan priors, tool reliability. |
| **SkillLibrary** | Per-entity repository of promoted reusable plans (Voyager-style). |
| **DomainTreeBase** | Refactor base class for the four memory-domain services. |
| **Provenance** | Structured source-tracking block on every CORTEX knowledge node. |
| **ScopePolicy** | Read/write policy for subtree-scoped CortexService instances. |
| **PlanGenerator v2** | Multi-candidate planner that uses priors, runs invariants, and consults Intelligence rules. |
| **PlanInvariants** | Deterministic checks (cycle, capability, budget feasibility) run before execution. |
| **ChildResolver** | Single function that resolves dropped `entity_id`s in `CHILD_ENTITY_INVOCATION` steps. Used by both planner and executor. |
| **ToolCostResolver** | Consolidated tool-cost lookup against `IntegrationRegistry`. |
| **ToolResilience** | Reformat-retry + fallback chain in one place; used by both direct TOOL_CALL and REACT paths. |

---

## 7. What to look at *first*

If you are the tech lead and have **20 minutes**:

1. Skim §1, §2, §5, §6 of this README.
2. Read [`01_overview_and_principles.md`](./01_overview_and_principles.md)
   end-to-end (it has the architecture pictures).
3. Skim the **Objectives** + **Architecture** sections of Tracks 2, 3, 5
   (the three highest-leverage tracks).
4. Skim [`13_observability_feature_flags_rollout.md`](./13_observability_feature_flags_rollout.md)
   for how we will roll out safely.
5. Skim [`15_risk_register_and_acceptance.md`](./15_risk_register_and_acceptance.md)
   for what could blow up.

That's enough to staff and schedule the work. Owners can then deep-read
their own Track.
