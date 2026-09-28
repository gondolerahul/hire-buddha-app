# Tenant data plane, Cortex, and ad hoc work

These epics add the ad hoc capabilities requested after the first roadmap pass. They extend the marketing/sales foundation to a complete business platform while preserving a shared control plane for identity, subscriptions, billing and minimal job routing. Business data, source files, Cortex state, generated code, applications and websites remain inside an isolated tenant environment.

## E36 — Isolated relational tenant data plane

**Outcome:** each tenant has a queryable, exportable business database and no tenant can read another tenant's business payload. **Baseline:** current code has shared models and several operational tables; the isolated relational data plane is new. **Dependencies:** E01/E02/E03/E04/E06/E07/E09/E12.

### E36-F01 — Tenant database and API

| Story | User need | Acceptance criteria | Gate |
|---|---|---|---|
| E36-S01 | As a tenant, I can store business records in a dedicated relational database. | Typed tables, foreign keys, constraints, indexes and reviewed versioned migrations are used; campaigns, contacts, activities, finance and other module records are queryable without a generic JSONB record store or JSONB custom-field bag. | H0 |
| E36-S02 | As a Skill or application, I can use a safe tenant data API. | Every request is tenant-scoped and authorized; filtering, sorting, pagination, transactions, validation, optimistic concurrency and audit attribution are defined; cross-tenant identifiers and unbounded queries fail safely. | H1 |

### E36-F02 — Control-plane boundary and operational migration

| Story | User need | Acceptance criteria | Gate |
|---|---|---|---|
| E36-S03 | As a platform owner, I can keep only the agreed metadata in the shared control plane. | Shared services retain identity/login, subscriptions, billing and minimal job-routing/accounting metadata; tenant business records, detailed execution payloads, files, Cortex, code, apps and websites are tenant-local; data placement is visible in architecture and access tests. | H0 |
| E36-S04 | As a GTM operator, I can use one tenant-owned history for campaigns, leads and calling. | Existing `campaigns`, `campaign_calls`, `lead_queue` and related lead/contact/calling data are migrated into typed tenant tables aligned with E13–E18; IDs, statuses, timestamps, consent, recordings/references and outcomes are preserved; the old shared path is removed after verified cutover. | H1 |

### E36-F03 — Isolation, limits and portability

| Story | User need | Acceptance criteria | Gate |
|---|---|---|---|
| E36-S05 | As a security owner, I can prove tenant isolation under every execution path. | API, tools, workers, event consumers, scheduled jobs, logs, caches, volumes and network policies enforce tenant boundaries; negative tests show a tenant cannot address another tenant's records or files; resource and storage limits are enforced. | H2 |
| E36-S06 | As an owner, I can recover or leave with my complete business state. | Export and restore include the tenant database plus artifact, source-document, Cortex and application manifests; checksums, schema version, permissions and restoration evidence are recorded; restore does not expose data to another tenant. | H4 |

## E37 — Tenant runtime, generated software and hosting

**Outcome:** a tenant can safely create and operate internal applications, generated tools and websites in its own containerized runtime. **Dependencies:** E01/E02/E03/E04/E08/E09/E12/E36.

### E37-F01 — Isolated runtime and persistent code

| Story | User need | Acceptance criteria | Gate |
|---|---|---|---|
| E37-S01 | As a tenant, I can run generated tools and code without host access. | Tenant containers have versioned runtime images, sandboxed processes, network/credential policy, CPU/memory/time limits and metering; no worker silently falls back to the host filesystem or host credentials. | H2 |
| E37-S02 | As a capability owner, I can reuse generated code safely. | Source, dependencies, tests, configuration references and build provenance are stored in tenant-local versioned repositories; workers rehydrate a pinned version; changes are reviewed, evaluated, promoted and rolled back through E32. | H5 |

### E37-F02 — Custom internal applications

| Story | User need | Acceptance criteria | Gate |
|---|---|---|---|
| E37-S03 | As an owner, I can request an internal app for a business need. | A goal is converted into a tenant-local app specification covering data tables/API, UI, workflows, permissions, limits and acceptance tests; the app can be previewed, edited and versioned before deployment. | H4 |
| E37-S04 | As an administrator, I can operate an app without bypassing platform controls. | App requests use the tenant API and approved Skills/tools; deployments are isolated, observable, cancellable and auditable; upgrades and rollback preserve records and active-run behavior. | H5 |

### E37-F03 — Websites, artifacts and storage

| Story | User need | Acceptance criteria | Gate |
|---|---|---|---|
| E37-S05 | As a tenant, I can build, preview and host a website. | Website source, assets, builds, preview URL and publication state are tenant-owned; provider/domain configuration is explicit and portable; publication is gated by permissions, safety checks and rollback. | H4 |
| E37-S06 | As an operator, I can find and manage files and generated artifacts. | Tenant storage uses stable folders for source mirrors, uploads, artifacts, code, apps and site builds; metadata includes owner, provenance, version, retention and checksum; quotas, alerts, deletion and restore are enforced. | H2 |

## E38 — Cortex knowledge graph and legacy RAG retirement

**Outcome:** tenant agents use a traceable, editable Cortex knowledge graph and procedural memory built from original source material. **Dependencies:** E01/E02/E05/E06/E09/E10/E12/E36/E37.

### E38-F01 — Guided source acquisition

| Story | User need | Acceptance criteria | Gate |
|---|---|---|---|
| E38-S01 | As a new tenant, I can teach the system about my company in a clear sequence. | Registration triggers bounded company-website research; the user is then asked for relevant uploads and connections to Google Drive, OneDrive, SharePoint and approved sources; progress, consent, scope and failures are visible in Pragya. | H1 |
| E38-S02 | As a tenant, I can keep originals and mirror updates predictably. | Original files are saved unchanged in tenant folders with source URI, path, version, checksum, timestamps and sync cursor; re-sync, rename, deletion and permission changes are represented without silently overwriting provenance. | H2 |

### E38-F02 — Traceable procedural intelligence

| Story | User need | Acceptance criteria | Gate |
|---|---|---|---|
| E38-S03 | As an operator, I can inspect and edit the tenant knowledge graph. | Entities, relationships, procedures, assumptions and confidence link back to exact source documents/locations; edits are versioned with author and reason; retrieval is tenant-scoped and permission-aware. | H3 |
| E38-S04 | As an agent, I can use Cortex evidence during work. | Skills receive citations/provenance, freshness and access decisions; conflicting or missing evidence is surfaced for review; procedural updates can be tested before they affect approved workflows. | H3 |

### E38-F03 — Remove the old RAG path

| Story | User need | Acceptance criteria | Gate |
|---|---|---|---|
| E38-S05 | As a platform owner, I can retire the legacy document-ingestion and RAG implementation. | Inventory old document/chunk tables, endpoints, jobs, indexes and flags; migrate required evidence; after cutover no production path reads or writes the legacy store, and old code/tables are removed (or retained only as an explicitly isolated legal archive). | H2 |
| E38-S06 | As an operator, I can verify the cutover did not lose knowledge. | Replay and comparison prove required source coverage, links, permissions and retrieval behavior; rollback is limited to the new Cortex version and does not re-enable the legacy RAG path; dashboards show orphaned or un-ingested originals. | H3 |

## E39 — Pragya solution design and ad hoc workbench

**Outcome:** Pragya is the single human interface for both packaged business operations and one-off work, and every new solution is designed collaboratively before deployment. **Dependencies:** E03/E05/E07/E08/E10/E12/E31/E33/E36/E38.

### E39-F01 — Ad hoc workbench

| Story | User need | Acceptance criteria | Gate |
|---|---|---|---|
| E39-S01 | As an owner, I can describe a finite business goal outside a standard pack. | Pragya accepts a goal, constraints, source data and desired outputs; it proposes a bounded one-off plan without requiring a permanent agent hierarchy or Solo/MSME/startup/enterprise pack activation. | H2 |
| E39-S02 | As an analyst, I can turn raw data into a defensible financial model, market study or presentation. | The run selects approved Skills/models/tools, records assumptions and calculations, cites evidence, produces editable artifacts, and routes material uncertainty or external effects for review. | H3 |

### E39-F02 — Collaborative solution architecture

| Story | User need | Acceptance criteria | Gate |
|---|---|---|---|
| E39-S03 | As a tenant, I can brainstorm a proposed solution with Pragya before deployment. | A full solution-architect Meta Agent turns the conversation into an editable blueprint containing goals, users, records, Skills/tools, integrations, events, schedules, permissions, budgets, risks, tests and success measures; unresolved assumptions remain visible. | H3 |
| E39-S04 | As a tenant and Pragya, we can edit the same design without losing decisions. | Voice, text and visual controls edit one versioned specification with near-real-time presence and conflict handling; changes show authorship/diff, conflicts and approval state; deployment is blocked until required reviewers approve the blueprint. | H5 |

### E39-F03 — Pragya control surface

| Story | User need | Acceptance criteria | Gate |
|---|---|---|---|
| E39-S05 | As a human operator, I can access supported business functions through one workspace. | Pragya supports voice-first and text interaction, contextual visual controls, generated analytics and drill-down; all actions still call authorized platform APIs/Skills and preserve audit/provenance. | H5 |
| E39-S06 | As an operator, I can stop unsafe work immediately. | A prominently available authenticated stop control revokes eligible execution, prevents queued effects, settles known usage, shows deterministic status and works when voice, a model or a secondary channel is unavailable. | H2 |

## E40 — Optional Graph/Loop operating model and digital twin

**Outcome:** tenants that need organizational modeling can traverse and operate an optional Graph → Loop → Process → Agent → Skill → Action structure. Graph and Loop are a nice-to-have; ordinary workflows remain valid without them. **Dependencies:** E03/E06/E07/E08/E10/E31/E33/E39.

### E40-F01 — Hierarchy persistence and compilation

| Story | User need | Acceptance criteria | Gate |
|---|---|---|---|
| E40-S01 | As an owner, I can model my whole business as an optional Graph. | A Graph represents the tenant business; a Loop represents a department/function; Process, Agent (role), Skill and Action (tool wrapper) retain their defined semantics; each node has version, owner, policy, budget and data scope. | H5 |
| E40-S02 | As an administrator, I can validate and compile the hierarchy into executable work. | References resolve to versioned Skills/actions; permissions, budgets, memory scope, schedules and event subscriptions are checked before activation; cycles, duplicate ownership and unresolved nodes fail with actionable diagnostics. | H5 |

### E40-F02 — Isometric digital twin and analytics

| Story | User need | Acceptance criteria | Gate |
|---|---|---|---|
| E40-S03 | As an owner, I can zoom from business overview to an individual action. | The new frontend's isometric digital twin traverses Graph → Loop → Process → Agent → Skill → Action, shows dependencies and live status, and distinguishes organizational Graph from workflow DAG and evidence knowledge graph. | H5 |
| E40-S04 | As an operator, I can edit the model visually and inspect its evidence. | Visual edits use the same versioned blueprint as Pragya, show impacted permissions/budgets/runs, link analytics to tenant records and source documents, and provide an accessible non-3D fallback. | H5 |

### E40-F03 — Optional organizational operations

| Story | User need | Acceptance criteria | Gate |
|---|---|---|---|
| E40-S05 | As a business owner, I can add or reorganize departments without duplicating execution. | Adding/removing Loops recomputes routing, policy inheritance, budgets and reporting; existing runs pin their versions; event and schedule subscriptions remain idempotent. | H6 |
| E40-S06 | As a tenant without the hierarchy, I can still run normal work. | Flat Process/Agent/Skill/Action workflows and ad hoc jobs operate with equivalent authorization, observability and stop controls; enabling the hierarchy is reversible and does not copy executable Skills. | H5 |
