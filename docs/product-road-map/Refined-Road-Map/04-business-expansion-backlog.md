# Extending the GTM foundation across a business

These domains are rebuilt from business responsibilities rather than inherited agent names. Each uses E06's record service, E07's scheduling/events, E08's reusable Skills and E09's ownership/sync model. No domain gets a separate identity, consent, approval, wallet, or workflow engine.

The product must support local-master operation for the records it advertises and connected-system operation where that system is authoritative. A customer adopting support does not need to adopt payroll, and a company with an accounting system need not replace it to use collections. Sector-specific manufacturing, payroll calculation, tax filing and regulated workflows need dedicated scope and evaluation before being promised.

All stories below are **H4 module expansion**, unless stated otherwise. H4 is a portfolio of independently releasable modules, not a single giant release. Product ordering within it needs customer evidence and capacity, not the old blueprint's process order.

## E19 — Customer care, retention, and expansion

**Outcome:** customers receive continuous help from onboarding through renewal. **Baseline:** channel/KB components exist; customer operations are new. **Sources:** GTM §9 lifecycle signals; BP support/retention/education inventory. **Dependencies:** E05/E06/E07/E09/E11/E18. **Records added:** Ticket, Customer Onboarding Plan, Service Entitlement, Health Snapshot, Renewal; reuse Account, Contact, Activity and Opportunity.

### E19-F01 — Owned support and knowledge resolution

| Story | User need | Acceptance criteria |
|---|---|---|
| E19-S01 | As a customer, I can report a problem and receive an accountable response across supported channels. | Intake creates/dedupes a ticket, identifies entitlement/priority, assigns an owner and response deadline; related conversations remain linked; urgent/security cases route to the correct incident owner; closure requires a recorded resolution or explicit unresolved state. |
| E19-S02 | As a support operator, I can resolve known issues from approved evidence and escalate the rest. | Suggested answers cite current KB/product context; permitted diagnostics use scoped tools; low confidence, failed remediation and human requests route with history; customer-facing answers follow policy; feedback can propose a reviewed KB update. |

### E19-F02 — Onboarding and customer education

| Story | User need | Acceptance criteria |
|---|---|---|
| E19-S03 | As a customer-success owner, I can turn the accepted sales promise into an onboarding plan. | Plan has customer goals, commitments, tasks, owners, dates and acceptance; completion is based on evidence; blocked tasks escalate; changes to scope require an explicit decision; customer appointments reuse booking capability. |
| E19-S04 | As a customer, I can receive relevant training and find approved self-service material. | Guides/tutorials are versioned and linked to product/entitlement; completion and unresolved questions are recorded; repeated questions propose content improvements; inaccessible or obsolete content does not surface as current guidance. |

### E19-F03 — Retention, renewal, and advocacy

| Story | User need | Acceptance criteria |
|---|---|---|
| E19-S05 | As an account owner, I can identify at-risk or expansion-ready customers and act on evidence. | Health combines declared usage/support/payment inputs with freshness and explainable weights; risk creates an assigned intervention; renewal dates trigger governed tasks; new commercial terms use quote/contract approval rather than silent account edits. |
| E19-S06 | As an account owner, I can prepare QBRs, feedback surveys and advocacy requests. | QBR numbers link to records; consent/contact policy applies to surveys and review requests; complaint feedback routes to service recovery; case-study/public references require customer permission; metrics distinguish participation from satisfaction. |

## E20 — Orders, delivery, and fulfillment

**Outcome:** an accepted commercial promise becomes a delivered and accepted product or service. **Baseline:** new business workflow. **Sources:** GTM closed-won handoff; BP delivery inventory. **Dependencies:** E06/E07/E17/E26; E22 for purchased inputs; E21 for billing. **Records added:** Order/Line, Project, Task, Milestone, Deliverable, Acceptance, Shipment, Return; reuse Product/Service catalog.

### E20-F01 — Commitments, planning, and acceptance

| Story | User need | Acceptance criteria |
|---|---|---|
| E20-S01 | As a delivery manager, I can plan accepted work against available capacity and dependencies. | Approved scope creates one linked order/project; tasks have owners, required resources, dependencies and deadlines; overcommitment is visible; scope changes preserve the original commitment and obtain required approval. |
| E20-S02 | As a customer or reviewer, I can inspect a deliverable and accept it or request rework. | Completion requires specified evidence and reviewer authority; QA/proof-of-work results are linked; partial acceptance and rework remain visible; accepted milestones emit one eligible billing/handoff event. |

### E20-F02 — Operational fulfillment and exceptions

| Story | User need | Acceptance criteria |
|---|---|---|
| E20-S03 | As an operations owner, I can fulfill stocked goods or provision a service without promising unavailable capacity. | Inventory/resource availability is checked and reserved before confirmation; shipment/provisioning status comes from actual execution/provider evidence; failures create owned exceptions; deep production/BOM planning is an optional separately scoped capability. |
| E20-S04 | As a service operator, I can manage delays, returns and corrective action. | SLA risks alert the accountable owner; customer communications are reviewed as required; a return has eligibility, receipt, inspection and disposition states; refunds use authorized finance workflow; order/project/inventory state reconcile after cancellation or retry. |

## E21 — Invoicing and collections

**Outcome:** accepted commercial obligations become correct invoices, receipts and reconciled balances. **Baseline:** new business finance, distinct from platform billing. **Sources:** BP receivables; RT HBS idea; GTM payment attribution extension. **Dependencies:** E04 external commitments, E06/E07/E09/E11/E17; E23 for accounting. **Records added:** Invoice/Line, Receivable, Receipt, Credit Note, Collection Case; reuse Order, Contract, Payment.

### E21-F01 — Invoices and payment state

| Story | User need | Acceptance criteria |
|---|---|---|
| E21-S01 | As a finance operator, I can issue a reviewed invoice from accepted terms or delivered milestones. | Amounts, taxes, currency, numbering, due date and billing party are validated; draft/issued/void/credited state is explicit; immutable issued history is corrected by adjustment, not overwrite; repeated milestone events cannot invoice twice. |
| E21-S02 | As a finance operator, I can record and allocate payments accurately. | Provider callbacks/imports verify source and dedupe; partial/over/underpayments and fees are explicit; receipt allocations reconcile to invoice outstanding amounts; failed or reversed settlements reopen the appropriate balance without losing history. |

### E21-F02 — Governed collections and disputes

| Story | User need | Acceptance criteria |
|---|---|---|
| E21-S03 | As an accounts-receivable owner, I can follow up on overdue balances with context and restraint. | Deterministic reminders use current outstanding state, agreed windows and contact policy; disputes, payment confirmation and manual holds stop inappropriate reminders; collection actions and promises-to-pay are recorded with owners/dates. |
| E21-S04 | As a finance reviewer, I can resolve a dispute or approve a credit, refund or write-off. | Review includes contractual/delivery/support evidence and financial impact; authorized independent approval applies; adjustment updates receivables and accounting once; the customer receives only the approved outcome and the case is auditable. |

## E22 — Procurement and payables

**Outcome:** needed goods/services are purchased and suppliers paid under controlled authority. **Baseline:** new. **Sources:** BP procurement/vendor/payables inventory; RT ownership/SoD. **Dependencies:** E03/E04/E06/E07/E09/E23/E26. **Records added:** Vendor Profile, Requisition, Purchase Order, Goods/Service Receipt, Supplier Bill, Payment Instruction, Verification Result.

### E22-F01 — Vendor and purchasing lifecycle

| Story | User need | Acceptance criteria |
|---|---|---|
| E22-S01 | As a procurement owner, I can assess suppliers and activate an approved vendor. | Identity, risk, insurance/compliance documents and verification freshness are recorded; adverse results escalate; bank-detail changes require independent verification; the vendor creator cannot authorize its payment. |
| E22-S02 | As a requester, I can obtain an approved purchase for a documented business need. | Requisition compares available suppliers/terms and budget; approval creates a versioned PO; changes and cancellations update commitments; requester sees delivery/service acceptance and exception status. |

### E22-F02 — Matching and controlled payouts

| Story | User need | Acceptance criteria |
|---|---|---|
| E22-S03 | As an accounts-payable operator, I can match a bill to authorized purchasing and receipt evidence. | Duplicate invoice checks, amounts/quantities/taxes and PO/receipt tolerances are deterministic; unmatched differences create an exception with owner; matching does not itself authorize payment. |
| E22-S04 | As an authorized payer, I can execute a reviewed payout and know the settlement outcome. | Beneficiary, bank version, amount/currency, due date, authority and funds are rechecked; maker/checker and dual-approval rules apply; stable idempotency and provider reconciliation prevent duplicate payouts; pending/failure/reversal states remain distinct from paid. |

## E23 — Accounting and financial close

**Outcome:** the tenant can maintain consistent business books with traceable evidence. **Baseline:** new; platform usage logs are not accounting records. **Sources:** BP accounting/expenses/tax; RT HBS. **Dependencies:** E06/E09, E21/E22 transactional feeds, E03 review. **Records added:** Chart of Accounts, Journal/Entry/Line, Accounting Period, Bank Statement/Line, Reconciliation, Expense Claim, Tax Code.

### E23-F01 — Accounting records and reconciliation

| Story | User need | Acceptance criteria |
|---|---|---|
| E23-S01 | As an accountant, I can post balanced, evidence-backed transactions and correct them visibly. | Deterministic double-entry checks prevent imbalance; currencies, posting dates and accounts validate; posted entries are immutable with reversals/adjustments; open/closed periods are enforced; source documents and approved business events link to entries. |
| E23-S02 | As a bookkeeper, I can reconcile bank/payment records and employee expenses. | Imports dedupe and preserve source; suggested matches show evidence/confidence; approved matches and unmatched exceptions are explicit; expenses require receipts, policy checks and review; adjustments cannot bypass accounting controls. |

### E23-F02 — Close, reporting and jurisdiction support

| Story | User need | Acceptance criteria |
|---|---|---|
| E23-S03 | As a finance owner, I can close a period and produce reconciled management accounts. | Close checklist covers unresolved matches, receivables/payables and required adjustments; trial balance and supported statements reconcile to entries; reopening needs authority; missing inputs block a clean-close claim. |
| E23-S04 | As a domain reviewer, I can configure supported taxes and prepare required financial reports. | Tax/jurisdiction rules are versioned with source/effective date; arithmetic uses deterministic rules or approved providers; unsupported requirements are explicit; filings and statutory submissions require qualified review and approval; no generic global-compliance guarantee is made. |

## E24 — Planning, treasury, and forecasts

**Outcome:** leaders can decide budgets and cash actions using stated assumptions and actual business data. **Baseline:** new. **Sources:** GTM reporting extension; BP planning/pricing/treasury. **Dependencies:** E06/E18/E21–E23. **Records added:** Business Budget, Budget Version, Cash Forecast, Scenario, Target, Variance; distinct from platform spend envelopes.

### E24-F01 — Budgets and cash visibility

| Story | User need | Acceptance criteria |
|---|---|---|
| E24-S01 | As an owner, I can set operating targets and approve departmental budgets. | Budget versions have period, currency, assumptions, owner and approval; actuals/commitments reconcile to business ledgers; variance alerts use configured thresholds; changes retain history and do not change the AI wallet automatically. |
| E24-S02 | As a treasury owner, I can inspect cash balances, expected receipts/payments and runway. | Forecast distinguishes cleared, committed, expected and speculative cash; timing/FX assumptions and stale feeds are visible; scenarios can change collections/hiring/spend assumptions; cash movement is a separately approved action. |

### E24-F02 — Decision support and management reporting

| Story | User need | Acceptance criteria |
|---|---|---|
| E24-S03 | As a finance leader, I can compare forecast scenarios and record a decision. | Scenarios are reproducible from versioned inputs; calculations expose assumptions and sensitivities; recommendations cite evidence; approval creates owned follow-up work rather than silently reallocating funds. |
| E24-S04 | As an owner, I can receive a management pack combining financial and operational results. | Metrics define period, currency, source, freshness and drill-down; narrative separates observed facts from inference; risks and decisions are assigned; restricted finance information remains permissioned in Pragya and exports. |

## E25 — People lifecycle

**Outcome:** recruiting, employment operations and exits are coordinated with human accountability. **Baseline:** new domain; generic document/channel tools reusable. **Sources:** BP people/recruiting/payroll/benefits/training. **Dependencies:** E01/E03/E05/E06/E07/E09/E11/E26/E28. **Records added:** Position, Requisition, Candidate, Application, Interview, Employee, Employment Agreement, Leave, Payroll Input, Review, Training, Exit Case.

### E25-F01 — Recruiting and offers

| Story | User need | Acceptance criteria |
|---|---|---|
| E25-S01 | As a recruiter, I can coordinate sourcing, applications, interviews and evidence-based screening. | Job criteria and screening rubrics are approved/versioned; candidate consent and data scope are recorded; evaluations cite job-related evidence and uncertainty; human reviewers own consequential hiring decisions; scheduling and candidate communication reuse governed capabilities. |
| E25-S02 | As a hiring manager, I can produce an offer within an approved role and compensation range. | Approved requisition, compensation and terms are checked; all offers/nonstandard negotiations require the assigned human; final agreement is versioned/signed through E26; declined/expired offers cannot trigger onboarding. |

### E25-F02 — Employee operations and development

| Story | User need | Acceptance criteria |
|---|---|---|
| E25-S03 | As an employee, I can complete onboarding, request leave and obtain policy answers. | Employee record controls scoped access; onboarding tasks have owners/evidence; leave balances and approvals use deterministic rules; answers cite applicable policy; HR cases remain private and are escalated when uncertain. |
| E25-S04 | As a payroll or people operator, I can prepare reviewed payroll inputs and development records. | Approved hours, leave, compensation changes and reimbursements reconcile to their sources; exceptions require review; output targets an approved payroll provider or a separately validated local jurisdiction module; training/appraisals have transparent criteria and human review. |

### E25-F03 — Exit and people reporting

| Story | User need | Acceptance criteria |
|---|---|---|
| E25-S05 | As an HR owner, I can execute an approved exit with coordinated access and asset handling. | Separation decision is human-authorized; revocations, asset return, knowledge handover and final-pay inputs have owners/effective dates; delayed/failed revocation escalates; statutory/legal-hold needs are checked; completion is based on evidence. |
| E25-S06 | As an authorized people leader, I can inspect workforce needs and trends without exposing private records. | Headcount/capacity/leave/training metrics have access restrictions and aggregation rules; predictions are labeled and do not automatically trigger adverse employment action; corrections and approved record exports are supported. |

## E26 — Contracts and obligations

**Outcome:** commercial/legal work moves from request to approved terms, signature and tracked obligations. **Baseline:** document generation available; contract lifecycle new. **Sources:** GTM proposals/redlines; BP legal inventory. **Dependencies:** E03/E05/E06/E09/E11. **Records added:** Contract, Contract Version, Clause/Playbook, Approval, Signature Envelope, Obligation, Dispute.

### E26-F01 — Draft and review

| Story | User need | Acceptance criteria |
|---|---|---|
| E26-S01 | As a contract owner, I can draft from approved templates and inspect deviations. | Variables link to verified business records; template/playbook versions are pinned; comparison/redlines expose changed terms and missing information; liability and nonstandard terms route to qualified human review; no unreviewed legal conclusion becomes an approved clause. |
| E26-S02 | As a legal reviewer, I can authorize the exact version and signing parties. | Review includes commercial authority and exceptions; edits invalidate old approvals as appropriate; signatory identity/authority is checked; a rejected or outdated version cannot be sent for signature. |

### E26-F02 — Execution and continuing obligations

| Story | User need | Acceptance criteria |
|---|---|---|
| E26-S03 | As a contract owner, I can route an approved agreement and verify execution. | E-signature envelope creation is idempotent; signed/declined/expired/provider-pending states are verified; executed document and evidence are stored; only verified execution triggers downstream commitments. |
| E26-S04 | As an obligation owner, I can monitor renewals, notice dates, duties and disputes. | Extracted obligations are reviewable and linked to clauses; reminders have owners and due dates; changes/termination preserve contract history; disputes link relevant support, delivery and finance evidence; deadlines do not silently lapse. |

## E27 — Risk, privacy, and incidents

**Outcome:** the business can identify obligations, handle requests and respond to incidents with accountable evidence. **Baseline:** platform controls partially exist; business workflows new. **Sources:** GTM compliance/privacy requirements; BP risk/incident/corporate records inventory. **Dependencies:** E01/E03/E05/E06/E07/E09/E12; independent audit permissions. **Records added:** Risk, Control, Policy/Obligation, Evidence, Privacy Request, Legal Hold, Incident, Action, License/Insurance Record.

### E27-F01 — Obligations, risk and evidence

| Story | User need | Acceptance criteria |
|---|---|---|
| E27-S01 | As a risk owner, I can maintain applicable obligations and an owned control plan. | Applicability is reviewed for supported jurisdiction/sector, including any required sustainability/ESG disclosures; source/effective date, owner, evidence and due date are recorded; changes create reviewed tasks; monitoring claims do not imply universal legal compliance. |
| E27-S02 | As an independent auditor, I can sample controls and track findings. | Evidence has provenance, time, integrity checks, scoped retention and access history; auditors cannot alter audited operations; findings have severity, owner and remediation evidence; corporate licenses/insurance renewals receive owned reminders. |

### E27-F02 — Privacy requests and records lifecycle

| Story | User need | Acceptance criteria |
|---|---|---|
| E27-S03 | As a privacy officer, I can respond to a verified subject's access, correction or deletion request. | Verify identity and scope; enumerate business records, conversations, knowledge and derived stores; detect legal holds; reviewer authorizes actions; fulfillment records completion/exceptions and notifies downstream systems under declared responsibility. |
| E27-S04 | As a data owner, I can understand and govern where business data is used. | Data map covers integrations, models, logs, artifacts and backups; retention/residency and training choices are explicit; model training is separate from operational processing consent; revoked/deleted data cannot be silently reused by new learning jobs. |

### E27-F03 — Incidents and crisis response

| Story | User need | Acceptance criteria |
|---|---|---|
| E27-S05 | As an incident commander, I can triage, contain and recover a business or security incident. | Any permitted source can report an incident; severity/owner/runbook/timeline are recorded; safe pre-authorized containment is deterministic and bounded; unsafe work can be stopped promptly; recovery requires evidence and controlled re-enablement. |
| E27-S06 | As an accountable leader, I can review external incident communications and learn from the event. | Customer/public/regulatory drafts identify verified facts and uncertainty; named humans authorize required communications; deadlines and delivery outcomes are tracked; postmortem assigns corrective actions; funded AI reserve exhaustion leaves deterministic incident status/notification available. |

## E28 — Access, assets, and operational maintenance

**Outcome:** people and business workflows have the right systems/assets, with predictable maintenance. **Baseline:** some technical tooling exists; business administration new. **Sources:** BP IT/facilities/data-pipeline inventory; GTM connector health. **Dependencies:** E01/E03/E06/E07/E09/E12/E25. **Records added:** Access Request/Grant, Asset, Assignment, Maintenance Plan, Service Ticket, Data Job.

### E28-F01 — Access and asset administration

| Story | User need | Acceptance criteria |
|---|---|---|
| E28-S01 | As an IT owner, I can provision and revoke approved access with least privilege. | Requests link to a verified person/role and approval; privileged access is independently reviewed; granted scopes/effective dates are confirmed by the target system; failures remain open; recertification and exit revocation leave evidence. |
| E28-S02 | As an operations administrator, I can track physical/digital assets and recurring maintenance. | Ownership, assignment, lifecycle, licenses/leases and renewal dates are recorded; planned work has due dates and owners; overdue maintenance or unused licenses raise proposals; purchases/disposals follow procurement/approval policy. |

### E28-F02 — Data and service maintenance

| Story | User need | Acceptance criteria |
|---|---|---|
| E28-S03 | As a data owner, I can identify and repair stale or failed business-data flows. | Freshness/quality checks link to jobs and records; schema drift and reconciliation gaps create owned exceptions; repair preview preserves source-of-record rules and idempotency; after repair, reconciliation proves data consistency. |
| E28-S04 | As a service owner, I can restore an integration using approved runbooks or a reviewed fix. | Diagnosis captures evidence without exposing secrets; known low-risk runbooks respect permissions and limits; generated code/adapter changes enter E32's independent test/promotion path; failed repair escalates rather than repeatedly changing production. |

## E29 — Product, experiments, and pricing

**Outcome:** the business turns customer/market evidence into considered product and offer changes. **Baseline:** new business workflow. **Sources:** GTM voice-of-customer/CRO/competitive research; BP product/pricing inventory. **Dependencies:** E06/E13/E18/E19/E24; E03 for commercial/publishing changes. **Records added:** Idea, Research Finding, Product Requirement, Backlog Item, Experiment, Offer/Price Version, Launch Plan.

### E29-F01 — Evidence to product plan

| Story | User need | Acceptance criteria |
|---|---|---|
| E29-S01 | As a product owner, I can synthesize customer, market and support evidence into a prioritized backlog. | Findings preserve source/permission and affected segment; duplicate requests consolidate without losing counts; prioritization shows impact/effort/uncertainty assumptions; humans approve commitments; customer statements do not become fabricated roadmap promises. |
| E29-S02 | As a launch owner, I can coordinate an approved product or service release. | Scope, acceptance, enablement, support readiness, fulfillment and marketing tasks have owners; launch depends on actual readiness evidence; content/price publication obey approvals; rollback and customer-impact handling are defined. |

### E29-F02 — Experiments and pricing decisions

| Story | User need | Acceptance criteria |
|---|---|---|
| E29-S03 | As an experiment owner, I can test a hypothesis with agreed measurement and stop rules. | Population, allocation, success/guardrail metrics, duration and consent constraints are explicit; data gaps are visible; early stopping and exclusions are documented; analysis avoids declaring causation from unqualified correlations. |
| E29-S04 | As a commercial owner, I can compare price/packaging proposals before applying them. | Proposal uses cost, demand and contract constraints; audience/percentage/amount limits and approval apply; contractual prices are protected; activated price versions propagate coherently to quoting/billing and can be reverted with an audit trail. |

## E30 — Partnerships and capital stakeholders

**Outcome:** partner, board, investor and corporate-development work shares business evidence without uncontrolled commitments. **Baseline:** new; research/documents reusable. **Sources:** GTM later partner/channel backlog; BP partnerships/capital inventory. **Dependencies:** E06/E09/E13/E17/E18/E24/E26/E27. **Records added:** Partner Profile, Partner Agreement, Referral, Commission, Stakeholder, Board Action, Diligence Request, Data Room; reuse Account/Contact.

### E30-F01 — Partner lifecycle and revenue

| Story | User need | Acceptance criteria |
|---|---|---|
| E30-S01 | As a partnership owner, I can evaluate and onboard a business partner. | Due diligence, territory, rights, enablement and agreement terms are recorded; required review completes before activation; partner access exposes only shared records; channel enablement content is current and approved. |
| E30-S02 | As a channel manager, I can track referrals, co-selling and earned commission. | Referral ownership/dedupe and attribution rules are explicit; deal/receipt state determines eligibility; disputes enter review; commissions reconcile to approved agreements and payouts reuse E22 controls. |

### E30-F02 — Leadership and stakeholder coordination

| Story | User need | Acceptance criteria |
|---|---|---|
| E30-S03 | As a leader, I can prepare board/investor reports and maintain the decisions that follow. | Packs use permissioned, reconciled business metrics; narrative discloses assumptions; external sends receive named review; meetings create accepted actions with owners/dates; confidential strategy remains separately scoped. |
| E30-S04 | As a capital-process owner, I can maintain an access-controlled diligence room and research opportunities. | Documents have versions, purpose-limited access and expiry; requests and answers are owned; access/downloads are audited; research on funding or acquisition candidates cites sources; no negotiation or financial commitment occurs without explicit human authority. |

### E30-F03 — Executive coordination and strategy follow-through

| Story | User need | Acceptance criteria |
|---|---|---|
| E30-S05 | As an executive, I can delegate scheduling, inbox triage and meeting preparation within explicit boundaries. | Internal communications are classified with scoped access; proposed responses and meetings reuse approved channel/calendar controls; conflicts and sensitive requests route to the owner; minutes cite source notes and produce confirmed action items rather than invented commitments. |
| E30-S06 | As an owner, I can translate strategic decisions into owned work and review progress. | Objectives link to initiatives, budgets, measurable outcomes and accountable people; changes preserve decision rationale; periodic reviews show actual progress, blockers and assumptions; cross-functional assignments require acceptance and cannot override another owner's authority silently. |
