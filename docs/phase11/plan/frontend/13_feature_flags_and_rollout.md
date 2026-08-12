# 13 — Frontend Feature Flags & Rollout

This document defines **how the frontend resolves backend feature
flags**, how feature-flag-driven UI degrades, and how each frontend
Track is rolled out alongside its backend counterpart.

---

## 1. Principles

* The **backend is the source of truth** for flag state. The frontend
  reads flag state from one endpoint and re-renders.
* **Every Phase-11 UI component degrades gracefully** when its flag is
  OFF. There is no broken state where flag-off shows half-built UI.
* **Flag state is per-(user, company, entity, run)** as the backend
  resolves it. The frontend treats every flag read as a resolved
  boolean/value for the current scope.
* **Refresh is push-based**: WebSocket fan-out on the `feature_flags`
  channel triggers a re-fetch. No polling.
* **Flag failure mode is OFF**. If the backend doesn't return a flag,
  the UI assumes the flag is off and renders the legacy path.
* **Admin can override per company / per entity** from the Feature
  Flags admin page (FE-T9).

---

## 2. Architecture

### 2.1 The single source endpoint

```
GET /api/v1/feature_flags/me

Response:
{
  "global": {
    "agent_loop.enabled": true,
    "critic_pipeline.v2_enabled": true,
    "bandit.enabled": true,
    "bandit.epsilon": 0.10,
    ...
  },
  "company": {
    "agent_loop.enabled": null,            // inherit global
    "meta_agent.board_routing": true,      // company override
    "tools.experimental.video_generation": true
  },
  "entity": {
    // optional; populated when an entity_id is in query string
  }
}
```

The frontend stores this in a top-level context (`FeatureFlagsContext`)
created at app boot.

### 2.2 The hook

```ts
// hooks/useFeatureFlag.ts
export function useFeatureFlag<T = boolean>(
  key: string,
  options?: {
    scope?: 'global' | 'company' | 'entity' | 'run';
    entityId?: string;
    runId?: string;
    runMeta?: Record<string, unknown>;
    defaultValue?: T;
  }
): T {
  const ctx = useContext(FeatureFlagsContext);
  // 1. Highest priority: per-run override from the run.input_data.feature_flags
  if (options?.runMeta && key in options.runMeta) {
    return options.runMeta[key] as T;
  }
  // 2. Per-entity
  if (options?.scope === 'entity' && options.entityId) {
    const val = ctx.entity[options.entityId]?.[key];
    if (val !== undefined && val !== null) return val as T;
  }
  // 3. Per-company
  const companyVal = ctx.company[key];
  if (companyVal !== undefined && companyVal !== null) return companyVal as T;
  // 4. Global
  const globalVal = ctx.global[key];
  if (globalVal !== undefined && globalVal !== null) return globalVal as T;
  // 5. Default
  return options?.defaultValue ?? (false as unknown as T);
}
```

### 2.3 The push channel

A WebSocket (existing infra) listens for the `feature_flags` channel
and triggers a re-fetch of `GET /feature_flags/me` when a relevant
flag changes. If WebSocket isn't available (older browsers, blocked
networks), the FeatureFlagsContext falls back to a 60s polling
interval.

### 2.4 The admin write path

`services/feature_flags.service.ts`:

```ts
export const featureFlagsService = {
  async list(scope?: 'global'|'company'|'entity'): Promise<FlagRow[]> { ... },
  async set(row: {
    flag_key: string;
    enabled?: boolean;
    value_json?: unknown;
    company_id?: string;
    entity_id?: string;
  }): Promise<FlagRow> { ... },
  async delete(id: string): Promise<void> { ... },
};
```

After a write, the backend pushes a WebSocket message; the frontend
re-fetches.

---

## 3. Per-Track flag references

Each frontend Track lists the flags it consumes. The table below is the
**single rollup**.

| Flag | Consumed by | UI effect |
|------|-------------|-----------|
| `agent_loop.enabled` | FE-T2 (ExecutionDetail branch) | OFF → legacy step list |
| `agent_loop.snapshot_every_iteration` | FE-T2 | Increases AgentState polling frequency |
| `agent_loop.executor_dialog_enabled` | FE-T5 (Dialog executor stub) | Hidden until backend stub fills |
| `agent_loop.executor_skill_enabled` | FE-T5 (Skill executor) | Same |
| `agent_loop.executor_tool_burst_enabled` | FE-T7/8 | Same |
| `critic_pipeline.v2_enabled` | FE-T3 (StepHealthStrip) | OFF → strip hidden |
| `critic_pipeline.pre_critic_enabled` | FE-T3 | OFF → PRE chip greyed |
| `critic_pipeline.different_model_critic` | FE-T3 | OFF → no model badge on critic verdict |
| `critic_pipeline.budget_share_cap` | FE-T3 (gauge) | Drives the gauge cap line |
| `critic_pipeline.calibration_enabled` | FE-T9 KPI critic page | OFF → calibration chart empty-state |
| `meta_review.v2_enabled` | FE-T4 | OFF → no supervisor verdict cards |
| `meta_review.fast_path_enabled` | FE-T4 | Informational tooltip |
| `bandit.enabled` | FE-T4 | OFF → no bandit badge |
| `bandit.epsilon` | FE-T4 (badge tooltip) | Shown verbatim |
| `task_classifier.v2_enabled` | FE-T4 | OFF → tag classification quality may vary; UI same |
| `meta_agent.board_routing` | FE-T5 | OFF → no Meta-Agent nav section |
| `meta_agent.spec_critic_required` | FE-T5 | Informational |
| `meta_agent.draft_lifecycle` | FE-T5 | OFF → no DRAFT badge / promote action |
| `meta_agent.testdriver_suite_enabled` | FE-T5 | OFF → TestDriver card empty |
| `meta_agent.testdriver_budget_usd` | FE-T5 | Shown verbatim |
| `meta_agent.skill_promotion_cron` | FE-T5 | OFF → skill candidates panel empty |
| `meta_agent.prompt_evolution_cron` | FE-T5 | OFF → prompt candidates queue empty |
| `meta_agent.curator_consolidation_enabled` | FE-T5 (Phase 12 placeholder) | OFF → no consolidation UI |
| `memory.v2_canonical` | FE-T6 | OFF → memory strip uses v1 shape |
| `memory.viewport_compact` | FE-T6 | OFF → viewport renders legacy ops-help (no visual change) |
| `memory.scope_policy_enforced` | FE-T6 | OFF → scope violation banner never shows |
| `memory.dreaming_outcome_trigger` | FE-T6 | OFF → no dreaming toast |
| `memory.embedding_resolver_v2` | FE-T6 | Informational |
| `planner.v2_enabled` | FE-T7 | OFF → no "view candidates" CTA |
| `planner.n_candidates` | FE-T7 | Shown as info in modal |
| `planner.invariants_enforced` | FE-T7 | OFF → invariant badge hidden |
| `planner.judge_enabled` | FE-T7 | OFF → judge score column hidden |
| `planner.priors_enabled` | FE-T7 | Informational |
| `tools.cost_resolver_v2_enabled` | FE-T8 | OFF → cost dashboard sparse |
| `tools.resilience_v2_enabled` | FE-T8 | OFF → no resilience icons |
| `tools.experimental.{tool_id}` | FE-T8 | Per-tool, per-company. Hides EXPERIMENTAL tool when off |

---

## 4. Rollout discipline

The frontend rolls out behind the **same flags as the backend**. Each
backend Track's rollout cadence (per
[`../13_observability_feature_flags_rollout.md` §4](../13_observability_feature_flags_rollout.md))
governs the frontend too.

### 4.1 The standard cadence

```
Day 0     Backend Track lands; flag OFF in production.
Day 1     Frontend PR lands behind same flag. CI green. Internal tenant only.
Day 2-3   Canary tenant: flag ON for backend + frontend. UI/UX QA pass.
Day 4-5   10% of tenants. Monitor errors.
Day 6-7   50% of tenants.
Day 8     100%.
Day 35    Flag deleted (post-Track 9 sweep).
```

### 4.2 Hard rule

**Frontend never enables a Phase-11 UI without its backend flag being
ON.** The frontend resolves the flag and disables the UI if backend
says OFF. So a frontend deploy with the flag plumbed (but OFF on
backend) is safe.

### 4.3 Rollback

For every Track:

1. Backend flips flag OFF.
2. Frontend re-fetches via push channel.
3. UI degrades to legacy path.
4. No frontend redeploy required.

If the issue is a **frontend bug** rather than a backend regression:

1. Revert the offending frontend PR (CI redeploys).
2. Backend flag may stay ON; UI just won't render the buggy widget.

### 4.4 Canary feature-flag overrides

The admin Feature Flags page (FE-T9) lets ops set per-company
overrides:

* Open `/admin/feature-flags`.
* Filter `scope=company`.
* For company X, set `agent_loop.enabled` → `true` while global is
  `false`. Test.
* Revert → set to `null` (delete row) → company inherits global.

### 4.5 Per-entity overrides

For surgical canaries (e.g. test the AgentLoop on one specific
PROCESS entity), set the entity-scoped flag:

```
flag_key:    agent_loop.enabled
entity_id:   <UUID>
enabled:     true
```

The frontend `useFeatureFlag` resolves entity > company > global.

### 4.6 Per-run override

For ad-hoc test runs, `POST /api/v1/execute` accepts an
`override_feature_flags` body field. The backend stamps it onto
`run.input_data.feature_flags` and the frontend reads it as the
highest-priority scope.

This is the **only programmatic** way to flip a flag mid-run; admins
must use the UI for everything else.

---

## 5. Frontend feature-flag UI conventions

### 5.1 "Coming soon" empty states

When a backend Track's flag is OFF but the UI would otherwise render
new content, show a friendly empty state:

```
🧪 Phase-11 supervisor critique is not yet enabled for your account.
   Ask your admin to enable `meta_review.v2_enabled`.
```

This is preferable to silently hiding the widget — users see *what's
coming*.

### 5.2 Admin "What's new" hint

The PhaseElevenTour overlay (FE-T9) only triggers when **at least one
Phase-11 flag is ON** for the admin's company. New tenants on the
legacy path see no tour.

### 5.3 Flag debugging panel

A dev-only floating panel (`?debug=flags`) shows the resolved flag
state for the current page. Off in production. Implementation:

```tsx
// components/dev/FlagsDebugPanel.tsx
if (!window.location.search.includes('debug=flags')) return null;
const ctx = useContext(FeatureFlagsContext);
return (
  <pre className="fixed bottom-2 right-2 ...">
    {JSON.stringify(ctx, null, 2)}
  </pre>
);
```

---

## 6. Backend → frontend events for flag changes

When an admin flips a flag, the backend emits:

```
WS channel:    feature_flag_invalidations
payload:       { flag_key, company_id?, entity_id?, new_value }
```

Frontend subscriber:

```ts
// services/feature_flags_subscription.ts
ws.on('feature_flag_invalidations', () => {
  // Re-fetch /feature_flags/me; FeatureFlagsContext re-emits
  refetchFeatureFlags();
});
```

This means a Phase-11 widget can appear/disappear **without page
reload** when an admin flips its flag. Useful for canary toggles.

---

## 7. Acceptance for "feature flags wired correctly"

A frontend Track is **flag-wired** when:

1. The Track's flag appears in the table in §3.
2. The component(s) under that Track render the legacy / empty state
   when the flag is OFF.
3. Toggling the flag (via Feature Flags admin or programmatically) →
   UI updates within 2 seconds without page reload.
4. CI test `frontend/tests/featureFlags/<track>.spec.ts` covers both
   ON and OFF states for at least one component in the Track.

---

## 8. Open questions

* Should the frontend cache `feature_flags/me` in `localStorage`?
  **Decision:** no. Each app boot fetches fresh — the latency is
  acceptable and the safety guarantee is worth it.
* Should non-boolean flags (e.g. `bandit.epsilon`, `planner.n_candidates`)
  be configurable per-tenant from the admin UI? **Yes** in FE-T9, with
  type-aware editors.
* Should we expose flag values to **regular users** (not just admins)?
  **No** — flags are operational concerns; users don't need to know.
  The exception is the "Coming soon" empty state which describes
  *capability availability*, not flag names.
