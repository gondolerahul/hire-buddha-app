-- Phase 12 `02` S6 + `07` §1 — sandbox & MCP cost panels.
--
-- New cost-attribution tags landed in Phase 12: 'sandbox' (per-tenant container
-- exec/browser, metered by duration) and 'mcp' (external MCP connector calls).
-- These extend infra/dashboards/phase11/02_cost.sql with the new surfaces.

-- ---------------------------------------------------------------------
-- 1. Sandbox spend over time (last 30 days)
-- ---------------------------------------------------------------------
SELECT
    date_trunc('day', timestamp) AS day,
    SUM(calculated_cost) AS cost_usd,
    SUM(raw_quantity)    AS seconds_billed,
    COUNT(*)             AS execs
FROM usage_logs
WHERE attribution = 'sandbox'
  AND timestamp >= now() - interval '30 days'
  AND (:company_id IS NULL OR company_id = :company_id)
GROUP BY day
ORDER BY day;

-- ---------------------------------------------------------------------
-- 2. MCP spend by server/tool (last 7 days)
-- ---------------------------------------------------------------------
SELECT
    COALESCE((log_metadata::jsonb)->>'mcp_server', 'unknown') AS mcp_server,
    COALESCE((log_metadata::jsonb)->>'mcp_tool', 'unknown')   AS mcp_tool,
    SUM(calculated_cost) AS cost_usd,
    COUNT(*)             AS calls,
    ROUND(AVG((log_metadata::jsonb->>'latency_ms')::numeric), 0) AS avg_latency_ms
FROM usage_logs
WHERE attribution = 'mcp'
  AND timestamp >= now() - interval '7 days'
  AND (:company_id IS NULL OR company_id = :company_id)
GROUP BY mcp_server, mcp_tool
ORDER BY cost_usd DESC
LIMIT 50;

-- ---------------------------------------------------------------------
-- 3. UNATTRIBUTED guard: any cost row whose attribution is unknown.
--    Should always be empty (tools.cost_attribution_required is ON).
-- ---------------------------------------------------------------------
SELECT attribution, COUNT(*) AS rows, SUM(calculated_cost) AS cost_usd
FROM usage_logs
WHERE attribution NOT IN (
    'planner','actor_step','critic_pre','critic_post','critic_align',
    'critic_super','reformat_retry','meta_review','dreaming','tool',
    'child_run','embedding','meta_spec_critic','test_driver','sandbox','mcp'
)
  AND timestamp >= now() - interval '7 days'
GROUP BY attribution
ORDER BY cost_usd DESC;
