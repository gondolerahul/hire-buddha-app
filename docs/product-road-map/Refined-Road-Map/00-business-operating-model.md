# Rebuilt whole-business functional model

## The starting point

The owner's direction is to **use the more mature marketing/sales design as the base and rebuild the whole-business vision from scratch**. This model therefore starts with the work a business must complete, the records that make that work coherent, and the controls required to act. It does not start by allocating 100 agent identities to 19 prescribed Processes.

The product serves owners, functional operators, reviewers and service administrators. It supports businesses with existing software and businesses that need native record management. Native depth is declared per module: supporting customer tickets does not imply a complete accounting or payroll product.

## The reusable unit of business automation

Every supported workflow has the following contract:

| Element | Required functional meaning |
|---|---|
| Purpose | A business outcome with an accountable human owner and measurable completion |
| Entry | A manual request, verified external event, record change or scheduled occurrence |
| Inputs | Validated business records, scoped knowledge, known assumptions and required evidence |
| State | Durable, inspectable lifecycle; explicit waiting, partial completion, failure and cancellation |
| Judgment | Versioned Skills for research, interpretation, drafting or recommendations; Agents only when iterative judgment is needed |
| Deterministic controls | Eligibility, time, identity, consent, arithmetic, limits, permissions, state transitions and approvals |
| Effects | Named record changes or external operations through controlled services/tools |
| Review | Exact artifact/diff/action, authorized reviewer, decision, version and expiry |
| Completion | Confirmed outcome, linked records/artifacts, reconciled cost and accepted downstream work |
| Recovery | Idempotent retry, reconciliation of uncertain effects, owned exceptions, safe cancellation and version rollback where possible |

A workflow's breadth is determined by its outcome. A Skill may be reused across many domains: document assembly, evidence retrieval, summarization, identity resolution assistance, comparison, scheduling assistance, classification, and report narration should not be copied into one Agent per department. Credentials, money movement and authoritative state changes remain controlled primitives.

## Where intelligence belongs

| Work | Deterministic service | Skill / agent contribution | Human accountability |
|---|---|---|---|
| Outreach | Consent, enrollment timing, caps, stop conditions, dispatch | Research, personalization, reply interpretation | Contact policy, content approval and exceptions |
| Support | Ticket state, entitlement, SLA and assignment | Grounded answers, diagnosis and suggested remediation | Service standards and escalated decisions |
| Delivery | Dependencies, capacity reservations, acceptance state | Plan proposals, risk analysis, work product | Commitments, acceptance and scope changes |
| Finance | Amounts, balancing, matching, approvals, settlement | Classification suggestions, discrepancy explanation, forecasts | Approved treatment, payments and filings |
| People | Access, workflow state, scheduling, approved payroll rules | Drafting, evidence summaries and policy retrieval | Hiring, employment and other consequential decisions |
| Governance | Permission, mandatory checkpoint, legal hold, stop controls | Evidence analysis, control recommendations, incident summaries | Policy applicability, exceptions and public decisions |

An LLM never decides whether it is time to send the next sequence step, whether a journal balances, whether money is available, or whether an approval can be bypassed. An LLM can help interpret an ambiguous reply or explain a discrepancy; the workflow then applies explicit rules or sends the ambiguity to a person.

## Shared records, separated responsibilities

The GTM core provides Account, Contact, Opportunity, Activity, Business Signal, Segment, GTM Campaign, Sequence, Enrollment, Content Asset, Message, Consent, ICP Definition and Messaging Library. Expansion adds domain-specific records rather than another generic agent memory store.

| Business area | Additional record families | Native responsibility / integration boundary | Backlog |
|---|---|---|---|
| Sales execution | Product/Service, Quote/Line, Meeting, Qualification | Own approved sales work locally or mirror CRM state with confirmed write-back | E15/E17 |
| Customer operations | Ticket, Entitlement, Onboarding, Health, Renewal | Own service lifecycle and customer evidence; connect helpdesk/usage systems if present | E19 |
| Delivery | Order, Project, Task, Milestone, Deliverable, Acceptance, Shipment, Return | Own commitments and progress; use fulfillment/warehouse/provisioning systems for verified effects | E20 |
| Receivables | Invoice, Credit Note, Receipt, Collection Case | Own supported invoicing/collection state or honor accounting master | E21 |
| Purchasing/payables | Vendor, Requisition, PO, Receipt, Bill, Payment Instruction | Match and authorize commitments; payment providers execute settlement | E22 |
| Accounting | Chart of Accounts, Journal, Period, Reconciliation, Expense, Tax Code | Offer deterministic local books for supported scope or connect authoritative accounting | E23 |
| Financial planning | Budget, Target, Scenario, Cash Forecast, Variance | Model from reconciled inputs; planning never directly authorizes a payout | E24 |
| People | Position, Candidate/Application, Employee, Leave, Payroll Input, Review, Exit | Coordinate employee records and reviewed operations; full statutory payroll is a separate supported module/provider | E25 |
| Legal | Contract/Version, Clause, Signature Envelope, Obligation, Dispute | Manage evidence and approvals; signing and legal decisions have explicit authorized parties | E26 |
| Risk/privacy/incidents | Risk, Control, Policy, Evidence, Privacy Request, Legal Hold, Incident | Own cases and evidence; qualified humans determine applicability and consequential decisions | E27 |
| Business administration | Access Grant, Asset/Assignment, Maintenance, Service Ticket, Data Job | Track actual grants/assets and lifecycle; downstream providers confirm changes | E28 |
| Product/pricing | Idea, Requirement, Backlog Item, Experiment, Offer/Price, Launch | Govern evidence-to-decision-to-release; implementation systems may remain external | E29 |
| Partners/stakeholders | Partner Profile, Referral, Commission, Board Action, Diligence Request | Reuse counterparties and contracts; compartmentalize sensitive corporate information | E30 |

Two kinds of ownership must remain distinct: **system of record** decides whose data is authoritative; **business owner** decides who is authorized and accountable to change it. A mirror may be read locally while writes need external confirmation. Cross-domain work proposes changes to another owner's records or obtains explicit delegated authority. Every accepted change has provenance and a concurrency version.

Core vocabulary, validation and relationship integrity are shared. A supplier can also be a customer, but financial identity details, contact permission and vendor verification do not become interchangeable merely because records link to the same organization. Employee/candidate identities require separate access controls; customer-facing agents cannot retrieve their private records.

Business records, semantic knowledge and operational signals have different jobs. A record stores the state of a deal/invoice/ticket; knowledge supplies supporting evidence and learned context; a signal requests work. An Activity records a real interaction or confirmed action. None substitutes for the others.

## Cross-functional journeys that prove the model

| Journey | Functional handoff | Required proof |
|---|---|---|
| Inquiry to paid delivery | Capture → qualify → quote → contract → order/project → acceptance → invoice → receipt → accounting | Same customer and accepted terms remain linked; downstream owner acknowledges; duplicate events cannot create duplicate orders, invoices or receipts |
| Customer issue to commercial resolution | Ticket → permitted diagnosis → delivery/contract evidence → reviewed credit/refund → corrected account state | Customer sees one coherent case; support cannot pay a refund on its own; financial correction and final response are auditable |
| Need to supplier settlement | Requisition → vendor approval → PO → receipt → matched bill → approved payout → reconciliation | Vendor creator and payer are separated; each effect confirms actual state; uncertain settlement cannot be retried blindly |
| Hire to productive access to exit | Requisition → assessed application → approved offer → signed terms → employee onboarding → access/assets → reviewed exit | Human employment decisions and effective dates are preserved; access is verified and later revoked; missed revocation escalates |
| Risk signal to learning | Verified signal → risk/incident → containment → reviewed communication → recovery → evidence → improvement proposal | Unsafe effects can stop without waiting for AI; improvement does not auto-promote itself; the original evidence remains accessible |
| Evidence to new offer | Market/customer signals → product hypothesis → experiment → approved product/price → enablement/launch | Assumptions and findings are separate; contractual prices remain protected; new quotes and content use the approved version |

These are acceptance journeys, not mandatory monolithic runtime graphs. Each may cross several small workflows that share record IDs, ownership and recoverable events.

## Human roles and operating experience

| Role | Product responsibilities |
|---|---|
| Owner / goal setter | Set outcomes and budget, accept scope, choose autonomy and review exceptions |
| Functional operator | Manage records/queues, inspect evidence, handle failures and accept cross-functional work |
| Authorized reviewer | Approve/edit/reject exact effects within assigned authority; independently review where required |
| Domain specialist | Resolve legal, accounting, employment, security or sector-specific decisions |
| Auditor / quality owner | Inspect evidence, sample results, evaluate improvements and require corrective action |
| Tenant administrator | Users, delegated roles, integrations, retention, policies and workspace lifecycle |
| Platform / partner operator | Support assigned tenants within explicit access and commercial boundaries |

The everyday experience combines a business activity feed, record workspaces, owned queues, approvals, outcomes/cost reports, and Pragya's conversational assistance. The current frontend must expose the early capabilities honestly. The future Generative UI is a new frontend, preceded by the owner-confirmed design gate; generated presentation does not generate permissions.

The platform has a shared control plane for identity, subscriptions, billing and minimal job-routing metadata. Each tenant receives an isolated containerized data plane containing its typed relational business database, source files, artifacts, Cortex/knowledge graph, generated code, internal apps and websites. Tenant APIs are the only supported path for Skills, agents and applications to access that state; storage, compute, network and export limits are enforced per tenant.

Pragya is the single human operating workspace. A voice-first conversation can be continued with text and direct visual edits, including an immediate stop control. Before a new packaged workflow, app, website or ad hoc analysis is deployed, Pragya and the solution-architect Meta Agent produce one editable, versioned blueprint with assumptions, evidence, permissions, budget, risks and acceptance tests. The same workspace can request a finite financial model, market study, presentation or other one-off outcome without activating a permanent business pack.

Business supervision is an overview of active workflows, deadlines, budgets, exceptions and outcomes. If the name Sheel is retained, it describes that experience. It does not obligate a perpetual reasoning loop. If Karuna is retained, it describes shared external-interaction conduct and controls, rather than requiring five extra gateway Agent reasoning cycles on every request.

## What the rebuild deliberately retires

- Mandatory counts of Loops, Processes, Agents, Skills or Actions; a separate agent for every job title; fixed-depth execution chains for simple work.
- An all-business Solo Pack as a day-one promise, or exactly seven bundles as the commercial model.
- Automatic schema/code/autonomy changes justified only by a model's own tests or elapsed weeks.
- Promises of complete standalone ERP/HR/accounting depth from a few JSON definitions or connector names.
- “Always on” meaning unbounded LLM spending; “never pause” overriding security stop or exhausted funds.
- Physical database separation as proof that authorization, privacy and safe exports are solved.
- The legacy document-ingestion/RAG store and dual-write path; originals are retained in tenant folders and the production intelligence path is Cortex with traceable, editable knowledge and procedures.

The retained ambition is broad business operation. The delivery mechanism is a modular, skill-first product with explicit native scope, controlled integrations and evidence of completed work.
