-- Phase 11 Track 9 — Meta-Agent dashboard queries.
--
-- Sourced from MetaIntelligenceTree (CORTEX nodes with metadata_extra.kind
-- in {anti_pattern, curator_decision, skill_candidate, prompt_update_candidate, ...})
-- and from execution_runs for Meta-Agent runs themselves.

-- ---------------------------------------------------------------------
-- 1. Curator decision distribution (REUSE / ADAPT / COMPOSE / CREATE)
-- ---------------------------------------------------------------------
SELECT
    (cn.content::jsonb)->>'decision' AS decision,
    COUNT(*) AS count
FROM cortex_nodes cn
WHERE (cn.metadata_extra::jsonb)->>'kind' = 'curator_decision'
  AND cn.created_at >= now() - interval '30 days'
GROUP BY decision
ORDER BY count DESC;

-- ---------------------------------------------------------------------
-- 2. MetaIntelligenceTree growth — per-section node count
-- ---------------------------------------------------------------------
SELECT
    (cn.metadata_extra::jsonb)->>'kind' AS kind,
    COUNT(*) AS rows
FROM cortex_nodes cn
WHERE cn.tree_id IN (
    SELECT id FROM cortex_trees
    WHERE scope_level = 'tenant'
      AND memory_domain = 'intelligence'
      AND entity_id IS NULL
)
GROUP BY kind
ORDER BY rows DESC;

-- ---------------------------------------------------------------------
-- 3. Promoter outcome distribution (last 30 days)
--   Reads `agent.meta.promotion.outcome` events mirrored into
--   execution_runs.result_data. Adjust source for your telemetry.
-- ---------------------------------------------------------------------
SELECT
    er.result_data::jsonb->>'promoter_outcome' AS outcome,
    COUNT(*) AS count
FROM execution_runs er
WHERE er.completed_at >= now() - interval '30 days'
  AND er.result_data::jsonb ? 'promoter_outcome'
GROUP BY outcome
ORDER BY count DESC;

-- ---------------------------------------------------------------------
-- 4. Skill candidates awaiting promotion
-- ---------------------------------------------------------------------
SELECT
    cn.id AS node_id,
    cn.title,
    (cn.metadata_extra::jsonb)->>'frequency' AS frequency,
    (cn.metadata_extra::jsonb)->>'source_entity_id' AS source_entity_id,
    cn.created_at
FROM cortex_nodes cn
WHERE (cn.metadata_extra::jsonb)->>'kind' = 'skill_candidate'
ORDER BY ((cn.metadata_extra::jsonb)->>'frequency')::int DESC NULLS LAST
LIMIT 25;
