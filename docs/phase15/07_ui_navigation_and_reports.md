# 07 — UI remodel: workspaces, navigation, pages, reports and analytics

> **Implements:** REQ-UI-1 and the user-facing side of every requirement in [05](05_requirements_decisions_and_conflicts.md), on top of [06](06_technical_design.md).
> **Today's UI (studied):** one sidebar for every role (`frontend/src/components/layout/MainLayout.tsx`, 7 groups and ~45 links) with ad-hoc role checks per link; role dashboards under `pages/dashboards/*`; per-role report pages (`pages/reports/*Reports.tsx`) with placeholder tabs; finance screens split across "Finance & Administration" and "Agent Kernel"; engineering screens (Feature Flags, Cost Attribution, Risk & Exit, Meta-Agent) shown to tenant and partner admins; an acting-company switcher for partners and staff.

---

## 1. Problems with the current UI

| # | Problem | Example |
|---|---|---|
| U-1 | One menu for six roles; links appear that the user cannot use or should not see | Tenant users see Records, Apps, Code, Integrations, Wallet, Business Settings, Automation Settings; tenant admins see Agent Kernel → Feature Flags, Cost Attribution, Risk & Exit |
| U-2 | Engineering vocabulary in customer screens | "Entity Library", "Guardian Oversight", "Streaming Sessions", "Memory Trees", "Agent Kernel" |
| U-3 | Money scattered and in USD with base cost | Wallet in Finance, cost in Agent Kernel, reports elsewhere; `$` everywhere; raw provider cost on run pages |
| U-4 | Partners have three overlapping screens, one broken | "Partner Dashboard", "Portfolio Analytics", "Tenant Support"; the partner admin dashboard fails on a 403 |
| U-5 | Reports are tabs on role pages, many placeholders, no filters/exports/drill-down | "Subscription Matrix", "Upsell Opportunities", "Channel" tabs are empty states |
| U-6 | No company-level 360° view for staff; "Platform Hub" mixes partners, tenants and users in one list | `PlatformManagement.tsx` tabs ALL / PARTNERS / TENANTS / USERS |
| U-7 | No place for plans, currencies, FX, daily credits, invoices, partner programme | — |
| U-8 | The brand design system (`buddha-cognitive-lab-design-system`) is used by the mobile app but not by the web app | Glass components and ad-hoc CSS per page |

---

## 2. Principles

1. **Three workspaces, one app.** *Platform Console* (staff: `app_admin`, `app_user`), *Partner Portal* (`partner_admin`, `partner_user`, Silver/Gold variants), *Business Workspace* (`tenant_admin`, `tenant_user`). Each has its own home, menu and vocabulary; the shell (top bar, notifications, profile) is shared.
2. **Menus are generated, not hand-filtered.** One navigation config declares each item's roles, partner type, required entitlement and required permission; `MainLayout` renders what applies. A test renders the menu for each role and snapshots it.
3. **Task language for customers.** Agents are "AI employees" (brand: *your Buddhas*), runs are "Work history", approvals are "Approvals", calls are "Calls". Engineering screens live only in the Platform Console.
4. **Money is always in the viewer's currency.** Customers see billed amounts in their billing currency (₹ for India); staff see the display currency (₹ by default) with USD on hover; cost appears **only** in the Platform Console, labelled "Cost".
5. **Plans gate features visibly.** A feature outside the company's plan shows as locked with "Available on Growth and above" — never a 403.
6. **Every report is a page with the same frame**: title, period picker, filters, KPI tiles, chart, table, drill-down, export (CSV/XLSX/PDF), "as of" time, and the currency.
7. **Acting is explicit.** When staff or a Gold partner works inside a tenant, a persistent banner names the tenant, the grant scope and expiry, and every page is the tenant's view (billed only for partners).
8. **One design system.** Adopt the brand tokens (`colors_and_type.css`, gold accent, warm ink surfaces, Chakra Petch for eyebrows) and its components (buttons, inputs, badges, cards, agent row) for the web app; retire per-page glass styles progressively.

---

## 3. The shell

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│ [B] Hire Buddha   Workspace ▾        ⌕ Search        ₹ 12,450 ●  🔔 3   👤 ▾ │
│                                                     balance chip   notif   │
├────────────┬─────────────────────────────────────────────────────────────────┤
│ Menu       │ [Acting banner: Working in Acme Pvt Ltd · support access ·      │
│ (per role) │  expires 18:00 · Exit]                                          │
│            │ [Balance banner: Your balance is negative (−₹420). Agents and   │
│            │  apps are paused. Recharge]                                      │
│            │  Page                                                           │
└────────────┴─────────────────────────────────────────────────────────────────┘
```

| Element | Who | Behaviour |
|---|---|---|
| Workspace switcher | staff, Gold partners | Own console ↔ a tenant they may act in (grant-checked); Silver never sees it |
| Balance chip | tenant admin/user | Available balance in billing currency; colour by state (ok / low / negative); click → Billing |
| Balance banner | tenant roles | `in_debt` / `over_tolerance` / `suspended` messages with a Recharge action (06 §6.3) |
| Locked banner | tenant roles | "Your plan is managed by <partner>" when a plan/spend-cap lock exists |
| Search | all | Agents, runs, companies (staff), tenants (partner) |
| Notifications | all | 06 §14 |

---

## 4. Navigation by role

Legend: 🔒 = shown locked when the plan lacks the entitlement · (G) = Gold only · (S) = Silver only.

### 4.1 Platform Console — `app_admin`

| Group | Item | Route | Contents |
|---|---|---|---|
| **Home** | Platform overview | `/console` | §8.1 dashboard |
| **Customers** | Companies | `/console/companies` | Directory of tenants and partners: type, country, currency, plan, partner, balance (display ccy), state, MTD billed; filters; tree view toggle |
| | Company 360 | `/console/companies/:id` | Tabs: Overview · Billing (wallet lots, entries, debt, invoices, plan, locks, daily-credit policy in effect, adjust) · Usage (billed **and cost**, by category) · Users · Agents & runs · Calls & numbers · Apps & hosting · Partner (assignment history) · Entitlements · Audit |
| | Users | `/console/users` | All users; role; company; last active; deactivate; reset sessions |
| | Workspaces | `/console/workspaces` | (today `/admin/tenants`) tenant databases, servers, provisioning |
| **Partners** | Partner network | `/console/partners` | Partners list + tree (type, status, depth, tenants, sourced revenue, fee status) |
| | Applications | `/console/partners/applications` | Underwriting queue (KYC, checks, approve with type) |
| | Partner 360 | `/console/partners/:id` | Profile, agreement, annual fee, tenants, network, ledger, statements, access grants, audit |
| | Leads | `/console/leads` | Silver-registered leads queue for BCL sales: assign owner, status, convert → create tenant with attribution |
| | Programme rules | `/console/partners/rules` | Partner types, annual fees, commission rules (levels, caps, months), fee rules (ranges, splits), holdback, payout minimum, TDS, max depth, simulation |
| **Commercial** | Plans & entitlements | `/console/plans` | Plans (price USD with ₹ preview, bonus %, tolerance, limits) and the **entitlement matrix** (features × plans) |
| | Pricing | `/console/pricing` | Billing formula (platform / plan / company versions); **price items editor** — per-number rent (USD amount and ₹ override, both editable, O-2), partner annual fees — with version history and the resulting price per currency; SKU rates link |
| | Daily credits | `/console/daily-credits` | Policies (direct / per partner / all partners), bands editor with day ranges and a preview ("a tenant signed up today receives …"), company overrides |
| | Currency & FX | `/console/currency` | Display currency, default currency, currencies, **FX rates with history** (add rate, reason), country profiles |
| | Wallet & admission | `/console/wallet-policy` | Top-up validity days, min/max/presets, admission minimums per level, call hold, negative-balance grace and suspension days, number hold days |
| | Tax & invoicing | `/console/tax` | Legal entity, GSTIN, state, SAC, GST rate, LUT, invoice series |
| **Finance** | Revenue & margin | `/console/finance/revenue` | Report R-A02 |
| | Receivables | `/console/finance/receivables` | Negative balances with ageing; blocked/suspended companies; actions |
| | Payments & invoices | `/console/finance/payments` | All payments, invoices, credit notes, refunds |
| | Partner payouts | `/console/finance/payouts` | Statements to approve, export, mark paid; disputes |
| | Wallet liability | `/console/finance/liability` | Prepaid balances by expiry; breakage |
| **Operations** | Runs | `/console/ops/runs` | Cross-company run monitor (status, billed, cost) |
| | Approvals oversight | `/console/ops/approvals` | Global HITL queue |
| | Calls & campaigns | `/console/ops/calls` | Live calls, campaigns, refusals by reason |
| | Phone number pool | `/console/ops/numbers` | Pool, claims, rentals (status, next charge), provider cost |
| | Apps & hosting | `/console/ops/apps` | All hosted apps, stopped-for-balance list, resource use |
| | Automation | `/console/ops/automation` | Platform limits, paused businesses |
| | Health & incidents | `/console/ops/health` | Workers, queues, settlement backlog, unpriced usage, unit mismatches |
| **AI platform** | Models & SKUs | `/console/ai/skus` | System integrations with **unit dropdown** (CostUnit), rates in USD, ₹ preview |
| | Model routing | `/console/ai/routing` | Task defaults and fallbacks |
| | Tools | `/console/ai/tools` | Tool registry, prices/free reasons |
| | Templates | `/console/ai/templates` | Curate the marketplace |
| | Connectors | `/console/ai/connectors` | Connector approvals |
| | Agent kernel | `/console/ai/kernel/*` | KPI, Meta-Agent, Cost attribution (cost), **Feature flags (staff only)**, Risk & exit |
| **Reports** | Report library | `/console/reports` | §7.1 catalogue |
| **Settings** | Platform settings | `/console/settings` | Settings catalogue (06 §8.4) with scope, inherited value, history |
| | Audit log | `/console/audit` | Every money/config change, every acting session |

### 4.2 Platform Console — `app_user` (staff: support, sales, operations, finance)

Staff users share the console with **permissions** instead of new roles: `users.staff_functions` ⊆ {`support`, `sales`, `finance`, `ops`}.

| Function | Sees |
|---|---|
| support | Home, Companies (read), Company 360 (no Billing adjust), act-as with audit, Operations, Reports (ops) |
| sales | Home, Leads (own queue), Companies (read), Partner network (read), Reports (pipeline, conversion) |
| finance | Finance group, Company 360 Billing (adjust with reason), Reports (finance) |
| ops | Operations, AI platform (read), Health |

No `app_user` edits pricing, FX, plans, daily credits, programme rules or flags (app_admin only).

### 4.3 Partner Portal — `partner_admin`

| Group | Item | Route | Gold | Silver | Contents |
|---|---|---|---|---|---|
| **Home** | Overview | `/partner` | ✓ | ✓ | §8.3 dashboard |
| **Customers** | My tenants | `/partner/tenants` | ✓ | — | Tenants: plan, state, balance runway, MTD **billed**, health, lock icons; create tenant; open (act-as with grant) |
| | Tenant view | `/partner/tenants/:id` | ✓ | — | Overview, billed usage, plan & locks (change plan, lock), spend cap, charges, access grant, users |
| | Referred customers | `/partner/customers` | — | ✓ | Converted referrals: status, plan, MTD billed, lifetime commission earned (commission has no end date, O-8) — **no data access** |
| | Leads | `/partner/leads` | ✓ | ✓ | Register a lead; status (registered → accepted → in progress → converted / lost / expired); exclusivity end; duplicate warnings. Gold may convert its own leads |
| | Setup & customisation fees | `/partner/charges` | ✓ | — | Raise a charge for a tenant within the allowed range (shows the split and your share); status; reminders |
| **Network** | My partners | `/partner/network` | ✓ | ✓ | Recruited partners (name, type, status, level), invite a partner (link), override earnings — **never** their tenants |
| **Earnings** | Earnings | `/partner/earnings` | ✓ | ✓ | Ledger: accrued / held / payable / paid, by source (usage, subscriptions, setup fees, overrides), clawbacks |
| | Statements & payouts | `/partner/statements` | ✓ | ✓ | Monthly statements (PDF), TDS, payout status, upload GST invoice |
| **Partnership** | Partnership | `/partner/partnership` | ✓ | ✓ | Type, agreement (rates snapshot), annual fee (pay / invoice / renewal date), KYC and bank status, probation |
| | Programme guide | `/partner/guide` | ✓ | ✓ | Rules, fee ranges, commission rates, FAQs |
| **Reports** | Reports | `/partner/reports` | ✓ | ✓ (subset) | §7.2 catalogue |
| **Team** | Team | `/partner/team` | ✓ | ✓ | Partner company users, roles |
| | Access grants | `/partner/access` | ✓ | — | Active grants per tenant, expiry, scopes, request/renew |

**Partner's own workspace.** A partner company is not a tenant: it has no AI workspace or wallet usage of its own. A Gold partner may get a **demo tenant** created by staff (a normal tenant attributed to the partner, with a demo daily-credit policy) for presales.

### 4.4 Partner Portal — `partner_user`

Gold: Home, My tenants (read), Tenant view (read + support scope through grants), Leads, Reports (tenant health, leads). Silver: Home, Leads, Referred customers, Reports (leads). No earnings, statements, partnership, team, charges.

### 4.5 Business Workspace — `tenant_admin`

| Group | Item | Route | Entitlement | Contents |
|---|---|---|---|---|
| **Home** | Overview | `/home` | — | §8.4 dashboard |
| **AI employees** | Employees | `/agents` | `agents.builder` | Library (today Entity Library), create, versions |
| | Templates | `/agents/templates` | `agents.templates` 🔒 | Marketplace |
| | Knowledge | `/knowledge` | `knowledge.base` 🔒 | Documents; memory explorer as a tab (`knowledge.cortex_explorer`) |
| **Work** | Work history | `/work` | — | Runs (today Executions), billed per run |
| | Approvals | `/approvals` | `agents.hitl` | HITL queue |
| | Automation | `/automation` | `automation.*` 🔒 | Control room, schedules, triggers |
| **Customers & calls** | Campaigns | `/calls/campaigns` | `voice.outbound_campaigns` 🔒 | |
| | Calls | `/calls` | `voice.*` 🔒 | Call log (today Streaming Sessions), recordings, billed per call (per second) |
| | Phone numbers | `/calls/numbers` | `phone_numbers` 🔒 | Claim (shows the current monthly rent in the company's currency — ₹2,000 by default, set by the admin), release, assign agent, rental status and next charge date |
| | Mobile dialer | `/calls/dialer` | `voice.mobile_dialer` 🔒 | Reps, devices, analytics |
| **Data & apps** | Records | `/records` | `records` 🔒 | Records, schema, data keys |
| | Apps | `/apps` | `apps.hosting` 🔒 | Apps, previews, domains; "stopped for balance" state |
| | Code | `/code` | `code.lanes` 🔒 | |
| | Connections | `/connections` | `connections.*` | Connected accounts |
| | Files | `/files` | — | Artifacts |
| **Billing** | Wallet | `/billing` | — | §5.1 |
| | Plan | `/billing/plan` | — | Current plan, compare, change (unless locked), cancel |
| | Usage & charges | `/billing/usage` | — | Billed by category, agent, user, channel, day (R-T02) |
| | Invoices | `/billing/invoices` | — | GST invoices, credit notes, billing profile (GSTIN, address) |
| | Spend controls | `/billing/controls` | — | Spend cap (lock shown), low-balance alerts |
| **Reports** | Reports | `/reports` | `reports.advanced` for some | §7.3 catalogue |
| **Settings** | Business profile | `/settings` | — | Name, country (read-only after money moved), currency (read-only), time zone |
| | Team | `/settings/team` | — | Users and roles |
| | Automation & data | `/settings/automation` | — | Limits, records settings |
| | Partner access | `/settings/partner-access` | — | Partner, grants, history, revoke |
| | Notifications | `/settings/notifications` | — | Preferences |

### 4.6 Business Workspace — `tenant_user`

Home (my work), AI employees (run only; no edit unless the admin allows), Work history (mine), Approvals (assigned to me), Calls & Campaigns (assigned), Knowledge (read), Files, My reports. **No** Billing (only the balance chip), Settings, Records schema, Apps, Code, Connections admin.

---

## 5. Key pages (functional specification)

### 5.1 Tenant · Wallet (`/billing`)

| Section | Content |
|---|---|
| Balance card | Available ₹ (sum of lots), free (minus running holds), debt (if any, red), state badge, runway ("≈ 9 days at the last 7 days' spend") |
| Recharge | Presets (₹1,000 / ₹2,500 / ₹5,000 / ₹10,000 from settings), custom amount within min/max, GST shown (₹1,000 + ₹180 GST = ₹1,180), "your debt of ₹420 is settled first", Razorpay checkout |
| Credit lots | Table: kind (Daily / Plan credit / Plan bonus / Recharge / Grant), granted, expires, original, remaining; "₹3,200 expires in 6 days" warning |
| Daily credits | Today's daily credit, days left in the free period ("day 12 of 30") — read-only |
| Activity | Wallet entries: recharges, plan credits, deductions (grouped per day and category), expiries, debt repayments |

### 5.2 Tenant · Usage & charges (`/billing/usage`)

Period picker (month default), KPI tiles (billed this period, vs last period, top category, top agent), stacked bar by day × category (AI models, Knowledge, Tools, Media, Voice, Video, Sandbox, Hosting, Database, Phone numbers), tables by agent / user / channel / campaign with drill-down to runs and calls; per-second call charges shown as duration × rate. Export CSV/XLSX/PDF (statement).

### 5.3 Tenant · Plan (`/billing/plan`)

Current plan card (price ₹/month incl. note on GST, bonus %, renewal date, credits this cycle), comparison table of active plans with entitlements (✓ / 🔒) and limits, change/cancel buttons (disabled with "Managed by <partner>" when locked).

### 5.4 Console · Plans & entitlements (`/console/plans`)

Left: plans list (drag to order; archive). Right: editor — name, monthly price USD (₹ at today's rate and optional ₹ override), bonus %, negative tolerance, limits (users, agents, live sessions, runs/min, apps, numbers, sandbox size, storage). Below: **entitlement matrix** (rows = features grouped as in 06 §10.2, columns = plans, toggles), "impact" panel ("12 companies on Growth would lose Video calls").

### 5.5 Console · Daily credits (`/console/daily-credits`)

Policies table (audience, partner, duration, bands, active, companies affected). Editor: audience picker (Direct tenants / A partner / All partners), duration select (10, 15, 30, 60, 90, 180, 365), bands editor (from day – to day – amount USD with ₹ preview; validation: contiguous, within duration), effective from. Preview: timeline chart of daily amount by day. Company overrides tab (none / custom / back to policy).

### 5.6 Console · Currency & FX (`/console/currency`)

Display and default currency selects; currencies table (code, symbol, minor units, active); **FX rates**: current rate per currency (INR 100.00 per USD), "Add rate" (value, effective from, reason, impact preview: "a $20 number rent becomes ₹2,000 → INR override keeps ₹2,000"), history chart and table (who, when, why); country profiles table (country → currency, time zone, phone code, tax regime, calling rules).

### 5.7 Console · Company 360 → Billing tab

Wallet card (as tenant sees it) + **cost and margin** for the period; lots and entries; debt and state with actions (adjust with reason, grant credits, extend grace); plan and locks (lock/unlock); daily-credit policy in effect and override; invoices and payments; partner assignment history.

### 5.8 Partner · Overview (`/partner`)

Gold: tiles — tenants (active/at risk), tenants' MTD billed, my MTD earnings (accrued/payable), next payout, annual fee status; charts — tenants' billed trend, earnings trend by source; lists — at-risk tenants (negative balance, runway < 3 days, failing runs), open charges, leads needing action. Silver: tiles — leads (open, converted this quarter), referred customers, earnings; lists — leads by status.

### 5.9 Partner · Earnings (`/partner/earnings`)

Filters (period, source, tenant, level, status). Table of ledger entries: date, tenant (or sub-partner for overrides), source event (top-up / subscription / setup fee), base, rate, amount, status (accrued → payable after holdback → paid), clawbacks in red. Totals by status. Explanation drawer per entry ("20 % of ₹1,00,000 top-up by Acme on 12 Nov; payable from 12 Dec").

### 5.10 Console · Programme rules (`/console/partners/rules`)

Tabs: Types (Silver/Gold capabilities), Annual fees (price items), Commission rules (per type × revenue kind × level: rate, cap, months), Fee rules (setup/customisation: min, max, split with a 100 % check), Payout policy (holdback, probation, minimum, TDS, payout day), Network (max depth, override activity minimum, override months). **Simulator**: enter a sample chain and revenue → payouts per level, platform share, cap/margin guard effects. Changes create new versions; agreements keep their snapshot.

---

## 6. Role × capability matrix (summary)

| Capability | app_admin | app_user | partner_admin G | partner_admin S | partner_user | tenant_admin | tenant_user |
|---|---|---|---|---|---|---|---|
| See provider cost | ✓ | ✓ (finance/ops) | — | — | — | — | — |
| See billed amounts | all | all | own tenants | referred (summary) | own tenants (G, read) | own | balance only |
| Set FX, currency, prices, formula | ✓ | — | — | — | — | — | — |
| Daily-credit policies | ✓ | — | — | — | — | — | — |
| Plans & entitlements (define) | ✓ | — | — | — | — | — | — |
| Choose/change tenant plan | ✓ | — | ✓ (own tenants, lock) | — | — | ✓ (unless locked) | — |
| Spend cap | ✓ | — | ✓ (lock) | — | — | ✓ (unless locked) | — |
| Recharge wallet | ✓ (grant) | finance (grant) | — | — | — | ✓ | — |
| Feature flags | ✓ | — | — | — | — | — | — |
| Create tenants | ✓ | sales (from leads) | ✓ | — | — | — | — |
| Register leads | — | — | ✓ | ✓ | ✓ | — | — |
| Raise setup/customisation fees | ✓ | — | ✓ | — | — | pays | — |
| Recruit partners | ✓ | — | ✓ (invite) | ✓ (invite) | — | — | — |
| Approve partners | ✓ | — | — | — | — | — | — |
| Earnings & statements | all | finance | own | own | — | — | — |
| Act inside a tenant | ✓ (audited) | support (audited) | grant | — | grant (read/support) | — | — |

---

## 7. Reports and analytics catalogue

Every report: period, filters, export, drill-down, currency label. "Src" = main source table/view.

### 7.1 Platform Console reports

| ID | Report | Audience | Key measures | Dimensions / filters | Visual | Src |
|---|---|---|---|---|---|---|
| R-A01 | Platform overview | admin, staff | Billed revenue, cash collected, gross margin %, MRR, ARR, active companies, partner-sourced share, daily-credit cost | period | KPI tiles, trend | billing_lines, payments, subscriptions |
| R-A02 | Revenue & margin | admin, finance | Billed, cost, margin, margin % | month, category, company, plan, partner, country, currency | stacked bars, table | billing_lines |
| R-A03 | Cost of goods & provider reconciliation | admin, finance | Cost by SKU/provider, per-second vs provider increment gap (K-2), variance to provider invoices | SKU, provider, month | table, waterfall | usage_logs, registry |
| R-A04 | Subscriptions & MRR | admin, finance | New, expansion, contraction, churned MRR, net MRR, plan mix, cohort retention | month, plan, partner | MRR waterfall, cohort grid | subscriptions, payments |
| R-A05 | Wallet liability & breakage | admin, finance | Prepaid balance by kind and expiry bucket (0–7, 8–30, 31–90 days), expired value (breakage) | currency, kind | stacked bars | wallet_lots, entries |
| R-A06 | Receivables & negative balances | admin, finance | Debt by company, ageing (0–7, 8–30, 30+), state counts, recovered | state, partner, plan | ageing table | credit_wallets, entries |
| R-A07 | Daily credit programme | admin | Free credit granted/consumed by policy, audience, partner; cost of free credit; trial → paid conversion | policy, partner, cohort | funnel, bars | wallet_lots (daily), payments |
| R-A08 | Acquisition funnel | admin, sales | Sign-ups → first agent → first run → first recharge → subscription; time between steps | source (direct/partner/lead), country | funnel | companies, runs, payments |
| R-A09 | Partner performance | admin, sales | Per partner: tenants, sourced billed revenue, cash, commissions, setup fees, network size, fee status | type, status, depth | ranked table, tree | partner_* , billing_lines |
| R-A10 | Commission & payout ledger | admin, finance | Accrued, held, payable, paid, clawbacks, TDS by partner and level; run-rate of open-ended referral commission (O-8) | period, partner, level, status | table | partner_ledger |
| R-A11 | Setup & customisation fees | admin, finance | Raised, paid, outstanding, split by recipient | partner type, fee kind | table | one_time_charges |
| R-A12 | Partnership fees | admin, finance | Due, paid, overdue, renewals next 30 days, lapsed | type | table | partner_profiles, payments |
| R-A13 | Lead pipeline | admin, sales | Leads by status, conversion rate, time to convert, by partner and owner | partner, owner, country | funnel, table | partner_leads |
| R-A14 | GST / tax | admin, finance | Taxable value, CGST, SGST, IGST, zero-rated by month and state, B2B vs B2C (GSTR-1 export) | month, state | table + export | invoices |
| R-A15 | FX impact | admin, finance | Revenue at locked vs current rates, rate history | currency | line | fx_rates, billing_lines |
| R-A16 | Phone numbers & rent | admin, ops | Numbers by status, utilisation (calls per number), rent billed, held numbers, provider cost | provider, company | table | number_rentals, voice_sessions |
| R-A17 | Hosting & database | admin, ops | vCPU-h, GB-h, egress, storage, DB share; cost vs billed by company; stopped-for-balance apps | company, app | table, bars | app_usage, billing_lines |
| R-A18 | Feature adoption | admin, sales | Companies using each feature, usage by channel; plan entitlement vs use (upsell) | plan, feature | heat map | billing_lines, entitlements |
| R-A19 | Execution health / LLM performance / tool efficacy | admin, ops | (existing reports, kept) | — | — | runs, logs |
| R-A20 | HITL oversight | admin, ops | (existing) | — | — | human_approvals |
| R-A21 | Billing exceptions | admin, ops | Unsettled rows by age, failed settlements, unpriced SKUs, unit mismatches, shortfalls | type | table | usage_logs |
| R-A22 | Data growth | admin, ops | (existing) | — | — | — |
| R-A23 | Commercial change audit | admin | FX, prices, plans, policies, rules changes | actor, key | timeline | audit_log |

### 7.2 Partner Portal reports

| ID | Report | Gold | Silver | Measures | Notes |
|---|---|---|---|---|---|
| R-P01 | Portfolio overview | ✓ | light | Tenants, MTD billed, plan mix, my earnings | Billed only |
| R-P02 | Tenant billed usage | ✓ | — | Billed by tenant × month × category | Drill to tenant view (grant) |
| R-P03 | Tenant health & risk | ✓ | — | One health score (usage trend, success rate, runway, state, adoption breadth) with reasons | Replaces the two scores |
| R-P04 | Referred customers | — | ✓ | Status, plan, MTD billed, commission MTD and lifetime | No data access |
| R-P05 | Earnings | ✓ | ✓ | Earnings by source, level, status | |
| R-P06 | Statements & payouts | ✓ | ✓ | Statements, TDS, paid | PDF |
| R-P07 | Network | ✓ | ✓ | Sub-partners, their status, my override earnings | Aggregates only |
| R-P08 | Leads | ✓ | ✓ | Leads by status, conversion rate, exclusivity expiring | |
| R-P09 | Charges | ✓ | — | Setup/customisation fees raised, paid, my share | |
| R-P10 | Upsell & plan matrix | ✓ | — | Tenants near plan limits, features used vs plan, upgrade candidates | Fills today's placeholder tabs |

### 7.3 Business Workspace reports

| ID | Report | Admin | User | Measures |
|---|---|---|---|---|
| R-T01 | Business overview | ✓ | — | Billed MTD vs cap, balance, runway, runs, success rate, calls, approvals pending |
| R-T02 | Usage & charges (statement) | ✓ | — | Billed by category, agent, user, channel, day; per-second call charges |
| R-T03 | Wallet activity | ✓ | — | Recharges, plan credits, daily credits, deductions, expiries, debt |
| R-T04 | Credit forecast | ✓ | — | Burn rate, days left, expiring lots, recommended recharge |
| R-T05 | AI employee performance | ✓ | own | Runs, success, billed per run, time saved, failures by reason |
| R-T06 | Campaign analytics | ✓ | assigned | Dials, connects, conversations, outcomes, billed per call / per conversion |
| R-T07 | Calls | ✓ | own | Count, duration distribution (seconds), billed, voicemail rate, refusals |
| R-T08 | Automation | ✓ | — | Triggers fired, blocked (incl. negative balance), failures, waits |
| R-T09 | Approvals | ✓ | own | Volume, approval time, rejection rate |
| R-T10 | Spend by user | ✓ | — | Billed per user (wallet is shared — REQ-WL-3) |
| R-T11 | Phone numbers | ✓ | — | Numbers, rent, calls per number |
| R-T12 | Apps & hosting | ✓ | — | Billed hosting/DB by app, uptime, stopped events |
| R-T13 | Invoices & receipts | ✓ | — | List and downloads |
| R-T14 | My work | — | ✓ | My runs, time saved, my approvals (today's "My Analytics") |

### 7.4 Report infrastructure

- **Facts:** `billing_lines` (daily × company × category × grouping), `wallet_entries`, `partner_ledger`, `payment_transactions`/`invoices`, runs/calls (tenant DBs). Nightly rollups for heavy reports extend `kpi_daily_rollup`.
- **API shape:** `GET /api/v1/reports/{id}?period=…&filters=…` → `{currency, as_of, tiles[], series[], rows[], drill}`; one renderer component (`ReportShell`) draws every report; `?format=csv|xlsx|pdf` for export.
- **Scoping:** the report router resolves the viewer's scope (staff: all or a company; partner: its tenants/referred; tenant: own) **and** applies the money view (06 §5.2) — partner and tenant reports cannot request cost columns.
- **Scheduled reports (P2):** weekly e-mail of chosen reports to subscribers.

---

## 8. Dashboards (home pages)

| Role | Tiles | Charts | Lists |
|---|---|---|---|
| **8.1 app_admin** | Billed MTD, cash MTD, margin %, MRR, active companies, companies in debt, payouts pending | Revenue vs cost (12 months), revenue by category, partner share | Billing exceptions, applications to review, top companies, FX last changed |
| **8.2 app_user** | By function: open tickets/at-risk (support), leads to work (sales), unpaid/failed payments (finance), queue health (ops) | — | Own queues |
| **8.3 partner_admin** | See §5.8 | | |
| **8.4 tenant_admin** | Balance (₹) + runway, billed MTD vs cap, active AI employees, runs today, calls today, approvals waiting | Billed by category (30 days), runs success | Low balance / expiring credits, failed runs, approvals |
| **8.5 tenant_user** | My runs, approvals for me, time saved | My activity | Recent work |

---

## 9. Current → new mapping (every existing page)

| Current route / page | New place | Action |
|---|---|---|
| `/dashboard` (role switch) | `/console`, `/partner`, `/home` | Split per workspace |
| `/platform-management` (Platform Hub) | `/console/companies`, `/console/users`, `/partner/tenants`, `/settings/team` | Split |
| `/partner` (Partner Dashboard), `/reports/analytics/partner-admin`, `/reports/analytics/partner-user` | `/partner`, `/partner/reports` | Merge; fix 403 |
| `/ai/entities` (Entity Library), `/ai/entities/create|edit` | `/agents` | Rename "AI employees" |
| `/ai/templates` | `/agents/templates`; staff curation `/console/ai/templates` | |
| `/ai/approvals` (Guardian Oversight) | `/approvals`; staff `/console/ops/approvals` | Rename |
| `/ai/executions`, `/ai/executions/:id`, `/ai/execute/:id` | `/work`, `/work/:id` | Rename; billed only |
| `/automation`, `/settings/automation` | `/automation`, `/settings/automation` | Keep |
| `/admin/automation` | `/console/ops/automation` | Move |
| `/records*`, `/apps*`, `/code`, `/connections*` | `/records*`, `/apps*`, `/code`, `/connections*` | Keep; entitlement-gated; tenant_user hidden |
| `/cortex*` (Memory Trees) | `/knowledge` tab | Merge |
| `/knowledge` | `/knowledge` | Keep |
| `/phone-numbers` | `/calls/numbers`; staff `/console/ops/numbers` | Add rent |
| `/streaming/sessions`, `/streaming/calls/:id` | `/calls`, `/calls/:id` | Rename |
| `/streaming/campaigns*` | `/calls/campaigns*` | |
| `/integrations` | staff `/console/ai/skus`; tenant → `/connections` | Split (REGISTRY_PLATFORM_ONLY) |
| `/ai-config` | `/console/ai/routing` | Move |
| `/ai/tool-registry` | `/console/ai/tools` | Move |
| `/artifacts` | `/files` | Rename |
| `/wallet` | `/billing`, `/billing/plan` | Rebuild |
| `/settings/billing` | `/console/pricing`, `/console/plans`, `/console/daily-credits`, `/console/currency`, `/console/wallet-policy` | Split and extend |
| `/reports/costing` | `/console/reports` R-A02/R-A03 | Merge |
| `/reports/analytics/app-admin`, `/app-user` | `/console/reports` | Merge into library |
| `/reports/analytics/tenant-admin`, `/tenant-user` | `/reports` | Merge into library |
| `/admin/agent-kernel/*` | `/console/ai/kernel/*` | Staff only |
| `/admin/tenants` | `/console/workspaces` | Move |
| `/admin/connectors` | `/console/ai/connectors` | Move |
| `/settings/tenant` | `/settings` | Extend (country, currency, partner access) |
| `/onboarding` | `/onboarding` | Add country & billing profile step |
| `/profile` | `/profile` | Keep |
| Old redirects (`/agents`, `/workflows`, `/executions` …) | Keep redirecting to new routes | |

---

## 10. Frontend architecture changes

| Change | Files |
|---|---|
| Navigation config (`nav/config.ts`: id, label, route, icon, roles, partnerTypes, staffFunctions, entitlement) + renderer; per-role snapshot tests | `components/layout/MainLayout.tsx` (rewrite), `nav/*` (new) |
| Route guard by role, partner type, entitlement (locked page instead of 403) | `router/index.tsx`, `ProtectedRoute` |
| Workspace layouts: `ConsoleLayout`, `PartnerLayout`, `BusinessLayout` sharing `AppShell` | `components/layout/*` |
| Money: `formatMoney`, `<Money>`, `<DualMoney>` (staff), currency from `/me` | `utils/money.ts`, `components/money/*` |
| Entitlements hook `useEntitlement(key)` from `/me/entitlements` | `hooks/useEntitlement.ts` |
| Balance chip and state banners | `components/billing/*` |
| Report framework: `ReportShell`, `KpiTile`, `TrendChart`, `DataTable` with export, `PeriodPicker`, `FilterBar`; report registry per workspace | `components/reports/*`, `pages/*/reports/*` |
| Design-system adoption: tokens, buttons, inputs, badges, cards; dark warm theme; progressive replacement of glass components | `styles/tokens.css` from `colors_and_type.css`, `components/ui/*` |
| Copy: customer vocabulary (AI employees, Work history, Calls); sentence case; no emoji (brand rules) | all customer pages |
| Accessibility: keyboard navigation of menus and tables, chart summaries (`AccessibleChart` exists) | — |
