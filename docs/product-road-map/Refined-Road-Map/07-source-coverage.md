# Source coverage, baseline evidence, and defect linkage

## What informed the synthesis

All six files present in `rough-outline/` were reviewed for product requirements and conflicting claims. The functional sections, decision amendments, catalogs and target-state designs informed this roadmap. Code illustrations in those documents are not treated as implemented behavior. The owner subsequently directed a rebuild from the GTM model, so the older blueprint is an inventory of needs rather than a governing architecture.

| Key | Source | Treatment |
|---|---|---|
| **GTM** | [Marketing and sales design](../rough-outline/marketing-sales-automation.md) | Primary business design: hybrid records, tenant zero, lean entities, explicit triggers, deterministic enrollment and governed outreach; extend these patterns across business functions |
| **FEAS** | [Marketing and sales feasibility](../rough-outline/marketing-sales-automation-feasibility.md) | Reality corrections and missing foundations; September correction to experimental-tool gating takes precedence over the stale contradictory sentence in its own §5 |
| **SK** | [Skill-first capability model](../rough-outline/skill-first-capability-model.md) | Owner-confirmed authoring direction: DB-backed immutable Skills, assets, controlled primitives, runtime images, progressive disclosure, metering and measured migration |
| **RF** | [Rough product functional documentation](../rough-outline/product_functional_documentation.md) | Useful Pragya, UX, memory, routing, governance and modality requirements; maturity labels and sales promises are not accepted at face value |
| **RT** | [Rough product technical documentation](../rough-outline/product_technical_documentation.md) | Candidate semantics for ownership, sync, scoping, versioning, budgets, evaluation and exports; correct inconsistencies between separate databases and transaction claims; Graph/Loop is optional rather than a mandatory runtime architecture |
| **BP** | [Unified business blueprint v2](../rough-outline/Unified Business Process & Agent Template Blueprint v2.md) | Coverage inventory of business responsibilities, governance and human roles; discard mandatory counts, default Solo Pack, fixed bundles and old entity hierarchy |
| **CURRENT** | [Current documentation index](../../current/README.md) | Current architecture/navigation and distinction between current vs target product; older summary manuals can contain overclaims |
| **DR** | [Module defect index](../../current/defect-register/README.md) and [earlier defect register](../../current/DEFECT-REGISTER.md) | Launch/readiness work and known integration defects; preserve original IDs and confidence labels rather than treating every issue as freshly verified |

No missing `codebase_current_state_analysis.md`, `roadmap_gap_register.md`, earlier v1 blueprint, or deleted refined roadmap was used as an unseen authority. Existing broken/old relative paths in rough documents were not copied into the new roadmap. Source documents were not rewritten.

## Coverage of the rough functional direction

| Source area | Refined destination | Disposition |
|---|---|---|
| RF §§1–2: design/deploy/employ, hierarchy, bundles | E02/E08/E10/E34; operating model | Retain lifecycle and configurable work; replace rigid roster/Loop packaging with capability-based adoption |
| RF §3 / RT §§3–5: model fleet, router, media and voice | E31/E35; E11 | Retain as staged capabilities; optional proprietary-model research does not gate business usefulness |
| RF §4 / RT §11: Pragya nine-stage discovery and verified channels | E10; E01-S06 | Retain research → assumptions → ingest → revise → co-design → blueprint → integrate → test/deploy → operate; no compulsory Solo Pack |
| RF §5 / RT §6: Meta-Agent / Board | E10-S03/S04; E32 | Reuse candidate construction, but repair iteration/promotion/evaluation gaps before promising automatic builds |
| RF §6: web, documents, email, media, connector catalog | E08/E09/E11/E13/E14/E31 | Native Skills and controlled tools; a connector name is not a working integration |
| RF §7 / RT §12: execution | E02/E03/E04 | Retain finite execution; avoid inconsistent 8/9/10-stage counts as product requirements |
| RF §8: channels/campaigns | E11/E15/E16 | Separate voice campaign from GTM campaign; add actual scheduling and policy gates |
| RF §9 / RT §§13,24: knowledge/personality/memory | E05/E11 | Grounded scoped retrieval, counterparty continuity and evaluated conduct; remove “memory shipped” shortcut |
| RF §10 / RT §7: learning | E32 | Measure changes against incumbent; no promised Week-12 compounding |
| RF §11 / RT §8: Generative UI | E33 | Owner reconfirmed new frontend after explicit design gate |
| RF §12 / RT §9: self-evolving code | E08/E32 | Skills first; independent evaluation and promotion; no self-approved production rewriting |
| RF §13 / RT §§10,19,21,23: schema/native business systems | E06/E09 and E19–E30 | Extend GTM records into native modules; separate system-of-record authority from business write ownership |
| RF §14 / RT §§14,20,23: credits/budget/reservations | E04 | Correct live billing first; owner rejected intentional debt; reserve safe completion |
| RF §15 / RT §§15,20: security/authority | E01/E03/E11/E27 | Deterministic controls and enforceable audit boundaries |
| RT §17: standing LOOP | E07/E34/E40 | Retain standing-work supervision and health; implement Graph/Loop only as an optional organizational model under the owner's new hierarchy |
| RT §18: signals | E07 | Durable local outbox plus relay when business/control stores differ; at-least-once delivery with idempotent consumption/effects |
| RT §22: evaluation | E12/E31/E32 | Independent suites/canaries/model regressions retained; claimed functioning CI corrected by current defects |
| BP §§9–13: governance, humans, continuity, scale | E01/E03/E04/E11/E12/E27/E34 | Retain functional requirements; replace “never pause” and physical-isolation absolutes with explicit boundaries |
| GTM §§4–5: decisions and 14-object core | E06/E09/E36; D02 | GTM record and mastering patterns are extended into the isolated tenant relational data plane; exact connector choices remain open; Contact lifecycle and typed core/custom extensions are the proposed semantic model |
| GTM §§6,9–10: six GTM processes and increments | E13–E18; delivery gates | Retain outcomes; bring safe deal preparation/RFP drafts forward; reporting waits for real records |
| GTM §§8,11–12: timing, consent, review, economics, PII | E03–E07/E11/E12/E16/E18/E34 | Treat as first-class product requirements; no external live pilot bypass for tenant zero |
| SK §§6–11: Skill storage/assets/runtime/governance/promotion | E08/E32 | Owner-confirmed target; immutable versions, isolated scripts, metered runtime and controlled primitives |
| SK §12: migration | E08-S05/S06; delivery gates | Document factory reference first; social pilot only after controls and measurements; no mandated primitive-count target |

## Coverage of the ad hoc requirements

| Ad hoc requirement | Refined destination | Disposition / evidence |
|---|---|---|
| Revalidate and fix current defects | E12-S07–S09; all epic stories inherit the defect register | Every register item is rechecked against the current implementation, classified with evidence, and either repaired, replaced, retired or explicitly deferred; no “fixed” claim is made by documentation alone |
| Exotel telephony comparable to Smartflo use cases | E11-F04 (E11-S07–S10) | Complete tenant-scoped credentials, inbound/outbound lifecycle, signed callback reconciliation, recordings/consent, metering, retry and human fallback. Current code contains Smartflo adapters and a gateway Exotel mention, so a provider label is not treated as proof of Exotel support. |
| Signal bus, pub/sub, scheduling and autonomous execution | E07 plus E02/E03/E04; E07-S01–S06 | Durable schedules, outbox/relay, idempotent consumers/effects, policy-approved routine autonomy, exception review, stop and recovery are foundational. |
| Isolated tenant relational DB, APIs, runtime, apps/sites, storage and artifacts | E36/E37 | Shared control plane is limited to identity, subscription/billing and minimal routing; tenant containers own business DB, Cortex, files, code, apps and sites. |
| Campaign, lead and calling data in tenant DB | E36-S04; E13–E18 | Current `campaigns`/`campaign_calls`/`lead_queue` code is treated as migration input; IDs, outcomes and consent are reconciled before the shared path is removed. |
| Graph → Loop → Process → Agent → Skill → Action | E40; E07/E08/E33 | Optional organizational hierarchy with Graph as whole business and Loop as department/function; distinct from workflow DAG and knowledge graph; flat workflows remain valid. |
| Unified whole-business process based on GTM | 00 operating model; E13–E30 | GTM is the governing base, extended into customer, delivery, finance, people, legal, risk, product and corporate functions; old packs/counts are not copied. |
| Ad hoc modeling/research/presentation work | E39-F01 | Goal/data/output intake creates bounded one-off work with cited evidence and editable artifacts alongside recurring business packs. |
| Pre-deployment brainstorming and solution architecture | E39-F02; E10; E33 | Pragya and a full Meta Agent architect produce one editable, versioned blueprint; required approval gates deployment; visual/3D editing is covered by E40. |
| Required model catalog and intelligent routing | E31-F01/F02/F03/F04 | Gemini, Claude, OpenAI, GLM, Qwen, Kimi; Veo, Seedance, Wan; Gemini Image, GPT Image, Qwen Image, Kling. Adapter/version validation and measured routing precede production use. |
| Cortex learning, editable knowledge graph and procedural intelligence | E05/E32/E38 | Originals and source links stay tenant-local; Cortex graph/procedures are editable, permission-aware and traceable; current Cortex code is partial evidence, not completion. |
| Pragya as the only human interface | E39-F03; E10/E33 | Voice-first with text, visual controls, analytics drill-down and immediate stop; legacy screens are transitional until parity and accessibility pass. |
| BabyBuddha and OmniBuddha | E35 | Conditional H6 research with opt-in data use, independent evaluation and rollback; not an assumed launch dependency. |
| Remove old RAG/document ingestion | E38-F01/F03 | Registration → website research → uploads → connected drives; originals persist in tenant folders; Cortex becomes the sole production path and old tables/jobs/endpoints are removed after verified cutover. Current ARQ code explicitly mentions dual-write to `document_chunks`, so retirement remains required work. |

## Old business process coverage, not the new product taxonomy

This mapping prevents loss of useful business needs without retaining the old 19-process architecture. Many old Processes become several capabilities; some new epics combine responsibilities. The new epics do not require corresponding runtime entities.

| Old ID / label | Refined coverage | Important correction |
|---|---|---|
| P01 Signal-to-Insight | E13, E18, E27, E29 | Distinguish business observations, operational events and actual activities |
| P02 Awareness-to-Demand | E14, E16 | Drafting, editorial state, permission and publication are separate capabilities |
| P03 Cold-to-Closed Acquisition | E13, E15–E17, E26 | Split inbound/outbound/deal work by state and control needs |
| P04 Partner-to-Revenue | E30-S01/S02 | Commercial partners reuse counterparties and agreements; distinct from platform partner administration |
| P05 Order-to-Fulfilled | E20 | Delivery acceptance and resource/inventory constraints must be real before billing |
| P06 Resolve-to-Retain | E19; shared E05/E11/E15 | Support, education and appointments reuse shared services instead of duplicate agents |
| P07 Renew-and-Expand | E19-S05/S06; E17/E26 | Renewal dates and terms are authoritative records, not inferred promises |
| P08 Order-to-Cash | E21/E23 | Business receivables are not the platform wallet |
| P09 Source-to-Pay | E22/E20/E23 | Supplier verification, matching and payout approval remain independent |
| P10 Record-to-Report | E23/E24 | Double-entry and close controls are explicit native requirements |
| P11 Plan-Budget-Forecast | E24/E29 | Business financial planning is separate from AI execution budgets |
| P12 Hire-to-Retire | E25/E28 | Human employment decisions, supported payroll scope and verified revocation |
| P13 Draft-Review-Sign | E26 | Review binds exact terms/version/signatories; signature is provider-confirmed |
| P14 Continuous Guardrails | E27 plus E01/E03/E11 | Mandatory runtime policy is a service, not an optional compliance agent |
| P15 Provision-and-Maintain | E28/E09/E12/E32 | Distinguish business assets/access, platform operations and reviewed code repair |
| P16 Idea-to-Launch | E29 | Evidence, experiments, approved pricing and launch readiness |
| P17 Incident-to-Resolution | E27-S05/S06; E03-S06/E12 | Emergency stop and deterministic alerts cannot depend on unbounded paid AI |
| P18 Capital-and-Stakeholders | E30-S03/S04 | Reports/diligence/research retained; no autonomous capital commitments |
| P19 Sense-Decide-Optimize | E10/E18/E24/E30/E32 | Separate executive decision support from platform self-modification |

Additional blueprint functions have explicit homes: PR/community/reputation/events → E14; customer education/advocacy → E19; manufacturing/inventory/shipping/returns → E20 with depth scoped separately; insurance/secretarial/privacy/security/ESG obligations → E27 with applicability reviewed; facilities/licenses/access/data pipelines → E28; pricing/R&D/product → E29; executive coordination/board work and corporate-development research → E30. Physical tasks are assigned to humans/providers and verified through evidence; generic AI execution is not a promise of physical automation.

## Selected current-state checks made during this review

Repository HEAD at review: `4da8f2f`. The working tree also contained pre-existing changes. These are static checks on 16 September 2026, not runtime tests or an audit of every module.

| Observed code | What the observation supports | Backlog |
|---|---|---|
| [AgentLoop](../../../backend/src/ai/core/agent_loop.py), `_setup_components`, line 766 constructs `memory_assembler=None` | Live perceiver is not receiving the intended memory assembler | E05-S02/S04 |
| [Step executor](../../../backend/src/ai/step_executor.py), context filtering around line 217 | Internal memory/semantic context keys are stripped on this path; simply storing knowledge is insufficient | E05-S02/S03; E02-S01 |
| [Tool executor](../../../backend/src/ai/tool_executor.py), lines 119 and 287 | Lookup/schema calls omit company context; current path cannot be assumed to enforce tenant capability visibility/status | E08-S04 |
| [MCP client](../../../backend/src/ai/tools/mcp/client.py) | Client is a protocol contract, not a implemented production transport in that file | E09-S02; broader no-caller finding remains sourced to FEAS/TL |
| [Worker](../../../backend/src/ai/worker.py), `WorkerSettings.cron_jobs` | Listed jobs are platform maintenance; no tenant schedule dispatcher or billing-cycle registration in this list | E07-S01/S02; E04-S01 |
| [Approval service](../../../backend/src/ai/governance/governance_service.py), lines 376–396 | Timeout may auto-approve; other pub/sub exceptions log and continue; generic failures are not fail-closed | E03-S02 |
| [Campaign model](../../../backend/src/ai/campaign_models.py), line 72, plus search for `scheduled_start` in `backend/src` | Results are declaration/acceptance/storage/response, not a due-time dispatcher | E07-S02 |

Other baseline claims in the backlog are **documentation-reported**, including no complete business-object store, incomplete social integrations, billing defects, CI failures and gateway/voice defects. The source registers state their original verification dates/confidence. Re-check against current code before implementing a fix. No percentages of product readiness are inferred from this small sample.

## Defects that materially change the functional roadmap

Identifiers below preserve the source register's ownership. This is a capability-level triage, not a duplicate issue tracker or a claim that every listed defect is freshly verified.

| Known finding / source IDs | Functional consequence / required work | Stories |
|---|---|---|
| AU-01/AU-02/AU-03/AU-04; EP-01; TL-03/TL-06/TL-09 | Permissions, tenant ownership, credential access and suspension must be reliable before external operation | E01-S01–S04; E11-S01 |
| AU session/reset/revocation findings; GW-04 | User and streaming identities must be authenticated/revocable | E01-S03/S04/S06; E11-S06 |
| BC-01–BC-04; legacy D-01–D-03 | Purchased credits/subscriptions and recurrence must actually work | E04-S01 |
| BC-05/BC-06; AK-02; GH-02/GH-18 | Admission, cost gates and concurrency need consistent reservation/enforcement | E04-S02–S05 |
| BC-07–BC-13; TL-19/TL-20 | Missing/double cost rows and voice/tool attribution prevent honest economics | E04-S02; E18-S04 |
| GH-01/GH-06/GH-07/GH-09/GH-11 | Fail-open, blocking, malformed, opaque approval is not usable A1 autonomy | E03-S01/S02 |
| GH-03/GH-04/GH-21; TL-11–TL-15/TL-21 | Flag/limit/policy text is not an enforced control | E01-S04; E02-S05; E03-S03; E08-S03/S04 |
| AK-01/AK-03/AK-07/AK-17; PC-06 | Completion, suspend/finalize, child limits and retries need real-path correction | E02-S03–S05 |
| EP-04–EP-11; PO-09 | Input contracts, editable settings, status and versions must affect behavior | E02-S01/S02/S05 |
| MC-01/MC-03/MC-04; AK-05/AK-06; FEAS N-1/N-2 | Stored knowledge and lessons must reach agent retrieval/context | E05-S02/S04 |
| MC scoping/deletion/retrieval findings | Cross-channel memory needs explicit permissions, source lifecycle and evaluation | E05-S03/S05/S06 |
| EP-02; TL-10/TL-13/TL-14/TL-22; legacy D-20; FEAS N-6 | Tenant tools, disabled statuses, durable registration and MCP are not solved by metadata rows | E08-S04; E09-S02 |
| TL-01/TL-02/TL-07/TL-08/TL-15–TL-18/TL-36/TL-42; MI-16; FEAS N-7 | Scripts/browser/artifacts cannot rely on host-user execution or scratch persistence | E08-S03; E12-S04/S05 |
| GW-01/GW-03/GW-17; VT-14; FEAS N-5 | Verified deterministic event routing and working queued entry points are prerequisites for inbound sales | E01-S05; E07-S03/S04; E15-S01 |
| FEAS N-4 | A stored start time must create due work | E07-S02 |
| TL-39; EP-13/EP-14; GW-03 | Retryable external operations need real effect idempotency and reconciliation | E02-S04; E07-S04; E16-S04 |
| TL-04/TL-09; FEAS N-9 | Recipient/account/credential and external ad-spend boundaries need enforcement | E11-S01; E04-S06; E14-S06 |
| FEAS N-10 | Tenant automation needs machine identity, not a human refresh-token workaround | E01-S05 |
| PO-06/PO-07; TL-37–TL-49; voice/messaging register | Experimental/incompatible/unconfirmed providers cannot be advertised as supported | E09-S01/S06; E11; E14-S04; E31-S03/S04 |
| MI-01–MI-09/MI-18 | Reuse, revision and meaningful tests must precede generated capability promotion | E10-S03; E32-S02 |
| TS-01–TS-05/TS-08; FE-01–FE-04 | Releases need actual CI, truthful checks, safe local defaults and recoverable UI | E12-S01–S03 |
| Source absent capabilities: consent, records, tenant scheduling, enrollment | These are new features, not merely defect repairs | E06/E07/E11/E16 |

FEAS's stdout truncation issue is covered by E02-S06; its inert memory UI toggles by E02-S01/E05-S02; its missing entrypoint-type filtering by E07-S03. The feasibility file's later corrections about social opt-in and missing platform connections override earlier optimistic paragraphs.

## Register ownership for subsequent delivery

The historical module index reports 459 defects and 202 improvements. Those counts are **source-reported inventory**, not a new census or a commitment to create one story per issue. The original 45-item register overlaps the module registers; do not add its count again. Use the relevant register when splitting a functional story into implementation tasks.

| Register | Refined epics that own affected capabilities |
|---|---|
| [01 Product](../../current/defect-register/01-PRODUCT-OVERVIEW-DEFECTS.md) | E02/E03/E05/E08/E09/E12/E36/E37/E38/E39/E40 |
| [02 Architecture](../../current/defect-register/02-SYSTEM-ARCHITECTURE-DEFECTS.md) | E02/E07/E11/E12 |
| [03 Data model](../../current/defect-register/03-DATA-MODEL-DEFECTS.md) | E02/E04/E05/E06/E08/E12/E36/E38 |
| [04 Authentication](../../current/defect-register/04-AUTH-RBAC-TENANCY-DEFECTS.md) | E01/E09/E10/E34/E36/E37/E39/E40 |
| [05 Agent kernel](../../current/defect-register/05-AGENT-KERNEL-DEFECTS.md) | E02/E04/E05 |
| [06 Execution](../../current/defect-register/06-EXECUTION-PIPELINE-DEFECTS.md) | E01/E02/E05/E08/E36/E37/E39/E40 |
| [07 Planning/critics](../../current/defect-register/07-PLANNING-AND-CRITICS-DEFECTS.md) | E02/E03/E32 |
| [08 Memory](../../current/defect-register/08-MEMORY-AND-CORTEX-DEFECTS.md) | E05/E32 |
| [09 Tools](../../current/defect-register/09-TOOLS-DEFECTS.md) | E08/E09/E11/E31/E36/E37/E39 |
| [Tool layer](../../current/defect-register/TOOL-LAYER-DEFECTS.md) | E01/E02/E04/E08/E09/E11/E14/E16/E31 |
| [10 LLM providers](../../current/defect-register/10-LLM-PROVIDERS-DEFECTS.md) | E02/E04/E31 |
| [11 Meta-intelligence](../../current/defect-register/11-META-INTELLIGENCE-DEFECTS.md) | E08/E10/E32 |
| [12 Voice/telephony](../../current/defect-register/12-VOICE-AND-TELEPHONY-DEFECTS.md) | E07/E11/E15/E16/E31/E36 |
| [13 Gateway](../../current/defect-register/13-GATEWAY-AND-REALTIME-DEFECTS.md) | E01/E02/E07/E11 |
| [14 Billing](../../current/defect-register/14-BILLING-AND-CREDITS-DEFECTS.md) | E04/E18/E34 |
| [15 Governance](../../current/defect-register/15-GOVERNANCE-AND-HITL-DEFECTS.md) | E01/E03/E04/E08 |
| [16 Frontend](../../current/defect-register/16-FRONTEND-DEFECTS.md) | E02/E03/E12/E33/E39/E40 |
| [17 API](../../current/defect-register/17-API-REFERENCE-DEFECTS.md) | E01/E02/E09/E12/E36/E37/E38/E39 |
| [18 Infrastructure](../../current/defect-register/18-INFRASTRUCTURE-AND-DEPLOYMENT-DEFECTS.md) | E08/E12/E34/E36/E37/E38 |
| [19 Testing](../../current/defect-register/19-TESTING-DEFECTS.md) | E12/E31/E32/E33/E36/E37/E38/E39/E40 |
| [20 Onboarding/glossary](../../current/defect-register/20-ONBOARDING-AND-GLOSSARY-DEFECTS.md) | E12/E38/E39/E40 and consistent terminology across this roadmap |

The scope of this task was documentation refinement. None of these defects was marked fixed or changed in its owning register.
