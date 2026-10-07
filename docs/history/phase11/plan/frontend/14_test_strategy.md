# 14 — Frontend Test Strategy

This document defines the **frontend test contract** for the Phase 11
programme: which test layers, what coverage gates, which fixtures, and
what is wired into CI.

---

## 1. Test layers

| Layer | Tool | Where it lives | When it runs |
|-------|------|----------------|--------------|
| Unit | Vitest + React Testing Library | `frontend/src/**/*.test.tsx` | every PR |
| Integration | Vitest + RTL + MSW (mock service worker) | `frontend/src/**/*.int.test.tsx` | every PR |
| Storybook + visual | Storybook 8 + Chromatic (if available) or Playwright pixel-diff | `frontend/src/**/*.stories.tsx` | every PR |
| E2E | Playwright | `frontend/e2e/**/*.spec.ts` | nightly + pre-deploy |
| A11y | axe-core via Playwright | inside E2E specs | nightly |
| Performance | Lighthouse CI | inside CI nightly | nightly |

If Storybook is not already wired in the repo, **add it in Frontend
Track 0** as part of the lint/cleanup pass — components rely on
isolated rendering.

---

## 2. Coverage gates

| Path | Min coverage |
|------|-------------:|
| `components/agent/*` | 80% lines / 70% branches |
| `components/admin/*` | 75% / 65% |
| `hooks/*` | 85% / 75% |
| `services/*` | 70% / 60% (mostly thin axios wrappers) |
| `pages/admin/*` | 70% / 60% |
| `pages/ai/ExecutionDetail.tsx` (revamp) | 75% / 65% |
| `pages/ai/MetaAgentRunDetail.tsx` | 75% / 65% |

CI fails any PR that lowers coverage in a touched directory below the
threshold above. New code in a PR has a per-PR floor of 80%.

---

## 3. Unit testing playbook

### 3.1 Recipe for an atom component

```tsx
// components/agent/VerdictChip.test.tsx
import { render, screen } from '@testing-library/react';
import { VerdictChip } from './VerdictChip';

describe('VerdictChip', () => {
  it('renders PASS in green', () => {
    render(<VerdictChip stage="POST" verdict="PASS" />);
    const chip = screen.getByTestId('verdict-chip');
    expect(chip).toHaveClass('verdict-chip--pass');
    expect(chip).toHaveAttribute('aria-label', 'Post-action critic: PASS');
  });

  it('shows tags when REVISE', () => {
    render(<VerdictChip stage="POST" verdict="REVISE" tags={[FailureTag.OFF_TOPIC]} />);
    expect(screen.getByText(/OFF_TOPIC/)).toBeInTheDocument();
  });

  it('renders all 4 stages without crashing', () => {
    (['PRE','POST','ALIGN','SUPER'] as const).forEach(stage => {
      const { unmount } = render(<VerdictChip stage={stage} verdict="PASS" />);
      unmount();
    });
  });
});
```

### 3.2 Recipe for a reducer hook

Test the reducer directly with synthetic actions, then test the hook
with MSW-mocked SSE.

```ts
// hooks/useExecutionEvents.test.tsx
describe('useExecutionEvents reducer', () => {
  it('adds an iteration card on iteration_start', () => {
    const s0 = INITIAL_STATE;
    const s1 = reducer(s0, { type: 'iteration_start', iteration: 1, executor: 'DAG', budget_pressure: 0.1, open_subgoals: 2 });
    expect(s1.iterations).toHaveLength(1);
    expect(s1.iterations[0].iteration).toBe(1);
  });

  it('ignores iteration_end for unknown iter', () => {
    const s = reducer(INITIAL_STATE, { type: 'iteration_end', iteration: 99, outcome: 'success', decision: 'CONTINUE', cost_iter_usd: '0.01' });
    expect(s).toBe(INITIAL_STATE);  // same ref
  });
});
```

### 3.3 Recipe for a service

```ts
// services/agent.service.test.ts
import { agentService } from './agent.service';
import { rest } from 'msw';
import { setupServer } from 'msw/node';

const server = setupServer(
  rest.get('/api/v1/executions/:id/agent_state', (req, res, ctx) =>
    res(ctx.json({ run_id: req.params.id, iteration: 3, ... }))),
);

beforeAll(() => server.listen());
afterAll(() => server.close());

test('getAgentState returns snapshot', async () => {
  const s = await agentService.getAgentState('abc');
  expect(s?.iteration).toBe(3);
});
```

---

## 4. Integration testing playbook

Integration tests render a full page (or a meaningful sub-tree),
mock the network with MSW, and assert user-visible behaviour.

### 4.1 Example: ExecutionDetail (AgentLoop branch)

```tsx
// pages/ai/ExecutionDetail.int.test.tsx
test('renders agent loop layout when flag is on', async () => {
  server.use(
    rest.get('/api/v1/feature_flags/me', (_, res, ctx) =>
      res(ctx.json({ global: { 'agent_loop.enabled': true }, company: {} }))),
    rest.get('/api/v1/executions/:id', (_, res, ctx) =>
      res(ctx.json(MOCK_RUN))),
    rest.get('/api/v1/executions/:id/agent_state', (_, res, ctx) =>
      res(ctx.json(MOCK_AGENT_STATE))),
  );

  render(<MemoryRouter initialEntries={['/executions/abc']}>
           <ExecutionDetail />
         </MemoryRouter>);

  await waitFor(() => screen.getByTestId('agent-state-panel'));
  expect(screen.queryByTestId('legacy-step-list')).toBeNull();
});

test('falls back to legacy when flag is off', async () => {
  server.use(
    rest.get('/api/v1/feature_flags/me', (_, res, ctx) =>
      res(ctx.json({ global: { 'agent_loop.enabled': false }, company: {} }))),
    rest.get('/api/v1/executions/:id', (_, res, ctx) =>
      res(ctx.json(MOCK_RUN))),
  );

  render(<ExecutionDetail />);
  await waitFor(() => screen.getByTestId('legacy-step-list'));
  expect(screen.queryByTestId('agent-state-panel')).toBeNull();
});
```

### 4.2 Required integration suites

| Suite | Track | What it asserts |
|-------|------:|-----------------|
| `executionDetail.agentLoop.int.test.tsx` | FE-T2 | New layout renders when flag ON; legacy when OFF; SSE-driven iterations appear |
| `executionDetail.critic.int.test.tsx` | FE-T3 | StepHealthStrip + retry badge render from events |
| `executionDetail.supervisor.int.test.tsx` | FE-T4 | SupervisorVerdictCard appears at the right iteration |
| `metaAgent.runDetail.int.test.tsx` | FE-T5 | Role timeline runs through all 7 roles |
| `metaAgent.skillCandidates.int.test.tsx` | FE-T5 | Promote button creates DRAFT entity |
| `metaAgent.promptCandidates.int.test.tsx` | FE-T5 | Approve calls endpoint with confirmation |
| `cortex.provenance.int.test.tsx` | FE-T6 | Nodes show provenance ribbon when present |
| `planCandidates.int.test.tsx` | FE-T7 | Modal renders 3 candidates with chosen starred |
| `experimentalTools.admin.int.test.tsx` | FE-T8 | Per-company toggle PUTs payload |
| `costAttribution.int.test.tsx` | FE-T8 | Chart renders from mocked data |
| `kpiDashboard.int.test.tsx` | FE-T9 | All six sub-tabs render |
| `featureFlagsAdmin.int.test.tsx` | FE-T9 | Edit modal sets payload correctly |

---

## 5. Storybook + visual regression

Every component in `components/agent/` and `components/admin/` has a
`.stories.tsx` with these mandatory stories:

* `Default` (happy path).
* `Empty` (no data yet).
* `Loading` (skeleton).
* `Error` (toast/error fallback).
* `Populated` (representative data).

CI compares snapshots on PR. If a story changes its visual output,
the diff must be approved by a designer / reviewer.

If Chromatic isn't wired, Playwright pixel-diff snapshots at
`frontend/e2e/snapshots/` serve the same purpose; tolerance 0.1% by
default.

---

## 6. E2E (Playwright)

### 6.1 Required spec files

| Spec | Track | Flow |
|------|------:|------|
| `auth.happy.spec.ts` | existing | Login → dashboard |
| `execution.agent-loop.spec.ts` | FE-T2 | Trigger fixture entity → observe iteration timeline → terminal state |
| `execution.critic.spec.ts` | FE-T3 | Hostile fixture → REVISE → DIFFERENT_MODEL retry → final |
| `execution.supervisor-replan.spec.ts` | FE-T4 | Force replan → diff modal opens correctly |
| `meta-agent.create-flow.spec.ts` | FE-T5 | NL request → Board roles run → PROMOTED → entity appears in EntityLibrary |
| `meta-agent.blocked-by-critic.spec.ts` | FE-T5 | Hostile spec → Critic BLOCK → Promoter REJECT |
| `memory.provenance.spec.ts` | FE-T6 | Open CortexExplorer → scraper node → provenance ribbon |
| `plan-candidates.spec.ts` | FE-T7 | View candidates modal opens with 3 candidates |
| `tools.experimental.spec.ts` | FE-T8 | Admin opts company in → non-admin user sees tool in builder |
| `cost.attribution.spec.ts` | FE-T8 | Dashboard renders for fixture |
| `kpi.dashboard.spec.ts` | FE-T9 | Switch tabs, change window |
| `feature-flags.admin.spec.ts` | FE-T9 | Create per-company override |

### 6.2 E2E environment

* `playwright.config.ts` points at a staging server seeded with
  fixture entities.
* Fixtures live in `frontend/e2e/fixtures/`.
* Each spec uses a fresh admin login (token short-lived).

### 6.3 E2E cadence

* Nightly (full suite).
* Pre-deploy gate (smoke subset).
* On each Phase-11 PR (smoke subset relevant to the Track).

---

## 7. Accessibility (a11y)

Every new page MUST score **≥ 90** on Lighthouse a11y. Wired via:

```ts
// e2e/a11y.spec.ts
import AxeBuilder from '@axe-core/playwright';

test('ExecutionDetail a11y', async ({ page }) => {
  await page.goto('/executions/fixture-1');
  const { violations } = await new AxeBuilder({ page }).analyze();
  expect(violations.filter(v => v.impact === 'critical')).toHaveLength(0);
});
```

Critical violations fail CI. Serious violations log a warning.

Specific to Phase 11:

* All `VerdictChip` / `FailureTagChip` have non-colour-only signals
  (icons + text).
* Iteration timeline has `aria-live="polite"`.
* Modals (ReplanDiff, PlanCandidatesCompare) trap focus and have
  Escape-to-close.
* Sidebar nav additions get correct `role` and `aria-label`.

---

## 8. Performance budgets

Tracked via Lighthouse CI. Targets:

| Page | LCP | TBT |
|------|----:|----:|
| ExecutionDetail (AgentLoop) | ≤ 2.5s | ≤ 200ms |
| ExecutionDetail (Legacy) | ≤ 2.0s | ≤ 150ms (unchanged baseline) |
| MetaAgent Run Detail | ≤ 2.5s | ≤ 200ms |
| KPI Dashboard | ≤ 3.0s | ≤ 300ms |
| Other | ≤ 2.5s | ≤ 200ms |

Bundle size:

* No single chunk > 500KB gzipped (`build` warns at 500KB by default
  in Vite).
* `lazy()` boundaries used for every new route.

---

## 9. Mock data + fixtures

All fixtures live in `frontend/src/__fixtures__/`:

```
frontend/src/__fixtures__/
├── runs/
│   ├── agentLoop_3iter.json
│   ├── recursive_with_replan.json
│   └── legacy_dag.json
├── agentState/
│   ├── early_iter.json
│   └── budget_pressure.json
├── healthRecords/
│   └── post_revise_with_tags.json
├── metaAgent/
│   ├── create_path.json
│   ├── blocked_by_critic.json
│   └── promotion_outcome.json
├── kpi/
│   ├── runHealth_7d.json
│   ├── cost_30d.json
│   └── critic_30d.json
└── flags/
    ├── all_on.json
    └── all_off.json
```

These are imported by both Storybook stories and integration tests.
They mirror the canonical fixtures from
[`../14_test_strategy.md` §3.3](../14_test_strategy.md).

---

## 10. CI matrix

Each PR runs:

```
[install]    npm ci
[lint]       npm run lint                        (eslint, 0 warnings)
[typecheck]  npx tsc --noEmit
[unit]       npm test                            (vitest)
[integ]      npm test --runInBand --testPathPattern '\.int\.test'
[storybook]  npm run build-storybook && npm run test-storybook (or chromatic)
[build]      npm run build
[a11y]       npx playwright test e2e/a11y
[smoke-e2e]  npx playwright test --grep @smoke
```

Nightly:

```
[full-e2e]   npx playwright test
[lighthouse] lhci autorun
[chromatic]  npx chromatic --exit-zero-on-changes
```

---

## 11. Definition of "frontend tests green" for the programme

Frontend tests are green when:

1. All required integration suites in §4.2 pass.
2. All E2E specs in §6.1 pass nightly.
3. Coverage gates from §2 met for every touched path.
4. Lighthouse a11y ≥ 90 on every new page.
5. No Storybook visual regression unresolved.
6. Performance budgets in §8 met.

This is the bar for shipping each frontend Track to production.
