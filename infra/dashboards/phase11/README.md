# Phase 11 KPI Dashboards

Six pages of SQL queries that consume the `kpi_daily_rollup`
materialised view + the `usage_logs.attribution` column added in
Track 8 + StepHealthRecord / MetaIntelligenceTree CORTEX nodes from
Tracks 3 / 5.

| File | Page |
|------|------|
| `01_run_health.sql` | Goal hit rate, failure/pause breakdown, budget overshoot, re-plan rate |
| `02_cost.sql` | Cost by attribution, cost per success, weekly trend, top cost-bearing tools |
| `03_critic_pipeline.sql` | Verdict distribution, failure tags, critic cost share, calibration false-pass rate |
| `04_meta_agent.sql` | Curator decisions, MetaIntelligenceTree growth, Promoter outcomes, skill candidates |
| `05_memory.sql` | Prompt overhead per step, dreaming runs, candidate→confirmed promotions, provenance trust scores |
| `06_loop_telemetry.sql` | Iterations per run, resume events, bandit arm distribution, retry strategy distribution |

## Source data

- `kpi_daily_rollup` — pre-aggregated daily counts; refreshed hourly
  by `core/arq_jobs.kpi_rollup_refresh`.
- `usage_logs` — per-charge billing rows with `attribution` tag
  (planner / actor_step / critic_* / tool / child_run / embedding /
  meta_spec_critic / test_driver / dreaming / reformat_retry /
  meta_review).
- `cortex_nodes` — StepHealthRecords (`node_type='health_record'`),
  snapshots (`node_type='snapshot'`), bandit arm tables (under
  🎯 Strategies with `metadata_extra.kind='bandit_arm_table'`),
  MetaIntelligenceTree rows (anti_pattern, curator_decision,
  skill_candidate, prompt_update_candidate, tool_reliability).
- `llm_interaction_logs` / `tool_interaction_logs` — direct
  observability.

## Wiring into Grafana / Metabase

The queries take a single `:company_id` parameter. Pass `NULL` for
platform-wide aggregates. The materialised view is the recommended
source for any panel that aggregates more than 7 days of data
(`execution_runs` table scans get slow past ~1M runs); join through
the rollup wherever possible.
