# Frontend Track 9 — KPI Dashboard + Feature Flags Admin (parallel with backend T9)

> **Backend Track:** [`../11_track_9_hardening_and_kpi.md`](../11_track_9_hardening_and_kpi.md)
> **Owner:** Frontend engineer.
> **Duration:** 5 working days.
> **Behaviour change:** New admin Phase-11 KPI dashboard (6 pages),
>   Feature Flags admin page, onboarding tour, P11→canonical rename.
> **Risk:** Low.

---

## 1. Objectives (functional)

After Frontend Track 9:

1. New admin page **`/admin/kpi-dashboard`** with six sub-tabs:
   1. **Run Health** — goal hit rate, re-plan rate, budget overshoot.
   2. **Cost** — cost by attribution, cost per success, trend.
   3. **Critic** — verdict distribution, catch rate, false-pass rate,
      cost share.
   4. **Meta-Agent** — Curator decisions, promotion outcomes, anti-
      pattern growth, skill candidates.
   5. **Memory** — viewport bytes/step, dreaming runs, intelligence
      rule promotions, provenance coverage.
   6. **Loop telemetry** — iterations / run, resumes, bandit
      exploration vs exploit, arm distribution.
2. New admin page **`/admin/feature-flags`** to view, create, edit, and
   delete `feature_flags` rows. Filter by `scope` (global / company /
   entity).
3. **Onboarding tour** (a one-time guided overlay using framer-motion)
   for new admins explaining where the Phase-11 UI lives.
4. **`P11` prefix removed**: every component graduated to
   `components/agent/<Name>.tsx`, with re-export shims at the old
   `P11<Name>.tsx` paths kept for one release.
5. Sidebar nav refreshed: a single "AI Platform" group with the new
   pages grouped sensibly.
6. Layout-lint frontend equivalent (`scripts/check_no_p11_prefix.ts`)
   enforces "no new `P11*` files in `src/`" post-Track 9.

---

## 2. Scope

### In scope

* New pages:
  * `pages/admin/KPIDashboard.tsx` + six sub-pages.
  * `pages/admin/FeatureFlagsAdmin.tsx`.
  * `OnboardingTour` overlay component.
* `services/kpi.service.ts` for dashboard queries.
* `services/feature_flags.service.ts` admin methods.
* P11→canonical rename (with re-exports).
* Sidebar nav restructuring.
* CI lint script.

### Out of scope

* New metrics not already emitted by backend.
* Editing telemetry pipeline.
* Customising dashboards per role.
* Customising chart palette per tenant.

---

## 3. Architecture (technical)

### 3.1 KPI dashboard layout

A tabbed page using react-router nested routes:

```
/admin/kpi-dashboard           → redirects to /run-health
/admin/kpi-dashboard/run-health
/admin/kpi-dashboard/cost
/admin/kpi-dashboard/critic
/admin/kpi-dashboard/meta-agent
/admin/kpi-dashboard/memory
/admin/kpi-dashboard/loop
```

Each tab has the same layout: top filter bar (date range, company,
entity), N charts in a responsive grid, optional table.

### 3.2 Data sources

| Page | Backend endpoint |
|------|------------------|
| Run Health | `GET /admin/kpi/runs?since=...&company_id=...` |
| Cost | `GET /admin/kpi/cost?since=...&company_id=...` |
| Critic | `GET /admin/kpi/critic?since=...&company_id=...` |
| Meta-Agent | `GET /admin/kpi/meta_agent?since=...&company_id=...` |
| Memory | `GET /admin/kpi/memory?since=...&company_id=...` (NEW for FE-T9) |
| Loop | `GET /admin/kpi/loop?since=...&company_id=...` (NEW) |

These all query `kpi_daily_rollup` plus targeted aggregations.

### 3.3 Reusable chart components

* `KPILineChart` — single-line trend (recharts LineChart).
* `KPIStackedBarChart` — daily stacked bars (reused from FE-T8).
* `KPIDonut` — share-of-pie (used by Critic verdict distribution).
* `KPITopList` — top-N table with sortable columns.

### 3.4 Feature flags admin

```
/admin/feature-flags

[ Filter scope ▼ ]   [ Search flag key ]

┌─────────────────────────────────────────────────────────────┐
│ Flag key                  | Scope   | Value | Updated      │
│ agent_loop.enabled        | global  | true  | 2 days ago   │
│ agent_loop.enabled        | acme    | false | 5 min ago    │ [✎]
│ critic_pipeline.v2_enabled| global  | true  | 7 days ago   │
│ bandit.epsilon            | global  | 0.10  | 14 days ago  │ [✎]
└─────────────────────────────────────────────────────────────┘
[ + New flag override ]
```

Edit modal:

* Scope: global / company / entity.
* Key (dropdown of known flags).
* Value: boolean toggle OR free text for non-boolean (json_value).

On save: `POST /admin/feature_flags/set` (backend Track 13).

### 3.5 P11 prefix removal

For each `P11Foo.tsx`:

1. Move to `components/agent/Foo.tsx`.
2. Add a back-compat re-export:

   ```tsx
   // components/agent/P11Foo.tsx (legacy)
   export { Foo as P11Foo } from './Foo';
   ```

3. Codemod all imports in `pages/` to use `Foo`.
4. Layout-lint script asserts no new `P11*` filenames anywhere.

### 3.6 Onboarding tour

A small framer-motion overlay that runs once per admin user (gated by
`localStorage.phase11OnboardingSeen`). 4 steps:

1. Highlight the sidebar's new "Meta-Agent" section.
2. Highlight the AgentLoop iteration timeline on a sample run.
3. Highlight the KPI dashboard.
4. Highlight Feature Flags admin.

Skippable; resumable.

---

## 4. Detailed deliverables

### 4.1 FE-T9-1 — Services (Day 1 AM)

`services/kpi.service.ts`:

```ts
export const kpiService = {
  runHealth(filters): Promise<RunHealthResponse> { ... },
  cost(filters): Promise<CostResponse> { ... },
  critic(filters): Promise<CriticResponse> { ... },
  metaAgent(filters): Promise<MetaAgentKpiResponse> { ... },
  memory(filters): Promise<MemoryKpiResponse> { ... },
  loop(filters): Promise<LoopKpiResponse> { ... },
};
```

### 4.2 FE-T9-2 — KPI dashboard scaffolding (Day 1 PM)

* `pages/admin/KPIDashboard.tsx` with nested routes.
* Shared `KPIPageLayout` with FilterBar + grid.
* Shared chart components.

### 4.3 FE-T9-3 — Run Health page (Day 2 AM)

Three charts:

* Goal hit rate (LineChart, weekly).
* Re-plan rate + budget overshoot rate (combined LineChart).
* Iterations per run (BarChart histogram).

### 4.4 FE-T9-4 — Cost page (Day 2 PM)

* Daily stacked bar by attribution (StackedBarChart).
* Cost-per-success trend (LineChart).
* Top-20 expensive entities (TopList).

### 4.5 FE-T9-5 — Critic page (Day 3 AM)

* Verdict distribution (Donut, per stage).
* Catch rate vs false-pass rate (combined LineChart).
* Critic cost share (LineChart).

### 4.6 FE-T9-6 — Meta-Agent page (Day 3 PM)

* Promotion outcomes (StackedBarChart by week).
* Curator decisions (Donut).
* Anti-pattern count growth (LineChart).
* Skill candidates proposed/promoted (BarChart).

### 4.7 FE-T9-7 — Memory + Loop pages (Day 4)

* Memory: viewport bytes, dreaming runs, intelligence rule
  candidate→confirmed funnel.
* Loop: iterations/run histogram, resume count, bandit exploration
  rate, arm distribution.

### 4.8 FE-T9-8 — Feature Flags admin page (Day 4)

* List + filter + edit modal.
* `services/feature_flags.service.ts::list`, `::set`, `::delete`.

### 4.9 FE-T9-9 — P11 rename + lint (Day 5 AM)

* Codemod with `jscodeshift` to rename all `P11Foo` imports.
* Back-compat re-exports.
* Lint script asserts no new `P11` files.

### 4.10 FE-T9-10 — Onboarding tour (Day 5 PM)

* `components/onboarding/PhaseElevenTour.tsx`.
* Mount via top-level Layout effect.

### 4.11 FE-T9-11 — Tests + PR (Day 5 PM)

Per §9.

---

## 5. Database / schema changes

N/A (frontend).

---

## 6. API changes (consumed)

| Endpoint | Status |
|----------|--------|
| `GET /admin/kpi/runs` | NEW (backend T9) |
| `GET /admin/kpi/cost` | NEW (Track 8 / 9) |
| `GET /admin/kpi/critic` | NEW |
| `GET /admin/kpi/meta_agent` | NEW |
| `GET /admin/kpi/memory` | NEW |
| `GET /admin/kpi/loop` | NEW |
| `GET /admin/feature_flags` | NEW |
| `POST /admin/feature_flags/set` | NEW |
| `DELETE /admin/feature_flags/{id}` | NEW |

---

## 7. Telemetry events

None emitted from frontend.

---

## 8. Feature flags

The KPI dashboard itself is admin-gated (no flag); each KPI page
gracefully renders "no data" if its underlying flag has never been on.

---

## 9. Tests

### 9.1 Unit

* Each chart component renders with empty / loading / populated data.
* Filter bar correctly composes query params.
* Feature flag edit modal preserves scope on save.
* Onboarding tour can be dismissed and not re-shown.

### 9.2 Integration

* Open `/admin/kpi-dashboard` → six tabs render with mocked data.
* Open `/admin/feature-flags` → edit a flag → POST sent.
* Onboarding tour runs once for a fresh admin user.

### 9.3 E2E

* `kpi-dashboard.spec.ts` — switch tabs, change date range, confirm
  data updates.
* `feature-flags-admin.spec.ts` — create per-company flag override.

---

## 10. Acceptance criteria

1. KPI dashboard live with all six pages.
2. Feature flags admin lets admin toggle any Phase-11 flag.
3. P11 prefix removed (with shims).
4. Onboarding tour runs once for new admins.
5. Layout lint enforces no new `P11*` files.
6. Coverage ≥ 75% on new components.
7. Lighthouse a11y ≥ 90 on all new pages.

---

## 11. Effort (5 days)

| Day | Work |
|-----|------|
| 1 | services + scaffold |
| 2 | Run Health + Cost pages |
| 3 | Critic + Meta-Agent pages |
| 4 | Memory + Loop pages + Feature Flags admin |
| 5 | P11 rename + Onboarding tour + tests + PR |

---

## 12. Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Backend KPI endpoints not all ready by FE-T9 start | M | Empty dashboards | Mock data + feature-gate per page; backend can land endpoints incrementally |
| Codemod misses an import → broken build | M | Time loss | CI catches; small batches; one PR per Track of components |
| Onboarding tour annoying on second login | L | UX | Strict localStorage gating; admin reset button |
| Chart palette doesn't fit dark glass theme | L | Visual | Use existing CSS tokens; ban hard-coded colours in charts |

---

## 13. Dependencies

* **Upstream:** All prior FE Tracks (so the rename has all components
  in place), Backend T8/T9.
* **Downstream:** None.

---

## 14. Open questions

* Should the KPI dashboard be exportable (CSV/PNG)? **Phase 12**.
* Should non-admin users see a subset of KPIs (per-tenant Run Health)?
  **Decision:** yes — tenant admin sees Run Health and Cost for their
  own company; Critic/Meta-Agent/Memory/Loop remain app_admin.
