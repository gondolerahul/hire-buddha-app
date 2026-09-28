# Platform epics, features, and stories

All items are proposed backlog, not claims of shipped functionality. Gates are defined in [06](06-delivery-gates.md); source and defect references resolve through [07](07-source-coverage.md). Owner choices D01–D06 are tracked in [01](01-product-decisions.md).

## E01 — Identity, tenancy, and permissions

**Outcome:** business data and actions are accessible only to authorized users and automation. **Baseline:** existing, needs repair. **Sources:** RF §15, RT §11.3; AU, EP, GW, TL defects. **Dependencies:** none for core access repair; E03 for protected action approval.

### E01-F01 — Tenant and role boundaries

| Story | User need | Acceptance criteria | Gate |
|---|---|---|---|
| E01-S01 | As a tenant administrator, I can manage only the people and businesses within my authority. | Attempts to promote oneself to platform admin, access another tenant's records/credentials/artifacts, or resolve another tenant's child entities are rejected. Partner access is explicit for assigned tenants; every privileged action is attributable. | H0 |
| E01-S02 | As an owner, I can give operators, reviewers, and auditors different permissions. | Server-side role checks cover UI, API, worker, tools and channel entry points. Read-only auditors cannot mutate; reviewers cannot approve outside their assigned scope; changed permissions apply before the next protected action. | H0 |

### E01-F02 — Account and session lifecycle

| Story | User need | Acceptance criteria | Gate |
|---|---|---|---|
| E01-S03 | As a user, I can verify my account, recover access, and sign out reliably. | Verification and reset flows are backed by expiring, single-use server operations; logout revokes the relevant session; reset and reuse of rotated refresh credentials revoke compromised sessions without revealing whether an arbitrary account exists. | H0 |
| E01-S04 | As an administrator, I can disable a user or suspend a company and know the restriction is effective. | New API, streaming, worker, and tool actions are blocked across the affected scope; in-flight activity follows the configured safe-stop policy; revocation is audited and cannot be bypassed through another channel. | H0 |

### E01-F03 — Authenticated automation and channel identities

| Story | User need | Acceptance criteria | Gate |
|---|---|---|---|
| E01-S05 | As an integration owner, I can use a scoped machine identity without storing a person's refresh token in automation. | Credentials have explicit tenant/capability scope, expiry or rotation policy, revocation, and audit attribution; replayed or invalid webhook signatures cannot dispatch work; internal schedules use trusted service identity. | H2 |
| E01-S06 | As an owner speaking to Pragya, I can prove my identity before receiving private information or giving sensitive instructions. | Channel enrollment binds verified identities; caller ID or email From alone grants no sensitive authority; step-up is required by command impact; an unverified party receives no tenant data. Approval identity is distinct from the proposing agent. | H2 |

## E02 — Reliable execution and truthful configuration

**Outcome:** an authored workflow behaves as configured and reports real results. **Baseline:** partial; substantial kernel exists with correctness gaps. **Sources:** RF §§2,7; FEAS N-8; AK/EP/PC defects. **Dependencies:** E01; integrates with E03/E04/E05/E08.

### E02-F01 — Validated authoring and publishing

| Story | User need | Acceptance criteria | Gate |
|---|---|---|---|
| E02-S01 | As a workforce designer, I can save a configuration without losing settings silently. | Unsupported or misspelled fields produce actionable validation errors; supported fields survive save/reload and affect runtime; input/output contracts, references, cycles, permitted composition and tenant scope are checked. Inert controls are disabled or removed until supported. | H0 |
| E02-S02 | As a designer, I can test a draft, publish a version, and return to a known working version. | Draft/published/paused/archived transitions have enforced rules; a run records the exact configuration version; archived or disabled capabilities cannot start new work; rollback changes future selection without rewriting historic runs. | H1 |

### E02-F02 — Correct completion and recovery

| Story | User need | Acceptance criteria | Gate |
|---|---|---|---|
| E02-S03 | As an operator, I can distinguish success, partial success, failure, cancellation, and waiting. | Mandatory-step failure cannot produce successful completion; the result lists completed effects, failures, artifacts and required next action; errors are not relabeled as success; cost remains visible for failed work. | H0 |
| E02-S04 | As an operator, I can resume interrupted work without repeating completed effects. | Worker restart, child completion, delayed approval and retry restore durable state; completed steps remain completed on replan; duplicate callbacks do not double-resume or double-settle; ambiguous external outcomes are reconciled before retry. | H0 |

### E02-F03 — Bounded execution and useful traces

| Story | User need | Acceptance criteria | Gate |
|---|---|---|---|
| E02-S05 | As an owner, I can set real execution limits and understand a failed attempt. | Child concurrency, recursion, tool-call count, timeouts and budget limits are enforced; pre-action policy/critic gates actually run; selected retry remedies change behavior and stop at the configured limit. | H0 |
| E02-S06 | As an operator, I can follow a run and inspect its outputs after reconnecting. | Parent/child lineage, tool results, policy decisions, costs and registered artifacts are linked; trace reconnection recovers missed events; long outputs expose pagination/download or explicit truncation rather than silently losing content; secrets are redacted. | H1 |

## E03 — Human review and deterministic governance

**Outcome:** a human can review the exact proposed effect and the platform enforces the resulting decision. **Baseline:** existing approval triggers, unsafe/incomplete lifecycle. **Sources:** BP §9; RT §§20,23; FEAS N-3/N-9; GH/TL defects. **Dependencies:** E01, E02; E04 for financial reservations. Autonomy follows D03.

### E03-F01 — Durable, inspectable review

| Story | User need | Acceptance criteria | Gate |
|---|---|---|---|
| E03-S01 | As a reviewer, I can approve, edit, or reject the full proposed action. | Review shows recipient/account, channel, content or record diff, evidence, attachments, estimated platform cost and external commitment. Edits are versioned and revalidated; approval is bound to that exact action/version; later material changes require another approval. | H0 |
| E03-S02 | As a reviewer, I can return hours later without an action having executed in my absence. | Waiting releases worker capacity; approval survives restarts; timeout, unavailable approval service or malformed policy never grants approval. Rejection and expiry have explicit outcomes; duplicate decisions cannot execute twice; overdue items escalate to a named human. | H0 |

### E03-F02 — Enforced action policies

| Story | User need | Acceptance criteria | Gate |
|---|---|---|---|
| E03-S03 | As an owner, I can configure authority bands and mandatory checkpoints. | A deterministic pre-effect decision allows, requests approval, or prohibits an action. Rules cover external messages, contracts, payouts/refunds, hiring/offboarding, pricing, filings, data deletion, bank changes, channel bindings, cross-owner writes and code promotion; unknown action categories fail closed. | H2 |
| E03-S04 | As an auditor, I can verify independent approval of sensitive work. | Maker/checker, vendor-create/pay, access-grant/use and independent-audit rules are checked at deployment and execution. The proposing agent cannot approve itself; two-approver cases require distinct authorized people; direct tools and generic connectors cannot bypass the rules. | H2 |

### E03-F03 — Autonomy and emergency control

| Story | User need | Acceptance criteria | Gate |
|---|---|---|---|
| E03-S05 | As an owner, I can grant autonomy to a proven use case and reduce it when performance deteriorates. | Promotion presents sample size/window, edits/rejections, success, complaints and costs; a human authorizes the new scope and policy version. Hard policy breaches restrict affected actions immediately; reinstatement requires review. No elapsed-time-only promotion occurs. | H3 |
| E03-S06 | As an owner or authorized operator, I can pause or emergency-stop unsafe work immediately. | Scope distinguishes action/process/business pause from security stop; queued and active effects respect revocation before execution; remaining funded guardrail work is explicit; emergency stop is accessible without an AI conversation; restart is authorized and audited. | H0 |

## E04 — Wallets, budgets, and cost attribution

**Outcome:** users receive purchased entitlement and cannot unknowingly overcommit platform or external spend. **Baseline:** existing, needs repair. **Sources:** RF §14; RT §§20,23; SK §10; FEAS N-9; BC/TL/GH defects. **Dependencies:** E01/E02; E03 for commitment approval. Owner decision D06 requires reserved safe completion without intentional debt.

### E04-F01 — Correct credits and billing

| Story | User need | Acceptance criteria | Gate |
|---|---|---|---|
| E04-S01 | As a paying tenant, I receive exactly the entitlement I purchased once. | Top-up verification uses the stored/provider-confirmed amount and currency; callback replay cannot grant credit twice; subscription activation and renewal grant the intended credits; changing plan does not strand spendable balance; cycle jobs are scheduled and idempotent. | H0 |
| E04-S02 | As a tenant or partner, I can reconcile a bill to actual work and the applicable rate. | One authoritative ledger attributes model, critic, tool, media, voice, sandbox and child-run usage; retries are visible; no duplicate charge for the same consumption; rates, units, fees, discounts and currencies are explicit; partner pricing edits are scoped. | H0 |

### E04-F02 — Reservations and controlled exhaustion

| Story | User need | Acceptance criteria | Gate |
|---|---|---|---|
| E04-S03 | As an owner, I can run concurrent work without allocating the same funds twice. | Admission atomically reserves funds across the applicable wallet/envelopes; nested work does not reserve or bill the same use twice; unavailable funds block new spend; completion, cancellation and stale-run recovery release residual holds exactly once. | H0 |
| E04-S04 | As an owner, I can see what happens when a run reaches its spending limit. | Admission includes reserved funds for bounded safe closure; the system tops up before extending work and closes/pauses before available reservation is exhausted. Live calls receive a bounded closing message or handoff. No intentional negative balance is allowed; provider reconciliation discrepancies are recorded as exceptions, not authorization for more spend. | H2 |

### E04-F03 — Business envelopes and external commitments

| Story | User need | Acceptance criteria | Gate |
|---|---|---|---|
| E04-S05 | As an owner, I can allocate a monthly budget across processes and keep a funded incident reserve. | Business/process/agent/run limits compose; warnings precede exhaustion; reserve cannot be spent by unrelated work; exhausted work parks visibly; reserve exhaustion does not imply free execution. Calendar/cycle boundaries and allocation changes are audited. | H2 |
| E04-S06 | As a campaign or finance owner, I can limit money committed outside HireBuddha separately from AI usage. | Ad budgets, payouts, refunds and other commitments have account-, currency-, amount- and time-scoped controls; cumulative/repeated operations cannot evade caps; approvals show both costs; unknown provider outcomes reserve exposure until reconciled. | H2 |

## E05 — Cortex knowledge, memory, and retrieval

**Outcome:** agents ground work in current, permitted evidence and useful prior experience. **Baseline:** storage and partial retrieval exist; live paths are disconnected. **Sources:** RF §9; RT §24; FEAS N-1/N-2; MC/AK/EP defects. **Dependencies:** E01/E02; E09 for connected knowledge sources.

### E05-F01 — Usable Cortex source and search

| Story | User need | Acceptance criteria | Gate |
|---|---|---|---|
| E05-S01 | As a knowledge owner, I can add approved sources and know when they are usable in Cortex. | Source acquisition reports success/failure, source/version, access scope and extraction quality; scanned material can be routed for OCR; unsupported files have an actionable result; replacing/removing a source updates Cortex eligibility while preserving the original and its provenance. | H1 |
| E05-S02 | As an operator, I receive agent answers grounded in the knowledge I supplied. | Agent-callable retrieval and prompt assembly use permitted source passages; answers cite provenance; missing or conflicting evidence is disclosed; retrieval failure is distinguishable from no results; builder retrieval settings have observable effect in a real run. | H1 |

### E05-F02 — Scoped continuity and institutional memory

| Story | User need | Acceptance criteria | Gate |
|---|---|---|---|
| E05-S03 | As a customer or operator, I can continue a conversation across agents and channels without repeating verified context. | Tenant-scoped counterparty identity links relevant history; uncertain identity is not silently merged; sensitive domains and user permissions filter retrieval; support cannot retrieve payroll just because the tenant is the same. | H2 |
| E05-S04 | As a workforce owner, I can see which prior lessons affected a new run and retire a bad lesson. | Knowledge/episodic context is distinct from entity experience/intelligence; verified lessons can be inherited within approved scope; active rules reach actual prompts; retired rules are excluded; a shared Skill's lessons remain attributable to that Skill version. | H1 |

### E05-F03 — Retrieval quality and data lifecycle

| Story | User need | Acceptance criteria | Gate |
|---|---|---|---|
| E05-S05 | As a knowledge owner, I can improve search quality against representative questions. | Structure-aware extraction/chunking, lexical and semantic retrieval, metadata filters and optional reranking are compared against a maintained question set; cost/latency and wrong-source retrieval are measured; rollout can revert to the incumbent. | H3 |
| E05-S06 | As a privacy administrator, I can enforce retention and removal across derived knowledge. | Retention/deletion covers documents, chunks, embeddings, counterparty history, learned content and derived artifacts where applicable; legal holds are explicit; export includes permitted knowledge and memory; deleted content is not returned from stale indexes or caches. | H2 |

## E06 — Business records and schema evolution

**Outcome:** HireBuddha can answer and update business-state questions across runs. **Baseline:** new; existing dialer queues and voice campaigns are not a CRM. **Sources:** BP §3.2; RT §§10,19,21,23; GTM §§4–5; FEAS §3. **Dependencies:** E01/E02; E12 persistence/restore; E09 for externally mastered records. Placement/mastering follows D02; schema choices D08–D13.

### E06-F01 — Canonical GTM records and identity

| Story | User need | Acceptance criteria | Gate |
|---|---|---|---|
| E06-S01 | As a GTM operator, I can manage records and relationships consistently through UI, import, and agents. | Initial catalog covers Account, Contact, Opportunity, Activity, Business Signal, Segment, GTM Campaign, Sequence, Enrollment, Content Asset, Message, Consent, ICP Definition and Messaging Library. Agents can discover schemas, query with pagination, validate/upsert and link through one record service; no direct database bypass. | H2 |
| E06-S02 | As a data steward, I can import and reconcile duplicate identities without losing history. | Imports offer mapping, preview, invalid-row reporting and repeat-import dedupe; uncertain matches enter review; merging retains external IDs, consent provenance and activities and can be corrected. Contact lifecycle represents a lead; anonymous capture does not invent identity. | H2 |

### E06-F02 — Ownership, consistency, and change control

| Story | User need | Acceptance criteria | Gate |
|---|---|---|---|
| E06-S03 | As a process owner, I can protect my records from conflicting edits. | Each object has a business owner and separately declared system of record; cross-owner changes are proposals unless explicitly authorized; stale-version writes cannot silently overwrite; links validate tenant/type/existence; conflicts retain both intended change and current truth. | H2 |
| E06-S04 | As an administrator, I can extend the schema while existing workflows remain intelligible. | Custom fields/types/relations are validated and versioned; schema changes show dependent forms, queries, skills and reports; renames support aliases, incompatible changes use migration/backfill, and deprecation preserves history. Agents propose schema growth; permissions govern activation. | H4 |

### E06-F03 — Durable standalone business modules

| Story | User need | Acceptance criteria | Gate |
|---|---|---|---|
| E06-S05 | As an owner without a CRM, I can operate the supported GTM workflows entirely inside HireBuddha. | Records persist independently of execution sandbox sleep/reaping; UI supports search, filters, detail, relationships and activity history; backups begin with the first operational write; export/restore verifies records and links; unavailable external CRM is not a requirement for local-master work. | H2 |
| E06-S06 | As a business owner, I can later activate full standalone modules without creating disconnected data silos. | CRM, accounting, HR, operations, legal, marketing and planning modules reuse canonical parties/products/records; each module's end-to-end acceptance is proven before being advertised as standalone; externally mastered equivalents obey declared sync rules. | H4 |

## E07 — Schedules, signals, and business supervision

**Outcome:** finite business workflows run reliably on events and schedules without a human pressing Execute. **Baseline:** new tenant automation on an existing worker framework. **Sources:** GTM §§3,8; FEAS N-4/N-5; useful requirements from RT §§17–18. **Dependencies:** E01/E02; E06 for business-record events; E04 for admissions. The signal bus uses durable pub/sub, schedules and idempotent consumers; no mandatory LOOP entity is required.

### E07-F01 — Tenant schedules and delayed work

| Story | User need | Acceptance criteria | Gate |
|---|---|---|---|
| E07-S01 | As an operator, I can schedule recurring work in my business timezone. | Create/edit/pause schedules with next-run preview; daylight-saving, missed-run, overlap and catch-up rules are explicit; one schedule occurrence causes at most one admitted workflow; tenant timezone replaces hardcoded IST. | H1 |
| E07-S02 | As an operator, I can delay a follow-up or start a voice campaign at its scheduled time. | Waiting releases workers and survives restart; a due campaign actually starts once subject to current permissions, consent and budget; cancelled or superseded work cannot wake; timing history explains late or blocked starts. | H2 |

### E07-F02 — Event routing and recovery

| Story | User need | Acceptance criteria | Gate |
|---|---|---|---|
| E07-S03 | As a process owner, I can declare which events start my workflow. | Verified events have tenant, source/trust, subject references, event ID, time and type; routing picks a deterministic allowed entry workflow; missing/ambiguous routes park visibly instead of choosing an arbitrary entity; critical events receive configured priority. | H2 |
| E07-S04 | As an operator, I can account for every accepted event after a failure. | Business writes have a durable local outbox when databases differ; relay and dispatch are idempotent under at-least-once delivery; pending, parked, retrying, dead-letter and terminal outcomes are visible; replay links the original and preserves effect dedupe. Completion events cannot create unbounded event loops. | H2 |

### E07-F03 — Standing business oversight

| Story | User need | Acceptance criteria | Gate |
|---|---|---|---|
| E07-S05 | As an owner, I can see and control the recurring work keeping my business operating. | Overview lists active workflows, schedules, stale signals, budgets, results and accountable people; business-level pause delegates to the same execution controls; supervision uses deterministic health checks, with reasoning dispatched only as finite, billed runs. | H3 |
| E07-S06 | As an operator, I am alerted when a recurring function stops making progress. | Missed schedules, unhealthy connectors, expired approvals, sleeping/unavailable data stores and abandoned work generate actionable status; recovery does not duplicate work; the operator can inspect a replay/repair plan before enabling new effects. | H2 |

## E08 — Skills and controlled capabilities

**Outcome:** reusable business capabilities are authored as Skills while controlled tools enforce effects. **Baseline:** existing Skill tier and partial dynamic-tool code; new skill version/asset model. **Sources:** SK entire; GTM §6; FEAS N-6/N-7; TL/EP/MI defects. **Dependencies:** E01–E05, E12 sandbox controls. Owner decision D04 is confirmed.

### E08-F01 — Versioned Skill authoring

| Story | User need | Acceptance criteria | Gate |
|---|---|---|---|
| E08-S01 | As a skill author, I can create a reusable capability with instructions, contracts, scripts and assets. | DB-backed Skill drafts have purpose, discoverable description, permitted primitives, input/output schemas, governance, runtime reference and assets; published versions are immutable; diff/test/publish/rollback work; executions pin and record the chosen version. | H1 |
| E08-S02 | As a workforce designer, I can reuse a Skill without multiplying unnecessary agent loops. | Eligible skills are initially disclosed by brief metadata, with full content loaded on selection; selection respects access and task fit; direct invocation and optional Action wrappers work; the same version supports multiple consumers without duplicating ownership or memory indiscriminately. | H1 |

### E08-F02 — Safe execution and durable capability discovery

| Story | User need | Acceptance criteria | Gate |
|---|---|---|---|
| E08-S03 | As a tenant administrator, I can run authored scripts without exposing credentials or host access. | Approved runtime images supply dependencies; assets are hash-verified and isolated by tenant/version/run as needed; no runtime package installation or host fallback is permitted for authored code; resource/network/file limits are enforced; external credentials remain behind tools. | H0 |
| E08-S04 | As an operator, I can enable a capability once and use it across workers and restarts. | Registry metadata resolves to executable implementations; workers rehydrate versioned tenant capabilities; schema discovery and execution both enforce tenant, enabled/status and permission checks; disabling a capability takes effect everywhere; unknown definitions cannot execute. | H1 |

### E08-F03 — Measured migration from tool-heavy workflows

| Story | User need | Acceptance criteria | Gate |
|---|---|---|---|
| E08-S05 | As an operator, I can generate documents reproducibly through the reference Skill family. | Deterministic DOCX/PPTX/PDF/spreadsheet boilerplate becomes stored scripts/assets; prompts retain judgment; outputs are registered artifacts; tests compare output quality, tokens, latency and cost against the current path; skill-version and sandbox usage are attributable. | H1 |
| E08-S06 | As a capability owner, I can consolidate social/integration wrappers without losing controls. | Pilot selected operations through controlled authenticated primitives plus platform Skills; operation-level permissions, consent, idempotency and budgets remain mandatory; compare task quality/cost before migration; rollback is possible and old paths are retired only after verified cutover. | H3 |

## E09 — Connections and system-of-record sync

**Outcome:** integration setup produces usable, recoverable capabilities with clear data ownership. **Baseline:** some adapters exist; MCP transport and complete sync are new. **Sources:** GTM §§4,7; FEAS N-6; RT §21; TL defects. **Dependencies:** E01/E03/E08; E06/E07 for record sync. Strategy follows D02.

### E09-F01 — Connection lifecycle and MCP

| Story | User need | Acceptance criteria | Gate |
|---|---|---|---|
| E09-S01 | As an administrator, I can connect, test, rotate and revoke an external service. | Setup displays supported operations/scopes, account identity, test result, health and limits; encrypted credentials never enter model prompts; expired tokens produce actionable reconnect status; revocation disables dependent effects and identifies impacted workflows. | H1 |
| E09-S02 | As an administrator, I can attach an approved MCP server and use its permitted capabilities. | A supported transport is implemented end to end; persisted configuration rebinds on every worker; tool discovery does not grant execution by itself; server metadata is untrusted; explicit operation policy and limits apply; timeout/outage/revocation results are observable. | H1 |

### E09-F02 — Record mastering and reconciliation

| Story | User need | Acceptance criteria | Gate |
|---|---|---|---|
| E09-S03 | As a CRM owner, I can declare where each object is authoritative and rely on a truthful local mirror. | HubSpot is the proposed first reference connector; external IDs, mappings and freshness are visible; external-master writes await confirmed write-back; conflicts preserve the losing delta and raise review; retries and webhook replays do not duplicate or oscillate records. | H2 |
| E09-S04 | As an owner, I can move an object between local and external ownership deliberately. | Migration previews affected records/links/consent and conflicts, snapshots a recovery point, backfills mappings, reconciles counts and obtains required approval; partial failure can resume or roll back; no silent switch of master on connector outage. | H4 |

### E09-F03 — Integration coverage by demonstrated use case

| Story | User need | Acceptance criteria | Gate |
|---|---|---|---|
| E09-S05 | As a business user, I can synchronize the knowledge and collaboration sources my workflow requires. | Prioritize Drive/SharePoint/Notion and Slack/Teams by chosen pilot; sync respects source access, changed/deleted documents and cursors; review cards call the same authenticated approval service; each advertised integration passes a representative end-to-end use case. | H2 |
| E09-S06 | As an administrator, I can see which business integrations are supported rather than infer readiness from tool names. | Catalog distinguishes available, preview, unavailable and planned capabilities; roadmap includes calendar, email, CRM, analytics, enrichment, e-signature, payments, bank feeds, tax, HRIS, inventory and helpdesk families. Each enablement requires connection, metering, policy and recovery evidence. | H4 |

## E10 — Pragya and business onboarding

**Outcome:** an owner can turn business goals into a reviewable operating setup and supervise it. **Baseline:** new experience; partial entity-builder/Board substrate. **Sources:** RF §§4–5; GTM §11; RT §11; MI defects. **Dependencies:** E01/E03/E05/E08; E06/E09 for connected operations.

### E10-F01 — Evidence-based discovery

| Story | User need | Acceptance criteria | Gate |
|---|---|---|---|
| E10-S01 | As a new owner, I can establish business context without answering questions the product can already resolve. | Pragya researches supplied/public sources, presents assumptions, ingests approved internal sources, revises conclusions with provenance and asks only unresolved questions; no speculative business fact is silently saved as verified. Discovery can pause/resume. | H1 |
| E10-S02 | As an owner, I can agree the intended workflows, outcomes and boundaries before deployment. | Collaborative planning captures pains, owners, priorities, KPIs, budget, data/mastering, permitted channels and review rules; proposal lists required Skills/integrations and missing capabilities; changes remain reviewable; there is no mandatory Solo Pack or fixed agent roster. | H2 |

### E10-F02 — Build, test and deploy

| Story | User need | Acceptance criteria | Gate |
|---|---|---|---|
| E10-S03 | As a designer, I can ask for a capability and receive an editable, tested candidate. | Builder searches for reuse before creation; can revise failed candidates; tests include independent known cases, failures and permission boundaries; skipped or budget-exhausted tests do not count as passes; generated work remains a draft until authorized promotion. | H2 |
| E10-S04 | As an owner, I can activate a business workflow after seeing a realistic preview. | Preview shows representative inputs, outputs, approval points, records touched, dependencies and estimated costs without live effects; missing credentials/policies block activation; deployment uses pinned versions and the selected autonomy policy. | H2 |

### E10-F03 — Daily operating relationship

| Story | User need | Acceptance criteria | Gate |
|---|---|---|---|
| E10-S05 | As an owner, I can ask what happened, what needs me, and what it cost. | Pragya answers from actual records/runs and links supporting evidence; separates observed results from estimates; presents pending reviews, failures and business outcomes; routes changes through the same permission/approval controls as the UI. | H2 |
| E10-S06 | As an owner, I can continue working with Pragya by text, voice or a verified collaboration channel. | Stage channels by proven adapter readiness; authorized identity and scoped context survive a handoff; private reports are not exposed to an external counterparty; unverified/sensitive requests trigger the relevant verification; failed channels offer a valid fallback. | H3 |

## E11 — Karuna and communication channels

**Outcome:** customer-facing interactions share policy, identity, history and escalation behavior. **Baseline:** voice/email/messaging paths exist with major gaps. **Sources:** GTM §§3,8,11; FEAS §§2–4; BP §2.3 as a requirements source; VT/GW/TL defects. **Dependencies:** E01–E05, E07–E09; E06 consent/activity records. D03 determines initial external autonomy.

### E11-F01 — Shared external-action policy

| Story | User need | Acceptance criteria | Gate |
|---|---|---|---|
| E11-S01 | As an owner, I can enforce contact permission and conduct before any external action. | Email, call, messaging, social, browser and connector paths check applicable consent/purpose, suppression, recipient/account ownership, time windows, disclosure policy and human-review requirements at execution time; policy failure blocks action; prompts cannot override it. | H2 |
| E11-S02 | As a customer, I can choose contact preferences, stop contact, and reach a human. | Opt-out updates shared suppression promptly and stops queued/future prohibited touches; verified preferences apply across linked channels; request for a human creates an owned handoff; unavailable humans produce an honest callback/response expectation rather than a false transfer. | H2 |

### E11-F02 — Voice and messaging that report real results

| Story | User need | Acceptance criteria | Gate |
|---|---|---|---|
| E11-S03 | As an operator, I can run inbound and outbound voice interactions under an approved session policy. | Carrier routing, recording/disclosure choices, interruption, tool calls, costs, disposition and activity linkage work end to end; consent and funds are checked before dialing; every tool effect uses platform controls; safe closure is funded in advance; low credit or outage cannot create intentional debt. | H2 |
| E11-S04 | As an operator, I can handle email, messaging and web conversations in a coherent inbox. | Threading, participant identity, attachments, delivery state and assignment are visible; reconnect/retry cannot duplicate sends; uncertain delivery is not reported as success; structured handoff carries permitted history without leaking private operator conversations. | H2 |

### E11-F03 — Channel quality and resilience

| Story | User need | Acceptance criteria | Gate |
|---|---|---|---|
| E11-S05 | As a customer, I receive context-appropriate communication in a supported language. | Brand tone and accessibility rules apply; language detection/translation indicate uncertainty and preserve material meaning; unsupported language routes to help; persona settings affect delivery but do not promise deterministic empathy from a numeric slider. | H3 |
| E11-S06 | As an operator, I can recover from a channel outage without surprising a recipient. | Fallback respects that channel's consent and the customer's preferences; queued work preserves ordering/stop rules; any callback promise has an owned task; real-time stream access is authenticated and resumable where possible; failed sessions retain trustworthy cost and outcome records. | H3 |

### E11-F04 — Exotel telephony integration

| Story | User need | Acceptance criteria | Gate |
|---|---|---|---|
| E11-S07 | As an owner, I can connect Exotel for approved calling use cases. | Exotel credentials, account/number ownership, webhook signing, regional settings and recording/disclosure policy are tenant-scoped; connection health and capability limits are visible; unsupported Smartflo-like use cases fail clearly. | H2 |
| E11-S08 | As an operator, I can place and receive Exotel calls through governed workflows. | Outbound and inbound call setup, answer/busy/no-answer/failed states, transfers, hangup and human handoff map to durable call/activity records; consent, suppression, schedule and funds are checked immediately before dialing. | H2 |
| E11-S09 | As an operator, I can trust Exotel callbacks and recordings. | Signed callbacks are idempotently reconciled; delayed/duplicate/out-of-order events do not regress state; recording references, consent, retention and access are stored in the tenant data plane; unknown outcomes are surfaced for review. | H3 |
| E11-S10 | As a service owner, I can operate Exotel safely during failures. | Timeouts, rate limits, provider outages and webhook gaps trigger bounded retry/reconciliation; no blind redial or duplicate business effect occurs; metered cost and closure reserve settle truthfully; fallback and emergency stop behavior are tested. | H3 |

## E12 — Operational readiness and service continuity

**Outcome:** the product can be demonstrated, released and recovered with evidence. **Baseline:** existing application with substantial release/ops defects. **Sources:** DR; FE/TS/IN/SA/DM/API registers; GTM §4.2. **Dependencies:** cross-cutting; implement alongside the capabilities it protects.

### E12-F01 — Reproducible development and actual release checks

| Story | User need | Acceptance criteria | Gate |
|---|---|---|---|
| E12-S01 | As a developer, I can start a fresh clone locally without production domains or credentials. | Document supported environment, dependencies, migrations and fixtures; local URLs are explicit; absent configuration never defaults to production; mock/offline and live-provider tests are distinguished; public callback setup is separate from basic local operation. | H0 |
| E12-S02 | As a release owner, I can know that required checks actually ran. | CI triggers on active backend/frontend paths; required unit, integration, UI and regression gates report executed counts; missing infrastructure fails required lanes; security/tenant, approval, money and replay scenarios exercise real dispatch paths; documentation marks unverified services accurately. | H0 |

### E12-F02 — Visible failures and recoverable state

| Story | User need | Acceptance criteria | Gate |
|---|---|---|---|
| E12-S03 | As an operator, I can diagnose incidents without a blank screen or misleading success message. | UI provides error/loading/empty/permission states, reconnect guidance and actionable request IDs; metrics expose failed policy gates, queue age, approvals, cost mismatch, connector health and run outcomes; log access is scoped and secrets are redacted. | H0 |
| E12-S04 | As a tenant owner, I can recover or export the complete supported business state. | Automated encrypted backups begin before operational writes; restore drills include record versions/links, knowledge, memory, configurations, relevant history/ledger and artifact manifests. Exports are usable and tenant-scoped, exclude raw credentials, and state missing external data; recovery/data-loss targets are agreed and measured. | H2 |

### E12-F03 — Controlled operations and honest readiness

| Story | User need | Acceptance criteria | Gate |
|---|---|---|---|
| E12-S05 | As a service owner, I can operate many tenant data stores without coupling them to code execution. | Database sleep/start, connection pools, durable volumes, upgrades, capacity and backups have explicit lifecycle controls; a waking/unavailable tenant parks work; monitoring reports per-tenant readiness; storage topology never relies on local scratch directories. | H4 |
| E12-S06 | As a product owner, I can decide if a release is supportable. | Each enabled capability has a supported-version record, owner, rollback/runbook and acceptance evidence; blockers and unresolved defects are explicit; unsupported tools are inaccessible; superseded runtime paths are removed after verified migration and defined rollback retention. | H1 |

### E12-F04 — Defect applicability and closure register

| Story | User need | Acceptance criteria | Gate |
|---|---|---|---|
| E12-S07 | As a product owner, I can tell which current-register defects still apply to the enabled roadmap slice. | Before work starts in an area, its numbered current register is rechecked against the current code and runtime path; each item is classified `applicable-repair`, `replaced-path`, `not-reproducible`, `deferred`, or `accepted-risk`, with evidence, owner and date; duplicate IDs remain cross-referenced rather than counted twice. | H0 |
| E12-S08 | As an engineering lead, I can turn applicable defects into release-blocking acceptance criteria. | Relevant T0/T1 defects become stories/tests in the owning epic; a fix is verified through API, worker, tool, UI and external-provider paths as applicable; feature flags and seeds are not evidence; required infrastructure is present and tests cannot pass by silently skipping. | H0 |
| E12-S09 | As a release owner, I can close or defer a defect without losing history. | Closure links the change, regression evidence and current behavior; migrations remove superseded live paths after cutover; deferrals name rationale, mitigation and review date; unresolved defects are visible in release readiness and do not get relabeled as feature complete. | H1 |
