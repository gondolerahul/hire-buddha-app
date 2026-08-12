# Phase 12 KPI Dashboards (P-O1)

Three SQL pages covering the Phase 12 capability surfaces, extending the Phase 11
dashboards. Same convention: each query takes a single `:company_id` parameter
(`NULL` = platform-wide). Wire into Grafana/Metabase as SQL-backed panels.

| File | Page |
|------|------|
| `01_csat.sql` | CSAT rate over time, critic false-pass proxy (thumbs-down on COMPLETED), thumbs-down triage queue |
| `02_sandbox_mcp_cost.sql` | Sandbox (`02` S6) spend, MCP (`07` §1) spend by server/tool, UNATTRIBUTED-cost guard |
| `03_tool_synthesis_trust.sql` | Synthesized (DRAFT) tool inventory + promotion funnel (`06` §2), learned vs prior source trust (`07` §3) |

## New source data (Phase 12)

- `execution_runs.csat_score` / `csat_comment` — first-party CSAT (migration `p12_run_csat`).
- `usage_logs.attribution` adds `sandbox` and `mcp` tags.
- `tool_registry_entries` with `tool_type='SYNTHESIZED'` — synthesized DRAFT tools;
  `configuration` JSON holds `status` / `trust` / `network_policy` / `audit`.
- `source_trust_scores` — learned per-source provenance trust (migration `p12_source_trust_scores`).
