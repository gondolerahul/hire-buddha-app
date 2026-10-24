# Phase 15 — Configuration, costing & billing, and the partner module

> **Status:** Analysis (01–04), plan (05–08); implementation under way — M15.0 Guardrails, M15.1 Money core, M15.2 Wallet and controls, M15.3 Commercial, M15.4 Partner programme and M15.5 New UI built (09).
> **Date:** 2026-10-22 (analysis) · 2026-10-23 (plan)
> **Branch analysed:** `roadmap-development-defect-fixes` at `53be0bd`

Phase 15 starts by taking stock of three areas that grew piece by piece through Phases 1–14: **where the product is configured**, **how it costs and bills work**, and **what partners (resellers) can do**. These documents describe what the code does today, with file references, and propose what to change.

| # | Document | What it answers |
|---|----------|-----------------|
| 01 | [Configuration and settings inventory](01_configuration_and_settings.md) | Every setting (environment, Python constants, YAML/JSON, database), what it changes in the product, which ones the UI can change, which could move to the database and the UI |
| 02 | [Costing and billing rules](02_costing_and_billing.md) | Every rule for pricing, metering, credit admission, settlement, wallets, subscriptions and payments; what is configurable; gaps, leaks and the multi-currency design |
| 03 | [Partner module](03_partner_module.md) | Every partner rule that exists today, and an approach to a richer, safer partner (reseller) module |
| 04 | [Consolidated improvement backlog](04_consolidated_improvements.md) | One prioritised list built from 01–03, grouped into workstreams with dependencies |
| 05 | [Requirements, decisions and conflicts](05_requirements_decisions_and_conflicts.md) | The owner's feature requests and answers (23 Oct), numbered requirements, every conflict with 01–04 and the approach adopted, and the decisions on the 12 open questions |
| 06 | [Technical design](06_technical_design.md) | Money pipeline, cost units, currency/FX, per-second metering, rating, wallet lots/debt/enforcement, daily credits, settings and locks, hosting SKUs, entitlements, partner programme (types, levels, commissions, underwriting, risks), payments/GST, number rent, APIs, data model |
| 07 | [UI, navigation and reports](07_ui_navigation_and_reports.md) | Three workspaces, menus per role, key page specs, role × capability matrix, report catalogue (47 reports), dashboards, mapping of every current page |
| 08 | [Implementation plan](08_implementation_plan.md) | Workstreams WS15-0…10 with tasks and files, milestones, migration order, testing, switches, risks, effort, traceability |
| 09 | [Implementation status](09_implementation_status.md) | What is built, where, and the proof; decisions taken while building |

Read order: analysis — this page → 02 → 03 → 01 → 04; plan — 05 → 06 → 07 → 08.

---

## How the product works (the parts these documents depend on)

HireBuddha is a multi-tenant platform where a business builds AI agents in a web form, runs them on background workers, watches them reason live, approves risky steps, and is billed for what the work cost.

### Company tree and roles

`companies` is a tree ([auth/models.py:9](../../backend/src/auth/models.py)):

```
APP (exactly one — HireBuddha)
 ├── PARTNER (resellers)
 │    └── TENANT (end customers of a partner)
 └── TENANT (direct customers; parent_id NULL)
```

Six roles ([auth/roles.py](../../backend/src/auth/roles.py)): `app_admin`, `app_user`, `partner_admin`, `partner_user`, `tenant_admin`, `tenant_user`. Visibility is one rule ([auth/visibility.py](../../backend/src/auth/visibility.py)): app roles see every company, partner roles see their own company and its direct children, everyone else sees their own company. A user may work "as" a visible company by sending `X-Company-Id` ([common/tenancy/session.py:130](../../backend/src/common/tenancy/session.py)).

### What runs, and where data lives

- **Agents are rows.** `hierarchical_entities` holds ACTION / SKILL / AGENT / PROCESS (plus the optional LOOP/GRAPH levels) with nine JSON columns: identity, hierarchy, logic gate, planning, capabilities, **governance** (cost cap, timeouts, HITL), I/O contract, observability, metadata extensions (per-entity feature-flag overrides).
- **Runs** (`execution_runs`) execute on Arq workers under the `AgentLoop` (planner → steps → critics → memory), streamed to the browser over SSE.
- **Channels:** web "Execute", automation triggers and schedules (Phase 14 WS3), inbound phone calls and WhatsApp, outbound voice campaigns (Twilio / Tata Smartflo), a mobile dialer app, browser audio/video calls.
- **Phase 14 tenancy:** a *control* database (identity, companies, billing, registry, flags, directory) and, in `TENANCY_MODE=split`, one *tenant* database per business (agents, runs, records, apps, campaigns). Billing is control-plane.
- **Tenant platform (Phase 14):** a records schema engine and Data API per business, connections (OAuth/API keys), code lanes with Git, hosted apps on AKS, per-tenant sandbox.

### Money in one paragraph

Every model call, tool call, phone minute and sandbox second writes a `usage_logs` row at the **provider's price** (from `integration_registry.internal_cost`, or a hard-coded price). A run's raw cost is the sum of its rows. When a top-level run or a call ends, the raw cost goes through the **TB formula** — `TB = c·mf + c·mf·pf + c·mf·spf − c·mf·d` — and the result is deducted from the company's **credit wallet** (daily → subscription → bonus → top-up buckets) and added to a monthly **billing event**. Credits are US dollars; top-ups and subscriptions are paid through **Razorpay in USD**.

### Database snapshot used for this analysis

The local control database (`hirebuddha`) was rebuilt on 21 Oct 2026 and holds seed data only: 5 companies (the APP company "HireBuddha" and four TENANTs, **no PARTNER**), 3 users, 4 `integration_registry` price rows (Gemini 2.5 Flash in/out, text-embedding-005, sandbox-runtime), 5 `model_task_defaults`, 14 `connector_catalog` rows, 2 wallets with zero balances, and **no** `billing_config`, `subscription_tiers`, `billing_events` or `feature_flags` rows. Tenant databases `t_devacme01`, `t_devbeta001` and two isolation tenants exist with the 54-table `platform` schema. Because the data is thin, the rules below are taken from the code and the schema; where data would change a conclusion it says so.
