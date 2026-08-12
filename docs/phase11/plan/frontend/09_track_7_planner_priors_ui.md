# Frontend Track 7 — Planner v2 UI (parallel with backend T7)

> **Backend Track:** [`../09_track_7_planner_priors.md`](../09_track_7_planner_priors.md)
> **Owner:** Frontend engineer.
> **Duration:** 3 working days.
> **Behaviour change:** Multi-candidate plan visible at the iteration
>   that ran the planner; plan_history queryable; invariant violations
>   surfaced.
> **Risk:** Low.

---

## 1. Objectives (functional)

After Frontend Track 7:

1. When the planner runs, the relevant `P11IterationCard` shows a
   **"View plan candidates"** CTA.
2. The CTA opens a **`P11PlanCandidatesCompare`** modal showing all 2-3
   candidates side-by-side with steps, estimated cost, invariant
   violations (if rejected), and the judge's score.
3. The chosen plan is highlighted; alternates are dimmed.
4. The Replan diff modal from FE-T4 is **upgraded** to use the
   `plan_history` endpoint so it has full fidelity (not just
   proposed_subgoals).
5. The Strategist's **task class tag** (from FE-T4) gets a tooltip
   that explains the bandit choice when present (delegates to the
   bandit panel).
6. EntityBuilder's plan editor receives the new
   `_plan_meta.style` annotation on dynamic-plan runs (read-only;
   informational).
7. A small **plan invariant indicator** appears in the run header
   when at least one candidate failed an invariant (this is normal
   information, not an error).

---

## 2. Scope

### In scope

* Extend `useExecutionEvents` reducer with `plan_candidates`,
  `plan_invariant_violations`, `plan_judge_decision`, `plan_chosen`,
  `plan_replan`.
* New components:
  * `P11PlanCandidatesCompare` (modal)
  * `P11PlanCandidateCard` (one per candidate inside the modal)
  * `P11InvariantViolationBadge`
  * `P11PlanStyleTag`
* Service: `agent.service.ts::getPlanCandidates`,
  `agent.service.ts::getPlanHistory`.
* `P11IterationCard` adds the "View plan candidates" CTA when planner
  ran at that iteration.
* Upgrade FE-T4's `P11ReplanDiffModal` to consume `plan_history`.

### Out of scope

* Editing plans inline (Phase 12).
* Custom cost estimator visualisation (the candidate card just shows
  the estimated cost number).

---

## 3. Architecture (technical)

### 3.1 Plan candidates compare modal

```
┌─────────────────────────────────────────────────────────────────┐
│ Plan candidates — iteration 1                            ✕     │
├─────────────────────────────────────────────────────────────────┤
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────┐  │
│  │ Candidate A      │  │ Candidate B      │  │ Candidate C  │  │
│  │ style: DAG_PAR   │  │ style: RECURSIVE │  │ style: DAG   │  │
│  │ cost: $0.08      │  │ cost: $0.21      │  │ cost: $0.12  │  │
│  │ invariants ✓     │  │ ⚠ cost > budget  │  │ invariants ✓ │  │
│  │ judge: 0.78  ★   │  │ rejected         │  │ judge: 0.62  │  │
│  │ ──────           │  │                  │  │ ──────       │  │
│  │ 1. search        │  │                  │  │ 1. scrape    │  │
│  │ 2. extract       │  │                  │  │ 2. summarise │  │
│  │ 3. summarise     │  │                  │  │              │  │
│  └──────────────────┘  └──────────────────┘  └──────────────┘  │
│                                                                 │
│  Chosen candidate is starred ★                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 3.2 Invariant violation badge

Per candidate card, a small chip listing the failed invariants
(linkified to plan-invariants help page):

```
⚠ cost_estimate_within_budget
⚠ no_dangling_variable_refs
```

If `kept = 1`, the modal still shows the rejected candidates with the
violation chips so users understand why.

### 3.3 Plan history endpoint

```ts
// services/agent.service.ts (additions)
async getPlanHistory(runId: string): Promise<PlanHistoryResponse> {
  const { data } = await apiClient.get(
    `/executions/${runId}/plan_history`);
  return data;
}
```

`PlanHistoryResponse`:

```ts
interface PlanHistoryResponse {
  versions: Array<{
    iteration: number;
    steps: PlanStep[];
    style: string;
    estimated_cost_usd: string;
    chosen_at: string;     // ISO datetime
    reason: string;        // "initial" | "replan_supervisor" | "replan_failure"
  }>;
}
```

### 3.4 Plan-style tag in run header

Reuses `P11TaskClassTag`'s positioning; new component
`P11PlanStyleTag` shows the chosen style on the most-recent iteration:

```
[ task: research_topic ]  [ plan: DAG_PARALLEL (judge 0.78) ]
```

---

## 4. Detailed deliverables

### 4.1 FE-T7-1 — Reducer extension (Day 1 AM)

```ts
case 'plan_candidates': {
  return { ...s, planCandidatesMeta: {
    candidates_kept: e.candidates_kept,
    chosen_style: e.chosen_style,
    estimated_cost_usd: e.estimated_cost_usd,
  } };
}
case 'plan_invariant_violations': {
  return { ...s, planInvariantViolations: [...s.planInvariantViolations, e] };
}
case 'plan_judge_decision': {
  return { ...s, planJudgeDecision: e };
}
case 'plan_chosen': {
  return { ...s, planChosen: e };
}
case 'plan_replan': {
  return { ...s, replanEvents: [...s.replanEvents, e] };
}
```

### 4.2 FE-T7-2 — Service methods (Day 1 PM)

`getPlanCandidates`, `getPlanHistory`. Cache the latter for the page
lifetime.

### 4.3 FE-T7-3 — `P11PlanCandidatesCompare` modal (Day 2)

Loads on click; uses `getPlanCandidates`. Renders cards with:

* Style badge.
* Estimated cost / latency.
* Invariants chip list (✓ all green, or ⚠ list).
* Judge score (★ for chosen).
* Step list — re-uses existing step row component for visual
  consistency.

### 4.4 FE-T7-4 — `P11InvariantViolationBadge` (Day 2 PM)

Small chip listing failed invariants per candidate. Tooltip lists the
invariant rule.

### 4.5 FE-T7-5 — `P11IterationCard` CTA (Day 3 AM)

For iterations where `view.planCandidatesMeta` was set, show a "View
plan candidates" link in the card footer. Clicking opens the modal.

### 4.6 FE-T7-6 — Upgrade Replan diff modal (Day 3 AM)

Replan diff modal from FE-T4 now consumes `plan_history` for old/new
plans. Diff is full step-by-step.

### 4.7 FE-T7-7 — Plan style tag + run header polish (Day 3 PM)

Per §3.4.

### 4.8 FE-T7-8 — Tests + PR (Day 3 PM)

Per §9.

---

## 5. Database / schema changes

N/A (frontend).

---

## 6. API changes (consumed)

| Endpoint | Status | Where used |
|----------|--------|------------|
| `GET /api/v1/executions/{id}/plan_candidates` | NEW (backend T7) | `agent.service.getPlanCandidates` |
| `GET /api/v1/executions/{id}/plan_history` | NEW (backend T7) | `agent.service.getPlanHistory` |
| SSE stream | extended (plan_*) | events |

---

## 7. Telemetry events

None emitted from frontend.

---

## 8. Feature flags (consumed)

| Flag | Effect |
|------|--------|
| `planner.v2_enabled` | Without → no plan candidates events; modal CTA hidden |
| `planner.n_candidates` | Read-only; informational tooltip ("Generated N candidates") |
| `planner.judge_enabled` | If OFF → judge score column hidden in candidate cards |

---

## 9. Tests

### 9.1 Unit

* `P11PlanCandidateCard` highlights chosen vs alternates correctly.
* `P11InvariantViolationBadge` shows correct invariants list.
* Reducer absorbs the five new events.
* Modal opens with no candidates → "No candidate data" empty state.

### 9.2 Integration

* Render a run with 3 candidates, one rejected; modal shows all
  three; chosen has star.
* Open replan diff for a fixture run; left/right step lists differ
  correctly.

### 9.3 E2E

* `execution-plan-candidates.spec.ts` — trigger a fixture entity
  with dynamic_planning + n_candidates=3 → wait for plan_chosen
  event → click "View plan candidates" → modal shows all candidates
  with judge scores.

---

## 10. Acceptance criteria

1. Iteration cards show "View plan candidates" CTA where planner ran.
2. Modal renders 2-3 candidates side-by-side with chosen starred.
3. Invariant violations visible.
4. Replan diff upgraded to use full plan history.
5. Plan style tag in header.
6. Coverage ≥ 75% on new components.

---

## 11. Effort (3 days)

| Day | Work |
|-----|------|
| 1 AM | Reducer extension |
| 1 PM | Service methods + types |
| 2 | PlanCandidatesCompare modal + cards |
| 3 AM | IterationCard CTA + Replan diff upgrade |
| 3 PM | Plan style tag + tests + PR |

---

## 12. Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Modal too wide on small screens | M | Layout breaks | Stack cards vertically below 1024px |
| `plan_history` endpoint not in T7 backend | L | Replan diff falls back to FE-T4 behaviour | Modal copes — both code paths exist |
| Judge score absent (planner.judge_enabled OFF) | L | Star confusion | Show "no judge — cost tiebreak" badge instead |
| Step rows render inconsistently between modal and timeline | L | Visual drift | Reuse the same `<StepRow />` component in both |

---

## 13. Dependencies

* **Upstream:** FE-T2 (IterationCard), FE-T4 (Replan diff modal),
  Backend T7.
* **Downstream:** FE-T9 KPI dashboard uses chosen-style aggregates.

---

## 14. Open questions

* Should the modal allow **manually selecting** an alternate
  candidate? **No** in Phase 11 — that would require a backend "re-run
  with this plan" endpoint. Phase 12 candidate.
* Should we visualise plan dependencies (DAG)? `reactflow` is in deps
  already. **Phase 12** if the plain step list is insufficient.
