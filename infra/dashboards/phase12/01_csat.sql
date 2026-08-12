-- Phase 12 `07` §6 (P-O2) — CSAT panels.
--
-- Backed by execution_runs.csat_score (+1 / -1) + csat_comment (migration
-- p12_run_csat). The only first-party "was this actually good?" signal; pair it
-- with critic verdicts to calibrate false-pass rate against ground truth.

-- ---------------------------------------------------------------------
-- 1. CSAT rate (last 30 days, per company): % thumbs-up of rated runs
-- ---------------------------------------------------------------------
SELECT
    date_trunc('day', completed_at) AS day,
    COUNT(*) FILTER (WHERE csat_score = 1)  AS thumbs_up,
    COUNT(*) FILTER (WHERE csat_score = -1) AS thumbs_down,
    COUNT(*) FILTER (WHERE csat_score IS NOT NULL) AS rated,
    ROUND(
        100.0 * COUNT(*) FILTER (WHERE csat_score = 1)
        / NULLIF(COUNT(*) FILTER (WHERE csat_score IS NOT NULL), 0), 1
    ) AS csat_pct
FROM execution_runs
WHERE completed_at >= now() - interval '30 days'
  AND (:company_id IS NULL OR company_id = :company_id)
GROUP BY day
ORDER BY day;

-- ---------------------------------------------------------------------
-- 2. Critic false-pass proxy: runs the critic passed but the user disliked
--    (csat_score = -1 on a COMPLETED run). Calibration target.
-- ---------------------------------------------------------------------
SELECT
    date_trunc('week', completed_at) AS week,
    COUNT(*) FILTER (WHERE csat_score = -1 AND status = 'COMPLETED') AS likely_false_pass,
    COUNT(*) FILTER (WHERE csat_score IS NOT NULL) AS rated
FROM execution_runs
WHERE completed_at >= now() - interval '12 weeks'
  AND (:company_id IS NULL OR company_id = :company_id)
GROUP BY week
ORDER BY week;

-- ---------------------------------------------------------------------
-- 3. Recent thumbs-down with comments (triage queue)
-- ---------------------------------------------------------------------
SELECT id, entity_id, completed_at, csat_comment
FROM execution_runs
WHERE csat_score = -1
  AND csat_comment IS NOT NULL
  AND (:company_id IS NULL OR company_id = :company_id)
ORDER BY completed_at DESC
LIMIT 50;
