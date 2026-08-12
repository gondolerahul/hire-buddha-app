# Frontend Track 8 — Tool & Cost UI (parallel with backend T8)

> **Backend Track:** [`../10_track_8_tool_and_cost.md`](../10_track_8_tool_and_cost.md)
> **Owner:** Frontend engineer.
> **Duration:** 4 working days.
> **Behaviour change:** Tool status badges everywhere; admin panel for
>   experimental tools; cost-by-attribution dashboard.
> **Risk:** Low.

---

## 1. Objectives (functional)

After Frontend Track 8:

1. **Tool status badges** (`ACTIVE`/`EXPERIMENTAL`/`DEPRECATED`)
   appear on every tool in:
   * `ToolManagement` page.
   * `EntityBuilder` tool selector.
   * `Tools` API explorer.
2. **`EXPERIMENTAL`** tools are hidden from non-admin tool selectors
   unless the per-company opt-in flag is set.
3. New admin page **`/admin/experimental-tools`** lists every
   experimental tool with a per-company toggle.
4. New admin page **`/admin/cost-attribution`** shows cost broken down
   by attribution (planner / actor_step / critic_* / tool / etc.) per
   run / per entity / per company / time window.
5. The Run header gets a **cost-by-attribution mini-chart** (sparkline
   stacked bar).
6. **Tool resilience events** (`tool_reformat_attempt`,
   `tool_fallback_taken`, `tool_final_empty`) annotate the
   corresponding step row with a small icon + tooltip.

---

## 2. Scope

### In scope

* New components:
  * `P11ToolStatusBadge`
  * `P11ResilienceIndicator` (inline icon on step row)
  * `P11CostBreakdownChart` (stacked bar via recharts)
  * `P11CostBreakdownTable`
  * `P11AttributionPill`
* New pages:
  * `pages/admin/ExperimentalTools.tsx`
  * `pages/admin/CostAttribution.tsx`
* Augment `ToolManagement` and `EntityBuilder` tool-selectors.
* Reducer extension for resilience events.
* New service: `services/cost.service.ts`.
* Updated `services/tool.service.ts` to filter experimental on the
  client when the company has not opted in (defensive; the backend
  already filters).

### Out of scope

* Tool synthesis from NL (Phase 12).
* Tool registry editing from the UI (admin uses the existing
  `ToolManagement` page; we add badges only).

---

## 3. Architecture (technical)

### 3.1 Tool status badge

```tsx
<P11ToolStatusBadge status={tool.status} />
```

| Status | Icon | Colour |
|--------|------|--------|
| ACTIVE | `<CheckCircle2 />` | green |
| EXPERIMENTAL | `<FlaskConical />` | amber |
| DEPRECATED | `<XCircle />` | slate |

In EntityBuilder, hovering an EXPERIMENTAL tool shows a tooltip:
"Experimental — enable for your company in Admin → Experimental Tools."

If the user is not admin, selection is disabled.

### 3.2 Experimental tools admin page

```
/admin/experimental-tools

[ Filter by category ▼ ]   [ Search ]

┌────────────────────────────────────────────────────────────────┐
│ video_generation        EXPERIMENTAL                            │
│ category: media | cost: ~$0.05/call                             │
│ [ ☐ enabled for ACME Corp ]   [ ☑ enabled for Globex ]          │
│ recently used by 2 companies                                    │
└────────────────────────────────────────────────────────────────┘
...
```

Each row shows the tool + a list of company toggles (admin sees their
own company; app_admin sees all companies).

### 3.3 Cost attribution dashboard

```
/admin/cost-attribution

[ Window: 7d ▼ ]   [ Company ▼ ]   [ Entity ▼ ]

┌─────────────────────────────────────────────────────────────┐
│  Stacked bar by day (planner / actor / critic / tool / …)  │
│                                                              │
│  (recharts StackedBarChart)                                 │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│  Table — top 20 runs by cost                                │
│  run_id | entity | total | breakdown   ...                  │
└─────────────────────────────────────────────────────────────┘
```

Data from `GET /admin/kpi/cost?since=7d` (Track 11 admin endpoints
that wrap `usage_logs.attribution`).

### 3.4 Resilience indicators

Inside `P11IterationCard` step rows:

* `tool_reformat_attempt` → small `<Wand2 />` icon at the right of
  the step row.
* `tool_fallback_taken` → `<Shuffle />`.
* `tool_final_empty` → `<AlertOctagon />`.

Tooltip on each shows the originating tool / failure_kind / the
substituted tool.

### 3.5 Run header micro-chart

A 60px-wide stacked bar (recharts) showing the live cost breakdown
for the current run. Hover → tooltip with absolute numbers.

---

## 4. Detailed deliverables

### 4.1 FE-T8-1 — `services/cost.service.ts` (Day 1 AM)

```ts
export const costService = {
  async getRunBreakdown(runId: string): Promise<CostBreakdown> {
    const { data } = await apiClient.get(`/runs/${runId}/cost_attribution`);
    return data;
  },
  async getCompanyBreakdown(companyId: string, since: string = '7d')
    : Promise<CompanyCostBreakdown> {
    const { data } = await apiClient.get(
      `/companies/${companyId}/cost_attribution`, { params: { since } });
    return data;
  },
};
```

### 4.2 FE-T8-2 — `P11ToolStatusBadge` + integration (Day 1 PM)

* Add to `ToolManagement` row.
* Add to EntityBuilder tool selector (with hover tooltip + disabled
  state for EXPERIMENTAL when not opted-in).
* Tool listing API now returns `status`; consume.

### 4.3 FE-T8-3 — Experimental tools admin page (Day 2)

```tsx
// pages/admin/ExperimentalTools.tsx
const ExperimentalTools: React.FC = () => {
  const { data: tools, isLoading } = useExperimentalTools();
  const { user } = useAuth();
  const isAppAdmin = user.role === 'app_admin';

  return (
    <Page title="Experimental Tools">
      <FilterBar />
      {tools.map(t => (
        <Card key={t.tool_id}>
          <P11ToolStatusBadge status={t.status} />
          <h3>{t.tool_id}</h3>
          <p>{t.description}</p>
          {(isAppAdmin ? t.companies : [user.company_id]).map(cid => (
            <ToggleRow key={cid}
                       companyId={cid}
                       enabled={t.enabledByCompany[cid] ?? false}
                       onToggle={(v) => toolAdminService.setExperimental(t.tool_id, cid, v)}
            />
          ))}
        </Card>
      ))}
    </Page>
  );
};
```

Endpoint: `POST /api/v1/admin/tools/{tool_id}/experimental` with body
`{enabled: bool, company_id?: string}`.

### 4.4 FE-T8-4 — Cost attribution dashboard (Day 3)

* `P11CostBreakdownChart` — recharts stacked bar.
* `P11CostBreakdownTable` — top-N runs by cost.
* Filters: window, company (app_admin), entity.
* Drill-in: click a bar segment → filter table to that attribution.

### 4.5 FE-T8-5 — Resilience indicators in iteration cards (Day 4 AM)

* Reducer extension:
  ```ts
  case 'tool_reformat_attempt': { /* attach to step row */ }
  case 'tool_fallback_taken': { /* attach + show 'from→to' */ }
  case 'tool_final_empty': { /* attach warning */ }
  ```
* Step row component renders inline icons.

### 4.6 FE-T8-6 — Run header micro-chart (Day 4 PM)

* Tiny stacked bar fed by `costService.getRunBreakdown(runId)`.
* For RUNNING runs: derives from observed `cost_charged` events; for
  TERMINAL runs: fetches from endpoint.

### 4.7 FE-T8-7 — Tests + PR (Day 4 PM)

Per §9.

---

## 5. Database / schema changes

N/A (frontend).

---

## 6. API changes (consumed)

| Endpoint | Status | Where used |
|----------|--------|------------|
| `GET /api/v1/tools` (extended `status` field) | extended | `tool.service` |
| `POST /api/v1/admin/tools/{tool_id}/experimental` | NEW | `tool.service.setExperimental` |
| `GET /api/v1/runs/{run_id}/cost_attribution` | NEW | `cost.service.getRunBreakdown` |
| `GET /api/v1/companies/{company_id}/cost_attribution` | NEW | `cost.service.getCompanyBreakdown` |
| SSE stream | extended (tool_*, cost_charged) | events |

---

## 7. Telemetry events

None emitted from frontend.

---

## 8. Feature flags (consumed)

| Flag | Effect |
|------|--------|
| `tools.cost_resolver_v2_enabled` | Without → cost dashboard may be sparse (no attribution column populated) |
| `tools.resilience_v2_enabled` | Without → resilience icons never appear |
| `tools.experimental.{tool_id}` | Per-company; toggled via admin page |

---

## 9. Tests

### 9.1 Unit

* `P11ToolStatusBadge` renders three states.
* Tool selector hides EXPERIMENTAL when not opted-in.
* `P11CostBreakdownChart` renders all attributions in order.
* Reducer absorbs the three tool resilience events.
* Admin toggle POSTs the correct payload.

### 9.2 Integration

* Render EntityBuilder for a non-admin user with no opt-in → no
  EXPERIMENTAL tools listed.
* Render `/admin/experimental-tools` as app_admin → all companies shown
  with toggles.
* Render `/admin/cost-attribution` → chart renders for fixture data.

### 9.3 E2E

* `tool-experimental.spec.ts` — admin opts company in to
  `video_generation`; non-admin user can now see it in EntityBuilder.
* `cost-attribution.spec.ts` — open dashboard; switch window from 7d
  to 30d; chart re-renders.

---

## 10. Acceptance criteria

1. Status badges visible on every tool listing.
2. Experimental tools admin page toggles persist.
3. Cost attribution dashboard renders breakdown.
4. Resilience indicators inline on step rows.
5. Run header micro-chart shows breakdown.
6. Coverage ≥ 75% on new components.
7. Lighthouse a11y ≥ 90.

---

## 11. Effort (4 days)

| Day | Work |
|-----|------|
| 1 AM | cost.service.ts + types |
| 1 PM | ToolStatusBadge + integrations |
| 2 | Experimental tools admin page |
| 3 | Cost attribution dashboard |
| 4 AM | Resilience indicators in step rows |
| 4 PM | Run header micro-chart + tests + PR |

---

## 12. Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Stacked bar chart hard to read for many attributions | M | UX | Group rare attributions into "Other" if % < 2 |
| Toggling experimental tool fails mid-action | L | UI flicker | Optimistic update + rollback on error |
| Mini-chart per run too noisy in ExecutionHistory list | L | Visual density | Show only on the detail page, not the list |
| Backend not yet populating attribution for older runs | M | Empty breakdown | Empty-state CTA: "No attribution data — older run" |

---

## 13. Dependencies

* **Upstream:** FE-T2, FE-T3, Backend T8.
* **Downstream:** FE-T9 KPI dashboard reuses CostBreakdownChart.

---

## 14. Open questions

* Should we surface the **tool_fallback** as a separate, more prominent
  block (e.g. a "Resilience timeline" panel)? **Phase 12** — for now,
  inline icons suffice.
* Should non-admin users see the cost attribution dashboard for their
  own runs? **Decision:** yes for tenant admins on their own
  company's data; the global dashboard is app_admin only.
