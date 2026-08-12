# 15 — Frontend Risks, Acceptance KPIs, and Programme Exit

This document collects **frontend-specific risks**, the acceptance
KPIs that gate each Track, and the programme exit checklist for the
frontend portion of Phase 11.

---

## 1. Frontend-level risks

### 1.1 R-FE-1 — SSE connection unreliable on flaky networks

| Field | Value |
|-------|-------|
| Description | EventSource drops mid-run; iteration cards stop appearing |
| Likelihood | Medium |
| Impact | User watches a stuck UI; thinks the run is frozen |
| Mitigation | EventSource auto-reconnects; on reconnect, refetch `/agent_state` for the latest snapshot; "Re-fetching state…" status banner during reconnect |
| Owner | Frontend engineer |

### 1.2 R-FE-2 — AgentState polling interval cost

| Field | Value |
|-------|-------|
| Description | 2-second polling for live runs adds up across many open tabs |
| Likelihood | Low |
| Impact | Backend load |
| Mitigation | Pause when tab hidden (`visibilitychange`); poll backoff (2s → 4s → 8s) when no state change observed twice in a row |
| Owner | Frontend engineer |

### 1.3 R-FE-3 — Iteration timeline scaling

| Field | Value |
|-------|-------|
| Description | Runs with 50+ iterations make the page jank |
| Likelihood | Medium |
| Impact | Slow UI for long runs |
| Mitigation | Lazy-mount IterationCard via Intersection Observer; if 50+ become common, add `react-window` |
| Owner | Frontend engineer |

### 1.4 R-FE-4 — TypeScript enum drift between FE and BE

| Field | Value |
|-------|-------|
| Description | Backend adds a new FailureTag / StepType value; FE doesn't know about it |
| Likelihood | Medium |
| Impact | Unknown values render blank or crash strict switches |
| Mitigation | Codegen pipeline (FE-T1) keeps `_generated.ts` in sync; CI diff catches drift; UI always has a `default` branch with "Unknown: <value>" fallback |
| Owner | App platform engineer |

### 1.5 R-FE-5 — Feature flag flip mid-run

| Field | Value |
|-------|-------|
| Description | An admin flips `agent_loop.enabled` while a user has a RUNNING run open; UI tries to switch mid-stream |
| Likelihood | Low |
| Impact | Page may show stale layout for the rest of the run |
| Mitigation | Resolve the flag at run start and store in `run.input_data.feature_flags`; UI uses the run-stamped flag, not live; live flag changes only affect new runs |
| Owner | Frontend engineer |

### 1.6 R-FE-6 — Meta-Agent Board pipeline UI confusion

| Field | Value |
|-------|-------|
| Description | New users don't understand which role does what |
| Likelihood | Medium |
| Impact | Adoption friction |
| Mitigation | Onboarding tour (FE-T9); hover tooltips per role; "What is X?" link to docs |
| Owner | UX/Frontend engineer |

### 1.7 R-FE-7 — Bundle size growth

| Field | Value |
|-------|-------|
| Description | New pages + charts (recharts) + Storybook + Playwright add weight |
| Likelihood | Medium |
| Impact | Slower first paint |
| Mitigation | Lazy-load every new route; chart components dynamic-imported; baseline bundle stat tracked from FE-T0 |
| Owner | Frontend engineer |

### 1.8 R-FE-8 — Prompt update HITL approval is irreversible

| Field | Value |
|-------|-------|
| Description | Admin approves a bad Meta-Agent prompt diff; agents start generating worse output |
| Likelihood | Low |
| Impact | Quality regression |
| Mitigation | Two-step confirm ("Approve & Apply") modal; audit log entry; "Revert last prompt update" admin action (backend Phase 12) |
| Owner | Frontend engineer + Backend AI/ML |

### 1.9 R-FE-9 — A11y regression with new chips / charts

| Field | Value |
|-------|-------|
| Description | Custom recharts components lack proper a11y labels |
| Likelihood | Medium |
| Impact | Lighthouse score < 90 |
| Mitigation | axe-core in every E2E; chart components wrapped with `<figure>` + `<figcaption>` |
| Owner | Frontend engineer |

### 1.10 R-FE-10 — Coverage debt

| Field | Value |
|-------|-------|
| Description | Aggressive ship cadence; tests get deferred |
| Likelihood | High |
| Impact | Regressions slip into production |
| Mitigation | Coverage gates in CI per directory; PR template requires test plan; pair-review |
| Owner | Tech lead |

### 1.11 R-FE-11 — Coordination with backend Track timing

| Field | Value |
|-------|-------|
| Description | Frontend Track lands before backend endpoint is ready |
| Likelihood | Medium |
| Impact | UI shows "no data" forever |
| Mitigation | Frontend Tracks scheduled 3-5 days BEHIND backend Track; PRs include mock data so canary tenant can exercise the UI even before backend is ON |
| Owner | Tech lead |

### 1.12 R-FE-12 — Re-export shim drift

| Field | Value |
|-------|-------|
| Description | After FE-T9 P11 prefix removal, the back-compat re-exports get stale; new imports use the canonical path while tests still import the P11 path |
| Likelihood | Low |
| Impact | Two copies tested |
| Mitigation | Phase 12 deletes the re-exports after 30 days of zero usage (telemetry on import in dev) |
| Owner | Frontend engineer |

---

## 2. Acceptance KPIs (frontend-side)

These are the **observable user-facing metrics** that gate the
frontend programme. Tracked manually (or via Lighthouse/Playwright CI
nightly).

### 2.1 Quality

| KPI | Target | Source |
|-----|-------:|--------|
| Lighthouse a11y score (new pages) | ≥ 90 | Lighthouse CI |
| Lighthouse perf score (new pages) | ≥ 80 | Lighthouse CI |
| Lighthouse best-practices | ≥ 90 | Lighthouse CI |
| Coverage (component dirs) | ≥ 80% lines | Vitest |
| Coverage (hooks dir) | ≥ 85% lines | Vitest |
| E2E pass rate (nightly) | ≥ 99% | Playwright |
| Bundle size delta (vs FE-T0 baseline) | ≤ +30% | Vite stats |
| Console errors in production | 0 per session | client error reporter |

### 2.2 Adoption

| KPI | Target |
|-----|-------:|
| % of admin sessions visiting `/meta-agent` (when board_routing is on) | ≥ 60% |
| % of admin sessions visiting `/admin/kpi-dashboard` weekly | ≥ 80% |
| % of executions opened by user with AgentLoop view (when flag on) | ≥ 95% |

### 2.3 Reliability

| KPI | Target |
|-----|-------:|
| SSE reconnect rate per session | ≤ 1 |
| AgentState polling failure rate | ≤ 1% |
| Feature flag fetch failure rate | ≤ 0.5% |

### 2.4 UX

| KPI | Target |
|-----|-------:|
| Time-to-first-iteration-card (live runs) | ≤ 3s after run start |
| ReplanDiffModal open latency | ≤ 500ms |
| PlanCandidatesCompare modal open latency | ≤ 500ms |
| KPI page tab switch latency | ≤ 300ms |

---

## 3. Per-Track frontend acceptance (recap)

| FE-Track | Acceptance summary |
|---------:|--------------------|
| FE-0 | `npm run lint` clean; build clean; baseline bundle recorded |
| FE-1 | `types/` package; back-compat works; FailureTag/StepType/ExecutorName enums live; codegen output committed |
| FE-2 | ExecutionDetail renders AgentLoop or legacy per flag; AgentState rail updates live; resume indicator visible after simulated crash; 3 parity fixtures pass |
| FE-3 | StepHealthStrip + retry badge render on iteration cards; CriticCostGauge in header; health records admin page works |
| FE-4 | SupervisorVerdictCard inline on supervisor iterations; ReplanDiffModal opens with proposed_subgoals; BanditState admin page renders; TaskClassTag in run header |
| FE-5 | Meta-Agent nav section visible; Run Detail renders Role Timeline with all 7 roles; AntiPatterns + SkillCandidates + PromptUpdate pages all work; DRAFT lifecycle visible in EntityLibrary; meta-cognition defaults flipped in EntityBuilder |
| FE-6 | ProvenanceRibbon on CORTEX nodes; IntelStatusBadge on Intelligence nodes; MemoryAssemblyStrip in run header; DreamingToast on run end; ScopeViolationBanner for admins |
| FE-7 | "View plan candidates" CTA on planner iterations; PlanCandidatesCompare modal with judge stars; ReplanDiffModal upgraded to full plan history |
| FE-8 | Tool status badges everywhere; experimental tools admin per-company toggles work; cost attribution dashboard renders; resilience indicators inline; run header micro-chart |
| FE-9 | KPI dashboard with 6 sub-pages; Feature Flags admin page; P11 prefix dropped (with shims); onboarding tour runs once; layout-lint enforces "no new P11* files" |

Each Track's PR closes when its acceptance row above is green AND the
KPIs in §2 don't regress.

---

## 4. Programme exit checklist (frontend)

The frontend portion of Phase 11 is **done** when all are true:

- [ ] Every FE Track in §3 has shipped to production behind its flag.
- [ ] Every backend Track's flag has a corresponding ON-and-OFF UI
      branch confirmed working.
- [ ] No `P11*` files outside the deprecation shims.
- [ ] `types/` is split per domain; `_generated.ts` committed.
- [ ] `services/events.ts` covers every Phase-11 SSE event.
- [ ] Coverage gates in §2.1 met for all touched directories.
- [ ] Lighthouse a11y ≥ 90 on every new page.
- [ ] Nightly Playwright suite green ≥ 7 consecutive runs.
- [ ] Bundle size growth ≤ +30% vs FE-T0 baseline.
- [ ] Storybook stories exist for every `components/agent/*` and
      `components/admin/*`.
- [ ] Onboarding tour ships and triggers once per fresh admin.
- [ ] No client console errors in production (one full week of
      observation).
- [ ] Feature Flags admin page lets ops flip every Phase-11 flag.

When this list is complete, file the closing PR with
`docs/phase11/STATUS_FRONTEND.md` flipped to `done` and the FE-T9
deletion sweep merged.

---

## 5. Phase 12 candidates (frontend backlog)

* Editable Meta-Agent system prompt UI (today: HITL approval queue only).
* Drag-drop COMPOSE: build a PROCESS from multiple SKILL entities visually.
* Visual plan editor (use existing `reactflow` dep).
* Replay an old run's iteration animation.
* Customisable KPI dashboard layouts per role.
* Mobile-first responsive polish.
* i18n (Spanish first; Portuguese second).
* Export KPI dashboards to PDF / CSV.
* In-app diff approval for Meta-Agent prompt updates with revert.
* Tool synthesis wizard (when backend lands it).
* Skill marketplace browse / install.
* Bandit arm visualisation timeline (per-iteration trajectory).
* "Replay events" view that animates the iteration timeline on demand.
* Custom chart themes per tenant.
* Power-user keyboard shortcuts (`j/k` to navigate iterations, etc.).
