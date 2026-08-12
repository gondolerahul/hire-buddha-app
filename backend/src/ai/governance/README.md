# `governance/` — Cost, HITL, rate limiting

The thin "is the agent allowed to spend this?" layer between the
loop and the LLM / tool providers.

## What's in here

| File | Purpose |
|------|---------|
| `governance_service.py` | HITL approval handling, run-level budget caps, cost-threshold triggers. |
| `rate_limiter.py` | Per-company / per-tool call-budget enforcement. |
| `tool_cost_resolver.py` | Phase 11 Track 8 single source of truth for tool cost lookup. Cached per-process. Routes every charge through `CostLedger` with `attribution="tool"`. |

## Key types

- `ToolCostResolver`, `ToolChargeResult`.
- `TOOL_SKU_MAP`, `TOOL_FIXED_COST` (the canonical lookup tables).

## Entry points

- `ToolCostResolver(db, company_id).charge(run=..., tool_id=..., attribution=...)` — every tool-call cost in the agent loop.
- `CostLedger` (in `services/cost_attribution.py`) is the persistence side.

## See also

- `docs/phase11/plan/10_track_8_tool_and_cost.md`
- `services/cost_attribution.py` (the ledger + `CostAttribution` enum).
