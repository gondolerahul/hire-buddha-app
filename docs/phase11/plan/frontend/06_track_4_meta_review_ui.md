# Frontend Track 4 — Meta-Review + Bandit UI (parallel with backend T4)

> **Backend Track:** [`../06_track_4_meta_review_goalguard.md`](../06_track_4_meta_review_goalguard.md)
> **Owner:** Frontend engineer.
> **Duration:** 3 working days.
> **Behaviour change:** Supervisor verdict surfaced in the iteration
>   timeline; bandit state browsable per (entity, task_class); replan
>   visible.
> **Risk:** Low.

---

## 1. Objectives (functional)

After Frontend Track 4:

1. The supervisor verdict (`CONTINUE | REPLAN | ABORT | PAUSE`) renders
   as a **Supervisor card** at the iteration boundary where the
   supervisor ran (every Nth iteration).
2. When a **REPLAN** happens, a **Replan diff modal** lets the user
   inspect old plan vs new plan + the supervisor's reasoning.
3. The `bandit_arm` event lights up a small badge "Bandit chose: DAG
   (exploit)" on the iteration card; "(explore)" when exploration
   was used.
4. New admin page `/entities/:id/bandit-state` lists the bandit arm
   table per task_class with pulls / successes / avg_cost / score, and
   a sparkline of recent runs.
5. The `task_class.classified` event annotates the run header:
   "Task class: research_topic".

---

## 2. Scope

### In scope

* Extend `useExecutionEvents` reducer:
  * `critic_super` payload extension (proposed_subgoals_count).
  * `bandit_arm`, `bandit_arm_updated`.
  * `replan_triggered`.
  * `task_class.classified`.
* New components:
  * `P11SupervisorVerdictCard`
  * `P11ReplanDiffModal`
  * `P11BanditArmBadge` (the per-iteration "chose X" pill)
  * `P11BanditArmRow` (for the admin table)
  * `P11TaskClassTag` (in run header)
* New page: `pages/ai/BanditStatePanel.tsx` (admin only).
* Service: `services/agent.service.ts::getBanditState`,
  `services/agent.service.ts::getReplanDetails`.

### Out of scope

* Editing bandit arms by hand (Phase 12; can be done in DB if needed).
* Configuring `epsilon` from the UI (admin Feature Flags page —
  FE-T9).
* The "Supervisor proposed_subgoals" being **applied** without the
  diff modal — Track 4 backend applies them automatically; the FE
  modal is informational, post-hoc.

---

## 3. Architecture (technical)

### 3.1 Where the Supervisor card lives

A Supervisor card is rendered **between two iteration cards** in the
`P11AgentLoopTimeline`. It looks like a horizontal banner spanning the
timeline width.

```
[ iter 4 ]
  [ supervisor: REPLAN — "two off-topic steps; narrow scope" ]
       ↓ replan diff (link to modal)
[ iter 5 ]   (new plan)
```

`P11AgentLoopTimeline` accepts an array of mixed items
(`IterationCard` or `SupervisorBoundary`) and renders accordingly.

### 3.2 Replan diff modal

```tsx
<P11ReplanDiffModal
  oldPlan={view.planAtIter[N]}
  newPlan={view.planAtIter[N + 1]}
  proposedSubgoals={superVerdict.proposed_subgoals}
  reasoning={superVerdict.reasoning}
/>
```

Two-column diff: left column shows the steps that were in the old
plan, right column shows the new plan. Removed steps in muted red,
added in green, kept neutral. Proposed subgoals listed above the
diff.

### 3.3 Bandit arm badge inline

Inside `P11IterationCard`, near the `P11ExecutorBadge`:

```
[ DAG ] [ ↳ bandit: DAG_PARALLEL (exploit, score 0.74) ]
```

* If `exploration=true` → tint amber + label "explore".
* If `exploration=false` → tint blue + label "exploit".
* Click → opens the bandit state panel for this entity / task_class
  in a new tab (admin only; for non-admin, the badge is read-only).

### 3.4 Bandit state panel

```
/entities/:id/bandit-state

# Task class: research_topic
# Bandit: PlanStyleBandit  epsilon: 0.10

┌──────────────────┬──────┬──────────┬────────────┬───────┐
│ Arm              │ Pulls│ Successes│ Avg cost $ │ Score │
├──────────────────┼──────┼──────────┼────────────┼───────┤
│ DAG_PARALLEL     │   23 │       18 │ 0.084      │ 0.93  │
│ RECURSIVE        │    7 │        4 │ 0.150      │ 0.40  │
│ SINGLE_TOOL      │   12 │       11 │ 0.012      │ 7.64  │  ← high score
└──────────────────┴──────┴──────────┴────────────┴───────┘

# Task class: extract_from_url
... (multiple tables, one per task_class)
```

Each row also gets a sparkline (recharts mini-line) of the last 30
runs' outcome.

### 3.5 Task class tag

In the run header:

```
[ status: RUNNING ]  [ task: research_topic ]  [ executor: DAG ]
```

Tag is clickable → opens the bandit state panel filtered to that task
class (admin only).

---

## 4. Detailed deliverables

### 4.1 FE-T4-1 — Reducer extension (Day 1 AM)

```ts
case 'critic_super': {
  const verdict: SupervisorVerdict = {
    iteration: e.iteration,
    recommendation: e.recommendation,
    confidence: e.confidence,
    reasoning: e.reasoning,
    proposed_subgoals: e.proposed_subgoals,
  };
  return { ...s,
           supervisorVerdicts: [...s.supervisorVerdicts, verdict] };
}
case 'bandit_arm': {
  return { ...s,
           banditChoices: [...s.banditChoices, {
             iteration: e.iteration,
             task_class: e.task_class,
             candidates: e.candidates,
             chosen: e.chosen,
             exploration: e.exploration,
           }] };
}
case 'replan_triggered': {
  return { ...s,
           replanEvents: [...s.replanEvents, {
             iteration: e.iteration,
             by: e.by,
             proposed_subgoals_count: e.proposed_subgoals_count,
           }] };
}
case 'task_class.classified': {
  return { ...s, taskClass: e.task_class };
}
```

### 4.2 FE-T4-2 — `P11SupervisorVerdictCard` (Day 1 PM)

Renders inline between iterations:

* Icon by recommendation (✅ continue, 🔄 replan, ⛔ abort, ⏸ pause).
* Confidence as `P11ConfidenceBar`.
* Reasoning paragraph.
* If `proposed_subgoals.length > 0` → "View replan diff" CTA →
  opens `P11ReplanDiffModal`.

### 4.3 FE-T4-3 — `P11ReplanDiffModal` (Day 2 AM)

Diff view:

* Reuses existing `EntityBuilder` step-row component to render each
  step (visual consistency).
* Added steps highlighted green; removed muted red; kept dimmed.

Plans-per-iteration are derived from the run's `dynamic_plan` plus
the SSE `plan_chosen` events. If the page didn't observe the plan
history live (e.g. arrived after the run finished), call
`GET /executions/:id/plan_history` (a new endpoint surface; defer to
T-FE-7 if not yet available — for T-FE-4 ship a placeholder modal
showing only proposed_subgoals).

### 4.4 FE-T4-4 — `P11BanditArmBadge` (Day 2 PM)

Per-iteration inline badge. ~60 lines.

### 4.5 FE-T4-5 — Bandit state panel page (Day 3 AM)

Route: `/entities/:id/bandit-state`.

Layout: one section per task_class. Each section: table + sparkline.

Data fetched from `agentService.getBanditState(entityId, taskClass?)`.
Without `taskClass`, the endpoint returns all task_classes for the
entity.

```ts
// services/agent.service.ts (additions)
async getBanditState(entityId: string, taskClass?: string):
    Promise<{tasks: Array<{task_class: string; arms: BanditArm[]}>}> {
  const params = taskClass ? { task_class: taskClass } : {};
  const { data } = await apiClient.get(
    `/entities/${entityId}/bandit_state`, { params });
  return data;
}
```

### 4.6 FE-T4-6 — `P11TaskClassTag` + run header integration (Day 3 PM)

Tag added to ExecutionHeader; clickable to bandit state panel for
admins.

### 4.7 FE-T4-7 — Tests + storybook (Day 3 PM)

Per §9.

---

## 5. Database / schema changes

N/A (frontend).

---

## 6. API changes (consumed)

| Endpoint | Status | Where used |
|----------|--------|------------|
| `GET /api/v1/entities/{id}/bandit_state` | NEW (backend T4) | `agent.service.ts::getBanditState` |
| `GET /api/v1/executions/{id}/plan_history` | new (deferred; see §4.3) | replan diff |
| SSE stream | extended (critic_super, bandit_*, replan_triggered, task_class.classified) | `services/events.ts` |

---

## 7. Telemetry events

None emitted from frontend.

---

## 8. Feature flags (consumed)

| Flag | Effect |
|------|--------|
| `meta_review.v2_enabled` | Without it, supervisor cards never render |
| `bandit.enabled` | Without it, bandit badge never renders |
| `task_classifier.v2_enabled` | Affects badge accuracy; no FE branch needed |

---

## 9. Tests

### 9.1 Unit

* Reducer handles `critic_super` payload with and without
  `proposed_subgoals`.
* `P11SupervisorVerdictCard` renders all four recommendations.
* `P11ReplanDiffModal` highlights added/removed/kept steps correctly.
* `P11BanditArmBadge` flips colour between exploit and explore.
* `P11BanditArmRow` renders sparkline without crashing on empty data.

### 9.2 Integration

* Render an iteration timeline with one supervisor REPLAN; confirm
  card renders inline and the diff modal opens.
* Bandit state panel renders for fixture entity with three task
  classes and three arms each.

### 9.3 E2E

* `execution-supervisor-replan.spec.ts` — trigger a fixture entity
  that forces a REPLAN; assert the SupervisorVerdictCard appears.

---

## 10. Acceptance criteria

1. SupervisorVerdictCard renders inline at supervisor iterations.
2. REPLAN events open a diff modal showing old vs new plan.
3. Bandit badge renders on iterations where the bandit chose; explore
   vs exploit visually distinct.
4. Admin can open `/entities/:id/bandit-state` and see arm tables.
5. Task class tag in run header; clickable for admins.
6. Coverage ≥ 75% on new components.
7. Lighthouse a11y ≥ 90.

---

## 11. Effort (3 days)

| Day | Work |
|-----|------|
| 1 AM | Reducer extension |
| 1 PM | SupervisorVerdictCard + ReplanDiffModal (skeleton) |
| 2 AM | ReplanDiffModal full impl + tests |
| 2 PM | BanditArmBadge + integration in IterationCard |
| 3 AM | Bandit state panel page + service |
| 3 PM | TaskClassTag + tests + PR |

---

## 12. Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| `plan_history` endpoint not in backend T4 | M | Diff modal only shows proposed_subgoals | Defer full diff to FE-T7; ship informational modal for T4 |
| Bandit panel chart performance for entities with many task_classes | L | Slow render | Limit to top 10 task_classes by pulls; "show all" CTA |
| Confusion between `task_class` and `tags` | L | UX wording | Tooltip: "Task class is auto-detected; tags are user-set" |
| Supervisor verdicts spam timeline if `meta_review_interval` is small | L | Cluttered | Group consecutive CONTINUE cards into "no changes" collapsible row |

---

## 13. Dependencies

* **Upstream:** FE-T3 (chips and reducer base), Backend T4.
* **Downstream:**
  * FE-T7 reuses the replan diff modal for plan-candidate compare.
  * FE-T9 KPI dashboard pulls bandit metrics.

---

## 14. Open questions

* Should non-admins see the bandit badge? **Decision:** yes, but
  read-only — only admins can navigate to the panel.
* Should the supervisor reasoning be Markdown-rendered? **Decision:**
  plain text for now; Markdown would risk XSS without a trusted
  sanitiser.
