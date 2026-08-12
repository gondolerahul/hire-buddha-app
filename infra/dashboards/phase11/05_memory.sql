-- Phase 11 Track 9 — Memory dashboard queries.

-- ---------------------------------------------------------------------
-- 1. Viewport / prompt overhead per step
--   The KPI is `prompt_token_overhead_per_step`. Sourced from
--   llm_interaction_logs.
-- ---------------------------------------------------------------------
SELECT
    date_trunc('day', timestamp) AS day,
    AVG(input_tokens) AS avg_input_tokens,
    AVG(input_tokens) FILTER (
        WHERE (log_metadata::jsonb)->>'cortex_enabled' = 'true'
    ) AS avg_input_tokens_cortex,
    AVG(input_tokens) FILTER (
        WHERE (log_metadata::jsonb)->>'cortex_enabled' = 'false'
    ) AS avg_input_tokens_no_cortex
FROM llm_interaction_logs
WHERE timestamp >= now() - interval '14 days'
GROUP BY day
ORDER BY day;

-- ---------------------------------------------------------------------
-- 2. Dreaming runs per week
-- ---------------------------------------------------------------------
SELECT
    date_trunc('week', created_at) AS week,
    COUNT(*) AS dreams
FROM cortex_nodes cn
WHERE cn.node_type = 'finding'
  AND cn.title ILIKE '%dream%'
  AND created_at >= now() - interval '12 weeks'
GROUP BY week
ORDER BY week;

-- ---------------------------------------------------------------------
-- 3. Intelligence rules promoted (candidate → confirmed)
-- ---------------------------------------------------------------------
SELECT
    date_trunc('day', updated_at) AS day,
    COUNT(*) FILTER (
        WHERE (source_ref::jsonb)->>'status' = 'confirmed'
    ) AS confirmed,
    COUNT(*) FILTER (
        WHERE (source_ref::jsonb)->>'status' = 'candidate'
    ) AS candidates
FROM cortex_nodes
WHERE node_type IN ('instruction', 'strategy', 'preference')
  AND updated_at >= now() - interval '30 days'
GROUP BY day
ORDER BY day;

-- ---------------------------------------------------------------------
-- 4. Provenance trust-score distribution (last 30 days of knowledge writes)
-- ---------------------------------------------------------------------
SELECT
    (source_ref::jsonb)->'provenance'->>'source_type' AS source_type,
    ROUND(AVG(((source_ref::jsonb)->'provenance'->>'trust_score')::numeric)::numeric, 3)
        AS avg_trust_score,
    COUNT(*) AS writes
FROM cortex_nodes
WHERE source_ref::jsonb ? 'provenance'
  AND created_at >= now() - interval '30 days'
GROUP BY source_type
ORDER BY writes DESC;
