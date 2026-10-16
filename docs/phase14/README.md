# Phase 14 — Autonomous business on Azure

> **Status:** Planning documents. Nothing here is implemented yet.
> **Date:** 2026-10-16

Phase 14 turns HireBuddha from "a person clicks Run" into a platform where the business runs itself, and gives every tenant its own private database, connections, code and apps — all on Azure.

| # | Document | For | What it answers |
|---|----------|-----|-----------------|
| 01 | [Implementation plan](01_implementation_plan.md) | Engineering leads | Workstreams WS0–WS9, tasks with the files they touch, milestones M0–M8, risks, switch-over runbook |
| 02 | [Technical specification](02_tech_spec.md) | Engineers | Architecture, tenant databases, events/triggers/scheduler, schema engine, Data API, connections, sandbox and app hosting, security, Azure services, decisions and spikes |
| 03 | [Functional specification](03_functional_spec.md) | Product, design, QA | What owners, admins, operators and app users can do; screens; rules; notifications; traceability to roadmap stories |
| 04 | [Azure environment setup (CLI)](04_azure_environment_setup.md) | Platform engineers | Step-by-step creation of the Azure dev environment with the Azure CLI, and how staging/production differ |
| 05 | [Azure environment setup (portal)](05_azure_environment_setup_portal.md) | Platform engineers | The same dev environment through the Azure portal in a browser; the few non-portal steps run in Cloud Shell |

Read order: 03 → 02 → 01 → 04 or 05.

**Roadmap links:** decisions D34–D40 and open items O10/O11 in [`01-product-decisions.md`](../product-road-map/Refined-Road-Map/01-product-decisions.md); stories in E07 and E09 ([`02-platform-backlog.md`](../product-road-map/Refined-Road-Map/02-platform-backlog.md)) and in E36, E37 and E41 ([`08-ad-hoc-tenant-platform-backlog.md`](../product-road-map/Refined-Road-Map/08-ad-hoc-tenant-platform-backlog.md)).

**Open before work starts:** O10 (how tenant databases are placed on servers), O11 (Azure regions), TD-13 (Bicep or Terraform), and spikes SP-1…SP-10 (tech spec §18.2). Spike notes go in `docs/phase14/spikes/`.
