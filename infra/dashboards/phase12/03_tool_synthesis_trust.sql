-- Phase 12 `06` §2 + `07` §3 — synthesized-tool inventory & learned trust.

-- ---------------------------------------------------------------------
-- 1. Synthesized (DRAFT) tool inventory per company
--    tool_type='SYNTHESIZED'; configuration JSON carries status/trust/audit.
-- ---------------------------------------------------------------------
SELECT
    company_id,
    name,
    (configuration::jsonb)->>'status'         AS status,
    (configuration::jsonb)->>'trust'          AS trust,
    (configuration::jsonb)->>'network_policy' AS network_policy,
    created_at
FROM tool_registry_entries
WHERE tool_type = 'SYNTHESIZED'
  AND (:company_id IS NULL OR company_id = :company_id)
ORDER BY created_at DESC;

-- ---------------------------------------------------------------------
-- 2. DRAFT → promotion funnel: how many synthesized tools are still DRAFT
--    vs enabled (promoted). Watch the promotion REJECT/backlog ratio.
-- ---------------------------------------------------------------------
SELECT
    (configuration::jsonb)->>'status' AS status,
    is_enabled,
    COUNT(*) AS tools
FROM tool_registry_entries
WHERE tool_type = 'SYNTHESIZED'
  AND (:company_id IS NULL OR company_id = :company_id)
GROUP BY status, is_enabled
ORDER BY tools DESC;

-- ---------------------------------------------------------------------
-- 3. Learned source trust vs the static prior (biggest movers)
--    source_trust_scores (migration p12_source_trust_scores).
-- ---------------------------------------------------------------------
SELECT
    source_key,
    observations,
    ROUND(prior::numeric, 3)         AS prior,
    ROUND(learned_trust::numeric, 3) AS learned_trust,
    ROUND((learned_trust - prior)::numeric, 3) AS delta
FROM source_trust_scores
WHERE observations >= 5
  AND (:company_id IS NULL OR company_id = :company_id)
ORDER BY ABS(learned_trust - prior) DESC
LIMIT 50;
