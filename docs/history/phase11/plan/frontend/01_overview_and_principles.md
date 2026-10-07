# 01 — Frontend Overview & Principles

This document fixes the **frontend architecture decisions** that
constrain every Track that follows.

If a Track conflicts with anything here, this document wins.

---

## 1. Target state (one picture)

```
                      ┌──────────────────────────┐
                      │      MainLayout          │
                      │   (sidebar + breadcrumbs)│
                      └─────────────┬────────────┘
                                    │
       ┌──────────────────┬─────────┴───────────┬──────────────────┐
       │                  │                     │                  │
   /entities          /executions          /meta-agent          /admin
   EntityLibrary     ExecutionHistory      MetaAgentBoard      FeatureFlags
   EntityBuilder     ExecutionDetail◄──┐   AntiPatterns       Experimental
                          │            │   SkillCandidates    Tools
                          │            │   PromptUpdates      KPIDashboard
                          ▼            │
   ┌───────────────────────────────────┴──┐
   │  EXECUTION DETAIL — agent-loop ready │
   │                                      │
   │  ┌─────────────┐   ┌────────────────┐│
   │  │ Iteration   │   │ AgentState     ││
   │  │  Timeline   │   │  Pane          ││
   │  │             │   │  Budget bar    ││
   │  │  ─ iter N   │   │  Subgoals      ││
   │  │  ─ iter N+1 │   │  Reflections   ││
   │  │     +health │   │  Cortex cursor ││
   │  │     +retry  │   └────────────────┘│
   │  └─────────────┘                     │
   │                                      │
   │  Legacy step list (flag OFF) ────────┤
   └──────────────────────────────────────┘
                       ▲
                       │ SSE
                       │
            services/events.ts (typed)
                       ▲
                       │ feeds
            useExecutionEvents (reducer hook)
                       ▲
                       │ uses
            services/api.client.ts + agent.service.ts
                                       meta.service.ts
                                       memory.service.ts
                                       kpi.service.ts
                                       feature_flags.service.ts
```

Three observations:

1. **ExecutionDetail is the centre of the universe.** Most Phase-11
   work either lands here or is reached from here.
2. **Meta-Agent gets its own route family.** Roles are first-class.
3. **Services are typed; events are typed; pages compose hooks that
   wrap services + events.** No untyped fetches; no untyped event
   listeners.

---

## 2. Six principles

### P1 — One typed surface for every backend boundary

`api.client.ts` (existing) + per-domain `*.service.ts` files own
HTTP. `services/events.ts` (NEW) owns SSE. Pages never call `fetch`
directly.

**Implication:** adding a new endpoint or event = update the service
file first.

### P2 — Feature-flag-driven rendering

Every Phase-11 UI is gated by the corresponding backend feature flag.
If the flag is OFF for the entity / company, the **legacy** UI renders.
There is no parallel "Phase 11 only" route; the SAME `ExecutionDetail`
route picks its layout per-run.

**Implication:** components must accept "legacy mode" props (often
`{ legacy: true }`) and degrade.

### P3 — SSE is the source of truth for live runs

While a run is `RUNNING`, the page is **event-driven**, not polling.
A central reducer keeps the derived state. When the run reaches a
terminal state, the page re-fetches `GET /executions/{id}` once and
becomes static.

**Implication:** no setInterval-based refresh. Events define the page.

### P4 — Typed enums everywhere

`StepType`, `RunStatus`, `EntityType`, `EntityStatus`, `FailureTag`,
`ExecutorName`, `ReasoningMode`, `HITLTriggerType`, `ToolStatus` are
TypeScript `enum`s mirroring the backend Pydantic enums. Strings are
not accepted at component boundaries.

**Implication:** components have exhaustive `switch` checks; TS
catches "did you forget a case?" at compile time.

### P5 — Typed reducer state, not prop drilling

ExecutionDetail uses one reducer hook that owns:

```ts
interface ExecutionViewState {
  run: ExecutionRun | null;
  agentState: AgentStateSnapshot | null;
  iterations: IterationCard[];          // built from events
  healthRecords: StepHealthRecord[];    // from events
  reflections: Reflection[];
  banditChoices: BanditChoiceEvent[];
  supervisorVerdicts: SupervisorVerdict[];
  planCandidates: PlanCandidatesResponse | null;
  budget: Budget | null;
  cortexTreeId: string | null;
  pendingHITL: HumanApproval[];
}
```

All children receive slices via context — no prop drilling >2 levels.

### P6 — Style discipline

* Reuse `GlassCard` / `JellyButton` / `GlassInput` from
  `components/ui/`.
* Per-component `.css` files for layout; CSS variables for tokens
  (`--accent`, `--text`, `--bg-glass`).
* Icons from `lucide-react`.
* Charts from `recharts` (already in deps).
* No new design system. No new icon set.

---

## 3. Type system additions

### 3.1 Typed enums (mirror backend)

```ts
// types/enums.ts (NEW — split out of types/index.ts in FE-1)
export enum StepType {
  THOUGHT = 'THOUGHT',
  ACTION = 'ACTION',
  TOOL_CALL = 'TOOL_CALL',
  CHILD_ENTITY_INVOCATION = 'CHILD_ENTITY_INVOCATION',
  NAVIGATE = 'NAVIGATE',
  READ = 'READ',
  WRITE = 'WRITE',
  RECURSE = 'RECURSE',
  AWAIT_CHILDREN = 'AWAIT_CHILDREN',
}

export enum FailureTag {
  OFF_TOPIC = 'OFF_TOPIC',
  HALLUCINATION = 'HALLUCINATION',
  INCOMPLETE = 'INCOMPLETE',
  WRONG_FORMAT = 'WRONG_FORMAT',
  TOOL_FAILURE = 'TOOL_FAILURE',
  CONTRADICTION = 'CONTRADICTION',
  UNVERIFIABLE = 'UNVERIFIABLE',
  POLICY_VIOLATION = 'POLICY_VIOLATION',
  UNDER_BUDGET = 'UNDER_BUDGET',
  OVER_BUDGET = 'OVER_BUDGET',
  BLOCKED_DEPENDENCY = 'BLOCKED_DEPENDENCY',
  NEEDS_CLARIFICATION = 'NEEDS_CLARIFICATION',
}

export type ExecutorName =
  | 'DAG' | 'Recursive' | 'SingleStep' | 'ChildEntity'
  | 'Dialog' | 'ToolBurst' | 'Skill';

export type CriticVerdictKind =
  | 'PASS' | 'BLOCK' | 'REVISE' | 'REJECT';

export type SupervisorRecommendation =
  | 'CONTINUE' | 'REPLAN' | 'ABORT' | 'PAUSE';

export type RetryStrategy =
  | 'NONE' | 'RETRY_AS_IS' | 'RETRY_DIFFERENT_MODEL'
  | 'RETRY_DIFFERENT_PROMPT' | 'RETRY_DIFFERENT_TOOL'
  | 'ASK_USER' | 'ABANDON';

export type ToolStatus = 'ACTIVE' | 'EXPERIMENTAL' | 'DEPRECATED';

export type CostAttribution =
  | 'planner' | 'actor_step' | 'critic_pre' | 'critic_post'
  | 'critic_align' | 'critic_super' | 'reformat_retry'
  | 'meta_review' | 'dreaming' | 'tool' | 'child_run'
  | 'embedding' | 'meta_spec_critic' | 'test_driver';

export type MetaBoardRole =
  | 'RequirementChat' | 'Curator' | 'Architect' | 'Critic'
  | 'Validator' | 'TestDriver' | 'Promoter';
```

### 3.2 New dataclasses (mirror backend §4)

```ts
// types/agent_state.ts (NEW)
export interface Budget {
  tokens_max: number;       tokens_used: number;
  usd_max: string;          usd_used: string;     // decimal as string
  wall_max_s: number;       wall_used_s: number;
  iters_max: number;        iters: number;
  pressure: number;         // 0..1, server-computed
}

export interface Subgoal {
  id: string;
  description: string;
  parent_id?: string;
  priority: number;
  blocked_on?: string | null;
  achieved: boolean;
}

export interface Reflection {
  iteration: number;
  scope: 'run' | 'entity' | 'task_class';
  what_worked: string;
  what_didnt: string;
  cause_hypothesis: string;
  proposed_change: string;
  confidence: number;
}

export interface AgentStateSnapshot {
  run_id: string;
  iteration: number;
  budget: Budget;
  open_subgoals: Subgoal[];
  achieved_subgoals: Subgoal[];
  blockers: Array<{
    kind: 'missing_tool'|'missing_data'|'awaiting_hitl'|'budget'|'error';
    detail: string;
    related_subgoal_id?: string;
  }>;
  hypotheses: Array<{
    id: string;
    claim: string;
    evidence_node_ids: string[];
    confidence: number;
  }>;
  last_action_summary: string;
  last_observation_summary: string;
  cortex_cursor?: string;
  chosen_executor?: ExecutorName;
}

export interface StepHealthRecord {
  record_id: string;
  step_id: string;
  iteration: number;
  move_id: string;
  pre_critic_verdict?: 'PASS' | 'BLOCK' | 'REVISE';
  pre_critic_concerns: string[];
  pre_critic_cost_usd: string;
  post_critic_verdict?: 'PASS' | 'REVISE' | 'REJECT';
  post_critic_tags: FailureTag[];
  post_critic_suggestion: string;
  post_critic_cost_usd: string;
  alignment_aligned?: boolean;
  alignment_drift?: number;
  alignment_cost_usd: string;
  supervisor_recommendation?: SupervisorRecommendation;
  supervisor_reasoning?: string;
  supervisor_cost_usd: string;
  total_latency_ms: number;
}
```

### 3.3 Discriminated event union

```ts
// services/events.ts (NEW)
export type AgentEvent =
  // Loop
  | { type: 'iteration_start'; iteration: number; executor: ExecutorName; budget_pressure: number; open_subgoals: number }
  | { type: 'iteration_end'; iteration: number; outcome: 'success'|'partial'|'fail'; decision: 'CONTINUE'|'DONE'|'PAUSE_HITL'|'ABORT'; cost_iter_usd: string }
  | { type: 'budget_pressure'; iteration: number; pressure: number }
  | { type: 'budget_exhausted'; iteration: number; dim: 'tokens'|'usd'|'wall'|'iters' }
  | { type: 'resume'; from_iteration: number }
  | { type: 'pre_critic_block'; iteration: number; concerns: string[] }

  // Critic
  | { type: 'critic_pre'; iteration: number; verdict: 'PASS'|'BLOCK'|'REVISE'; concerns?: string[]; cost_usd: string }
  | { type: 'critic_post'; iteration: number; verdict: 'PASS'|'REVISE'|'REJECT'; tags: FailureTag[]; suggestion?: string; cost_usd: string; model_used: string }
  | { type: 'critic_align'; iteration: number; aligned: boolean; drift: number; cost_usd: string }
  | { type: 'critic_super'; iteration: number; recommendation: SupervisorRecommendation; confidence: number; reasoning?: string; proposed_subgoals?: Subgoal[] }
  | { type: 'retry_queued'; iteration: number; strategy: RetryStrategy }
  | { type: 'retry_exhausted'; iteration: number; last_strategy: RetryStrategy }

  // Bandit
  | { type: 'bandit_arm'; iteration: number; task_class: string; candidates: string[]; chosen: string; exploration: boolean }
  | { type: 'bandit_arm_updated'; arm: string; pulls: number; successes: number; avg_cost_usd: number; score: number }
  | { type: 'replan_triggered'; iteration: number; by: 'supervisor'|'critic'|'failure'; proposed_subgoals_count: number }

  // Memory
  | { type: 'memory_assembled'; domains: string[]; knowledge_refs: number; intelligence_rules: number; episodic_context: number; prompt_chars: number }
  | { type: 'dreaming_triggered'; entity_id: string; reason: 'success'|'failure'|'cron' }
  | { type: 'intelligence_candidate_added'; entity_id: string; scope: 'entity'|'task_class' }
  | { type: 'memory_scope_violation'; subtree_root_id: string; attempted_parent_id: string }

  // Plan
  | { type: 'plan_candidates'; candidates_kept: number; chosen_style: string; estimated_cost_usd: string }
  | { type: 'plan_invariant_violations'; candidates_rejected: number; violations: string[] }
  | { type: 'plan_judge_decision'; winner_idx: number; scores: number[] }
  | { type: 'plan_chosen'; style: string; expected_cost_usd: string; alternates: string[] }
  | { type: 'plan_replan'; by: 'supervisor'|'critic'; reason: string; new_steps: number }

  // Meta-Agent
  | { type: 'meta_role_started'; role: MetaBoardRole; iteration: number }
  | { type: 'meta_role_completed'; role: MetaBoardRole; verdict?: string; concerns_count?: number; cost_usd: string }
  | { type: 'meta_test_case'; name: 'smoke'|'comparative'|'boundary'|'regression'|'hostile'; passed: boolean; cost_usd: string }
  | { type: 'meta_testdriver_suite_completed'; passed_cases: number; total_cases: number; cost_usd: string }
  | { type: 'meta_promotion'; outcome: 'PROMOTED'|'REJECT'|'PENDING_HITL'; entity_id?: string; reason?: string; failed_gates?: string[] }
  | { type: 'meta_curator_decision'; decision: 'REUSE'|'ADAPT'|'COMPOSE'|'CREATE'; top_candidate_id?: string }

  // Cost
  | { type: 'cost_charged'; attribution: CostAttribution; sku?: string; amount_usd: string; latency_ms: number }

  // Tool resilience
  | { type: 'tool_reformat_attempt'; tool_id: string; failure_kind: string }
  | { type: 'tool_fallback_taken'; from_tool: string; to_tool: string; success: boolean }
  | { type: 'tool_final_empty'; tool_id: string; failure_kind: string }
  ;
```

This discriminated union is the **canonical** event surface. The
`useExecutionEvents` reducer in `hooks/useExecutionEvents.ts` is the
only consumer in the codebase.

### 3.4 Reducer hook signature

```ts
// hooks/useExecutionEvents.ts (NEW)
export function useExecutionEvents(
  runId: string,
  options?: { enabled?: boolean }
): ExecutionViewState {
  // Opens SSE, dispatches events through a single reducer.
  // Returns memoised view state.
  // When run is in a terminal state, cleans up SSE and returns final state.
}
```

---

## 4. Routing additions

| Route | Page | Roles | Phase |
|-------|------|-------|------:|
| `/executions/:id` (existing) | `ExecutionDetail` (revamped) | all | T-FE-2 |
| `/meta-agent` | `MetaAgentDashboard` (NEW) | admin | T-FE-5 |
| `/meta-agent/runs/:id` | `MetaAgentRunDetail` (NEW, embeds RoleTimeline) | admin | T-FE-5 |
| `/meta-agent/anti-patterns` | `AntiPatternsBrowser` (NEW) | admin | T-FE-5 |
| `/meta-agent/skill-candidates` | `SkillCandidatesPanel` (NEW) | admin | T-FE-5 |
| `/meta-agent/prompt-candidates` | `PromptUpdateQueue` (NEW) | admin | T-FE-5 |
| `/entities/:id/bandit-state` | `BanditStatePanel` (NEW, admin) | admin | T-FE-4 |
| `/admin/feature-flags` | `FeatureFlagsAdmin` (NEW) | admin | T-FE-9 |
| `/admin/experimental-tools` | `ExperimentalToolsAdmin` (NEW) | admin | T-FE-8 |
| `/admin/kpi-dashboard` | `KPIDashboard` (NEW; 6 sub-pages) | admin | T-FE-9 |
| `/admin/cost-attribution` | `CostAttributionDashboard` (NEW) | admin | T-FE-8 |

All under existing `MainLayout`. New nav items added to sidebar (admin-gated).

---

## 5. Service files inventory

| Service file | Status | Purpose |
|--------------|--------|---------|
| `services/api.client.ts` | existing | Axios instance + 401 refresh |
| `services/auth.service.ts` | existing | login / token refresh |
| `services/ai-config.service.ts` | existing | AI config admin |
| `services/cortex.service.ts` | existing | CORTEX HTTP |
| `services/tool.service.ts` | existing | Tool listing |
| `services/template.service.ts` | existing | Templates |
| `services/billing.service.ts` | existing | billing |
| `services/agent.service.ts` | **NEW (T-FE-2)** | AgentState, HealthRecords, plan candidates |
| `services/meta.service.ts` | **NEW (T-FE-5)** | Meta-Agent: skill candidates, anti-patterns, prompt candidates, promotion |
| `services/memory.service.ts` | **NEW (T-FE-6)** | Provenance, intelligence candidate lifecycle |
| `services/feature_flags.service.ts` | **NEW (T-FE-13)** | Flag read + admin set |
| `services/kpi.service.ts` | **NEW (T-FE-9)** | KPI rollup queries |
| `services/cost.service.ts` | **NEW (T-FE-8)** | Cost-by-attribution |
| `services/events.ts` | **NEW (T-FE-2)** | Typed SSE event union + helpers |

---

## 6. Shared hooks inventory

| Hook | Status | Purpose |
|------|--------|---------|
| `useAuth` | existing | auth state |
| `useFeatureFlag(key)` | **NEW (FE-13)** | resolves a flag for the current user / company / entity |
| `useExecutionEvents(runId)` | **NEW (FE-2)** | SSE-driven derived state for an execution |
| `useAgentState(runId)` | **NEW (FE-2)** | Slice of the above: just the live AgentState |
| `useBandit(entityId, taskClass)` | **NEW (FE-4)** | Per-(entity, task_class) bandit arm table |
| `useKpiRollup(filters)` | **NEW (FE-9)** | KPI dashboard data |
| `useDebouncedSave(value, fn, ms)` | shared util (NEW) | Used by inline editors (skill promote, anti-pattern annotate) |
| `useSSE<T>(url)` | NEW helper | Low-level wrapper over `EventSource` returning the latest typed event + array of all events |

---

## 7. Component library additions (P11 prefix)

### 7.1 Atoms

| Component | What it shows |
|-----------|---------------|
| `P11BudgetBar` | Multi-segment progress: tokens / USD / wall / iters |
| `P11VerdictChip` | Coloured chip per `CriticVerdictKind`; tooltip with reasoning |
| `P11FailureTagChip` | Coloured chip per `FailureTag`; severity-tinted |
| `P11ExecutorBadge` | Icon + label per `ExecutorName` |
| `P11StatusBadge` | Reused across run / entity / tool status |
| `P11TrustScoreDot` | Small dot, hue from 0..1 trust |
| `P11ProvenanceRibbon` | Source type + tool/url + fetched-at |
| `P11AttributionPill` | Cost attribution label (planner / critic / tool / etc.) |
| `P11ConfidenceBar` | 0-100% bar, used for critic/supervisor confidence |

### 7.2 Molecules

| Component | Composition |
|-----------|-------------|
| `P11AgentStatePanel` | Budget bar + open subgoals + last action/observation + reflections list |
| `P11StepHealthStrip` | One row of 4 verdict chips per record |
| `P11IterationCard` | Iteration N header + executor badge + plan fragment + step health + retry badge |
| `P11ReflectionsList` | List of reflections, scope-coloured |
| `P11RoleTimelineItem` | One Meta-Agent role with verdict + cost |
| `P11PlanCandidateCard` | Steps + cost + invariant ribbon + judge score |
| `P11BanditArmRow` | Arm name + pulls / wins / cost / score, with sparkline |
| `P11AntiPatternCard` | Title + severity + evidence count + suggestion |
| `P11SkillCandidateCard` | Chain summary + frequency + Promote CTA |
| `P11PromotionOutcomeCard` | PROMOTED / REJECT / PENDING_HITL with failed gates |
| `P11CostBreakdownChart` | Stacked bar of cost-by-attribution |

### 7.3 Organisms

| Component | Composition |
|-----------|-------------|
| `P11AgentLoopTimeline` | Stack of IterationCard, with sticky AgentStatePanel side rail |
| `P11MetaAgentBoardView` | Top-to-bottom RoleTimeline + final PromotionOutcomeCard |
| `P11FeatureFlagsAdminPanel` | Table of flags, scope filter, edit modal |
| `P11ExperimentalToolsAdminPanel` | Tool list + per-company enable toggles |
| `P11KPIDashboardPage` (×6) | Filters + recharts panels + table |

---

## 8. UX states to design (please mock before building)

For each new component, three states need a designed look:

* **Empty / not yet** — e.g. no health records yet, no candidates yet.
* **Loading** — skeleton placeholders consistent with `GlassCard` style.
* **Error** — friendly message + retry button (uses `JellyButton`).

The legacy components already have these; new components mirror them.

---

## 9. Accessibility constraints

* All new pages: keyboard navigable (tab + enter).
* Verdict chips have `aria-label` describing the verdict and reasoning.
* Live regions (`aria-live="polite"`) on the iteration timeline so
  screen readers announce new iterations.
* Colour is **never** the sole signal: each chip pairs a colour with an
  icon (e.g. ✅ PASS, ⚠️ REVISE, ❌ REJECT, 🛑 BLOCK).
* Lighthouse a11y ≥ 90 on every new page; CI runs `axe-core` via
  Playwright.

---

## 10. Backwards compatibility

* Existing routes unchanged. Renamed pages keep their default export
  to avoid `lazy()` import drift.
* `ExecutionDetail` reads the new `agent_loop.enabled` flag for the
  RUN (not the user) and renders either the new layout or the legacy
  step list — never both.
* `ExecutionHistory` is unchanged this programme (Phase 12 may add a
  bandit-arm column).
* Sidebar additions are gated by `useFeatureFlag('agent_loop.enabled',
  { scope: 'company' })` so non-Phase-11 tenants see no new nav.

---

## 11. Performance constraints

* AgentLoop timelines can reach 30+ iterations. Use virtualised lists
  (`react-window` if needed; not yet in deps — add only if 60+ items
  becomes common).
* StepHealthStrip animations use framer-motion's `LayoutGroup` to
  avoid jank.
* SSE reducer is memoised; iteration cards are `React.memo`-wrapped
  with a `(prev, next) => prev.iteration === next.iteration`
  comparator.
* KPI dashboards use server-aggregated data (`kpi_daily_rollup` view);
  no client-side aggregation over thousands of rows.

---

## 12. Definition of "frontend Track done"

Each frontend Track exits when:

1. Components from §7 listed by that Track exist and render in every
   UX state from §8.
2. Service / events files updated per §3.3, §5.
3. Routes from §4 registered.
4. Unit tests with ≥75% coverage on new components.
5. Playwright smoke covers the happy path of the Track.
6. `npm run lint` clean, no warnings.
7. Lighthouse a11y ≥ 90 on touched pages.
8. The feature flag is wired (rendering legacy UI when flag is OFF).

These are the gates referenced by each Track's §10 "Acceptance".
