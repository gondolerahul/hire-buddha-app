-- Phase 11 Track 9 — Critic Pipeline dashboard queries.
--
-- StepHealthRecords live as CORTEX nodes of type ``health_record`` under
-- a 🩺 Health subtree per run. The Track 3 CriticPipeline writes one
-- per executed step.

-- ---------------------------------------------------------------------
-- 1. Post-critic verdict distribution (last 7 days)
-- ---------------------------------------------------------------------
SELECT
    (cn.content::jsonb)->>'post_critic_verdict' AS verdict,
    COUNT(*) AS occurrences
FROM cortex_nodes cn
WHERE cn.node_type = 'health_record'
  AND cn.created_at >= now() - interval '7 days'
GROUP BY verdict
ORDER BY occurrences DESC;

-- ---------------------------------------------------------------------
-- 2. Top failure tags by frequency (last 7 days)
-- ---------------------------------------------------------------------
SELECT
    tag,
    COUNT(*) AS occurrences
FROM cortex_nodes cn,
     LATERAL jsonb_array_elements_text((cn.source_ref::jsonb)->'tags') tag
WHERE cn.node_type = 'health_record'
  AND cn.created_at >= now() - interval '7 days'
GROUP BY tag
ORDER BY occurrences DESC
LIMIT 12;

-- ---------------------------------------------------------------------
-- 3. Critic cost share — what fraction of run cost is critic LLM calls?
-- ---------------------------------------------------------------------
SELECT
    date_trunc('day', timestamp) AS day,
    SUM(calculated_cost) FILTER (
        WHERE attribution IN ('critic_pre','critic_post','critic_align','critic_super')
    )::float / NULLIF(SUM(calculated_cost), 0) AS critic_cost_share,
    SUM(calculated_cost) AS total_cost
FROM usage_logs
WHERE timestamp >= now() - interval '30 days'
  AND (:company_id IS NULL OR company_id = :company_id)
GROUP BY day
ORDER BY day;

-- ---------------------------------------------------------------------
-- 4. False-pass rate (calibration view)
--   Pulled from Intelligence rules written by the weekly calibration
--   cron (planning/critic_calibration.py).
-- ---------------------------------------------------------------------
SELECT
    (cn.content::jsonb)->>'task_class' AS task_class,
    ((cn.content::jsonb)->>'false_pass_rate')::numeric AS false_pass_rate,
    ((cn.content::jsonb)->>'samples')::int AS samples,
    cn.updated_at AS computed_at
FROM cortex_nodes cn
WHERE cn.title ILIKE 'Calibration:%'
   OR (cn.metadata_extra::jsonb)->>'kind' = 'critic_calibration'
ORDER BY computed_at DESC
LIMIT 50;
