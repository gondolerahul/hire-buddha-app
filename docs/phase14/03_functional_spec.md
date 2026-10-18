# Phase 14 — Functional Specification

> **Status:** Draft for review.
> **Date:** 2026-10-16
> **What this is:** what Phase 14 lets people do, how it looks and which rules apply, in plain language. The technical design is in [02 — Technical specification](02_tech_spec.md); the build order is in [01 — Implementation plan](01_implementation_plan.md).
> **Roadmap:** E07 (schedules and events), E06-S04 and E36 (records, schema, Data API, tenant database), E09-F04 (connections), E37 (code, GitHub, apps), E41 (Azure move); decisions D34–D40.

---

## 1. The idea in one paragraph

Until now an agent works only when someone presses **Run**. After Phase 14 a business owner sets things up once, and the work keeps happening: on a timetable, when a customer writes, when an order is paid, when another agent finishes. Each business gets its **own private database** that can grow new tables, its **own connections** to Facebook, WhatsApp, LinkedIn, GitHub and others, and can have **small apps and websites** built and published for it. All of this runs on Azure.

---

## 2. Who uses it

| Person | Who they are | What they mainly do in Phase 14 |
|--------|--------------|----------------------------------|
| **Owner** | The business owner (tenant owner) | Decides what runs automatically, approves important changes, connects accounts, asks for apps |
| **Admin** | Someone the owner trusts to configure things | Creates triggers, manages connections, data structure, API keys and apps |
| **Operator** | Day-to-day user | Watches the control room, retries failed items, handles exceptions |
| **Reviewer** | Approves sensitive actions | Approves schema changes, code promotions, app publication |
| **Builder** | Technical user of the tenant (optional) | Reviews pull requests in GitHub, edits app code |
| **App user** | Someone who uses an app built for the tenant (e.g. Acme's sales staff or customers) | Logs in to the app; never sees HireBuddha |
| **Agent** | An AI worker in HireBuddha | Runs when triggered; may schedule work, send signals, wait for replies, read and write records within its permissions |
| **Platform admin** | HireBuddha staff | Manages system integrations, connector approvals, tenant databases, the Azure move |
| **Pragya** *(built after Phase 14)* | A separate assistant layer between the new Generative UI and the backend (D41) — not an agent | Will do anything in this specification **on behalf of** the person it is talking to, with that person's permissions; it cannot approve its own proposals, and every action shows "done by Pragya for <person>" |

Because Pragya will later drive everything described here, every action in this specification must be possible through the API as well as the screen, must ask the same approvals, and must be recorded with who asked for it.

### 2.1 Permissions

| Action | Owner | Admin | Operator | Reviewer | Builder | Platform admin |
|--------|:-----:|:-----:|:--------:|:--------:|:-------:|:--------------:|
| Create/edit/pause triggers and schedules | ✓ | ✓ | pause only | | | |
| Pause all automation (kill switch) | ✓ | ✓ | ✓ | | | ✓ (emergency) |
| Retry or replay failed events | ✓ | ✓ | ✓ | | | |
| Propose a data structure change | ✓ | ✓ | | | ✓ | |
| Approve a data structure change | ✓ | ✓ (additive only) | | ✓ | | |
| Create/rotate API keys | ✓ | ✓ | | | ✓ | |
| Connect / disconnect accounts | ✓ | ✓ | | | | |
| Approve code promotion / merge | ✓ | | | ✓ | ✓ (if granted `code.approve`) | |
| Publish / unpublish / roll back an app | ✓ | ✓ | rollback only | | | |
| Add custom domains | ✓ | ✓ | | | | |
| Manage app users and roles | ✓ | ✓ | | | | |
| System integrations, connector catalog, tenant DB placement | | | | | | ✓ |

The exact role names map onto the existing RBAC model (E01); a tenant can grant the permissions above to its own roles.

---

## 3. Automation: schedules, triggers and the control room (E07)

### 3.1 What the owner can set up

A **trigger** is a rule: *when this happens → run this agent with this input → under these rules*.

| Kind | Example | Notes |
|------|---------|-------|
| Schedule | "Every weekday at 09:00 → Daily sales report" | Uses the business time zone unless changed |
| One-time timer | "20 Oct at 15:00 → Webinar reminder" | Fires once, then ends |
| Event | "New Instagram comment that mentions price → Community manager" | Needs a connected account (§6) |
| Data change | "Order status becomes *paid* → Invoice agent" | Works on any table, including new ones (§4) |
| Condition | "Every hour, if stock < 10 → Re-order agent" | Checked without using AI; the agent runs only when true |
| Run finished | "When *Research* completes → *Report writer*" | Chains agents without them calling each other |
| Manual | The **Run** button | Still available |

### 3.2 Trigger editor (screen)

```
┌─ New trigger ──────────────────────────────────────────────────────────────┐
│ Name      [ Reply to Instagram comments                           ]        │
│                                                                            │
│ WHEN      ( ) On a schedule   ( ) At a time   (•) When something happens   │
│           Event  [ Instagram – new comment              ▾]                 │
│           Only if [ text ] [ contains ] [ price ]        [+ condition]     │
│                                                                            │
│ RUN       Agent  [ Community Manager                    ▾]                 │
│           Input  [ Reply politely to: {{event.data.text}}         ]        │
│                                                                            │
│ RULES     If still running from last time: [ Skip ▾]                       │
│           Missed while paused or down:     [ Run once ▾]                   │
│           At most [ 60 ] runs per hour                                     │
│                                                                            │
│ PREVIEW   Matches 3 of the last 50 Instagram comments  [ show ]            │
│                                                       [Cancel] [Save]      │
└────────────────────────────────────────────────────────────────────────────┘
```

* For schedules the preview shows the **next 10 run times** in the business time zone.
* For events the preview tests the filter against recent real events, so the owner sees what would have matched.
* Saving a trigger never runs anything immediately unless the owner presses **Run now**.

### 3.3 What agents can do on their own

When the owner allows it on the agent's settings (**Automation** tab):

| Agent ability | Example | Limits |
|---------------|---------|--------|
| Schedule work | "Follow up with this lead in 3 days" | Only agents the owner listed. Optional limits (none unless set, §3.5): active agent-made schedules per business, per run, shortest repeat |
| Send a signal | "lead qualified" → wakes the Sales agent's trigger | Only *custom* signals. Optional limit: signals per run |
| Wait for something | "Wait until the customer replies, up to 48 hours" | The run uses no resources while waiting. Optional limit: longest wait |
| Cancel its schedules | | Only schedules it (or its process) created |

Everything an agent schedules appears in the trigger list marked **"created by agent: <name>"**, and the owner can pause or delete it.

### 3.4 Control room (screen)

```
┌─ Control room ───────────────────────────────── Automation: ● Running [Pause all] ┐
│ TODAY        142 runs started · 3 waiting · 1 failed event · 0 missed schedules   │
│                                                                                   │
│ NEEDS ATTENTION                                                                   │
│  ⚠ Instagram connection needs reconnect — 2 triggers paused     [Reconnect]       │
│  ⚠ 1 event failed 5 times: crm.contact.created                  [View] [Retry]    │
│  ⚠ "Re-order agent" blocked: wallet below reserve                [Top up]          │
│                                                                                   │
│ UPCOMING                                                                          │
│  09:00  Daily sales report            (schedule)                                  │
│  11:30  Follow-up: Priya Sharma       (created by agent: Sales Assistant)         │
│                                                                                   │
│ TRIGGERS                         Last run        Next run      Status             │
│  Reply to Instagram comments     2 min ago       on event      ● On               │
│  Daily sales report              yesterday 09:00 today 09:00   ● On               │
│  Invoice on paid order           1 h ago         on change     ● On               │
│  Lead follow-up (agent)          —               Thu 11:30     ● On               │
└───────────────────────────────────────────────────────────────────────────────────┘
```

* **Event log:** every event with time, type, source, status (*handled*, *waiting*, *failed*, *held*) and what it started. Clicking an event shows each trigger's decision and the reason ("skipped: still running", "blocked: budget", "stopped: loop limit").
* **Failed events** can be retried; **held events** (automation was paused) run in order when automation resumes.
* **Waiting runs** list what each run waits for and its deadline; an operator can cancel a wait.

### 3.5 Rules

Every limit below is a setting on the **Automation settings** screen (owner and admin; platform staff set platform-wide defaults the same way) and in the API; **none applies unless someone sets it** (decision D47, 18 Oct 2026). A business's own value wins over the platform's.

| Rule | Default | Changeable by |
|------|---------|---------------|
| A duplicate event (same source id) starts nothing new | always | — |
| One trigger decides at most once per event | always | — |
| Loop limit: a chain of agent-caused events stops after *N* steps, with a visible "loop stopped" item | no limit | Owner, Admin (platform default: platform staff) |
| Runs at the same time per business | no limit | Owner, Admin |
| Runs per trigger per hour | no limit | Owner, Admin (per business and per trigger) |
| If the previous run is still going | Allow | Owner, Admin: skip / queue / allow (per business and per trigger) |
| Missed times (pause or outage) | Run all | Owner, Admin: skip / run once / run all, optionally at most *N* (per business and per trigger) |
| Agent-made schedules: per business, per run, shortest repeat | no limit | Owner, Admin |
| Agent signals per run; longest wait | no limit | Owner, Admin |
| Money: a triggered run starts only if the wallet can reserve its cost | always (D06) | — |
| Pausing automation | Holds new events; running work finishes; schedules do not fire | Owner, Admin, Operator |
| Time zone | Business time zone, set in settings (replaces the fixed India time) | Owner, Admin |
| Event history kept | forever unless set | Owner, Admin (platform default: platform staff) |

### 3.6 Notifications

In-app and email to Owner/Admin (Operator for operational items): failed event, trigger failing repeatedly, missed schedule, loop stopped, run blocked by budget, connection needs reconnect, waiting run timed out (optional per trigger).

### 3.7 Acceptance (from the roadmap)

E07-S01 schedules in business time zone with preview and catch-up rules · E07-S02 delayed follow-ups survive restarts and fire once · E07-S03 declared event routing, unmatched events visible · E07-S04 every accepted event accounted for, replay without duplicates, no endless loops · E07-S05 overview of recurring work with pause · E07-S06 alerts when recurring work stops making progress.

---

## 4. Business records and data structure (E06-S04, E36)

### 4.1 What changes for the owner

Each business has **its own database**. It starts with standard tables (**Accounts**, **Contacts**, **Activities**, **Consents**) and can grow new ones — *Orders*, *Shipments*, *Patients*, *Classes* — with real columns and links between tables (no "spreadsheet in a single field").

### 4.2 Records screen

```
┌─ Records ─────────────────────────────────────────────────────────────────┐
│ Tables: [Accounts] [Contacts] [Activities] [Consents] [Orders] [Shipments]│
│                                                                           │
│ Shipments                         Search [            ]  [Filter] [+ New] │
│  Order     Carrier     Status       ETA          Updated                  │
│  #1042     BlueDart    in transit   18 Oct       5 min ago by Ops Agent   │
│  #1039     DTDC        delivered    15 Oct       yesterday by Ravi        │
└───────────────────────────────────────────────────────────────────────────┘
```

Each record shows its **history** (who changed what: a person, an agent or an app) and its links (an Order's Shipments).

### 4.3 Changing the data structure

```
Owner or agent: "We need to track shipments"
   ▼
Proposal: new table Shipments — Order (link), Carrier, Status, ETA
   ▼
HireBuddha checks it and shows what it affects (agents, apps, keys, reports, triggers)
   ▼
Approval (person, or automatic for simple additions if the owner allows)
   ▼
Live: the table appears in Records, in the API and in agents' tools — no restart
```

**Schema designer (screen):** a list of tables, each with fields (name, type, required, default, link), plus **Propose change**. The **change review** screen shows: what will be added or changed, a plain-language impact list ("2 agents read Orders; 1 app writes Orders"), warnings ("12 existing rows have no ETA, so ETA cannot be required yet"), and **Approve / Reject**.

### 4.4 Rules

| Rule | Detail |
|------|--------|
| Field types | Text, long text, number, decimal, money (with currency), yes/no, date, date-time, choice list, email, phone, web address, link to another table, file |
| Names | Lowercase letters, digits and underscores; HireBuddha suggests names from the label |
| Safe by default | Adding is easy; renaming keeps the old name working for a while; deleting means **archiving** (hidden at once, removed after 90 days only by a separate approved step); risky type changes are done as "add new field → copy data → switch" |
| Approval | Additions by Owner/Admin: apply after preview. Changes proposed by an agent: need a person's approval unless the owner turned on "auto-approve simple additions by agents". Removing or narrowing: always a person |
| Conflicts | If two people edit the same record, the second save is refused with "this record changed — reload" |
| Sensitive fields | Fields marked personal (e.g. phone) are not copied into automation signals |
| Exports | The owner can export the whole database (E36-S06) |

### 4.5 Acceptance

E36-S01 typed tables with links and versioned changes · E06-S04 extend the schema with validation, versioning, impact and permissions · E36-S02 safe Data API for every caller · E36-S05 isolation proven · E36-S08 database created, backed up, restored and upgraded automatically · E36-S09 move to a dedicated server.

---

## 5. Data API and keys (E36-S02, E36-S07)

Every business has an **API** for its records. HireBuddha's agents, the business's apps and (if allowed) outside systems use it; nobody gets direct database access.

### 5.1 API keys screen

```
┌─ API keys ───────────────────────────────────────────────────────────────┐
│ Name               Used by          Can do                     Last used │
│ CRM app            App: CRM         Contacts: read/write       2 min ago │
│ Website form       App: Website     Contacts: create only      1 h ago   │
│ Zapier             Outside system   Orders: read               yesterday │
│                                         [+ New key] [Rotate] [Revoke]    │
│ Public access: Off  [change]   API docs: [open]                          │
└──────────────────────────────────────────────────────────────────────────┘
```

* A key is shown **once** at creation.
* Keys are limited to chosen tables and actions; rotation keeps the old key working for 24 hours.
* **Public access** (for website forms) is off by default and rate-limited when on.
* **API docs** are generated automatically and always match the current tables.

---

## 6. Connections (E09-F04, D40)

### 6.1 What changes

The business connects **its own** accounts — Facebook Pages, Instagram, WhatsApp Business, LinkedIn page, Google Drive/Gmail, Outlook, mailboxes, GitHub, CRM, and more — with a **Connect** button. No one pastes tokens or creates developer apps any more. AI-model keys, telephony provider settings, web search, payments (Razorpay) and similar **system integrations** are managed only by HireBuddha staff.

### 6.2 Connections screen

```
┌─ Connections ───────────────────────────────────────────────────────────┐
│ Search apps...                   [All] [Social] [Messaging] [Dev] [Docs] │
│                                                                          │
│ CONNECTED                                                                │
│  Facebook   Acme Store page    ● Healthy            3 agents   [Manage]  │
│  WhatsApp   +91 98xxx xxx10    ● Healthy            2 agents   [Manage]  │
│  LinkedIn   Acme Pvt Ltd       ▲ Expires in 5 days            [Reconnect]│
│                                                                          │
│ AVAILABLE                                                                │
│  [Instagram  Connect]  [GitHub  Connect]  [Google Drive  Connect]  ...   │
│  [X  Preview]  [TikTok  Coming soon]                                     │
└──────────────────────────────────────────────────────────────────────────┘
```

Connector badges: **Connect** (available), **Preview** (works, limited support), **Coming soon** (not yet approved by the platform). Only approved connectors can be connected (E09-S11).

### 6.3 Connect flow

```
Owner clicks "Connect Facebook"
   ▼
Facebook window: log in → "Allow HireBuddha to manage your Page?" → Allow
   ▼
Back in HireBuddha: choose Pages  (✓ Acme Store   ✗ Acme Jobs)
   ▼
Choose who may use it: all agents / only "Community Manager" / these apps
   ▼
Test passes → connected
   ▼
New comments and messages now arrive as events (usable in triggers)
```

Variants: **GitHub** installs the HireBuddha GitHub App on chosen repositories; **WhatsApp** uses Meta's sign-up window to pick the business number; **mailboxes** use the existing email wizard; **API-key services** show a short form.

### 6.4 Manage connection (screen)

Shows: account, permissions granted, health and last check, token expiry, last used, **who may use it** (editable), **what depends on it** (agents, apps, triggers), activity log (connected, refreshed, used by which run), **Test**, **Reconnect**, **Disconnect**. Disconnect first lists what will stop ("2 triggers will pause; 1 app loses Instagram posting") and asks to confirm.

### 6.5 Rules

| Rule | Detail |
|------|--------|
| Secrets | Stored only in the business's own database, encrypted with the business's own key; never shown again, never in AI prompts, logs or traces |
| Use | An agent or app can use a connection only if granted; every use is logged |
| Expiry | HireBuddha refreshes before expiry; 7 days before an unavoidable expiry the owner is warned; on failure triggers using it pause and the control room shows **Reconnect** |
| One business per account | The same Facebook Page cannot be connected to two HireBuddha businesses; the second attempt gets a neutral message and support can resolve it |
| Leaving | When a business leaves, its key is destroyed so stored tokens become unreadable |
| Existing connections | Moved automatically; any that relied on the business's own developer app ask for a one-time **Reconnect** |
| Pragya | Pragya can offer the same step: "This needs Instagram — [Connect]" |

### 6.6 System integrations (platform admin)

The current **Integrations** page becomes **System integrations**, visible only to HireBuddha staff: AI models and prices, telephony providers, web search and scraping, Razorpay, SMTP, and HireBuddha's own app registrations with Meta, LinkedIn, Google, X and GitHub. A **Connector approvals** view shows each platform's review status, expiry and limits.

### 6.7 Acceptance

E09-S07 Connections screen and connect flow · E09-S08 safe storage and use · E09-S09 registry holds system integrations only · E09-S10 webhooks reach the right business · E09-S11 platform approvals before offering connectors.

---

## 7. Code, GitHub and apps (E37)

### 7.1 Two kinds of code

| | **Scratch** | **Company asset** |
|--|-------------|-------------------|
| Examples | One-off data clean-up, a quick chart, an experiment | Website, CRM, mobile app backend, a reusable tool |
| Where it runs | A locked sandbox | Its own always-on (or sleep-when-idle) app container |
| Kept | 7 days (default), then deleted | In Git (your GitHub or built-in), with full history |
| Can use | Files handed to it, read-only data for 15 minutes | Its own API key for its declared tables, declared outside services |
| Checked | No review needed | Tests, security scan and a person's approval |

**Promote to company asset** turns scratch code into an asset: HireBuddha opens a pull request, runs the checks, and a Reviewer approves (merges).

### 7.2 Asking for an app

```
Owner (in Pragya): "Build me a simple CRM for my 5 sales people"
   ▼
Pragya + the architect agent draft a blueprint: screens, tables, users and roles, rules
   ▼
Owner edits and approves the blueprint (E39)
   ▼
Coding agent builds it in the sandbox and tests it
   ▼
Pull request in your GitHub (or built-in Git) with check results
   ▼
Reviewer approves
   ▼
Preview link to try it  →  Owner clicks "Publish"  →  live at crm-acme.apps.hirebuddha.com
                                                     (and crm.acme.com if added)
```

### 7.3 App detail (screen)

```
┌─ CRM ─────────────────────────────── ● Live  v14 (a1b2c3d)  [Open] [Roll back] ┐
│ [Overview] [Code & reviews] [Builds] [Preview & publish] [Domains]              │
│ [Users & roles] [Logs & metrics] [Settings]                                     │
│                                                                                 │
│ Overview   Requests today 1 240 · errors 0.1% · avg 180 ms                      │
│            Uses: Contacts (read/write), Activities (create)                     │
│            Hosting this month: ₹ 412                                            │
│ Pending    PR #7 "Add follow-up date" — checks passed — awaiting review [Open]  │
└─────────────────────────────────────────────────────────────────────────────────┘
```

| Tab | What the owner can do |
|-----|-----------------------|
| Code & reviews | See the repository, open pull requests, check results; approve (if allowed) |
| Builds | See each build: commit, result, scan summary |
| Preview & publish | Open preview links (expire after 7 days); Publish / Unpublish |
| Domains | Add `crm.acme.com`: HireBuddha shows the two DNS records to add, checks them, and sets up HTTPS automatically |
| Users & roles | Invite app users, assign roles (e.g. *Sales*: only own contacts; *Manager*: all) |
| Logs & metrics | Last 24 hours of logs, requests, errors, response time |
| Settings | Always on / sleep when idle, size limits, outside services the app may call |

### 7.4 GitHub

* **Connect GitHub** (Connections or Apps) installs the HireBuddha GitHub App on repositories the owner chooses.
* Every change an agent makes arrives as a **branch and pull request**; nothing is pushed straight to the main branch.
* Without GitHub, apps use **built-in Git**; GitHub can be connected later and the full history is copied over.
* GitHub events (pull request merged, issue opened) can start triggers ("issue opened → coding agent").

### 7.5 Templates in Phase 14

Static website · website with forms (form posts go into a table) · mobile app backend · mobile app · CRM / admin tool — all on one technology set (decision D48): **React** (TypeScript) for frontends and websites, **Python FastAPI** for backends, **React Native (Expo)** for mobile apps. App-store submission is not part of Phase 14.

### 7.6 Rules

| Rule | Detail |
|------|--------|
| Approval before going live | Code becomes an asset only after a person approves; an app is published only by Owner/Admin |
| Rollback | One click returns to the previous version; records are not touched |
| App users | Separate from HireBuddha users; each sees only what their role allows |
| Limits | CPU, memory and traffic limits per plan; apps cannot call the internet except declared services |
| Cost | Hosting and database cost appear in the wallet and usage reports |
| Safety | Scratch code cannot reach the database, secrets or other apps; nothing from scratch runs inside a live app |

### 7.7 Acceptance

E37-S01 code runs isolated · E37-S07 GitHub · E37-S08 scratch vs asset · E37-S09 publish to URL/domain with rollback · E37-S10 websites, mobile backends, internal tools with their own users · E37-S11 operate apps.

---

## 8. Tenant settings (new items)

| Setting | Values | Effect |
|---------|--------|--------|
| Business time zone | Any IANA zone (default Asia/Kolkata) | Schedules, reports, "today" for agents |
| Automation | Running / Paused | Kill switch (§3.5) |
| Auto-approve simple data additions by agents | Off (default) / On | §4.4 |
| Scratch retention | 1–30 days (default 7) | §7.1 |
| Public API access | Off (default) / On | §5.1 |

---

## 9. Platform admin (HireBuddha staff)

| Screen | Purpose |
|--------|---------|
| System integrations | Today's Integrations page, admin-only (§6.6) |
| Connector approvals | Platform review status per connector; switch Available / Preview / Unavailable |
| Tenants | Directory: database server, size, schema versions, health, automation state; **Move to dedicated server** with a preview of downtime; provisioning log; retry a failed setup |
| Unrouted events | Webhooks for accounts no business has connected (kept 7 days) |
| Migration status | During the Azure move: per-tenant migration result, counts and checksums |

---

## 10. The move to Azure: what customers notice (E41)

| When | What customers see |
|------|--------------------|
| 1 week before | Email and in-app banner announcing a maintenance window (date, time, expected duration) |
| During the window | A maintenance page; scheduled work and campaigns are paused; incoming webhooks are retried by providers |
| After | Everything works at the same web addresses; schedules resume (missed times follow each trigger's "missed times" rule); a short "we've moved" note |
| If something went wrong before reopening | The maintenance page is removed and the old system continues; nothing is lost |

Nothing changes for phone numbers, webhook addresses or login. Partners that allow-list HireBuddha's servers receive the new address in advance.

---

## 11. Out of scope for Phase 14

* Building and publishing native mobile apps to app stores.
* Per-tenant agent workers (agents run on shared, isolated workers).
* Remodelling campaigns, leads and calls into the new standard business tables (E13–E18); they move as they are.
* Full business modules (accounting, HR, inventory) — E19–E30.
* The new Generative UI frontend (E33) and Pragya itself (E10, E39, D41). Phase 14 screens are transitional; the Generative UI and Pragya reuse the same APIs and screen components.
* Optional Graph/Loop hierarchy (E40).

---

## 12. Non-functional expectations

| Area | Expectation |
|------|-------------|
| Reliability | No accepted event is lost; no trigger fires twice for the same event; work survives restarts |
| Timeliness | Schedules fire within a minute of their time under normal load (target confirmed in O06) |
| Isolation | One business can never see or change another's data, files, connections or apps (tested every release) |
| Recovery | Each business's database can be restored to a point in time; full export available |
| Privacy | Personal fields stay out of automation signals and logs; secrets never appear in prompts or logs |
| Cost control | No automated run without a funded reservation; per-business limits on runs and schedules |

Exact numeric targets (recovery times, retention) are product decisions O06.

---

## 13. Glossary

| Term | Meaning |
|------|---------|
| Event | Something that happened (a comment, a paid order, a scheduled time) |
| Trigger | A rule that starts an agent when an event matches |
| Control room | The screen that shows all automatic work and what needs attention |
| Wait | A paused run waiting for an event or a deadline |
| Data API | The only door to a business's records, for agents, apps and outside systems |
| Blueprint | The versioned description of a business's tables and fields |
| Connection | A business's link to one outside account (a Facebook Page, a GitHub org) |
| System integration | A service HireBuddha itself uses for everyone (AI models, telephony, payments) |
| Scratch code | Temporary code in a locked sandbox |
| Company asset | Reviewed code kept in Git and deployed as an app or tool |
| Preview | A private test link to a new app version |
| Tenant | One business (company) on HireBuddha |

---

## 14. Traceability

| Section | Roadmap stories | Decisions |
|---------|-----------------|-----------|
| §3 Automation | E07-S01 … E07-S06 | D03, D06, D12 |
| §4 Records and structure | E06-S04, E36-S01, E36-S05, E36-S06, E36-S08, E36-S09 | D09, D25, D38 |
| §5 Data API and keys | E36-S02, E36-S07 | D37 |
| §6 Connections | E09-S07 … E09-S11 | D40 |
| §7 Code, GitHub, apps | E37-S01, E37-S07 … E37-S11 | D34, D35, D36 |
| §9 Platform admin | E09-S09, E09-S11, E36-S08, E36-S09 | D38, D40 |
| §10 Azure move | E41-S01 … E41-S06 | D39 |
