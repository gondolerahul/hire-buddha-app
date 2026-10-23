# 05 — Phase 15 requirements, decisions and conflicts

> **Inputs:** the owner's review of documents 01–04 (feature requests and answers to Q1–Q8, 23 Oct 2026) and the findings in 01–04.
> **Purpose:** one numbered, unambiguous list of what Phase 15 must deliver; every place where the owner's request differs from what 01–04 recommended, with the approach this plan adopts; and the owner's decisions on the twelve questions the plan raised (§4 — all decided).
> **Next:** [06 Technical design](06_technical_design.md) · [07 UI, navigation and reports](07_ui_navigation_and_reports.md) · [08 Implementation plan](08_implementation_plan.md)

---

## 1. Owner's decisions (Q1–Q8)

| # | Question | Decision | Consequence for the plan |
|---|---|---|---|
| Q1 | Overrun of the wallet | **Negative balance up to a configurable tolerance per plan**, settled from the next recharge. **Once the balance is negative no agent may run and hosted apps are stopped.** | Debt in the wallet; tolerance on each plan; a "negative balance" enforcement state across runs, calls, campaigns, automation and apps (06 §6) |
| Q2 | Hosting and database cost | **Consume credits hourly/daily** from the same wallet, **shown as their own category**; SKUs and units to be proposed | Standalone-usage settlement and a hosting SKU set (06 §9) |
| Q3 | Wallet currency | **Wallet in the billing currency** | Wallets, holds, top-ups, grants in the company's currency (06 §3) |
| Q4 | Partner models | **Referral + resell-commission first; wholesale with pools second. No white-labelling.** | Silver = referral, Gold = resell-commission (06 §11); white-label removed from the backlog |
| Q5 | Who changes spend cap and plan | **Both (tenant and partner), with locks** | Lock model on spend cap and plan (06 §8.5) |
| Q6 | Feature flags customers may touch | **None** | Flags become staff-only; plan entitlements are a separate, staff-controlled catalogue (06 §10) |
| Q7 | Do tenants see base cost | **No — billed amounts only** | Extended to partners by request B-3; billed-only money views everywhere (06 §5) |
| Q8 | First non-USD currency and gateway | **INR via Razorpay with GST** | INR is the default currency; GST invoices (06 §12) |

---

## 2. Requirements

IDs are used in 06, 07 and 08. "Admin" means `app_admin` unless stated.

### 2.1 Billing (currency and visibility)

| ID | Requirement |
|---|---|
| REQ-BL-1 | Every company is billed in a **currency derived from its country**. The currency is set when the company is created and does not change by itself. |
| REQ-BL-2 | The **default currency is INR** (for India and for any country without a currency mapping). |
| REQ-BL-3 | **Tenants and partners only ever see billed amounts**, never provider cost, in every screen, report, export, e-mail and live stream. |
| REQ-BL-4 | The app admin sees amounts in the **platform display currency** (default INR, chosen by the admin) with the USD figure available alongside. |

### 2.2 Costing

| ID | Requirement |
|---|---|
| REQ-CO-1 | **Calls are costed per second.** Remove every rounding up and rounding of quantities and amounts in costing (no per-started-minute, no `ceil`, no `round`). |
| REQ-CO-2 | **Cost units are a fixed, enumerated set** (per 1M tokens, per second, per request, per GB, per minute, …) stored as codes. **Remove the unit text parser and string matching completely.** |
| REQ-CO-3 | **All calculations are in USD**, and registry rates are entered in USD (as today). Amounts are converted to the company's currency only when money is shown, held, charged or paid. |
| REQ-CO-4 | The **FX rate is configurable in the UI by the app admin only**; default **100 INR = 1 USD**. |
| REQ-CO-5 | A company that **claims a phone number is charged a fixed rent of USD 20 (₹2,000) per number per month**; the app admin can change the rate in the UI (O-2). |

### 2.3 Daily credits

| ID | Requirement |
|---|---|
| REQ-DC-1 | Daily credits are configured **only by the app admin**. |
| REQ-DC-2 | The admin chooses **how much** daily credit each company receives. |
| REQ-DC-3 | The admin chooses **for how many days from the company's sign-up** daily credits apply: 10, 15, 30, 60, 90, 180 or 365. |
| REQ-DC-4 | Daily credits **expire within 24 hours** and are **renewed to the set amount**; they never accumulate. |
| REQ-DC-5 | Policies can be set **for direct tenants of the app** and **per partner** (tenants who came through a partner), including **no** daily credits, and with **different amounts for different day ranges**. |
| REQ-DC-6 | **Every money-related setting is configurable** (e.g. minimum balance to run a process or agent); a list of them with who has access is part of this plan (06 §8.4). |

### 2.4 Wallet

| ID | Requirement |
|---|---|
| REQ-WL-1 | A recharge **expires after 90 days**; the number of days is configurable by the app admin. |
| REQ-WL-2 | A wallet **cannot be transferred** to another company. |
| REQ-WL-3 | A company's wallet is **shared by all its users**. |

### 2.5 Subscriptions

| ID | Requirement |
|---|---|
| REQ-SB-1 | Subscriptions are **configured entirely by the app admin**. |
| REQ-SB-2 | Each subscription has a **monthly price** (e.g. USD 100, 500, 1,000, 5,000) and an **extra-credit percentage** (e.g. 10 %, 20 %, …). |
| REQ-SB-3 | Each subscription defines **which features its subscribers may use** (future use); for now, list every feature the product has and give each a flag. |

### 2.6 Partners

| ID | Requirement |
|---|---|
| REQ-PT-1 | Two partner types: **Silver (basic)** — refers leads; Buddha Cognitive Lab (BCL) sales converts them and BCL delivers the solution. **Gold** — the partner sells end to end and delivers the solution. |
| REQ-PT-2 | Every partner pays an **annual partnership fee**, configurable by the app admin. |
| REQ-PT-3 | Partners may charge their tenants **one-time setup and customisation fees**; the fees and how they are **distributed** are configurable by the app admin. |
| REQ-PT-4 | **Any partner may onboard new partners**; the partner fees the system calculates are **distributed across the levels**. A logic with proper underwriting and the operational risks is to be proposed (06 §11.6–11.8). |
| REQ-PT-5 | No white-labelling (Q4). |

### 2.7 UI

| ID | Requirement |
|---|---|
| REQ-UI-1 | Remodel and rearrange pages, menus and each role's view, with new reports and analytics (07). |

---

## 3. Conflicts with documents 01–04, and the approach adopted

Each row: what 01–04 said, what the owner asked, the risk, and **the approach this plan adopts**. Rows marked ✓ were open questions, confirmed by the owner on 23 Oct 2026 (§4).

| # | Topic | 01–04 recommended | Owner asked | Risk / issue | **Adopted approach** |
|---|---|---|---|---|---|
| K-1 | Rounding | Round billed amounts to the currency's minor unit at settlement (04 A9) | Remove all rounding | Payment gateways take integer paise/cents; GST invoices must show 2-decimal amounts | **No rounding anywhere in costing, rating, holds, settlement or the ledger** (stored to 10 decimals). Rounding only at three edges that legally or technically need it: (1) **display**, (2) the **gateway amount** of a payment, (3) **invoice totals** (with a "rounding" line). Wallet balances are never rounded. |
| K-2 ✓ | Per-second calls | Keep per-started-minute (BC-12) | Per-second, no ceiling | Carriers (Tata, Twilio in India) bill by pulse — usually per started minute — so per-second customer billing earns less than the carrier charges on short calls | **Customers are billed per second, exactly.** Each telephony SKU carries a *provider billing increment* used **only** by the cost-of-goods reconciliation report (to show the true carrier cost and the margin gap). The admin covers the gap with the telephony rate or `mf`. |
| K-3 | Price units | Keep the parser, reject unknown text (LP-01) | Enum/DB codes; remove parser and string matching | Existing rows hold free text | **`CostUnit` enum + `cost_units` reference table + FK.** One-off migration maps every existing string to a code with an explicit table; any unmapped row stops the migration with a report. Parser deleted. |
| K-4 | Currency prices | Hand-set price books per currency + FX for usage (02 §13.4) | One configurable FX rate (100 INR = 1 USD); everything priced in USD | Prices follow FX movements | **USD price lists converted with the admin's FX rate.** Each fixed-price item may optionally carry a **per-currency override** (for round local prices). No separate per-currency price books in Phase 15. |
| K-5 ✓ | Number rent "₹2,000 or USD 20" | — | Fixed amount | At another FX rate, ₹2,000 ≠ USD 20 | Rent is a **fixed-price item, USD 20/month**, with an **INR override of ₹2,000** seeded, so Indian tenants always pay ₹2,000 whatever the rate. **Both the USD rate and the INR override are editable by the app admin on the Pricing page** (O-2); a change applies from each rental's next 30-day charge. |
| K-6 | Daily credits | Per-company `billing_config` row; partner could set custom credits at tenant creation (C-4, B-13) | App-admin only; policies by direct/partner and day ranges | Partners lose a capability they have today (P-3) | **Daily-credit policies** (06 §7), app admin only. `billing_config.default_daily_credits`, `companies.default_daily_credits` and `custom_daily_credits` are retired. |
| K-7 | Recharge validity | 365 days, each top-up restarts the whole balance (today) | 90 days per recharge, configurable | Existing balances have a different expiry | **Lots:** each recharge is its own lot with its own expiry (default 90 days); spending takes the earliest-expiring lot first. Existing balances migrate as one lot keeping their current expiry. |
| K-8 | Plan features | — (Q6: customers touch no flags) | Use feature flags for plan features | The existing 21 flags are engineering switches (critics, bandit, memory), not product features | **Entitlements**: a separate catalogue of product features (`feature.*` keys, 06 §10) granted by plans and staff overrides, resolved with the same machinery as flags. Engineering flags become staff-only. |
| K-9 | Who sets plans | Tiers app-admin only | "Subscriptions fully configured by app admin" **and** Q5 "tenant and partner change plan, with locks" | Reads as contradictory | Admin **defines** tiers (price, bonus, entitlements, tolerance); tenant or Gold partner **chooses** a tier for the tenant, subject to locks. |
| K-10 | Partner pricing | Partner price books and markups (03 §5.3, 04 E9) | Silver/Gold; referral + resell-commission | Partner markups add a pricing layer not asked for | **Phase 15: one platform price list for everyone; partners earn commission**, plus the one-time fees they are allowed to charge. Partner markups and wholesale pools are deferred (Q4). `sales_partner_fee_pct` (spf) is removed from the customer formula. |
| K-11 | Sub-partners | Optional, last (03 §5.6 step 7) | Any partner may onboard partners | Multi-level commissions carry regulatory risk (§3 K-12) | **In scope**, with a depth limit, approval (underwriting) of every new partner, and the commission rules in 06 §11.6. |
| K-12 ✓ | What is distributed across levels | — | "Total partner fees calculated by the system distributed to each level" | If **annual partnership fees** (or any fee for *joining*) flow to the recruiter, income comes from recruitment — the defining trait of a money-circulation scheme under India's *Prize Chits and Money Circulation Schemes (Banning) Act, 1978* | **Only customer revenue** (tenants' paid usage, subscriptions, setup/customisation fees) is commissionable. **Annual partnership fees are platform revenue and are never distributed.** Confirmed (O-3). |
| K-13 | White-label | Phase 3 item (04 E12) | Not allowed | — | **Removed.** `logo_url` stays a company avatar only. |
| K-14 ✓ | Stop apps on negative balance | — | Once negative: no agents run, hosted apps stopped | A balance a few paise below zero would take a customer's public app offline instantly; database share and number rent keep accruing even when everything is stopped | Negative balance **blocks new work immediately** (runs, calls, campaigns, automation). **Apps stop after a configurable grace (default 0 h — as asked)**; staff can set a grace. Unstoppable charges (database share, number rent, storage) may take the balance past the tolerance; past tolerance for N days (configurable) the company is **suspended (read-only)** and numbers are **held**, not released. |
| K-15 | Daily-credit reset time | Reset at the tenant's local midnight (04 F9) | Expire within 24 hours | A rolling 24 h per company is harder to reason about | **Reset at 00:00 in the company's time zone** (always within 24 hours of the last reset). |
| K-16 | Money settings in which currency | — | All calculations in USD; admin sees INR | — | **Every money setting is stored in USD** (rates, floors, tolerances, daily-credit amounts, fees, prices). The admin enters and sees it in the display currency with the USD value beside it. Optional per-currency overrides exist only on fixed-price items (K-4). |
| K-17 ✓ | Non-INR countries | Gateway per region (Stripe) | Billing currency by geography; INR via Razorpay | Razorpay India collects foreign currencies only with international payments enabled, and settles in INR | Phase 15 supports **INR and USD** billing currencies through Razorpay (USD for countries mapped to USD, international payments enabled; exports of services zero-rated under LUT). More currencies need a second gateway — later. |
| K-18 | Subscription price in USD, billed in INR | — | Prices in USD | Razorpay plans have a fixed amount; an FX change would need new plans | A Razorpay plan per **(tier, currency, FX version)**. An FX change applies to new subscriptions at once and to existing ones **at their next renewal** (admin can choose "new subscribers only"). |
| K-19 | Agent budgets | `governance.max_cost_usd` is a cost in USD | Tenants never see cost | Builders set and see cost caps | Agent budgets become **billed-amount caps in the company's currency** (`max_bill`); the old field is converted on migration. |
| K-20 | Partner access to tenant data | Access grants (03 §5.4 B) | Silver: BCL converts and delivers | A Silver partner has no business reason to see tenant data | **Silver: no access to tenant data** — billed summaries of referred customers only. **Gold: delegated access through audited, scoped grants.** |
| K-21 | Spend cap | USD cap, tenant can remove it | Both, with locks | — | Cap stored in USD, shown in the company currency; a partner or the admin can **lock** it. |
| K-22 ✓ | Silver referral commission period | A fixed window (proposed 12 months) | **Always** (O-8) | An open-ended liability for every referred tenant | **Silver earns referral commission for as long as the referred tenant pays and the Silver partner stays active** (no end date). Bounded by the same controls as Gold: cash basis, pool cap, margin guard, and termination. Uplines' **overrides** keep their own sunset (`partners.override_months`, default 24), an underwriting control that is separate from the originator's commission. |

---

## 4. Decisions on the open questions (owner, 23 Oct 2026)

All twelve are decided; none is open. Two differ from the proposed defaults (**bold**).

| # | Question | Decision | Applied in |
|---|---|---|---|
| O-1 | K-2: accept the margin gap of per-second billing against per-minute carriers (covered by rate/`mf`)? | Yes; the reconciliation report shows the gap | 06 §4; 07 R-A03 |
| O-2 | K-5: Indian tenants pay ₹2,000 per number whatever the FX rate? | Yes (INR override) — **and the per-number rate is configurable in the UI** | 06 §8.3, §8.4, §13; 07 §4.1, §5.6; 08 T5-3, T5-6, T7-1 |
| O-3 | K-12: annual partnership fees are never distributed to uplines? | Yes | 06 §11.4, §11.6 |
| O-4 | K-14: app-stop grace default 0 h and suspension after 7 days past tolerance? | 0 h; 7 days | 06 §6.3, §8.4 |
| O-5 | K-17: which countries map to USD at launch? | All non-India → USD | 06 §3.1 (country profiles seed) |
| O-6 | Top-ups and subscriptions: is GST added on top (tax-exclusive) or included? | Tax-exclusive: ₹1,000 credit costs ₹1,180 | 06 §12.3 |
| O-7 | Daily credits: count towards partner commission? | No — only paid credit is commissionable | 06 §7.3 DC-5, §11.6 |
| O-8 | Commission period for Silver referrals | **Always** — no end date (K-22) | 06 §11.1, §11.2, §11.6; 07 §4.3, R-P04; 08 T8-9 |
| O-9 | Maximum partner depth | 3 levels (originating partner + 2 uplines) | 06 §11.3, §11.6 |
| O-10 | Plan change mid-cycle | Upgrade immediately, downgrade at cycle end, no refunds | 06 §12.1 SB-4 |
| O-11 | Does a company's subscription bonus count as commissionable revenue? | No (free credit) | 06 §11.6 |
| O-12 | Seed tiers | Starter $100/10 %, Growth $500/20 %, Scale $1,000/30 %, Enterprise $5,000/40 % — editable | 06 §12.1 SB-7 |
