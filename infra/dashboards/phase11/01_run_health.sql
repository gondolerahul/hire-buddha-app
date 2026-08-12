-- Phase 11 Track 9 — Run Health dashboard queries.
--
-- Source: `kpi_daily_rollup` materialised view (refreshed hourly).
-- Filters: most queries take a :company_id parameter; pass NULL for
-- platform-wide aggregates.

-- ---------------------------------------------------------------------
-- 1. Goal hit rate (per day)
-- ---------------------------------------------------------------------
SELECT
    day,
    SUM(runs_completed)::float / NULLIF(SUM(runs_total), 0) AS goal_hit_rate,
    SUM(runs_total)     AS runs_total,
    SUM(runs_completed) AS runs_completed
FROM kpi_daily_rollup
WHERE day >= now() - interval '14 days'
  AND (:company_id IS NULL OR company_id = :company_id)
GROUP BY day
ORDER BY day;

-- ---------------------------------------------------------------------
-- 2. Failure breakdown
-- ---------------------------------------------------------------------
SELECT
    day,
    SUM(runs_failed)::float / NULLIF(SUM(runs_total), 0) AS failure_rate,
    SUM(runs_paused)::float / NULLIF(SUM(runs_total), 0) AS pause_rate
FROM kpi_daily_rollup
WHERE day >= now() - interval '14 days'
  AND (:company_id IS NULL OR company_id = :company_id)
GROUP BY day
ORDER BY day;

-- ---------------------------------------------------------------------
-- 3. Budget overshoot — runs whose actual cost > governance.max_cost_usd
-- ---------------------------------------------------------------------
SELECT
    date_trunc('day', er.completed_at) AS day,
    COUNT(*) FILTER (
        WHERE er.total_cost_usd > COALESCE(
            (e.governance::jsonb)->>'max_cost_usd', '0'
        )::numeric
    ) AS overshoot_runs,
    COUNT(*) AS total_runs,
    COUNT(*) FILTER (
        WHERE er.total_cost_usd > COALESCE(
            (e.governance::jsonb)->>'max_cost_usd', '0'
        )::numeric
    )::float / NULLIF(COUNT(*), 0) AS overshoot_rate
FROM execution_runs er
JOIN hierarchical_entities e ON e.id = er.entity_id
WHERE er.completed_at >= now() - interval '14 days'
  AND (:company_id IS NULL OR er.company_id = :company_id)
GROUP BY 1
ORDER BY 1;

-- ---------------------------------------------------------------------
-- 4. Re-plan rate — fraction of runs that emitted ≥1 agent.plan.replan
-- event (from llm_interaction_logs.log_metadata or app events table).
-- This query assumes events are mirrored into llm_interaction_logs;
-- adjust the event source for your telemetry setup.
-- ---------------------------------------------------------------------
SELECT
    date_trunc('day', er.completed_at) AS day,
    COUNT(DISTINCT er.id) FILTER (
        WHERE er.result_data::text ILIKE '%agent.plan.replan%'
    )::float / NULLIF(COUNT(DISTINCT er.id), 0) AS replan_rate
FROM execution_runs er
WHERE er.completed_at >= now() - interval '14 days'
  AND (:company_id IS NULL OR er.company_id = :company_id)
GROUP BY 1
ORDER BY 1;
