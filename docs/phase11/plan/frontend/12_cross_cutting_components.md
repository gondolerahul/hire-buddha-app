# 12 — Frontend Cross-Cutting Components, Hooks, and Utilities

This file is the **catalogue** of everything reusable that Phase 11
introduces, with canonical signatures, naming rules, and which Track
introduces / consumes each piece.

If a Track adds a new component / hook / util, it MUST also add a row
here.

---

## 1. Components inventory (canonical)

### 1.1 Atoms (single-purpose, ≤80 LoC each)

| Component | File (final path, post-T9) | Track | Props (signature) |
|-----------|----------------------------|------:|-------------------|
| `BudgetBar` | `components/agent/BudgetBar.tsx` | FE-T2 | `{ budget: Budget; layout?: 'full'\|'compact' }` |
| `VerdictChip` | `components/agent/VerdictChip.tsx` | FE-T3 | `{ stage: 'PRE'\|'POST'\|'ALIGN'\|'SUPER'; verdict?: CriticVerdictKind; aligned?: boolean; drift?: number; recommendation?: SupervisorRecommendation; tags?: FailureTag[]; suggestion?: string; reasoning?: string }` |
| `FailureTagChip` | `components/agent/FailureTagChip.tsx` | FE-T3 | `{ tag: FailureTag; suggestion?: string }` |
| `ExecutorBadge` | `components/agent/ExecutorBadge.tsx` | FE-T2 | `{ executor: ExecutorName }` |
| `StatusBadge` | `components/agent/StatusBadge.tsx` | FE-T5 | `{ status: RunStatus \| EntityStatus \| ToolStatus }` |
| `TrustScoreDot` | `components/agent/TrustScoreDot.tsx` | FE-T6 | `{ score: number; size?: 'sm'\|'md' }` |
| `ProvenanceRibbon` | `components/agent/ProvenanceRibbon.tsx` | FE-T6 | `{ provenance?: Provenance }` |
| `AttributionPill` | `components/agent/AttributionPill.tsx` | FE-T8 | `{ attribution: CostAttribution; amountUsd?: string }` |
| `ConfidenceBar` | `components/agent/ConfidenceBar.tsx` | FE-T4 | `{ value: number; label?: string }` |
| `RetryStrategyBadge` | `components/agent/RetryStrategyBadge.tsx` | FE-T3 | `{ strategy: RetryStrategy }` |
| `ResumeIndicator` | `components/agent/ResumeIndicator.tsx` | FE-T2 | `{ fromIteration: number }` |
| `IntelStatusBadge` | `components/agent/IntelStatusBadge.tsx` | FE-T6 | `{ status: 'candidate'\|'confirmed'\|'retired'; evidenceCount?: number }` |
| `ToolStatusBadge` | `components/agent/ToolStatusBadge.tsx` | FE-T8 | `{ status: ToolStatus }` |
| `DraftBadge` | `components/agent/DraftBadge.tsx` | FE-T5 | `{}` (renders "DRAFT" pill) |
| `ResilienceIndicator` | `components/agent/ResilienceIndicator.tsx` | FE-T8 | `{ kind: 'reformat'\|'fallback'\|'final_empty'; from?: string; to?: string; failureKind?: string }` |
| `TaskClassTag` | `components/agent/TaskClassTag.tsx` | FE-T4 | `{ taskClass: string; entityId?: string }` |
| `PlanStyleTag` | `components/agent/PlanStyleTag.tsx` | FE-T7 | `{ style: string; judgeScore?: number }` |
| `BanditArmBadge` | `components/agent/BanditArmBadge.tsx` | FE-T4 | `{ arm: string; exploration: boolean; score?: number }` |
| `InvariantViolationBadge` | `components/agent/InvariantViolationBadge.tsx` | FE-T7 | `{ violations: string[] }` |

### 1.2 Molecules (compose atoms)

| Component | File | Track | Props |
|-----------|------|------:|-------|
| `AgentStatePanel` | `components/agent/AgentStatePanel.tsx` | FE-T2 | `{ state?: AgentStateSnapshot; reflections: Reflection[] }` |
| `StepHealthStrip` | `components/agent/StepHealthStrip.tsx` | FE-T3 | `{ record: StepHealthRecord }` |
| `IterationCard` | `components/agent/IterationCard.tsx` | FE-T2/3/7/8 (extends) | `{ card: IterationCard }` |
| `ReflectionsList` | `components/agent/ReflectionsList.tsx` | FE-T2 | `{ reflections: Reflection[] }` |
| `SupervisorVerdictCard` | `components/agent/SupervisorVerdictCard.tsx` | FE-T4 | `{ verdict: SupervisorVerdict }` |
| `ReplanDiffModal` | `components/agent/ReplanDiffModal.tsx` | FE-T4 / extended T7 | `{ oldPlan: PlanStep[]; newPlan: PlanStep[]; proposedSubgoals?: Subgoal[]; reasoning?: string; onClose: () => void }` |
| `BanditArmRow` | `components/agent/BanditArmRow.tsx` | FE-T4 | `{ arm: BanditArm; sparkline?: number[] }` |
| `PlanCandidateCard` | `components/agent/PlanCandidateCard.tsx` | FE-T7 | `{ candidate: PlanCandidate; chosen: boolean }` |
| `MemoryAssemblyStrip` | `components/agent/MemoryAssemblyStrip.tsx` | FE-T6 | `{ stats: MemoryAssemblyStats }` |
| `RoleTimelineItem` | `components/agent/RoleTimelineItem.tsx` | FE-T5 | `{ role: MetaBoardRole; state: 'queued'\|'running'\|'done'\|'blocked'; verdict?: string; durationMs?: number; costUsd?: string }` |
| `CuratorDecisionCard` | `components/agent/CuratorDecisionCard.tsx` | FE-T5 | `{ decision: 'REUSE'\|'ADAPT'\|'COMPOSE'\|'CREATE'; topCandidateId?: string }` |
| `TestDriverSuiteCard` | `components/agent/TestDriverSuiteCard.tsx` | FE-T5 | `{ cases: TestCase[]; budgetUsd: string }` |
| `PromotionOutcomeCard` | `components/agent/PromotionOutcomeCard.tsx` | FE-T5 | `{ outcome: 'PROMOTED'\|'REJECT'\|'PENDING_HITL'; entityId?: string; failedGates?: string[]; reason?: string }` |
| `AntiPatternCard` | `components/agent/AntiPatternCard.tsx` | FE-T5 | `{ pattern: AntiPattern; onSeeInstances?: () => void }` |
| `SkillCandidateCard` | `components/agent/SkillCandidateCard.tsx` | FE-T5 | `{ candidate: SkillCandidate; onPromote: () => void }` |
| `PromptUpdateCard` | `components/agent/PromptUpdateCard.tsx` | FE-T5 | `{ candidate: PromptUpdateCandidate; onApprove: () => void; onReject: () => void }` |
| `DreamingToast` | `components/agent/DreamingToast.tsx` | FE-T6 | `{ entityId: string; onDismiss: () => void }` |
| `ScopeViolationBanner` | `components/agent/ScopeViolationBanner.tsx` | FE-T6 | `{ violations: ScopeViolation[] }` |
| `CostBreakdownChart` | `components/agent/CostBreakdownChart.tsx` | FE-T8 | `{ breakdown: CostBreakdown; height?: number }` |
| `CostBreakdownTable` | `components/agent/CostBreakdownTable.tsx` | FE-T8 | `{ rows: CostBreakdownRow[] }` |
| `CriticCostGauge` | `components/agent/CriticCostGauge.tsx` | FE-T3 | `{ criticCostUsd: string; totalCostUsd: string; capPct: number }` |

### 1.3 Organisms (page-level)

| Component | File | Track |
|-----------|------|------:|
| `AgentLoopTimeline` | `components/agent/AgentLoopTimeline.tsx` | FE-T2/4 |
| `MetaAgentBoardView` | `components/agent/MetaAgentBoardView.tsx` | FE-T5 |
| `PlanCandidatesCompare` | `components/agent/PlanCandidatesCompare.tsx` | FE-T7 |
| `KPIPageLayout` | `components/admin/KPIPageLayout.tsx` | FE-T9 |
| `FeatureFlagsAdminPanel` | `components/admin/FeatureFlagsAdminPanel.tsx` | FE-T9 |
| `ExperimentalToolsAdminPanel` | `components/admin/ExperimentalToolsAdminPanel.tsx` | FE-T8 |
| `PhaseElevenTour` | `components/onboarding/PhaseElevenTour.tsx` | FE-T9 |

> Note: pre-FE-T9, every component above ships with a `P11` prefix.
> FE-T9 renames + keeps re-export shims.

---

## 2. Hooks inventory

| Hook | File | Track | Signature |
|------|------|------:|-----------|
| `useFeatureFlag` | `hooks/useFeatureFlag.ts` | FE-T2 (cross-Track infra) | `(key: string, options?: { scope?: 'global'\|'company'\|'entity'\|'run'; entityId?: string; runId?: string; defaultValue?: boolean \| string \| number }) => boolean \| string \| number` |
| `useSSE` | `hooks/useSSE.ts` | FE-T2 | `<T>(url: string, options?: { enabled?: boolean }) => { latest: T \| null; all: T[]; close: () => void }` |
| `useExecutionEvents` | `hooks/useExecutionEvents.ts` | FE-T2 | `(runId: string, options?: { enabled?: boolean }) => ExecutionViewState` |
| `useAgentState` | `hooks/useAgentState.ts` | FE-T2 | `(runId: string) => AgentStateSnapshot \| null` |
| `useAgentStatePolling` | `hooks/useAgentStatePolling.ts` | FE-T2 | `(runId: string, dispatch: Dispatch) => void` (side-effect only) |
| `useBandit` | `hooks/useBandit.ts` | FE-T4 | `(entityId: string, taskClass?: string) => { tasks: Array<{ task_class: string; arms: BanditArm[] }> \| null }` |
| `useHealthRecords` | `hooks/useHealthRecords.ts` | FE-T3 | `(runId: string) => StepHealthRecord[] \| null` |
| `usePlanCandidates` | `hooks/usePlanCandidates.ts` | FE-T7 | `(runId: string) => PlanCandidatesResponse \| null` |
| `usePlanHistory` | `hooks/usePlanHistory.ts` | FE-T7 | `(runId: string) => PlanHistoryResponse \| null` |
| `useKpiRollup` | `hooks/useKpiRollup.ts` | FE-T9 | `(page: KPIPageName, filters: KPIFilters) => KPIResponse` |
| `useExperimentalTools` | `hooks/useExperimentalTools.ts` | FE-T8 | `() => ExperimentalToolRow[] \| null` |
| `useIntelligenceRules` | `hooks/useIntelligenceRules.ts` | FE-T6 | `(entityId: string, status?: 'candidate'\|'confirmed'\|'retired') => IntelRule[]` |
| `useDreamingHistory` | `hooks/useDreamingHistory.ts` | FE-T6 | `(entityId: string) => DreamingRun[]` |
| `useSkillCandidates` | `hooks/useSkillCandidates.ts` | FE-T5 | `() => SkillCandidate[]` |
| `useAntiPatterns` | `hooks/useAntiPatterns.ts` | FE-T5 | `(filters?: { severity?: string; entityType?: string }) => AntiPattern[]` |
| `usePromptCandidates` | `hooks/usePromptCandidates.ts` | FE-T5 | `() => PromptUpdateCandidate[]` |
| `useCostBreakdown` | `hooks/useCostBreakdown.ts` | FE-T8 | `(opts: { runId?: string; companyId?: string; since?: string }) => CostBreakdown \| null` |
| `useDebouncedSave` | `hooks/useDebouncedSave.ts` | FE-T5 | `<T>(value: T, save: (v: T) => Promise<void>, ms: number) => void` |

All hooks are **read-mostly**. Mutating actions go through services
directly + `useState`-driven optimistic updates.

---

## 3. Services inventory

| Service | File | Track |
|---------|------|------:|
| `apiClient` | `services/api.client.ts` | existing |
| `agentService` | `services/agent.service.ts` | FE-T2 |
| `metaService` | `services/meta.service.ts` | FE-T5 |
| `memoryService` | `services/memory.service.ts` | FE-T6 |
| `costService` | `services/cost.service.ts` | FE-T8 |
| `kpiService` | `services/kpi.service.ts` | FE-T9 |
| `featureFlagsService` | `services/feature_flags.service.ts` | FE-T2 (read), FE-T9 (admin write) |
| `eventsModule` | `services/events.ts` | FE-T2 (extended every Track) |

Mutation conventions:

* `service.mutateX()` returns the updated resource so the caller can
  optimistically update.
* All POST/PUT/DELETE go through `apiClient` (axios). Errors are
  caught at the caller and surfaced via a single `toast.error(...)`
  helper.

---

## 4. Utilities

| Util | File | Track |
|------|------|------:|
| `formatBudget` | `utils/formatBudget.ts` | FE-T2 (pretty-prints Budget) |
| `formatCost` | `utils/formatCost.ts` | FE-T8 (Decimal → "$0.084") |
| `verdictTint` | `utils/verdictTint.ts` | FE-T3 (verdict → CSS class) |
| `failureTagIcon` | `utils/failureTagIcon.ts` | FE-T3 (tag → icon) |
| `executorIcon` | `utils/executorIcon.ts` | FE-T2 |
| `diffPlanSteps` | `utils/diffPlanSteps.ts` | FE-T7 (old/new step list → diff records) |
| `truncate` | `utils/truncate.ts` | shared (cap strings for tooltips) |
| `toastError` / `toastSuccess` | `utils/toast.ts` | shared (mountable in MainLayout) |

---

## 5. Routes inventory

```ts
// router/index.tsx (after Phase 11)
<Route path="/executions/:id" element={<ExecutionDetail />} />
<Route path="/executions/:id/health" element={<HealthRecordsPage />} />              {/* FE-T3 */}
<Route path="/entities/:id/bandit-state" element={<BanditStatePanel />} />            {/* FE-T4 */}

<Route path="/meta-agent" element={<MetaAgentDashboard />} />                          {/* FE-T5 */}
<Route path="/meta-agent/runs/:id" element={<MetaAgentRunDetail />} />                 {/* FE-T5 */}
<Route path="/meta-agent/anti-patterns" element={<AntiPatternsBrowser />} />           {/* FE-T5 */}
<Route path="/meta-agent/skill-candidates" element={<SkillCandidatesPanel />} />       {/* FE-T5 */}
<Route path="/meta-agent/prompt-candidates" element={<PromptUpdateQueue />} />         {/* FE-T5 */}

<Route path="/admin/feature-flags" element={<FeatureFlagsAdmin />} />                  {/* FE-T9 */}
<Route path="/admin/experimental-tools" element={<ExperimentalTools />} />             {/* FE-T8 */}
<Route path="/admin/cost-attribution" element={<CostAttributionDashboard />} />        {/* FE-T8 */}
<Route path="/admin/kpi-dashboard" element={<KPIDashboard />} >                        {/* FE-T9 */}
  <Route index element={<Navigate to="run-health" replace />} />
  <Route path="run-health" element={<KPIRunHealth />} />
  <Route path="cost" element={<KPICost />} />
  <Route path="critic" element={<KPICritic />} />
  <Route path="meta-agent" element={<KPIMetaAgent />} />
  <Route path="memory" element={<KPIMemory />} />
  <Route path="loop" element={<KPILoop />} />
</Route>
```

All routes are admin-gated via `<ProtectedRoute allowedRoles={['app_admin', 'tenant_admin']}>`.

---

## 6. CSS conventions

* Each component owns a `Component.css` file with class names
  `component-name__element--modifier` (BEM-light).
* Tokens live in `src/styles/tokens.css` (the existing file or a new
  one). New tokens introduced this programme:

  | Token | Purpose |
  |-------|---------|
  | `--success` | already exists |
  | `--warn` | new — used by REVISE / EXPERIMENTAL |
  | `--error` | exists |
  | `--info` | exists |
  | `--accent` | exists |
  | `--tint-0` to `--tint-3` | severity scale for FailureTag |
  | `--glass-blur` | existing |
  | `--p11-iter-card-bg` | iteration card background |
  | `--p11-state-bg` | AgentStatePanel background |

* Animations: framer-motion `LayoutGroup` for the iteration timeline
  to avoid layout jank.

* Charts: use `useChartTheme()` (new helper) which reads CSS tokens
  and feeds them to recharts.

---

## 7. Naming rules

1. Phase-11 components use `P11<Name>` until FE-T9, then drop the
   prefix.
2. New hooks: `use<Domain><Action>` (e.g. `useHealthRecords`,
   `useBandit`).
3. New services: `<domain>.service.ts` exporting one const
   `<domain>Service`.
4. New types: PascalCase interfaces; UPPER_SNAKE_CASE for enums (TS
   enum names PascalCase; values UPPER_SNAKE).
5. Event types: discriminated union with `type` literal.

---

## 8. Boundary contracts

* **Components MUST NOT** call services directly. They consume hooks.
* **Hooks MAY** call services and SSE; they own caching / polling.
* **Services MUST NOT** depend on hooks or components.
* **Reducer (`useExecutionEvents`)** is the SINGLE writer to derived
  state for a live run. No other hook mutates that state.
* **Feature flags are read** by hooks; components receive resolved
  booleans/values.

---

## 9. Shared empty / loading / error states

A single helper, `<DataState />`, accepts `{ loading, error, empty,
children }` and ensures consistency:

```tsx
<DataState loading={!data} error={err} empty={data?.length === 0}>
  {/* normal content */}
</DataState>
```

Default skeletons match GlassCard styling.

---

## 10. Codegen + lint enforcement (post-Phase 11)

`scripts/check_component_contracts.ts`:

* Every component in `components/agent/` must export a single named
  React component.
* Every component must have a co-located `.test.tsx`.
* Every component must have a `.stories.tsx` (Storybook) OR a
  `.snapshots.spec.ts` (Playwright pixel diff) — at least one.
* No new `P11*.tsx` filenames anywhere in `src/`.

Hooked into pre-commit alongside the existing lint.

---

## 11. Versioning of types vs runtime

* Pydantic→TS codegen produces `types/_generated.ts`. Treat as
  immutable — every backend Pydantic change forces a regen + a CI
  diff catch.
* Handwritten files in `types/` may add UI-only fields, but must keep
  any field shape consistent with `_generated.ts` for the same name.

---

## 12. What this catalogue is NOT

* Not a substitute for the per-Track files. Each Track owns the
  *behaviour* and *acceptance*.
* Not a design system. Visual rules live in `styles/tokens.css` and
  per-component CSS.
* Not a list of every component in the app — only the additions.
