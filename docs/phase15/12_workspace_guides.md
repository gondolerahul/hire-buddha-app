# Phase 15 — Workspace guides

> **Task:** T10-5. How each of the three workspaces works, for the people who use them and for support. Navigation: 07 §4; reports: 07 §7; the menus are generated from `frontend/src/nav/config.ts`, so a page a person cannot use is not in their menu (or shows locked when their plan lacks it).

---

## 1. Business Workspace — businesses (`tenant_admin`, `tenant_user`)

**Home** (`/home`) — an admin sees billed this month against the spend cap, the balance and how many days it lasts at the last week's spend, AI employees, runs, calls and approvals waiting, with a list of what needs attention (low balance, credit expiring, approvals, failed runs). A user sees its own work.

| Area | What it is for | Who |
|---|---|---|
| AI employees (`/agents`) | Build, run and version AI employees; templates (admin) | both |
| Knowledge (`/knowledge`) | Documents and memory trees | both |
| Work (`/work`), Approvals (`/approvals`), Automation (`/automation`) | Every run and its result, work waiting for a person, schedules and triggers | both; automation admin |
| Customers & calls (`/calls…`) | Calls and campaigns; phone numbers with their monthly rent (admin) | both |
| Data & apps (`/records`, `/apps`, `/code`, `/connections`, `/files`) | Records, hosted apps, code, connected services | admin, as the plan allows |
| Billing (`/billing…`) | Wallet and recharges, plan, usage & charges, invoices, partner fees to pay, spend controls | admin only |
| Reports (`/reports`) | R-T01…R-T14 (some need the plan's advanced reports) | admin; users R-T05/06/09/14 |
| Settings (`/settings…`) | Business profile (country and currency, time zone), team, automation & data, partner access | admin |

**Money, in the business's currency.** Everything is shown in the currency the business is billed in (INR in India, with GST on invoices). Calls are billed per second. Recharges last `wallet.topup_validity_days` (90 by default); credit from before the cutover keeps its old expiry. When the balance runs out, work that was running finishes into debt, new work waits until it is repaid, and apps stop after a grace period — the banner at the top says so, with a Recharge button for admins.

**Spend controls** (`/billing/controls`) — a monthly spend cap (work that would pass it waits until next month or a higher cap); a cap set by the business's partner or by HireBuddha is shown locked. Per-agent budgets are on Automation settings.

**Partner access** (`/settings/partner-access`) — the business's partner (if any) works inside the account only under a grant the admin approved; every request it makes is listed there, and the admin revokes the grant at any time.

---

## 2. Partner Portal — partners (`partner_admin`, `partner_user`)

**Home** (`/partner`) — customers, billed this month, earnings, leads, the partnership's state (fee, KYC, agreement).

| Area | What it is for | Who |
|---|---|---|
| My tenants (`/partner/tenants`, Gold) / Referred customers (`/partner/customers`, Silver) | Resold or referred customers, their plan and billed amounts — never HireBuddha's cost | both |
| Leads (`/partner/leads`) | Register a lead (exclusive for `partners.lead_exclusivity_days`), convert it | both |
| Fees (`/partner/charges`) | Raise a setup or customisation fee on a customer, inside the agreed range, with its split | admin, Gold |
| Network (`/partner/network`) | Partners you recruited, invites, override earnings | admin |
| Earnings (`/partner/earnings`) | Every commission, its state (accrued → held → payable → paid), statements, disputes, GST invoice upload | admin |
| Partnership (`/partner/partnership`) | Agreement, annual fee, KYC and bank details | admin |
| Guide (`/partner/guide`) | How earning works and the partner's own rates | both |
| Reports (`/partner/reports`) | R-P01…R-P10 (by partner type) | admin; users P03, P08 |
| Team, Access (`/partner/team`, `/partner/access`) | People; grants into resold customers (Gold) | admin |

**Working in a customer's account** (Gold): choose the customer in *Working in* (sidebar). The screens become that business's, as its admin (a partner_user as its user), only while a grant is active; each request is recorded for the business to see. A suspended or terminated partner is refused.

### The partner programme in short

- **Silver** refers customers and earns on what they pay; it does not see their data. **Gold** also creates and supports customers' workspaces, raises setup and customisation fees, and works inside them under grants.
- **Commission** is a share of what the customer **paid** (net of GST and refunds), by revenue kind (subscriptions, recharges, fees, hosting, number rent), at the rates of the partner's agreement. **Overrides** pay a recruiter on the partners it brought in, up to three levels, for `partners.override_months`, if the recruiter has its own paid revenue that month.
- Earnings are **held** for `partners.holdback_days` (longer on probation) so refunds can reverse them, then become payable. Statements are made monthly; payment needs verified KYC and bank details; TDS is deducted; a balance under the minimum carries forward.
- The **annual partnership fee** keeps the partnership active; unpaid after the grace, the partner is suspended and its held earnings are forfeited.

---

## 3. Platform Console — HireBuddha staff (`app_admin`, `app_user`)

**Home** (`/console`) — the desks of the person's functions, what waits on each (R-A25: companies in debt and old approvals for support; leads and applications for sales; failed payments and statements to approve for finance; unsettled usage and failed runs for ops) and the platform overview (R-A01).

**Staff functions.** An `app_admin` has everything. An `app_user` has one or more of **support, sales, finance, ops** (set on **Team** by an app_admin); the menu, the reports and the read APIs follow them. Changes to money, plans, partners and settings are app_admin's only.

| Area | What it is for | Functions |
|---|---|---|
| Directory: Companies, Company 360, Users, Workspaces | Every company; one company's status, wallet, plan, partner, people, revenue, runs and change history; *Work in this business* opens its Business Workspace as its admin (audited) | support, sales, finance |
| Partners: network, applications, leads, rules | The programme: applications and underwriting, partner 360, commission and fee rules, the simulator | sales (rules: app_admin) |
| Money: plans, pricing, formula, daily credits, currency, wallet policy, tax | Commercial settings — every change audited, with a reason | app_admin |
| Finance: revenue, receivables, payments, payouts, liability, shadow | Revenue and margin, who owes, payments and refunds, partner statements, credit sold but not used, the v1/v2 comparison | finance |
| Operations: runs, approvals, calls, numbers, apps, automation, health | Oversight of what runs on the platform | ops, support |
| AI platform: SKUs, routing, tools, templates, connectors, kernel | The model and tool catalogue | app_admin; ops reads kernel KPIs |
| Reports (`/console/reports`) | R-A01…R-A25 | by function |
| Settings, Audit log | Money settings incl. the rollout switches; every staff change (R-A24) | app_admin; ops and support read the audit log |

Procedures: [11_operations_runbooks.md](11_operations_runbooks.md). The cutover: [10_cutover_runbook.md](10_cutover_runbook.md).
