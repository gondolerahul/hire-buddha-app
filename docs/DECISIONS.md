# Programme Decision Log

> Append-only. One block per decision. Maintained via the admin API
> (`POST /api/v1/ai/admin/admin/decisions`) and listed via
> `GET /api/v1/ai/admin/admin/decisions`. Manual edits welcome too.

Format:

```
YYYY-MM-DD  <kind>  <one-line summary>
              rationale: <optional explanation>
```

`<kind>` is one of `decision` / `pivot` / `defer` / `accept-risk`.

---

2026-05-28  decision  agent_loop.snapshot_every_iteration default ON
              rationale: resume reliability outweighs CORTEX write cost
2026-05-28  decision  critic_pipeline.different_model_critic default ON
              rationale: Track 3 catch-rate +12pp justifies +15% critic cost
2026-05-28  defer     LLM-driven Strategist to Phase 12
              rationale: out of scope; deterministic Strategist meets G1
2026-05-29  decision  tools.resilience_v2_enabled default ON for both REACT and direct paths
              rationale: T8-3 unified path eliminates 60-line duplication
2026-09-17  decision  Mobile dialer app: identify leads via call-intent + CLI match, DTMF token confirmation, gated AI start (ADR-001)
              rationale: zero recurring cost, fits existing session cascade; see docs/mobile-dialer-app/03-adr-001-lead-identification.md
2026-09-17  accept-risk  Mobile dialer reps call campaign leads from personal 10-digit SIMs (TRAI TCCCPR 2025)
              rationale: confirmed by product; in-app calling-hours, daily cap and do-not-call guardrails kept
2026-09-17  decision  Mobile dialer dial order is AI-first only; rep auto-muted after merge with unmute control
              rationale: 5-27s AI setup would otherwise leave answered leads on hold
2026-09-17  decision  Mobile dialer app distributed privately outside the Play Store; no public release
              rationale: default-dialer role and pilot scope; avoids Play review
