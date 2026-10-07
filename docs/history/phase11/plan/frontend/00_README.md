# Phase 11 — Frontend Implementation Plan

> **Scope:** Every UI change required by the Phase 11 backend tracks.
> **Stack target:** React 18 + TypeScript 5 + Vite + react-router-dom 6 +
>   axios + react-flow + recharts + framer-motion + lucide-react +
>   react-hook-form + zod (the existing stack at
>   `frontend/package.json`).
> **Companion docs:** the ten backend Track files in `../`. Each frontend
>   Track here mirrors the backend Track of the same number; a backend
>   change without a frontend implication is explicitly marked **"no UI
>   change"** so we don't lose track.

---

## How to use this plan

* Frontend Tracks land **in parallel with** their backend counterparts —
  start the day after the backend Track's API surface stabilises.
* Every frontend Track is gated behind the **same feature flag** as its
  backend Track. UI degrades gracefully when the flag is OFF: old run
  shape continues to render exactly as today.
* Frontend uses a single typed API surface (`@/services/api.client.ts`)
  and a typed event surface (`@/services/events.ts` — NEW). Adding a new
  endpoint or event means updating these two files first, then the
  consumer page.

---

## Document index

| # | File | Backend Track | What it covers |
|---|------|--------------:|----------------|
| 00 | [`00_README.md`](./00_README.md) | — | This index + conventions + glossary |
| 01 | [`01_overview_and_principles.md`](./01_overview_and_principles.md) | — | Frontend north-star, principles, type system, SSE event handling, design tokens |
| 02 | [`02_track_0_preflight.md`](./02_track_0_preflight.md) | T0 | no UI change (frontend lint / scripts cleanup only) |
| 03 | [`03_track_1_schemas_and_types.md`](./03_track_1_schemas_and_types.md) | T1 | `types/index.ts` split, codegen pipeline, typed enums (`StepType`, `FailureTag`, `HITLTriggerType`) |
| 04 | [`04_track_2_agent_loop_ui.md`](./04_track_2_agent_loop_ui.md) | T2 | AgentState side-panel, Budget bar, iteration timeline, resume indicator, SSE event refactor |
| 05 | [`05_track_3_critic_pipeline_ui.md`](./05_track_3_critic_pipeline_ui.md) | T3 | StepHealthRecord rows, FailureTag chips, retry-strategy badges, critic cost share gauge |
| 06 | [`06_track_4_meta_review_ui.md`](./06_track_4_meta_review_ui.md) | T4 | Supervisor verdict card, replan diff viewer, bandit arm visualisation per (entity, task_class) |
| 07 | [`07_track_5_meta_agent_ui.md`](./07_track_5_meta_agent_ui.md) | T5 | Meta-Agent Board view, DRAFT entity lifecycle, skill candidates panel, anti-patterns browser, prompt-update HITL queue |
| 08 | [`08_track_6_memory_v2_ui.md`](./08_track_6_memory_v2_ui.md) | T6 | Provenance ribbons on CORTEX nodes, trust-score badges, dreaming history, intelligence candidate→confirmed lifecycle |
| 09 | [`09_track_7_planner_priors_ui.md`](./09_track_7_planner_priors_ui.md) | T7 | Plan candidates compare view, invariant-violation indicators, judge rationale |
| 10 | [`10_track_8_tool_and_cost_ui.md`](./10_track_8_tool_and_cost_ui.md) | T8 | Tool status badges, experimental tool admin panel, cost-by-attribution dashboard |
| 11 | [`11_track_9_kpi_dashboard_ui.md`](./11_track_9_kpi_dashboard_ui.md) | T9 | Phase-11 KPI dashboard pages (run health / cost / critic / meta-agent / memory / loop) |
| 12 | [`12_cross_cutting_components.md`](./12_cross_cutting_components.md) | all | Shared components, hooks, utilities introduced for the programme |
| 13 | [`13_feature_flags_and_rollout.md`](./13_feature_flags_and_rollout.md) | all | Frontend feature-flag handling + admin UI + rollout discipline |
| 14 | [`14_test_strategy.md`](./14_test_strategy.md) | all | Unit (Vitest/RTL), e2e (Playwright), visual regression, accessibility |
| 15 | [`15_risk_and_acceptance.md`](./15_risk_and_acceptance.md) | all | Risk register + acceptance KPIs (UX latency, error rate, a11y) |

---

## 1. Backend-changes-to-UI map (quick reference)

| Backend Track | Frontend Track | New pages / panels |
|---------------|----------------|--------------------|
| T0 Pre-flight | T-FE-0 | — (no UI change) |
| T1 Schemas/ORM | T-FE-1 | `types/` codegen + typed enums; no visible UI change |
| T2 AgentLoop | T-FE-2 | **ExecutionDetail** revamped: AgentState pane, Budget bar, iteration timeline, Reflections list; SSE handler refactor |
| T3 Critic Pipeline | T-FE-3 | **StepHealthRecord** strip on each step; **FailureTag** chip palette; **critic cost share** indicator |
| T4 Meta-Review + Bandit | T-FE-4 | Supervisor verdict card; **BanditState** admin panel; Replan diff modal |
| T5 Meta-Agent Board | T-FE-5 | **Meta-Agent Board** view (role timeline); **DRAFT** entity badge; **Skill Candidates** panel; **Anti-Patterns** browser; **Prompt-Update Approval** queue |
| T6 Memory v2 | T-FE-6 | **Provenance ribbon** on CORTEX nodes; **trust-score** badges; **Intelligence rule** candidate→confirmed lifecycle |
| T7 Planner v2 | T-FE-7 | **Plan Candidates** compare modal; invariant-violation badge in plan view; judge rationale tooltip |
| T8 Tool + Cost | T-FE-8 | **Tool status** badges in EntityBuilder; **Experimental tool** admin toggle; **Cost-by-Attribution** dashboard |
| T9 Hardening + KPI | T-FE-9 | **Phase-11 KPI Dashboard** (6 pages); admin **Feature Flags** page; onboarding tour |

---

## 2. Goals

| # | Frontend goal | Maps to backend goal |
|---|---------------|----------------------|
| FE-G1 | Render the new autonomous loop as a first-class UX (iterations, budget, reflections) rather than a flat step list | G1 |
| FE-G2 | Give admins full visibility into the Meta-Agent Board: every role's verdict + the Promoter decision + the MetaIntelligence growth | G2 |
| FE-G3 | Surface the Critic Pipeline's structured verdicts and retry choices so quality work is visible, not hidden | G3, G4 |
| FE-G4 | Show memory as a navigable, trust-aware substrate (provenance, candidate-rule lifecycle, viewport occupancy) | G5 |
| FE-G5 | One typed surface (`api.client.ts` + `events.ts`) — no ad-hoc fetches; no untyped events | G6 |
| FE-G6 | KPI dashboard that proves Phase 11 worked — visible to tenant admins and platform admins | G1, G3, G8 |
| FE-G7 | Per-level meta-cognition toggles in EntityBuilder reflect new opt-in defaults | G7 |
| FE-G8 | Budget pressure is a real-time UX element, not buried in logs | G8 |

---

## 3. Non-goals

* Visual brand refresh — keep the existing GlassCard / JellyButton design language.
* New layout system. `MainLayout` and its sidebar/breadcrumb stay as-is.
* Mobile-first re-flow. The dashboard pages are desktop-grade; defer responsive polish.
* Internationalisation (i18n). Strings stay English-only this programme.
* Migrating away from CSS files to a CSS-in-JS lib. Existing per-component `.css` files continue.
* New auth / RBAC story. Existing `useAuth` + role gating stays.

---

## 4. Conventions

### 4.1 File paths

* `frontend/src/pages/...` — route-level components.
* `frontend/src/components/...` — reusable building blocks.
* `frontend/src/services/...` — API + SSE clients.
* `frontend/src/types/...` — typed contracts.
* `frontend/src/hooks/...` — custom hooks.

Track files name files **relative to `frontend/src/`** unless otherwise
noted.

### 4.2 New shared component naming

Phase-11 components are prefixed with `P11` until promoted to standard
reusable widgets at Track 9. Examples:

* `P11AgentStatePanel.tsx`
* `P11BudgetBar.tsx`
* `P11StepHealthStrip.tsx`
* `P11CriticVerdictChip.tsx`
* `P11RoleTimeline.tsx`
* `P11ProvenanceRibbon.tsx`
* `P11PlanCandidatesCompare.tsx`

At Track 9 they drop the `P11` prefix and move under
`frontend/src/components/agent/` as the canonical agent-kernel widgets.

### 4.3 Feature flag access

A single hook:

```tsx
const enabled = useFeatureFlag('agent_loop.enabled', { defaultValue: false });
```

Flags are loaded once at app boot via `GET /api/v1/feature_flags/me`
and refreshed on a Redis pubsub fan-out (via WebSocket — see Track 13).

### 4.4 SSE event contract

Every SSE event the backend emits has a TypeScript discriminated union
in `services/events.ts`:

```ts
type AgentEvent =
  | { type: 'iteration_start'; iteration: number; executor: ExecutorName; budget_pressure: number; open_subgoals: number }
  | { type: 'iteration_end'; iteration: number; outcome: 'success'|'partial'|'fail'; decision: 'CONTINUE'|'DONE'|'PAUSE_HITL'|'ABORT'; cost_iter_usd: string }
  | { type: 'resume'; from_iteration: number }
  | { type: 'critic_pre'; iteration: number; verdict: 'PASS'|'BLOCK'|'REVISE'; concerns?: string[] }
  | { type: 'critic_post'; iteration: number; verdict: 'PASS'|'REVISE'|'REJECT'; tags: FailureTag[]; suggestion?: string }
  | ...;
```

A central reducer (`useExecutionEvents`) consumes the union and
maintains a derived state object (`{ iterations, healthRecords,
banditChoices, reflections, supervisorVerdicts }`).

### 4.5 API client style

`services/api.client.ts` keeps the existing axios instance. New
endpoints add **typed methods** to per-domain services:

```ts
// services/agent.service.ts (NEW)
export const agentService = {
  getAgentState(runId: string): Promise<AgentStateResponse> { ... },
  getHealthRecords(runId: string): Promise<StepHealthRecord[]> { ... },
  getPlanCandidates(runId: string): Promise<PlanCandidatesResponse> { ... },
  getBanditState(entityId: string, taskClass: string): Promise<BanditState> { ... },
  ...
};
```

No new fetch lib introduced.

### 4.6 Form validation

All new forms use `react-hook-form` + `zod` schemas (already in the
deps). Each zod schema lives next to its form component.

---

## 5. Glossary (UI-side terms)

| Term | Meaning |
|------|---------|
| **AgentState pane** | Sidebar / collapsible panel inside ExecutionDetail showing live AgentState |
| **Iteration card** | One card per iteration in the timeline; replaces the legacy step list when agent loop is on |
| **StepHealthStrip** | Compact row at the bottom of each iteration card with pre/post/align/super verdicts |
| **Budget bar** | Horizontal multi-segment progress bar (tokens / USD / wall / iters) |
| **Reflections list** | Right-rail list of structured reflections produced this run |
| **Bandit panel** | Admin view of per-(entity, task_class) plan-style arm scores |
| **Role timeline** | Meta-Agent–specific timeline: RequirementChat → Curator → Architect → Critic → Validator → TestDriver → Promoter |
| **Anti-Patterns browser** | List + filter of MetaIntelligence anti-patterns |
| **Skill Candidates panel** | List of proposed reusable SKILL chains with a promote action |
| **Prompt-Update queue** | HITL approval queue for Meta-Agent prompt evolution candidates |
| **Provenance ribbon** | Small badge on a CORTEX node showing source / trust score |
| **Plan Candidates compare** | Modal showing the 2-3 candidates the planner generated, with the winner highlighted |

---

## 6. Definition of done (frontend)

The frontend portion of Phase 11 is **done** when:

1. Every backend SSE event has a TypeScript type in `services/events.ts`.
2. Every new backend endpoint has a typed method in the appropriate
   service file.
3. The ExecutionDetail page renders the new AgentLoop UX when the
   `agent_loop.enabled` flag is on for the run, AND renders the legacy
   step list when it's off.
4. The Meta-Agent Board view exists and shows every role's verdict for
   a Meta-Agent run.
5. The Phase 11 KPI dashboard exists with all six pages.
6. Admin can flip every Phase-11 feature flag from the Feature Flags
   admin page.
7. All new components have `*.test.tsx` files (Vitest + React Testing
   Library) with ≥75% coverage.
8. Playwright smoke runs end-to-end for the Meta-Agent create flow and
   the AgentLoop iteration flow.
9. `npm run lint` and `npm run build` pass with no warnings on the
   frontend kernel.
10. Lighthouse a11y ≥ 90 on all new pages.

---

## 7. Effort estimate (rough)

| Frontend Track | Effort | Notes |
|----------------|-------:|-------|
| FE-0 | 0.5 day | Lint / scripts cleanup |
| FE-1 | 2 days | Codegen pipeline + types refactor |
| FE-2 | 5 days | Largest single Track; ExecutionDetail revamp |
| FE-3 | 3 days | StepHealthStrip + chips + critic cost gauge |
| FE-4 | 3 days | Verdict card + bandit panel + replan diff |
| FE-5 | 8 days | Meta-Agent Board view + DRAFT lifecycle + skill / anti-pattern / prompt panels |
| FE-6 | 3 days | Provenance + trust UI + candidate-rule lifecycle |
| FE-7 | 3 days | Plan candidates compare + invariant indicators |
| FE-8 | 4 days | Tool badges + experimental admin + cost dashboard |
| FE-9 | 5 days | KPI dashboard pages + feature flags admin + onboarding tour |
| Cross-cutting | 3 days | Tests + a11y + visual polish |

**Total:** ~40 working days for one frontend engineer, or ~25 days for
two engineers working in parallel on independent Tracks.

The frontend work runs **behind** the backend by ~3-5 days per Track so
the API surface has stabilised before the UI lands. Aim to ship each
frontend Track within the same 2-week canary window as its backend
Track.

---

## 8. Where to start

If you have a single frontend engineer and **two days**:

1. Read [`01_overview_and_principles.md`](./01_overview_and_principles.md).
2. Spike the typed SSE event surface (`services/events.ts`) — even
   without backend events live, you can drive the reducer with
   fixtures.
3. Read [`04_track_2_agent_loop_ui.md`](./04_track_2_agent_loop_ui.md)
   and prototype `P11AgentStatePanel`.

Those three steps make every subsequent frontend Track much faster.
