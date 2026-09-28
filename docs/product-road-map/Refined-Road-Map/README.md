# HireBuddha refined functional roadmap

Prepared 16 September 2026. **Refined functional baseline:** rebuilt from the marketing/sales design and extended across business functions, following the owner's direction in this review. Remaining product questions are recorded in [01 — Product decisions](01-product-decisions.md). Suggested sequencing is not an approved delivery commitment.

**Inventory:** 40 epics, 112 features and 229 user stories, each with acceptance criteria. Start with the operating model, then the decisions and delivery gates; use the backlog files for detailed refinement.

**Confirmed:** rebuild from GTM; Skills are the main authoring unit; create a new Generative UI frontend after its Design Gate; reserve safe-completion funds without intentional debt; keep identity/billing/minimal routing in a shared control plane with isolated tenant data/runtime; approve workflow policy once and review exceptions; use Pragya as the voice-first human workspace. **Still awaiting implementation inputs:** exact connector/provider choices, commercial packaging, authority thresholds and operational targets recorded in [01 — Product decisions](01-product-decisions.md).

## Product direction

HireBuddha helps a business owner design, deploy, and supervise an AI workforce that works from durable business records and knowledge, operates through controlled integrations, and improves from measured outcomes. Skills are the main authoring unit. Deterministic services own record integrity, schedules, state transitions, permissions, approvals and spending; agents supply judgment where it adds value. Humans remain accountable for goals, permissions, approvals, and exceptions.

The marketing/sales design is the base, not merely an early slice of the old blueprint. Its record service, hybrid ownership, activity history, explicit triggers, controlled effects and lean skill composition extend to customer care, delivery, finance, people, legal and corporate operations. The old 19-process taxonomy, Solo Pack, seven bundles and agent counts are not product requirements. Their useful business needs are remapped into the new backlog.

The first usable slice is grounded research and reviewed drafts; the first sales slice adds durable records, governed inbound handling, and meeting booking. HireBuddha's own operations are the proposed validation setting. Pragya remains the named account-manager experience; Karuna describes shared external-interaction policy. Sheel may label the business overview/supervision experience, without requiring a new execution tier or one perpetual all-business agent.

## Read this roadmap

| Document | Purpose |
|---|---|
| [00 — Rebuilt business operating model](00-business-operating-model.md) | The new whole-business model derived from GTM, including records, roles and cross-functional journeys |
| [01 — Product decisions](01-product-decisions.md) | Conflicts, recommendations, outstanding owner questions, and terminology |
| [02 — Platform backlog](02-platform-backlog.md) | E01–E12: access, execution, approvals, money, memory, records, automation, skills, integrations, Pragya, channels, operations |
| [03 — Marketing and sales backlog](03-gtm-backlog.md) | E13–E18: research, content, inbound, outbound, deal desk, revenue reporting |
| [04 — Business expansion backlog](04-business-expansion-backlog.md) | E19–E30: customer success, operations, finance, HR, legal, risk, IT, product, partnerships, capital |
| [05 — Intelligence and experience backlog](05-intelligence-experience-backlog.md) | E31–E35: routing, learning, Generative UI, packaging/federation, proprietary models |
| [08 — Tenant and ad hoc backlog](08-ad-hoc-tenant-platform-backlog.md) | E36–E40: isolated tenant data/runtime, apps/sites, Cortex cutover, ad hoc work, Pragya design and optional Graph/Loop digital twin |
| [06 — Delivery gates](06-delivery-gates.md) | Suggested increments, dependencies, evidence needed to release, and success measures |
| [07 — Source coverage](07-source-coverage.md) | Source inventory, old-to-new coverage mapping, defect mapping, and corrections to source claims |

## How to use the backlog

- **Epic:** a coherent business or platform outcome, identified as `E01`–`E35`.
- **Feature:** a capability within an epic, identified as `E01-F01`.
- **Story:** a user/administrator need with observable acceptance criteria, identified as `E01-S01`. IDs are stable; subsequent refinement should add IDs rather than renumber existing ones.
- **Gate:** the earliest suggested delivery increment, `H0`–`H6`, defined in document 06. It is neither a date nor evidence that work is implemented. Later increments may start discovery earlier.
- **Baseline:** `Existing, needs repair`, `Partial`, or `New` describes evidence from documentation and selected static code checks. It is not runtime certification.

Every story is proposed work, including stories that repair existing behavior. A story is complete only when its acceptance criteria are demonstrated through the actual user-to-runtime path. A configuration field, seed template, isolated unit test, or registered tool name alone does not satisfy it.

The backlog contains functional stories rather than implementation tasks. Schema definitions, API contracts, migrations, detailed wireframes, jurisdiction packs, estimates, and assigned engineering owners are subsequent delivery work. Dependencies identify capabilities, not a requirement to finish every later story in the named epic.

## Epic directory

| ID | Epic | Principal outcome |
|---|---|---|
| E01 | Identity, tenancy, and permissions | Only authorized people and automation can act on the right business |
| E02 | Reliable execution and truthful configuration | Work runs, recovers, and reports its actual outcome |
| E03 | Human review and deterministic governance | Reviewers see and control the exact action being authorized |
| E04 | Wallets, budgets, and cost attribution | Spending is bounded, reconciled, and understandable |
| E05 | Knowledge, memory, and retrieval | Agents use current, permitted evidence across runs |
| E06 | Business records and schema evolution | The business has durable, queryable, consistently owned records |
| E07 | Schedules, signals, and business supervision | Work responds reliably to time and business events |
| E08 | Skills and controlled capabilities | Reusable capabilities can be authored and versioned safely |
| E09 | Connections and system-of-record sync | External systems connect with explicit ownership and recovery |
| E10 | Pragya and business onboarding | Owners discover, configure, and operate their workforce conversationally |
| E11 | Karuna and communication channels | Customers encounter a coherent, governed business presence |
| E12 | Operational readiness and service continuity | Operators can release, monitor, recover, and support the product |
| E13 | Market intelligence and targeting | Teams turn evidence into ICPs, target accounts, and insights |
| E14 | Content and demand generation | Approved brand content is produced, distributed, and measured |
| E15 | Inbound qualification and booking | New inquiries reach the right owner with useful context |
| E16 | Outbound sequences and deliverability | Outreach follows deterministic timing, permission, and stop rules |
| E17 | Deal desk and sales execution | Sales work advances from preparation to approved commercial handoff |
| E18 | Revenue operations and reporting | Owners can explain pipeline, outcomes, and cost |
| E19 | Customer care, retention, and expansion | Customer issues, onboarding, health, and renewals share one history |
| E20 | Orders, delivery, and fulfillment | Promises become tracked, accepted deliverables |
| E21 | Invoicing and collections | Approved charges become reconciled receipts |
| E22 | Procurement and payables | Purchases and payouts follow verified, separated responsibilities |
| E23 | Accounting and financial close | Business transactions become balanced, reviewable accounts |
| E24 | Planning, treasury, and forecasts | Owners manage budgets, runway, and financial scenarios |
| E25 | People lifecycle | Recruiting through offboarding remains coordinated and accountable |
| E26 | Contracts and obligations | Approved terms become signed agreements and tracked commitments |
| E27 | Risk, privacy, and incidents | Risks, requests, obligations, and incidents reach accountable humans |
| E28 | Access, assets, and operational maintenance | Business systems and assets are provisioned and maintained with oversight |
| E29 | Product, experiments, and pricing | Evidence informs product changes and controlled experiments |
| E30 | Partnerships and capital stakeholders | Partner and investor work has governed records and communications |
| E31 | Model routing and multimodal work | The right eligible model delivers work within quality and cost limits |
| E32 | Evaluated learning and self-improvement | Improvements earn promotion and can be reversed |
| E33 | Generative and adaptive experience | A designed new interface adapts without weakening user control |
| E34 | Product packaging and organizational scale | Businesses adopt capabilities progressively and govern multiple units |
| E35 | BabyBuddha and OmniBuddha research | In-house models earn use through comparative evaluation |
| E36 | Isolated relational tenant data plane | Tenant business data is relational, isolated and portable |
| E37 | Tenant runtime, generated software and hosting | Tenants can safely create code, internal apps and websites |
| E38 | Cortex knowledge graph and legacy RAG retirement | Original sources become traceable tenant intelligence |
| E39 | Pragya solution design and ad hoc workbench | One human workspace handles packaged and one-off goals |
| E40 | Optional Graph/Loop operating model and digital twin | Organizational scope is editable and visually traversable when enabled |

## Boundaries and evidence

All six rough-outline files informed this consolidation. Current-state interpretation uses the current documentation index, defect indexes and selected module registers, plus targeted static checks of the code. The source map states what was checked. This is not a new audit of every defect.

No dependencies were installed, application services started, live credentials used, or subdomains assumed. The local clone is not evidence of a running production system. Existing deletions and moved files in the working tree were left intact; these documents use new filenames.

Prices, provider names, tool counts, agent counts, sample authority limits, adoption-week promises, and claimed readiness percentages in the outlines are not accepted delivery commitments. This roadmap specifies behavior and release evidence; commercial numbers and legal/regulatory applicability require separate product decisions and specialist review at implementation time.
