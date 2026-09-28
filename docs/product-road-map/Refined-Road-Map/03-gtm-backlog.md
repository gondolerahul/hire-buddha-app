# Marketing and sales: the reference business implementation

These six epics establish the business pattern reused in the expansion backlog: canonical records, explicit ownership, durable activities, deterministic workflow state, reusable Skills, evidence-based judgment, and controlled external effects. The older GTM-P1…P6 names are references, not another entity layer to deploy.

**Shared dependencies:** E01–E05 for trust, execution, review, spend and grounding; E08 for versioned Skills. Record-based work additionally needs E06, recurring work E07, integration work E09, and external communication E11. A human approval does not waive any of these controls.

## E13 — Market intelligence and targeting

**Outcome:** a marketing/sales operator can build a defensible understanding of a market and target audience. **Baseline:** research/artifact tools exist; durable business intelligence is new. **Sources:** GTM §§6,9; FEAS §2. **Primary operator:** marketing/revenue operations.

### E13-F01 — Research and monitoring

| Story | User need | Acceptance criteria | Gate |
|---|---|---|---|
| E13-S01 | As a marketer, I can produce a cited company, market or competitor brief. | Findings identify source and observation date; claims are distinguished from inference; inaccessible/conflicting evidence is flagged; output follows a reusable brief Skill and can be downloaded without any external publication. | H1 |
| E13-S02 | As a marketer, I can monitor relevant market changes without receiving the same alert repeatedly. | Scheduled news, pricing/features, hiring/funding, reviews and category research compare observations with prior records; dedupe retains provenance; meaningful changes create owned Business Signals; unknown data does not become a fabricated trend. | H2 |

### E13-F02 — ICP, accounts and buying groups

| Story | User need | Acceptance criteria | Gate |
|---|---|---|---|
| E13-S03 | As a revenue owner, I can define and revise an ICP with explainable scoring. | ICP rules, weights and disqualifiers are versioned; score shows supporting evidence and missing fields; a changed definition can rescore a preview cohort before activation; protected/sensitive data restrictions apply to enrichment. | H2 |
| E13-S04 | As a seller, I can build target-account and buying-group lists from permitted evidence. | Account/contact enrichment records source, freshness and confidence; identities dedupe through E06; segments are reproducible from saved criteria; discovered contact details never imply permission to contact; vendor enrichment can replace research behind the same Skill contract. | H2 |

### E13-F03 — Actionable intelligence outputs

| Story | User need | Acceptance criteria | Gate |
|---|---|---|---|
| E13-S05 | As a seller, I can prepare account briefs, competitive battlecards and objection evidence. | Output uses the current approved messaging library and source citations; unsupported comparisons are marked; sensitive customer evidence is scoped; brief version is linked to the account/deal. | H1 |
| E13-S06 | As an owner, I can turn an insight into assigned work and later assess its value. | A signal can propose a campaign, account task, risk or product idea; destination owner accepts/rejects and records reason; resulting work and outcome link to the original insight; read-only research does not silently trigger a send. | H3 |

## E14 — Content and demand generation

**Outcome:** a brand owner can move from evidence-backed briefs to reviewed assets, distribution and learning. **Baseline:** content/media/document tools exist; brand records, editorial workflow and governed distribution are new. **Sources:** GTM §§6,8–11; SK; FEAS N-2/N-3/N-9. **Additional dependencies:** E06 for editorial records; E09/E11 for publishing; E04-S06 for paid commitments.

### E14-F01 — Brand brain and reusable asset production

| Story | User need | Acceptance criteria | Gate |
|---|---|---|---|
| E14-S01 | As a brand owner, I can maintain approved positioning, proof points, tone and prohibited claims. | Messaging Library is versioned and permissioned; content Skills retrieve approved material; brand/fact review cites offending passages and evidence; unavailable evidence produces an explicit gap rather than a confident claim. | H1 |
| E14-S02 | As a content operator, I can create and repurpose assets for a defined audience and channel. | Supported templates include articles, landing copy, case studies, newsletters, social posts, one-pagers, decks, video scripts and ad variants; derivatives preserve claim provenance; documents/media have previews and linked artifacts; reusable scripts avoid regenerating boilerplate. | H1 |

### E14-F02 — Editorial plan, review and publication

| Story | User need | Acceptance criteria | Gate |
|---|---|---|---|
| E14-S03 | As an editor, I can manage a content calendar and approve the exact asset to publish. | Brief/draft/review/approved/scheduled/published/failed states are visible; reviewers edit with version history; changes after approval invalidate it; schedule preview includes channel/account and timezone; rejection returns work to an assigned owner. | H2 |
| E14-S04 | As a marketer, I can publish approved content to validated channels and verify completion. | Current account permissions, policy and idempotency are checked before effect; provider acceptance is distinguished from publication; final URL/status and metrics link to the asset; partial multi-channel failure retries only unresolved eligible effects. | H2 |

### E14-F03 — Extended demand programs

| Story | User need | Acceptance criteria | Gate |
|---|---|---|---|
| E14-S05 | As a marketer, I can run event, community, review and nurture programs with governed follow-up. | Registration, invitations, attendance/no-show, replies, reminders and follow-up become records/activities; consent and stop rules apply; PR statements require named approval; complaints or sensitive community responses route to an accountable human. | H3 |
| E14-S06 | As a paid-marketing owner, I can plan and optimize advertising without unbounded ad-account spending. | Preview campaign/audience/creative and external budget separately from platform cost; spend-changing actions are approved under configured bands; pacing uses reconciled provider actuals/commitments; missing spend data stops increases; SEO/CRO/ad experiments distinguish recommendations from applied changes. | H4 |

## E15 — Inbound qualification and booking

**Outcome:** an inquiry becomes an identified, owned opportunity or a correctly routed service request. **Baseline:** voice/gateway components exist; reliable capture, qualification and booking workflow are new. **Sources:** GTM GTM-P4; FEAS N-5; GW/VT defects. **Dependencies:** E06/E07/E09/E11 plus shared foundations. External-response policy follows D03.

### E15-F01 — Capture and identity

| Story | User need | Acceptance criteria | Gate |
|---|---|---|---|
| E15-S01 | As a sales operator, I can capture inquiries from a form, web chat, email, messaging or phone. | A supported capture surface persists source, time, contact permission and supplied details; signatures/rate limits protect intake; duplicate submission does not create duplicate work; routing never selects an arbitrary ACTION/SKILL; unanswered/unroutable inquiries enter an owned queue. | H2 |
| E15-S02 | As a seller, I can see a new inquiry in the context of earlier interactions. | Identity matching is explainable and reversible; account/contact/activity records retain attribution; existing customer/support intent routes appropriately; anonymous or uncertain identity is kept separate until resolved. | H2 |

### E15-F02 — Qualification and response

| Story | User need | Acceptance criteria | Gate |
|---|---|---|---|
| E15-S03 | As a sales manager, I can qualify and assign inquiries using explicit business rules. | Versioned fit/intent scoring exposes evidence; assignment uses capacity/territory/availability rules and a fallback owner; inactivity triggers a configured SLA escalation; model uncertainty does not invent eligibility or a qualification answer. | H2 |
| E15-S04 | As a prospect, I receive a relevant response with an appropriate path to a human. | Response uses approved product/price facts and permitted history; action follows D03's initial review/session policy; response-time reports separate review wait from AI processing; requested human escalation and opt-out are honored. | H2 |

### E15-F03 — Scheduling lifecycle

| Story | User need | Acceptance criteria | Gate |
|---|---|---|---|
| E15-S05 | As a prospect, I can book a valid meeting in my timezone. | Availability is read before booking; working hours, buffers, round-robin rules and attendee timezones apply; last-moment conflict yields alternatives; only one provider-confirmed event is created and linked to the opportunity/activity. | H2 |
| E15-S06 | As a prospect or rep, I can reschedule/cancel and receive useful reminders or no-show follow-up. | Changes update the same meeting, cancel obsolete reminders and preserve history; provider failures are visible; follow-up uses current consent/reply state; attendance/outcome closes the original booking task. | H3 |

## E16 — Outbound sequences and deliverability

**Outcome:** approved outreach occurs at the right time and stops when it should. **Baseline:** single-message SMTP and dialer infrastructure; sequence/deliverability layer new. **Sources:** GTM §§3,5,8–11; FEAS §3/N-3/N-9. **Dependencies:** E06/E07/E09/E11; E03 durable approval; E04 budget controls. No live outbound pilot before these gates.

### E16-F01 — Sender and contact readiness

| Story | User need | Acceptance criteria | Gate |
|---|---|---|---|
| E16-S01 | As an outbound operator, I can validate a sender and its delivery limits before launch. | Chosen provider connection, domain authentication/readiness, mailbox identity, daily caps and volume ramp are visible; missing setup prevents launch; bounce/complaint thresholds pause affected sending; mailbox rotation cannot bypass account/domain caps. | H3 |
| E16-S02 | As a contact, I can withdraw permission and have it enforced immediately. | Channel/purpose-specific consent includes source/time/evidence; unsubscribe, complaint, hard bounce and DNC events update shared suppression; imported lists cannot clear suppression silently; queued steps recheck eligibility immediately before sending/dialing. | H2 |

### E16-F02 — Deterministic sequence execution

| Story | User need | Acceptance criteria | Gate |
|---|---|---|---|
| E16-S03 | As an operator, I can design, preview and approve a sequence before enrolling people. | Versioned steps specify channel, delay, conditions, template, send window and exit rules; preview renders representative recipients and shows cost/permissions; invalid schedules/loops/missing permissions fail validation; active enrollments pin a version until an explicit migration. | H3 |
| E16-S04 | As an operator, I can trust enrollment timing and effects through retries and restarts. | Deterministic states own step eligibility; each effect uses a stable idempotency key; per-recipient/enrollment leases prevent concurrent sends; caps/timezones apply; pause/cancel and provider uncertainty survive restart without duplicate contact. | H3 |

### E16-F03 — Reply, stop and performance handling

| Story | User need | Acceptance criteria | Gate |
|---|---|---|---|
| E16-S05 | As a seller, I can take over when a prospect replies or books. | Incoming replies correlate to the correct thread/contact; reply/booking/opt-out stop or alter enrollment under deterministic rules; ambiguous replies route to review; recheck immediately before the next effect closes the reply/send race; handoff includes qualified context. | H3 |
| E16-S06 | As a marketing owner, I can judge outreach results and spending honestly. | Delivery, replies, meetings, failures and suppression are reported by cohort/version; privacy-sensitive open/click tracking is optional under policy and labeled as approximate; platform cost and delivery/ad spend are separate; direct-message/connection automation is unavailable unless an approved supported provider capability exists. | H3 |

## E17 — Deal desk and sales execution

**Outcome:** sellers prepare, qualify, quote and hand off deals from shared evidence. **Baseline:** research/document generation partly available; deal workflow new. **Sources:** GTM GTM-P6/§9; FEAS N-2; BP sales requirements as inventory. **Dependencies:** E06/E09; E05 for grounded answers; E03/E11 for approvals/sends; E26 for signed contract lifecycle.

### E17-F01 — Preparation and discovery

| Story | User need | Acceptance criteria | Gate |
|---|---|---|---|
| E17-S01 | As a seller, I can prepare a meeting brief and demo plan from verified account context. | Brief lists stakeholders, history, current needs, open questions and sources; stale or absent CRM data is labeled; no invented interaction history; reviewable artifact works even before live CRM sync using approved uploaded input. | H1 |
| E17-S02 | As a seller, I can turn an authorized recording or notes into confirmed actions and qualification evidence. | Transcript/notes retain provenance and recording permissions; MEDDIC/BANT-style fields show supporting evidence/unknowns; CRM edits are proposed with a diff; confirmed actions get owner/date; external meeting ingest is distinct from platform-call transcription. | H2 |

### E17-F02 — Commercial proposals and evidence-based answers

| Story | User need | Acceptance criteria | Gate |
|---|---|---|---|
| E17-S03 | As a deal owner, I can create an accurate quote/proposal within approved terms. | Product/service catalog and Quote/line-item records support quantities, currencies, taxes, validity and versioning; arithmetic is deterministic; nonstandard terms/discounts route for approval; approved artifacts link to opportunity; price changes invalidate affected approvals. | H2 |
| E17-S04 | As a presales specialist, I can draft RFP and security-questionnaire answers from approved evidence. | Answers cite current accessible sources; gaps are assigned to experts; confidential evidence respects permissions; claims/certifications are not invented; final response and attachments are reviewed before dispatch. | H1 |

### E17-F03 — Deal health and commercial handoff

| Story | User need | Acceptance criteria | Gate |
|---|---|---|---|
| E17-S05 | As a manager, I can review deal risks, hygiene and forecast changes. | Missing fields, stale activity, stage inconsistencies, competitor/champion signals and close-date changes are explainable; updates respect system-of-record rules; win/loss reasons retain evidence; predictions remain distinct from confirmed bookings. | H3 |
| E17-S06 | As a delivery or customer-success owner, I receive an accepted closed-won handoff once. | Required approval/signature/commercial conditions are verified; accepted scope, obligations, quote and contacts create linked downstream order/onboarding work; recipient acknowledges ownership; duplicate close events cannot create duplicate work; reopening/cancellation propagates explicitly. | H4 |

## E18 — Revenue operations and reporting

**Outcome:** owners can trace revenue metrics back to records, interactions and costs. **Baseline:** platform usage reporting exists; business reporting new. **Sources:** GTM GTM-P2/§§9–11; FEAS §2 correction. **Dependencies:** E06; relevant channel/CRM/payment data; E04 cost ledger. A research artifact is not evidence that pipeline reporting already works.

### E18-F01 — Funnel and pipeline truth

| Story | User need | Acceptance criteria | Gate |
|---|---|---|---|
| E18-S01 | As a revenue owner, I can inspect funnel, pipeline and conversion by cohort. | Lifecycle/stage definitions, time period, timezone, currency, dedupe and exclusions are shown; numbers drill down to records/activities; incomplete/stale sync is visible; unavailable source data yields unknown rather than zero or invented revenue. | H2 |
| E18-S02 | As a manager, I can view forecast and outcome reports with explicit assumptions. | Commit/best-case/forecast are distinct from won/paid results; probability versions and missing data are disclosed; evidence is linked; weekly briefs include risks, required decisions and changed assumptions. | H3 |

### E18-F02 — Attribution and cost per outcome

| Story | User need | Acceptance criteria | Gate |
|---|---|---|---|
| E18-S03 | As a marketer, I can compare channels using a consistent, limited attribution model. | First/last touch and self-reported source are available; conversion windows and identity gaps are explicit; multi-touch claims are not treated as causal proof; campaign/content/sequence lineage survives merges and CRM synchronization. | H3 |
| E18-S04 | As an owner, I can see cost per qualified opportunity, meeting and sale. | Platform, provider and campaign costs reconcile to their ledgers and the outcome cohort; cancelled/duplicate/failed activity is treated consistently; missing external spend is disclosed; margin/ROI calculations show assumptions. | H3 |

### E18-F03 — Daily supervision and improvement

| Story | User need | Acceptance criteria | Gate |
|---|---|---|---|
| E18-S05 | As an owner, I can see what my AI workforce did today and what needs attention. | Activity feed is filterable by business object, workflow and outcome; links to runs, costs, approvals and artifacts; failures, skipped actions and waiting are included; no raw internal trace is required to understand the business result. | H2 |
| E18-S06 | As a revenue-operations owner, I can turn performance findings into controlled improvements. | Alerts use configured thresholds and data freshness; improvement proposals name affected Skill/rules and evidence; human changes/rejections feed evaluation; a recommendation cannot silently alter pricing, outreach or policy. | H3 |
