-- Phase 11 Track 9 — Loop telemetry dashboard queries.

-- ---------------------------------------------------------------------
-- 1. Iterations per run (snapshot count from CORTEX)
-- ---------------------------------------------------------------------
SELECT
    er.id AS run_id,
    er.completed_at,
    COUNT(cn.id) AS iterations
FROM execution_runs er
LEFT JOIN cortex_nodes cn ON cn.execution_run_id = er.id AND cn.node_type = 'snapshot'
WHERE er.completed_at >= now() - interval '14 days'
GROUP BY er.id, er.completed_at
ORDER BY er.completed_at DESC
LIMIT 200;

-- ---------------------------------------------------------------------
-- 2. Resume events — how often do workers crash mid-iteration?
--   Snapshots whose `iteration` does NOT start at 0 indicate a resume.
-- ---------------------------------------------------------------------
SELECT
    date_trunc('day', created_at) AS day,
    COUNT(*) FILTER (
        WHERE (content::jsonb)->>'iteration' = '0'
    ) AS fresh_starts,
    COUNT(*) FILTER (
        WHERE (content::jsonb)->>'iteration' != '0'
        AND sibling_order = 0
    ) AS resumes
FROM cortex_nodes
WHERE node_type = 'snapshot'
  AND created_at >= now() - interval '14 days'
GROUP BY day
ORDER BY day;

-- ---------------------------------------------------------------------
-- 3. PlanStyleBandit chosen-arm distribution per task_class
--   Bandit arm tables live as STRATEGY nodes under 🎯 Strategies with
--   metadata_extra.kind = 'bandit_arm_table'.
-- ---------------------------------------------------------------------
SELECT
    (cn.metadata_extra::jsonb)->>'task_class' AS task_class,
    arm.key AS arm,
    (arm.value->>'pulls')::int AS pulls,
    (arm.value->>'successes')::int AS successes,
    ROUND(
        (arm.value->>'successes')::numeric
        / NULLIF((arm.value->>'pulls')::numeric, 0),
        3
    ) AS win_rate,
    (arm.value->>'avg_cost_usd')::numeric AS avg_cost_usd
FROM cortex_nodes cn,
     LATERAL jsonb_each(cn.content::jsonb) arm
WHERE (cn.metadata_extra::jsonb)->>'kind' = 'bandit_arm_table'
ORDER BY task_class, win_rate DESC;

-- ---------------------------------------------------------------------
-- 4. Retry strategy distribution
-- ---------------------------------------------------------------------
SELECT
    (cn.content::jsonb)->>'post_critic_verdict' AS verdict,
    array_length(
        ARRAY(SELECT jsonb_array_elements_text((cn.source_ref::jsonb)->'tags')),
        1
    ) AS tag_count,
    COUNT(*) AS occurrences
FROM cortex_nodes cn
WHERE cn.node_type = 'health_record'
  AND (cn.content::jsonb)->>'post_critic_verdict' IS NOT NULL
  AND cn.created_at >= now() - interval '7 days'
GROUP BY verdict, tag_count
ORDER BY occurrences DESC
LIMIT 25;
