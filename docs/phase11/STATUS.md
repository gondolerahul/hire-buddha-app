# Phase 11 — Backend Programme Status

> Updated whenever a Track exits or the canary state changes. The
> machine-readable view lives at
> `GET /api/v1/ai/phase11/admin/exit_checklist`.

**Programme state:** `in-canary`

| Track | State | Notes |
|------:|-------|-------|
| T0 — Pre-flight | ✅ done | layout-lint + transitional allow-list active |
| T1 — Schemas / ORM split | ✅ done | re-export shims live |
| T2 — AgentLoop | ✅ done (flag default OFF) | parity within ±5% on 3 fixtures |
| T3 — Critic Pipeline v2 | ✅ done (flag default ON) | calibration cron weekly |
| T4 — Meta-Review + Bandit | ✅ done (flag default ON) | bandit per-(entity, task_class) |
| T5 — Meta-Agent Board | ✅ done (flag default OFF) | spec_critic in admin API |
| T6 — Memory v2 canonical | ✅ done (default v2) | LegacyEpisodicReader for first-run top-up |
| T7 — Planner v2 | ✅ done (flag default ON) | multi-candidate + invariants |
| T8 — Tool + Cost | ✅ done | REACT/AFC unified path (deferred item shipped) |
| T9 — Hardening + KPI | ✅ done | KPI dashboard live; 6 SQL panels |
| T12 — Data model | ✅ done | feature_flags + 4 backfill migrations applied |
| T13 — Observability | ✅ done | TelemetryEvent envelope + FF admin CRUD |
| T14 — Test strategy | ✅ done | integration + chaos suites; CI matrix script |
| T15 — Risk register | ✅ done | risk_indicators + exit_checklist endpoints |

## Open canary watches

* Critic false-pass rate (R-PRG-3)
* Critic cost share (R-PRG-5)
* Meta-Agent promotion REJECT rate (R-PRG-8)

## Deferred to Phase 12 (per retrospective §3)

* mypy --strict full kernel sweep
* Comment-narration sweep to 0 hits + lint promotion to error
* Deletion of legacy code paths after ≥30 days of telemetry showing zero traffic
* Tool subdomain `git mv` and README refresh
* LLM "critic of critic" inside `meta_agent_prompt_evolution`
* Grafana / Metabase panel JSON

## Exit criteria

See `docs/phase11/plan/15_risk_register_and_acceptance.md` §5.
