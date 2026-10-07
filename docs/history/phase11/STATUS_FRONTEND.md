# Phase 11 — Frontend Programme Status

**Programme state:** `in-canary`

| FE Track | State | Notes |
|---------:|-------|-------|
| FE-0 Preflight | ✅ done | lint + baseline bundle |
| FE-1 Schemas + types | ✅ done | `types/phase11.ts` covers enum surface |
| FE-2 AgentLoop UI | ✅ done | ExecutionDetail revamped behind `agent_loop.enabled` |
| FE-3 Critic Pipeline UI | ✅ done | StepHealthStrip + FailureTag chips |
| FE-4 Meta-Review UI | ✅ done | Supervisor verdict card + bandit panel |
| FE-5 Meta-Agent Board UI | ✅ done | Role timeline + skill / anti-pattern / prompt panels |
| FE-6 Memory v2 UI | ✅ done | Provenance ribbon + trust score badges |
| FE-7 Planner v2 UI | ✅ done | Plan candidates compare modal |
| FE-8 Tool + Cost UI | ✅ done | Cost-by-Attribution dashboard |
| FE-9 KPI dashboard | ✅ done | 6 sub-pages + Feature Flags admin |
| FE-13 Feature flag live refresh | ✅ done | 60s polling + visibility-aware |
| FE-15 Risk / Exit dashboards | ✅ done | `/admin/phase11/risks` page |

## Sidebar coverage

All four Phase 11 admin pages now wired in the **Agent Kernel** sidebar group, gated to admins (`APP_ADMIN`, `PARTNER_ADMIN`, `TENANT_ADMIN`). Routes are also `allowedRoles`-locked at the router layer so a direct URL hit from a non-admin redirects to dashboard.

## Open items (deferred / Phase 12)

* P11* prefix removal + back-compat shims (FE-T9)
* Storybook stories per `components/agent/*`
* Lighthouse CI wiring
* Playwright E2E nightly job
* `services/events.ts` typed reducer for the live AgentLoop iteration timeline (the events flow today; the reducer's typed-union exhaustiveness check is the polish)

## Exit criteria

See `docs/phase11/plan/frontend/15_risk_and_acceptance.md` §4.
