-- Phase 11 Track 9 — Cost dashboard queries.
--
-- Backed by the `usage_logs.attribution` column added in Track 8.
-- Every Decimal added to ExecutionRun.total_cost_usd MUST land here
-- with a structured attribution tag (planner / actor_step / critic_* /
-- tool / child_run / embedding / meta_spec_critic / test_driver / ...).

-- ---------------------------------------------------------------------
-- 1. Cost by attribution (last 7 days, per company)
-- ---------------------------------------------------------------------
SELECT
    attribution,
    SUM(calculated_cost) AS cost_usd,
    COUNT(*)             AS charge_count
FROM usage_logs
WHERE timestamp >= now() - interval '7 days'
  AND (:company_id IS NULL OR company_id = :company_id)
GROUP BY attribution
ORDER BY cost_usd DESC;

-- ---------------------------------------------------------------------
-- 2. Cost per success (per day) — total cost / number of COMPLETED runs
-- ---------------------------------------------------------------------
SELECT
    day,
    SUM(cost_usd) AS cost_usd,
    SUM(runs_completed) AS runs_completed,
    SUM(cost_usd) / NULLIF(SUM(runs_completed), 0) AS cost_per_success
FROM kpi_daily_rollup
WHERE day >= now() - interval '30 days'
  AND (:company_id IS NULL OR company_id = :company_id)
GROUP BY day
ORDER BY day;

-- ---------------------------------------------------------------------
-- 3. Weekly cost trend
-- ---------------------------------------------------------------------
SELECT
    date_trunc('week', day) AS week,
    SUM(cost_usd) AS cost_usd,
    SUM(runs_total) AS runs_total,
    SUM(tokens) AS tokens
FROM kpi_daily_rollup
WHERE day >= now() - interval '12 weeks'
  AND (:company_id IS NULL OR company_id = :company_id)
GROUP BY week
ORDER BY week;

-- ---------------------------------------------------------------------
-- 4. Top cost-bearing tools (last 7 days, joined via sku → tool name)
-- ---------------------------------------------------------------------
SELECT
    COALESCE((log_metadata::jsonb)->>'tool', 'unknown') AS tool_id,
    SUM(calculated_cost) AS cost_usd,
    COUNT(*) AS calls
FROM usage_logs
WHERE timestamp >= now() - interval '7 days'
  AND attribution = 'tool'
  AND (:company_id IS NULL OR company_id = :company_id)
GROUP BY tool_id
ORDER BY cost_usd DESC
LIMIT 25;
