# Phase 14 — Autonomous business on Azure

> **Status:** In development. WS0–WS8's code exists and is tested; Azure dev runs it — M1 proved except the owner's steps, **M2 proved on 21 Oct** (dev in `split`: every business in its own database, isolation suite passing). **Production is deployed** (21 Oct); **M6 proved on dev on 22 Oct** (slice 4: sandbox isolation, and a CRM through a pull request, preview, merge, publish and a custom domain). Left: slice 4 on production, WS4/WS3 leftovers, hardening; no staging (D51) and a manual move from GCP (D56) — see 06.
> **Date:** 2026-10-16 (plan) · 2026-10-22 (status)

Phase 14 turns HireBuddha from "a person clicks Run" into a platform where the business runs itself, and gives every tenant its own private database, connections, code and apps — all on Azure.

| # | Document | For | What it answers |
|---|----------|-----|-----------------|
| 01 | [Implementation plan](01_implementation_plan.md) | Engineering leads | Workstreams WS0–WS9, tasks with the files they touch, milestones M0–M8, risks, switch-over runbook |
| 02 | [Technical specification](02_tech_spec.md) | Engineers | Architecture, tenant databases, events/triggers/scheduler, schema engine, Data API, connections, sandbox and app hosting, security, Azure services, decisions and spikes |
| 03 | [Functional specification](03_functional_spec.md) | Product, design, QA | What owners, admins, operators and app users can do; screens; rules; notifications; traceability to roadmap stories |
| 04 | [Azure environment setup (CLI)](04_azure_environment_setup.md) | Platform engineers | Step-by-step creation of the Azure dev environment with the Azure CLI, and how staging/production differ |
| 05 | [Azure environment setup (portal)](05_azure_environment_setup_portal.md) | Platform engineers | The same dev environment through the Azure portal in a browser; the few non-portal steps run in Cloud Shell |
| 06 | [Implementation status](06_implementation_status.md) | Everyone | What is built and tested, decisions taken while building, what is left to get M1 on Azure dev |

Read order: 03 → 02 → 01 → 04 or 05.

**Roadmap links:** decisions D34–D40 and open items O10/O11 in [`01-product-decisions.md`](../product-road-map/Refined-Road-Map/01-product-decisions.md); stories in E07 and E09 ([`02-platform-backlog.md`](../product-road-map/Refined-Road-Map/02-platform-backlog.md)) and in E36, E37 and E41 ([`08-ad-hoc-tenant-platform-backlog.md`](../product-road-map/Refined-Road-Map/08-ad-hoc-tenant-platform-backlog.md)).

**Decided 18 Oct 2026:** O10 → shared pool servers (D42), O11 → Central India (D43; DR region open), TD-13 → Bicep (D44), O06 backups → weekly exports (D45), and no merge to `main` / no `release/gcp` for now (D46). **Still open:** O05 automation limits, the app template stacks, O06 recovery and support targets, and spikes SP-1…SP-10 (tech spec §18.2; notes go in `docs/phase14/spikes/`).
