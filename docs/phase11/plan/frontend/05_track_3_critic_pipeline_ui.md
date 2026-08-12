# Frontend Track 3 — Critic Pipeline UI (parallel with backend T3)

> **Backend Track:** [`../05_track_3_critic_pipeline.md`](../05_track_3_critic_pipeline.md)
> **Owner:** Frontend engineer.
> **Duration:** 3 working days.
> **Behaviour change:** Step health, critic verdicts, retry strategy
>   visible inside `P11IterationCard`.
> **Risk:** Low-Medium.

---

## 1. Objectives (functional)

After Frontend Track 3:

1. Each `P11IterationCard` shows a **StepHealthStrip** at the bottom:
   the four critic verdicts (pre / post / alignment / supervisor) as
   chips.
2. **FailureTag chips** appear under the post-verdict when REVISE /
   REJECT. Each chip has severity tint, icon, tooltip with the LLM's
   suggestion.
3. A **retry strategy badge** (e.g. "Retry: DIFFERENT_MODEL") appears
   when the loop queued a retry after the post-critic verdict.
4. A **critic cost share** indicator appears in the run header (small
   gauge: "Critic: $0.04 / $0.12 = 33%").
5. Admin-only **Health Records browser** (`GET /executions/{id}/health_records`)
   accessible from a debug button on the ExecutionDetail page.
6. The `critic_pipeline.v2_enabled` flag is plumbed (mirrors backend
   default).

---

## 2. Scope

### In scope

* Extend `useExecutionEvents` reducer with `critic_pre`, `critic_post`,
  `critic_align`, `critic_super`, `retry_queued`, `retry_exhausted`
  cases.
* New components:
  * `P11VerdictChip`
  * `P11FailureTagChip`
  * `P11StepHealthStrip`
  * `P11RetryStrategyBadge`
  * `P11CriticCostGauge`
* `P11IterationCard` augmented to render the StepHealthStrip and
  retry badge.
* ExecutionHeader augmented with `P11CriticCostGauge`.
* New page `/executions/:id/health` (admin only) — full health record
  list with filter by failure tag.
* `services/agent.service.ts::getHealthRecords` consumed.

### Out of scope

* Supervisor proposed_subgoals rendering (FE-T4).
* Replan diff modal (FE-T4).
* Editing the entity's `critic_model_override` from the UI (Phase 12).

---

## 3. Architecture (technical)

### 3.1 Reducer extension

```ts
case 'critic_pre': {
  // Find latest iteration card; attach pre verdict to the most recent
  // health record OR create a new health record if none exists for this iter.
  const iterIdx = lastIterCardIndex(s, e.iteration);
  if (iterIdx < 0) return s;
  const card = s.iterations[iterIdx];
  // For simplicity in T3: one health record per iteration in this
  // version; full step-level mapping arrives when backend emits step_id
  const rec = card.healthRecords.at(-1) ?? makeNewRec(card.iteration);
  rec.pre_critic_verdict = e.verdict;
  rec.pre_critic_concerns = e.concerns ?? [];
  rec.pre_critic_cost_usd = e.cost_usd;
  return upsertHealthRec(s, iterIdx, rec);
}
case 'critic_post': { /* similar; sets verdict, tags, suggestion */ }
case 'critic_align': { /* sets aligned, drift */ }
case 'critic_super': { /* sets supervisor_recommendation, reasoning */ }
case 'retry_queued': {
  const iterIdx = lastIterCardIndex(s, e.iteration);
  return setRetryStrategy(s, iterIdx, e.strategy);
}
```

The reducer remains pure; no side effects.

### 3.2 `P11StepHealthStrip`

```tsx
<P11StepHealthStrip record={record}>
  <P11VerdictChip stage="PRE"   verdict={record.pre_critic_verdict} />
  <P11VerdictChip stage="POST"  verdict={record.post_critic_verdict}
                                 tags={record.post_critic_tags}
                                 suggestion={record.post_critic_suggestion} />
  <P11VerdictChip stage="ALIGN" aligned={record.alignment_aligned}
                                 drift={record.alignment_drift} />
  <P11VerdictChip stage="SUPER" recommendation={record.supervisor_recommendation}
                                 reasoning={record.supervisor_reasoning} />
</P11StepHealthStrip>
```

Each chip:

* Tiny pill, 18px tall.
* Icon + label.
* On hover: popover with concerns / suggestion / reasoning.
* Colour:
  * PASS → green
  * BLOCK → red
  * REVISE → amber
  * REJECT → red
  * aligned → green; not-aligned → red
  * CONTINUE → grey; REPLAN → amber; ABORT → red; PAUSE → blue

### 3.3 `P11FailureTagChip`

Smaller chip, severity-tinted (uses `FailureTag.severity` mirror in TS):

```ts
const SEVERITY_TINT = {
  0: 'tag-tint-0',  // informational — slate
  1: 'tag-tint-1',  // minor — yellow
  2: 'tag-tint-2',  // moderate — amber
  3: 'tag-tint-3',  // critical — red
};
```

Icon per tag (e.g. `<Compass/>` for OFF_TOPIC, `<Sparkles/>` for
HALLUCINATION). Click → opens a side drawer with the suggestion.

### 3.4 `P11RetryStrategyBadge`

Inline pill on the iteration card, near the executor badge:

```
↻ retry: DIFFERENT_MODEL
```

Strategy → icon map:

| Strategy | Icon |
|----------|------|
| RETRY_AS_IS | `<Repeat />` |
| RETRY_DIFFERENT_MODEL | `<Layers />` |
| RETRY_DIFFERENT_PROMPT | `<MessageSquare />` |
| RETRY_DIFFERENT_TOOL | `<Wrench />` |
| ASK_USER | `<UserCheck />` |
| ABANDON | `<XCircle />` |

### 3.5 `P11CriticCostGauge`

Header micro-component:

```
Critic: $0.04 / $0.12  (33%)  ▓▓▓░░░░░░  cap 25%
```

Cap line shows when `critic_cost_share_pct` is breached → bar turns
amber. Tooltip explains the budget guard.

### 3.6 Health records page

```tsx
// pages/ai/HealthRecordsPage.tsx  (NEW; admin route /executions/:id/health)
export const HealthRecordsPage: React.FC = () => {
  const { id } = useParams();
  const { data, isLoading } = useHealthRecords(id!);

  const [tagFilter, setTagFilter] = useState<FailureTag[]>([]);

  return (
    <main>
      <FilterBar tags={tagFilter} onChange={setTagFilter} />
      <table>
        <thead><tr><th>iter</th><th>step</th><th>pre</th><th>post</th><th>tags</th><th>align</th><th>super</th><th>cost</th></tr></thead>
        <tbody>
          {records.filter(r => intersects(r.post_critic_tags, tagFilter)).map(r => (
            <tr key={r.record_id}>
              <td>{r.iteration}</td>
              <td>{r.step_id}</td>
              <td><P11VerdictChip stage="PRE" verdict={r.pre_critic_verdict} /></td>
              ...
            </tr>
          ))}
        </tbody>
      </table>
    </main>
  );
};
```

Reached by a "View health records" button in the ExecutionDetail
header (admin only).

---

## 4. Detailed deliverables

### 4.1 FE-T3-1 — Reducer extension (Day 1 AM)

* Add cases to `hooks/useExecutionEvents.ts`.
* Helpers `lastIterCardIndex`, `upsertHealthRec`, `setRetryStrategy`.
* Unit tests for each event flow.

### 4.2 FE-T3-2 — `P11VerdictChip` + `P11FailureTagChip` (Day 1 PM)

* Pure components, no data fetching.
* Storybook stories per state per stage.

### 4.3 FE-T3-3 — `P11StepHealthStrip` + `P11RetryStrategyBadge` (Day 2 AM)

* Compose the chips. Click chip → opens detail popover (uses framer-
  motion).

### 4.4 FE-T3-4 — `P11CriticCostGauge` (Day 2 PM)

* Reads `usage_logs` aggregates *or* derives critic cost from events
  (sum `cost_usd` from critic events). Both work; events-derived is
  the source of truth in-page; backend KPI dashboard uses aggregates.

### 4.5 FE-T3-5 — `P11IterationCard` integration (Day 3 AM)

* Render `P11StepHealthStrip` if `card.healthRecords.length > 0`.
* Render `P11RetryStrategyBadge` if `card.retryStrategy &&
  card.retryStrategy !== 'NONE'`.
* Smoke: scroll a 10-iteration timeline without jank.

### 4.6 FE-T3-6 — Health records page + route (Day 3 PM)

* `services/agent.service.ts::getHealthRecords` consumed.
* Admin guard via `useAuth().user.role === 'app_admin' ||
  user.role === 'tenant_admin'`.
* Add sidebar link **only when** the user is on an ExecutionDetail page
  (contextual, not global).

---

## 5. Database / schema changes

N/A (frontend).

---

## 6. API changes (consumed)

| Endpoint | Status | Where used |
|----------|--------|------------|
| `GET /api/v1/executions/{id}/health_records` | NEW (backend T3) | `agent.service.ts::getHealthRecords` |
| SSE stream | extended (critic_*, retry_*) | `services/events.ts` |

---

## 7. Telemetry events

None emitted from frontend.

---

## 8. Feature flags (consumed)

| Flag | Effect |
|------|--------|
| `critic_pipeline.v2_enabled` | Without it, no critic events flow; the StepHealthStrip simply doesn't render |
| `critic_pipeline.pre_critic_enabled` | If OFF → PRE chip greyed out |
| `critic_pipeline.budget_share_cap` (float) | Read for the gauge cap line |

---

## 9. Tests

### 9.1 Unit

* Reducer cases for every critic event.
* Verdict chip renders correct colour / icon per verdict.
* FailureTag chip renders severity tint correctly.
* RetryStrategyBadge renders 6 strategy variants.
* CriticCostGauge: cap line appears when share > cap.

### 9.2 Integration

* Render iteration card with a populated health record; assert all 4
  chips render; hover → popover content.
* Render multiple iterations with mixed verdicts; confirm strip
  updates per-iter.

### 9.3 E2E (Playwright)

* `execution-critic.spec.ts` — trigger fixture entity that fails post
  critic; confirm REVISE chip + DIFFERENT_MODEL retry badge appear.

---

## 10. Acceptance criteria

1. Step health visible on every iteration card when `critic_pipeline.v2_enabled`.
2. Retry strategy badge appears on iterations that triggered a retry.
3. Critic cost gauge in header reflects live cost; bar transitions to
   amber when share > cap.
4. Health records admin page renders all records with filter by
   FailureTag.
5. Coverage ≥ 75% on new components.
6. Lighthouse a11y ≥ 90.

---

## 11. Effort (3 days)

| Day | Work |
|-----|------|
| 1 AM | Reducer extension |
| 1 PM | VerdictChip + FailureTagChip |
| 2 AM | StepHealthStrip + RetryStrategyBadge |
| 2 PM | CriticCostGauge |
| 3 AM | IterationCard integration |
| 3 PM | Health records page + route + PR |

---

## 12. Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Critic events arrive without `iteration` for a step-level scope | M | Strip mis-attached | Reducer attaches to last iteration card and the last health record within it; backend confirmed `iteration` is always present |
| FailureTag enum drift between FE and BE | M | Unknown tag renders blank | Fallback chip "Unknown tag: <value>" + console warning |
| Cap line confuses users who don't know about the budget guard | L | UX confusion | Tooltip on the cap line explains the cap |
| Too many chips on iterations with many steps (T3 ships single-record-per-iter) | L | Visual clutter | Defer multi-record-per-iter to backend step_id evolution; T3 keeps simple |

---

## 13. Dependencies

* **Upstream:** FE-T2 (AgentLoop UI), Backend T3.
* **Downstream:**
  * FE-T4 reads SupervisorVerdict from these chips for the verdict
    card.
  * FE-T8 cost dashboard groups by attribution including critic_*.

---

## 14. Open questions

* Should we map FailureTag → suggested user action in the popover
  (e.g. "Consider tightening the entity goal")? Phase 12 idea; for now,
  show the LLM's `suggestion` verbatim.
* Should the iteration card group by step (multiple records / iter)
  once backend emits step_id? Yes — but that needs the backend to emit
  per-step events with step_id; not part of T3 backend scope.
