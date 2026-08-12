# Track 9 — Hardening + KPI Dashboard (Week 12)

> **Owner:** Whoever has cycles. Distribute among the team.
> **Duration:** 5 working days.
> **Behaviour change:** Cleanup pass; KPI dashboard activated; legacy
>   code paths deleted. No new feature flags ON; several legacy flags
>   removed.
> **Risk:** Low-Medium. Deletions are the riskiest piece; gated by
>   week-on-week feature-flag-off observation.
> **Goal mapping:** G6 (final layout lock), G1 (KPI visibility), G8
>   (cost discipline observable).

This Track closes the programme. It is the last chance to:

* Delete dead code paths whose flags have been OFF in production for
  ≥30 days.
* Strip "Phase N / Fix X" historical comments.
* Run `mypy --strict` on the whole agent kernel.
* Stand up the KPI dashboard that every prior Track wired events for.
* Ship per-package READMEs so a new engineer can land a PR in 90
  minutes.

---

## 1. Objectives (functional)

After Track 9:

1. **All legacy code paths** flagged off for ≥30 days are deleted:
   * `_review_step_output` (Track 3).
   * `MemoryRouter` (Track 6).
   * `MetaReviewer` class body (replaced by 5-line shim earlier;
     delete the shim).
   * `CortexRouter` (class) backwards-compat alias from Track 0.
   * The `_schemas_legacy.py` file from Track 1.
2. **Inline historical narration** (`# Phase N`, `# Fix B`, etc.) is
   removed from the agent kernel.
3. **`mypy --strict`** passes on `core/`, `planning/`, `memory/`,
   `meta/`, `governance/`, `schemas/`, `orm/`, and `tools/base.py`.
4. **`INTERNAL_CONTEXT_KEYS`** is documented (purpose, lifecycle,
   writer, reader) in a single Markdown file inside
   `backend/src/ai/core/INTERNAL_KEYS.md`.
5. **Per-package READMEs** exist under
   `backend/src/ai/{core,planning,memory,meta,governance,tools}/README.md`.
6. **KPI dashboard** (Grafana / Metabase / whichever) is live with all
   metrics defined in [`15_risk_register_and_acceptance.md`](./15_risk_register_and_acceptance.md).
7. The layout-lint script (Track 0) enforces the FINAL layout — no
   more "legacy allowed" exceptions.
8. **Onboarding doc** at `backend/src/ai/ONBOARDING.md` walks a new
   engineer from clone to first PR in ≤90 minutes.

---

## 2. Scope

### In scope

* Code deletions per §1.1.
* Comment cleanup (sweep + lint rule).
* `mypy --strict` extension to all listed packages.
* `INTERNAL_KEYS.md` and per-package READMEs.
* KPI dashboard build (data sources, Grafana/Metabase queries).
* Onboarding doc.
* Final layout-lint tightening.
* Removal of all feature flags from Tracks 0-8 that have been ON
  default + no negative signal for ≥30 days.

### Out of scope

* New features.
* Repricing.
* Performance tuning beyond what `mypy` / cleanup naturally surfaces.

---

## 3. Architecture (technical)

No new components. This Track is **subtraction and documentation**.

### 3.1 Deletion playbook (per item)

For each legacy path:

1. Confirm the flag has been OFF (or the new path ON) for ≥30 days
   in production via telemetry.
2. Confirm the legacy entry point has zero calls in telemetry
   (`grep -RIn` + log scrape).
3. Delete the file or symbol in a single PR.
4. Re-run full test suite.
5. Remove the now-unused feature flag from
   `feature_flags` table (Alembic migration if rows present).

### 3.2 Documentation deliverables

```
backend/src/ai/
├── README.md                 ← already from Track 0; expand
├── ONBOARDING.md             ← NEW (Track 9)
├── core/
│   ├── README.md             ← NEW
│   └── INTERNAL_KEYS.md      ← NEW
├── planning/README.md        ← NEW
├── memory/README.md          ← NEW
├── meta/README.md            ← NEW
├── governance/README.md      ← NEW
└── tools/README.md           ← NEW
```

Each README is ≤200 lines and follows a fixed template:

```
# <package>/ — <one-line purpose>

## What's in here
<file inventory with a one-line purpose>

## Key types
<dataclasses / classes / enums>

## Entry points
<how the rest of the system calls into this package>

## See also
<phase 11 plan files relevant to this package>
```

### 3.3 KPI dashboard

The dashboard has six pages:

1. **Run health** — `goal_hit_rate`, `re_plan_rate`,
   `budget_overshoot_rate`, `false_pass_rate`.
2. **Cost** — cost by attribution (Track 8); cost per success;
   weekly trend.
3. **Critic Pipeline** — verdict distribution per task class;
   critic catch rate vs false-pass rate; critic cost share.
4. **Meta-Agent** — Curator decisions (REUSE/ADAPT/COMPOSE/CREATE);
   Promoter outcome distribution; MetaIntelligenceTree growth.
5. **Memory** — viewport bytes per step; dreaming runs per week;
   intelligence rules promoted; provenance trust-score distribution.
6. **Loop telemetry** — iterations per run; resume events; bandit
   exploration vs exploitation; chosen-arm distribution per task
   class.

Backend: Postgres queries over `usage_logs` (attribution),
`execution_runs`, `llm_interaction_logs`, `tool_interaction_logs`, and
the CORTEX `health_records` / `snapshots` nodes. Pre-aggregated daily
into a `kpi_daily_rollup` materialised view (Alembic migration in §5).

Frontend: Grafana panels (preferred) or Metabase. Choice depends on
existing infra; both work.

### 3.4 Comment-narration lint

Add to `lint_ai_layout.py`:

```python
FORBIDDEN_COMMENT_PATTERNS = [
    re.compile(r"#\s*Phase\s+\d+", re.IGNORECASE),
    re.compile(r"#\s*Fix\s+[A-Z]?\d?\s*:", re.IGNORECASE),
    re.compile(r"#\s*RACE-\d+", re.IGNORECASE),
    re.compile(r"#\s*Ph-[A-Z]", re.IGNORECASE),
    re.compile(r"#\s*Gap\s*#\d+", re.IGNORECASE),
]
```

Sweep:

```bash
for pat in 'Phase \d+' 'Fix [A-Z]' 'RACE-\d' 'Ph-[A-Z]' 'Gap #\d+'; do
  grep -RIn "$pat" backend/src/ai/ \
    | grep -v "_legacy" \
    | wc -l
done
```

Target: 0 after Track 9.

---

## 4. Detailed deliverables

### 4.1 T9-1 — Comment cleanup sweep (Day 1)

* Run the sweep grep.
* For each hit, delete the comment if it's narrative ("# Phase 10D:
  this is what we did"); convert to an *invariant* comment if it
  describes a still-load-bearing rule ("MUST run before commit() to
  avoid …").
* Add the lint rule to `lint_ai_layout.py` (off-by-default warning
  initially; ON-error at end of Track 9).

### 4.2 T9-2 — Delete `_review_step_output` (Day 1 PM)

If `critic_pipeline.v1_compat` has been OFF in prod ≥30 days:

* Delete the method + its retry tree from `step_executor.py`.
* Delete the `critic_pipeline.v1_compat` flag entry.
* Update tests that imported the symbol.

### 4.3 T9-3 — Delete `MemoryRouter` body (Day 2)

If no production entity has been read by `MemoryRouter.retrieve` for
≥30 days (telemetry on `agent.memory.assembled.pipeline_used = "v1"`):

* Reduce `memory/memory_service.py` to a 5-line shim that raises
  `DeprecationWarning` and points to `MemoryAssemblyService`.
* Or, if `legacy_episodic_reader` covers all read paths, delete
  `memory_service.py` entirely.

### 4.4 T9-4 — Delete `MetaReviewer` shim (Day 2 PM)

* Confirm no callers.
* Delete `core/meta_review.py`.

### 4.5 T9-5 — Delete `CortexRouter` (class) alias (Day 3 AM)

* Remove the backwards-compat alias added in Track 0.
* Confirm imports clean.

### 4.6 T9-6 — `mypy --strict` extension (Day 3 PM)

```toml
[tool.mypy]
files = [
    "backend/src/ai/core",
    "backend/src/ai/planning",
    "backend/src/ai/memory",
    "backend/src/ai/meta",
    "backend/src/ai/governance",
    "backend/src/ai/schemas",
    "backend/src/ai/orm",
    "backend/src/ai/tools/base.py",
    "backend/src/ai/tools/resilience.py",
]
strict = true
```

Expect a wave of small fixes — annotate, narrow `Any`, add type
guards. **Time-box to one day**; remaining `# type: ignore[<code>]`
entries get a tracking issue.

### 4.7 T9-7 — Documentation (Days 4-5)

* `INTERNAL_KEYS.md` — table of every key in `INTERNAL_CONTEXT_KEYS`:

  | Key | Writer | Reader | Lifecycle | Notes |
  |-----|--------|--------|-----------|-------|

* Per-package READMEs per §3.2.

* `ONBOARDING.md`:

  1. Clone, `make setup`.
  2. Run worker locally; trigger one fixture entity.
  3. Read `core/agent_loop.py` (the heart of the system).
  4. Read `meta/board/architect.py` (an example role).
  5. Read `memory/cortex_service.py` overview comment.
  6. First PR: enable an EXPERIMENTAL tool for the dev tenant — guided
     exercise.

### 4.8 T9-8 — KPI dashboard (Days 4-5)

* New migration `p11t09_kpi_daily_rollup` adds a materialised view:

  ```sql
  CREATE MATERIALIZED VIEW kpi_daily_rollup AS
  SELECT
    date_trunc('day', er.completed_at) AS day,
    er.company_id,
    e.tags->>0 AS primary_tag,
    COUNT(*) AS runs_total,
    SUM(CASE WHEN er.status='COMPLETED' THEN 1 ELSE 0 END) AS runs_completed,
    SUM(er.total_cost_usd) AS cost_usd,
    SUM(er.total_tokens) AS tokens
  FROM execution_runs er
  JOIN hierarchical_entities e ON e.id = er.entity_id
  WHERE er.completed_at IS NOT NULL
  GROUP BY 1, 2, 3;

  CREATE UNIQUE INDEX kpi_daily_rollup_uniq
    ON kpi_daily_rollup(day, company_id, primary_tag);
  ```

* Cron `kpi_rollup_refresh` runs hourly:
  `REFRESH MATERIALIZED VIEW CONCURRENTLY kpi_daily_rollup;`

* Grafana / Metabase panels:
  * Six pages defined in §3.3.
  * Queries committed under `infra/dashboards/phase11/*.sql`.

### 4.9 T9-9 — Final layout-lint tightening (Day 5 PM)

* Remove every "legacy allowed" exception from `lint_ai_layout.py`.
* The script now enforces:
  * Final folder structure exactly.
  * Comment-narration ban (was warning, now error).
  * Size caps unchanged.
  * Forbidden imports unchanged.
* Run lint on `HEAD`; expect 0 violations.

### 4.10 T9-10 — Programme retrospective (Day 5 EOD)

A 1-page retrospective doc summarising:

* What landed.
* What slipped (link to Phase 12 backlog issues).
* KPI deltas observed.
* Recommended owners / on-call for the new modules.

Lives at `docs/phase11/RETROSPECTIVE.md`.

---

## 5. Database / schema changes

### 5.1 `p11t09_kpi_daily_rollup`

Materialised view + cron refresh as above.

### 5.2 Removal of unused feature flags

```python
def upgrade():
    op.execute("""
      DELETE FROM feature_flags
       WHERE flag_key IN (
         'critic_pipeline.v1_compat',
         'memory.v1_pipeline',
         'meta_review.v1_compat'
       )
    """)
```

### 5.3 No other migrations

This is mostly a cleanup track.

---

## 6. API changes

### 6.1 New dashboard endpoints (optional)

If serving dashboard data without Grafana/Metabase:

```
GET /api/v1/admin/kpi/runs?since=7d&company_id=...
GET /api/v1/admin/kpi/cost?since=7d
GET /api/v1/admin/kpi/critic?since=7d
GET /api/v1/admin/kpi/meta_agent?since=7d
```

Admin-only. Returns JSON aggregates straight from `kpi_daily_rollup`.

### 6.2 No removed endpoints

All public-facing APIs unchanged.

---

## 7. Telemetry events

No new events. Track 9 *consumes* the events emitted by all prior
Tracks. The dashboard queries `usage_logs.attribution`, plus event
counters if a Loki/Tempo backend is wired (otherwise PG counts via
the `kpi_daily_rollup` view).

---

## 8. Feature flags

| Flag | Action |
|------|--------|
| `critic_pipeline.v1_compat` | DELETE |
| `memory.v1_pipeline` | DELETE |
| `meta_review.v1_compat` | DELETE |
| `agent_loop.snapshot_every_iteration` | Keep (operational knob) |
| `tools.cost_resolver_v2_enabled` | DELETE (now default everywhere) |
| `tools.resilience_v2_enabled` | DELETE |
| `planner.v2_enabled` | Keep (debug switch only) |
| `meta_agent.board_routing` | Keep (still useful for rollback in dev) |
| `agent_loop.enabled` | Keep |

---

## 9. Tests

### 9.1 Existing tests

* Full suite green.
* All deleted-symbol tests removed.

### 9.2 New / updated tests

* `test_no_phase_narration_in_kernel` — sweep grep returns 0 hits in
  `core/`, `planning/`, `memory/`, `meta/`, `governance/`.
* `test_mypy_strict_full_kernel` — `mypy --strict` on the listed paths
  exits 0.
* `test_layout_lint_strict` — no exceptions left in lint config.
* `test_kpi_view_refresh` — `REFRESH MATERIALIZED VIEW` returns rows.
* `test_internal_keys_documented` — every key in
  `INTERNAL_CONTEXT_KEYS` has a row in `INTERNAL_KEYS.md`.

### 9.3 Smoke

* Full regression suite passes.

---

## 10. Acceptance criteria

1. All deletions in §4 land; CI green.
2. `mypy --strict` passes on every path in §4.6.
3. Layout-lint enforces final shape with no exceptions.
4. Comment-narration sweep returns 0.
5. Every package has a README per §3.2.
6. `INTERNAL_KEYS.md` covers all keys in `INTERNAL_CONTEXT_KEYS`.
7. KPI dashboard live with six pages.
8. `ONBOARDING.md` exercise tested against a fresh engineer in <90
   minutes.
9. Retrospective written.

---

## 11. Effort breakdown (5 working days)

| Day | Work |
|-----|------|
| 1 | T9-1 (comments sweep) + T9-2 (_review_step_output delete) |
| 2 | T9-3 (MemoryRouter) + T9-4 (MetaReviewer shim) |
| 3 AM | T9-5 (CortexRouter alias) |
| 3 PM | T9-6 (mypy --strict on full kernel) |
| 4 | T9-7 (READMEs + ONBOARDING + INTERNAL_KEYS) + T9-8 start (rollup view) |
| 5 | T9-8 cont'd (dashboards) + T9-9 (lint tighten) + T9-10 (retro) + PR |

---

## 12. Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Hidden caller of a deleted symbol breaks at runtime | M | Worker boot fails in some path | Telemetry check + full integration suite + canary deploy 24h before locking |
| `mypy --strict` wave exposes too many issues | H | Track 9 slips | Time-box; remaining ignores go to Phase 12 with tracking issues |
| KPI dashboard takes longer than 2 days | H | Track 9 slips | Minimum viable dashboard = 3 panels (run health, cost, critic); others can land Phase 11.1 |
| Comment cleanup deletes a comment that was load-bearing | L | Subtle behaviour drift | PR review explicitly checks each deletion; load-bearing comments converted not deleted |
| Materialised view refresh is slow | L | Stale dashboards | `REFRESH CONCURRENTLY`; cron hourly |
| Some legacy flag has never been actually OFF in production | M | Cannot delete safely | Check `feature_flags` table + telemetry; if doubt, defer one release |

---

## 13. Dependencies

* **Upstream:** every prior Track (this is the closer).
* **Downstream:** Phase 12 backlog.

---

## 14. Open questions

* Should the dashboard live in Grafana, Metabase, or a custom React
  page? Defer to existing infra; the SQL backing it doesn't care.
* Should we *delete* `MemoryRouter` entirely, or keep
  `legacy_episodic_reader`? Keep the reader (it has real data behind
  it) and delete the rest.
* Phase 12 candidates surfaced during Track 9 retrospective — open
  issues for them with the retro PR.
