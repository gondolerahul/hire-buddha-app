# Frontend Track 2 — AgentLoop UI (parallel with backend T2)

> **Backend Track:** [`../04_track_2_agent_loop.md`](../04_track_2_agent_loop.md)
> **Owner:** Frontend engineer (primary).
> **Duration:** 5 working days.
> **Behaviour change:** New ExecutionDetail layout behind `agent_loop.enabled`.
> **Risk:** Medium — biggest frontend Track. Mitigated by feature-flag
>   degradation to legacy step list.
> **Goal mapping:** FE-G1, FE-G5, FE-G8.

This is the **largest** frontend Track. It turns ExecutionDetail from
a flat step list into a live agent-loop view with iterations, budget,
reflections, and resume awareness.

---

## 1. Objectives (functional)

After Frontend Track 2:

1. ExecutionDetail renders an **iteration timeline** for runs whose
   `agent_loop.enabled` flag is on (per-run, not per-user).
2. A **sticky right rail** shows the live AgentState:
   * Budget bar (tokens / USD / wall / iters)
   * Open subgoals
   * Achieved subgoals
   * Blockers
   * Last action / observation summary
   * Reflections list
3. The page **subscribes to SSE** and updates live via the typed event
   reducer. No polling.
4. A **resume indicator** appears on the iteration card where the
   worker resumed after a crash.
5. The page renders the **legacy step list** when the flag is OFF, so
   no existing run loses fidelity.
6. SSE events flow through one typed reducer; legacy `setInterval`
   refresh paths are gone for new runs.
7. The first version of the `agent.service.ts` exists and exposes
   `getAgentState`, `getHealthRecords` (consumed by Track 3 too).

---

## 2. Scope

### In scope

* `services/events.ts` (typed SSE union + low-level hook).
* `hooks/useExecutionEvents.ts` (reducer-based derived state).
* `hooks/useAgentState.ts` (slice of the above).
* `services/agent.service.ts` (`getAgentState`, `getHealthRecords`,
  `getPlanCandidates` stub).
* `pages/ai/ExecutionDetail.tsx` — branched render (new or legacy).
* New components under `components/agent/` (initially with `P11` prefix):
  * `P11AgentStatePanel`
  * `P11BudgetBar`
  * `P11IterationCard`
  * `P11AgentLoopTimeline`
  * `P11ReflectionsList`
  * `P11ExecutorBadge`
  * `P11ResumeIndicator`
* SSE typed event union covers Track-2 backend events only.
  Tracks 3-8 extend it incrementally.
* Feature flag wiring through `useFeatureFlag('agent_loop.enabled')`
  resolved at the **run level** via the run's `entity.company_id` + the
  per-run override in `run.input_data.feature_flags`.

### Out of scope

* StepHealthRecord rendering (T-FE-3).
* Supervisor verdict card (T-FE-4).
* Meta-Agent Board view (T-FE-5).
* Plan candidates compare modal (T-FE-7).
* Cost-by-attribution breakdown (T-FE-8).
* KPI dashboard (T-FE-9).

---

## 3. Architecture (technical)

### 3.1 Page-level branching

```tsx
// pages/ai/ExecutionDetail.tsx (after T-FE-2)
export const ExecutionDetail: React.FC = () => {
  const { id } = useParams();
  const { data: run, isLoading } = useRun(id!);

  const agentLoopEnabled = useFeatureFlag('agent_loop.enabled', {
    scope: 'run',
    runId: id!,
    runMeta: run?.input_data?.feature_flags,
  });

  if (isLoading) return <PageLoader />;
  if (!run) return <NotFound />;

  if (agentLoopEnabled) {
    return <AgentLoopExecutionDetail run={run} />;
  }
  return <LegacyExecutionDetail run={run} />;
};
```

`LegacyExecutionDetail` is the current `ExecutionDetail` code extracted
verbatim — no logic change.

`AgentLoopExecutionDetail` is the new component implementing the
two-column layout described below.

### 3.2 Two-column layout

```
┌──────────────────────────────────────────────────────────────────────┐
│  Header: <run name>  status: RUNNING  cost: $0.07 / $1.00            │
├──────────────────────────────────────────────────────────────────────┤
│                                                  ┌──────────────────┐│
│  ITERATION TIMELINE                              │ AGENT STATE      ││
│                                                  │                  ││
│  ┌──────────────────────────────────────────┐    │ Budget           ││
│  │ iter #1                                  │    │ ▓▓▓▓░░░░ 31%     ││
│  │ executor: DAG  budget: 12%               │    │                  ││
│  │ plan fragment: 3 steps                   │    │ Open subgoals    ││
│  │ ✓ scrape URL                             │    │ • G1 narrow      ││
│  │ ✓ extract data                           │    │ • G2 synthesize  ││
│  │ ⏱ summarise                              │    │   (blocked)      ││
│  │ (StepHealthStrip — T3 adds)              │    │                  ││
│  │ retry: NONE                              │    │ Achieved         ││
│  └──────────────────────────────────────────┘    │ • narrowing done ││
│                                                  │                  ││
│  ┌──────────────────────────────────────────┐    │ Blockers         ││
│  │ iter #2  ↩ resumed at this point         │    │ (none)           ││
│  │ executor: SingleStep                     │    │                  ││
│  │ ...                                      │    │ Last action      ││
│  └──────────────────────────────────────────┘    │ TOOL_CALL[web…]  ││
│                                                  │                  ││
│                                                  │ Reflections      ││
│                                                  │ ・iter1: 1 fact   ││
│                                                  │   contradicted   ││
└──────────────────────────────────────────────────────────────────────┘
```

CSS: `display: grid` `grid-template-columns: 1fr 360px;` with the right
rail `position: sticky; top: 16px;`.

### 3.3 Event-driven reducer

```ts
// hooks/useExecutionEvents.ts
type S = ExecutionViewState;
type A = AgentEvent;

function reducer(s: S, e: A): S {
  switch (e.type) {
    case 'iteration_start': {
      const card: IterationCard = {
        iteration: e.iteration,
        executor: e.executor,
        budget_pressure_at_start: e.budget_pressure,
        open_subgoals_at_start: e.open_subgoals,
        healthRecords: [],
        decision: null,
        cost_iter_usd: '0',
        resumed: false,
        retryStrategy: null,
      };
      return { ...s, iterations: [...s.iterations, card] };
    }
    case 'iteration_end': {
      const i = s.iterations.findIndex(c => c.iteration === e.iteration);
      if (i < 0) return s;
      const updated = [...s.iterations];
      updated[i] = { ...updated[i], decision: e.decision, cost_iter_usd: e.cost_iter_usd, outcome: e.outcome };
      return { ...s, iterations: updated };
    }
    case 'resume': {
      // Find the iteration we resumed *to* and mark it
      const i = s.iterations.findIndex(c => c.iteration === e.from_iteration + 1);
      if (i < 0) return s;
      const updated = [...s.iterations];
      updated[i] = { ...updated[i], resumed: true };
      return { ...s, iterations: updated };
    }
    case 'budget_pressure':
    case 'budget_exhausted': {
      // Updates state.budget.pressure via a separate poll on /agent_state
      // (events are signal, not source of truth for state slices).
      return s;
    }
    // ... other events handled in T3-T8
    default:
      return s;
  }
}

export function useExecutionEvents(runId: string): ExecutionViewState {
  const [state, dispatch] = useReducer(reducer, INITIAL_STATE);
  useEffect(() => {
    const es = new EventSource(`/api/v1/executions/${runId}/stream`);
    es.onmessage = (msg) => {
      try {
        const data = JSON.parse(msg.data) as AgentEvent;
        dispatch(data);
      } catch (e) {
        console.warn('Bad SSE payload', e);
      }
    };
    return () => es.close();
  }, [runId]);

  // Poll /agent_state every 2s while RUNNING (truthy live state)
  useAgentStatePolling(runId, dispatch);

  return useMemo(() => state, [state]);
}
```

The reducer only handles **Track-2 events**. Each later Track adds
cases without re-architecting.

### 3.4 AgentState polling

Events tell us **what happened**, but the live state object
(`AgentStateSnapshot`) is fetched from
`GET /api/v1/executions/{id}/agent_state` periodically while the run
is RUNNING:

```ts
// hooks/useAgentStatePolling.ts (helper)
function useAgentStatePolling(runId: string, dispatch: Dispatch<...>) {
  useEffect(() => {
    let cancelled = false;
    const tick = async () => {
      const snapshot = await agentService.getAgentState(runId);
      if (!cancelled) dispatch({ type: '_internal_agent_state', snapshot });
    };
    tick();
    const id = setInterval(tick, 2000);
    return () => { cancelled = true; clearInterval(id); };
  }, [runId]);
}
```

When `run.status` becomes terminal (`COMPLETED|FAILED|...`), the poll
stops. Internal `_internal_agent_state` is not a backend event; it's a
synthetic dispatch action.

### 3.5 Backwards compatibility

If `agent_loop.enabled` is OFF for the run:

* `LegacyExecutionDetail` renders, no SSE subscription change.
* AgentState rail is hidden.
* No new requests fire.

Existing runs created before T-FE-2 ships have no `feature_flags`
metadata; the flag resolves to **OFF**, so they render legacy. Safe.

---

## 4. Detailed deliverables

### 4.1 FE-T2-1 — `services/events.ts` (Day 1 AM)

Implement:

```ts
// services/events.ts
import type { AgentEvent } from '@/types';  // discriminated union from §3

export function openExecutionStream(runId: string,
                                     onEvent: (e: AgentEvent) => void,
                                     onError?: (err: Event) => void) {
  const es = new EventSource(`/api/v1/executions/${runId}/stream`,
                              { withCredentials: true });
  es.onmessage = (msg) => {
    try { onEvent(JSON.parse(msg.data) as AgentEvent); }
    catch (e) { console.warn('SSE parse error', e); }
  };
  if (onError) es.onerror = onError;
  return () => es.close();
}
```

The legacy stream subscription in `ExecutionDetail.tsx` (the one that
listens to status messages) is left in place under the legacy branch.

### 4.2 FE-T2-2 — `hooks/useExecutionEvents.ts` (Day 1 PM)

Implement the reducer skeleton per §3.3. Track-2 cases only:

* `iteration_start`
* `iteration_end`
* `resume`
* `budget_pressure` / `budget_exhausted`
* `pre_critic_block` (treat as info-only for now; T3 adds the chip)
* `_internal_agent_state` (synthetic; injects polled state)

Returns memoised `ExecutionViewState`.

### 4.3 FE-T2-3 — `services/agent.service.ts` (Day 2 AM)

```ts
// services/agent.service.ts
import { apiClient } from './api.client';
import type {
  AgentStateSnapshot, StepHealthRecord, PlanCandidatesResponse,
} from '@/types';

export const agentService = {
  async getAgentState(runId: string): Promise<AgentStateSnapshot | null> {
    try {
      const { data } = await apiClient.get<AgentStateSnapshot>(
        `/executions/${runId}/agent_state`);
      return data;
    } catch (e: any) {
      if (e?.response?.status === 404) return null;
      throw e;
    }
  },

  async getHealthRecords(runId: string): Promise<StepHealthRecord[]> {
    // Used by T-FE-3
    const { data } = await apiClient.get<{records: StepHealthRecord[]}>(
      `/executions/${runId}/health_records`);
    return data.records;
  },

  async getPlanCandidates(runId: string): Promise<PlanCandidatesResponse | null> {
    // Stub for T-FE-7
    return null;
  },
};
```

### 4.4 FE-T2-4 — Components (Days 2-4)

Implement, in order:

#### `P11BudgetBar` (Day 2 PM)

Four-segment progress bar. Per segment: label + percent + remaining.
Reads `Budget` from props. Colour-blends from teal (0%) to amber
(60%) to red (≥90%).

```tsx
<P11BudgetBar budget={budget} compact={false} />
```

Two layouts: `compact` (horizontal strip, single line) and `full`
(stacked rows; used in the AgentState rail).

#### `P11ExecutorBadge` (Day 2 PM)

Icon + label per `ExecutorName`:

| Executor | Icon | Tint |
|----------|------|------|
| DAG | `<GitFork />` | accent |
| Recursive | `<Network />` | violet |
| SingleStep | `<MoveRight />` | grey |
| ChildEntity | `<Users />` | blue |
| Dialog | `<MessageCircle />` | green |
| ToolBurst | `<Zap />` | amber |
| Skill | `<Sparkles />` | gold |

#### `P11IterationCard` (Day 3)

```tsx
<P11IterationCard
  iteration={card.iteration}
  executor={card.executor}
  resumed={card.resumed}
  outcome={card.outcome}
  decision={card.decision}
  cost_iter_usd={card.cost_iter_usd}
  healthRecords={card.healthRecords}    // empty in T2; T3 populates
  retryStrategy={card.retryStrategy}    // null in T2; T3 populates
/>
```

Header shows iteration number, executor badge, optional resume
indicator. Body renders the plan-fragment step list (re-uses existing
step rendering from legacy ExecutionDetail). Footer shows decision +
cost.

#### `P11AgentLoopTimeline` (Day 4 AM)

Wraps an array of `P11IterationCard` and applies framer-motion's
`AnimatePresence` so new iterations slide in from the bottom.

#### `P11AgentStatePanel` (Day 4 AM-PM)

Sticky right rail. Composes:

* `P11BudgetBar` (full layout).
* `P11SubgoalList` (open + achieved + blocked).
* `P11ReflectionsList` (last 5).
* "Last action" line: `<P11ExecutorBadge />` + summary.
* "Last observation" line: summary text.
* CORTEX cursor link (if present): opens CortexExplorer for the tree.

#### `P11ResumeIndicator` (Day 4 PM)

A small inline badge: `↩ resumed at iter N`.

### 4.5 FE-T2-5 — Wire everything in `AgentLoopExecutionDetail` (Day 5 AM)

```tsx
const AgentLoopExecutionDetail: React.FC<{ run: ExecutionRun }> = ({ run }) => {
  const view = useExecutionEvents(run.id);
  const isTerminal = ['COMPLETED','FAILED','PARTIAL_COMPLETE'].includes(run.status);

  return (
    <div className="agent-loop-detail">
      <ExecutionHeader run={run} budget={view.agentState?.budget} />
      <div className="loop-grid">
        <main>
          <P11AgentLoopTimeline iterations={view.iterations} />
          {isTerminal && <FinalOutputCard run={run} />}
        </main>
        <aside>
          <P11AgentStatePanel state={view.agentState} reflections={view.reflections} />
        </aside>
      </div>
    </div>
  );
};
```

### 4.6 FE-T2-6 — Sidebar nav update (Day 5 PM)

No new sidebar entries this Track. ExecutionDetail is reached from
the existing ExecutionHistory page.

### 4.7 FE-T2-7 — Tests + storybook fixtures (Day 5 PM)

Per §9.

---

## 5. Database / schema changes

N/A (frontend).

---

## 6. API changes (consumed)

| Endpoint | Status | Where used |
|----------|--------|------------|
| `GET /api/v1/executions/{id}/stream` | extended (new event types) | `services/events.ts` |
| `GET /api/v1/executions/{id}/agent_state` | NEW (backend T2) | `services/agent.service.ts` |
| `GET /api/v1/executions/{id}` | unchanged | existing |
| `GET /api/v1/executions/{id}/refine` (POST) | unchanged | existing refine button |

---

## 7. Telemetry events (frontend → backend)

Frontend doesn't emit telemetry to the backend in this Track. The
existing `apiClient` request log + `localStorage`-tracked client error
reporter continue unchanged.

Within the frontend, we add a tiny **client log** for SSE backpressure
(if events arrive faster than the reducer can flush — should never
happen, but instrumented):

```ts
console.debug('[events]', name, runId, performance.now());
```

Gated by `localStorage.debug=events`.

---

## 8. Feature flags (consumed)

| Flag | Resolved at | Effect |
|------|-------------|--------|
| `agent_loop.enabled` | per run | If ON → new layout; OFF → legacy |
| `agent_loop.snapshot_every_iteration` | global | If ON → expect frequent agent_state polls |

Initial resolution: at page load, `useFeatureFlag` reads from the
`feature_flags` map shipped with `GET /executions/{id}` (added by
backend T2). No extra HTTP call.

---

## 9. Tests

### 9.1 Unit (Vitest + React Testing Library)

* `P11BudgetBar` — renders four segments; colour transitions at
  thresholds; `compact` layout differs.
* `P11IterationCard` — shows resume indicator iff `resumed=true`;
  decision colour matches enum.
* `P11AgentStatePanel` — handles empty subgoals, empty reflections,
  null agentState gracefully (loading skeleton).
* `useExecutionEvents` — reducer cases:
  - `iteration_start` adds a card.
  - `iteration_end` mutates the right card by iteration number.
  - `resume` marks the next card.
  - Out-of-order events don't crash (no card with iter N? ignore N+1).
* `services/events.ts` — `openExecutionStream` parses JSON; bad JSON
  doesn't crash the listener.

### 9.2 Integration (RTL + MSW)

* Render `ExecutionDetail` with `agent_loop.enabled=true` and a
  mocked SSE stream emitting a 3-iteration sequence. Assert all three
  cards appear; AgentState updates.
* Render with `agent_loop.enabled=false` → legacy component appears,
  no new endpoint calls fire (MSW asserts).

### 9.3 Visual regression

* Storybook stories for each `P11*` component covering empty / loading
  / error / populated states.
* Chromatic snapshot on PR (if Chromatic is wired) — otherwise pixel
  diff via `playwright-test`'s screenshot assertion.

### 9.4 E2E (Playwright)

* `execution-agent-loop.spec.ts` — admin user triggers a fixture
  PROCESS entity, watches the iterations appear, confirms 3+ cards,
  confirms cost matches the API response on completion.

---

## 10. Acceptance criteria

1. ExecutionDetail renders the new layout when `agent_loop.enabled` is
   ON for the run.
2. AgentState rail shows live budget + subgoals; updates every 2s.
3. Iteration cards appear via SSE; resume indicator shown after a
   simulated crash + restart.
4. Legacy ExecutionDetail unchanged when flag is OFF; no extra
   requests issued.
5. All new components have stories covering empty/loading/populated.
6. Coverage on new code ≥ 75% lines.
7. Lighthouse a11y ≥ 90 on ExecutionDetail (both branches).

---

## 11. Effort breakdown (5 days)

| Day | Work |
|-----|------|
| 1 AM | FE-T2-1: events.ts |
| 1 PM | FE-T2-2: useExecutionEvents reducer (Track-2 cases) |
| 2 AM | FE-T2-3: agent.service.ts |
| 2 PM | FE-T2-4: BudgetBar + ExecutorBadge + tests |
| 3 | FE-T2-4: IterationCard + ResumeIndicator + tests |
| 4 | FE-T2-4: AgentStatePanel + ReflectionsList + Timeline + tests |
| 5 AM | FE-T2-5: wire AgentLoopExecutionDetail; flag-gated branch |
| 5 PM | FE-T2-7: integration tests + storybook stories + PR |

---

## 12. Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| SSE reconnection on flaky network | M | Iterations missed | EventSource auto-reconnects; on reconnect, refetch `/agent_state` for up-to-date snapshot; gaps in event log are filled from snapshot |
| Iteration card explosion (50+ iters) | L | UI lag | Virtualise once iterations ≥ 30 (defer to T-FE-9 if not seen) |
| AgentState polling interval too aggressive | M | Network cost | 2s interval; pauses on terminal state; admin toggle to extend |
| Backend events arrive out of order | L | Cards rendered wrong | Reducer is iteration-keyed, not append-only |
| Legacy ExecutionDetail accidentally regresses | M | Old runs look broken | Extract verbatim into `LegacyExecutionDetail.tsx`; no edits |
| Right-rail sticky positioning breaks on narrow viewport | L | Layout glitch | Media query: <1024px collapses to a stacked bottom panel |

---

## 13. Dependencies

* **Upstream:** FE-T1 (types), Backend T2 (events + `/agent_state`
  endpoint).
* **Downstream:**
  * FE-T3 extends `useExecutionEvents` and adds StepHealthStrip into
    `P11IterationCard`.
  * FE-T4 adds Supervisor verdict card.
  * FE-T5 reuses the timeline pattern for Meta-Agent Board view.
  * FE-T7 adds Plan Candidates compare from a button on the iteration
    card.

---

## 14. Open questions

* Should the iteration cards collapse by default after iteration N
  (say 5)? **Decision:** keep all expanded; add a "Collapse old" CTA
  in FE-9 if needed.
* Should we let users scroll back to old runs and **replay** the
  iteration animation? Phase 12. Track 2 just renders the final state
  on completed runs.
* Where do we show the chosen executor for iteration #1 specifically?
  Inside `P11IterationCard` header — same place as every other iter.
