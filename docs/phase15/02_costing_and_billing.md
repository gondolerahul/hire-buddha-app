# 02 — Costing and billing: rules, configuration, gaps and multi-currency

> **Scope:** how HireBuddha prices work (costing), turns cost into a customer charge (billing), admits and stops work on credit, settles, keeps wallets, sells top-ups and subscriptions, and reports. Every rule is taken from the code at `53be0bd`, with its file.
> **Main code:** `backend/src/billing/*`, `ai/governance/{governance_service,tool_cost_resolver,run_cost}.py`, `ai/core/credit_guard.py`, `ai/usage_service.py`, `ai/services/{cost_attribution,attributed_usage}.py`, `voice/{usage_logger,call_admission}.py`, `gateway/call_spend.py`, `apps/metering.py`, `ai/tools/sandbox/metering.py`, `ai/planning/cost_estimator.py`; UI `pages/billing/*`, `pages/reports/{Costing,Billing}Report.tsx`.

---

## 1. Summary

**How it works.** Everything that costs money writes a `usage_logs` row at the *provider's* price (the **base cost**, `c`). When a top-level run, a phone call or a video call ends, its base cost goes through one formula — `TB = c·mf + c·mf·pf + c·mf·spf − c·mf·d` — and the result (the **billed amount**) is deducted from the company's **credit wallet** and added to a monthly **billing event**. A credit is one US dollar. Wallets are refilled by Razorpay top-ups (USD) and monthly Razorpay subscriptions (fee + bonus %), plus free daily credits.

**What is solid.** The ledger is now single-sourced (one `usage_logs` row per charge, attributed to one of 18 categories); unit parsing refuses ambiguous price units; runs reserve credit (holds) before they start, are stopped by a circuit breaker when credit runs out, and are settled exactly once; payments are idempotent across browser callback, webhook and reconciliation; a monthly spend cap exists.

**Most important gaps (detailed in §12).**

| # | Gap | Impact |
|---|---|---|
| B-1 | A phone call that costs more than the remaining balance is charged **nothing** (all-or-nothing `consume()`), yet its billing event is recorded | Revenue leak; reports overstate collections |
| B-2 | **Hosting, database share, and any usage outside a run** (background embeddings, sandbox seconds with no run) are logged but **never deducted or billed**; app builds and phone-number rent are computed but never billed | Unbilled cost of Phase 14 features |
| B-3 | A wallet that hits zero mid-settlement absorbs the **shortfall silently** — no debt, no negative balance, no recovery | Leak on every overrun |
| B-4 | LLM calls whose model has **no registry price row** are free (no usage row) | Leak when a model is added without a price |
| B-5 | Every run's charge lands in `api_charge`; the per-category charge columns, and the `partner/tenant/user` groupings, are never filled | Category and partner reports are wrong/empty |
| B-6 | The partner fee (`spf`) is one global/company percentage, charged even on direct tenants, credited to nobody | No partner commission ledger (see 03) |
| B-7 | **Single currency (USD) hard-coded** in Razorpay orders, plans, transactions and every screen; no tax, no invoices | Blocks India GST invoicing and any non-USD market |
| B-8 | Razorpay `key_secret` and `webhook_secret` are stored in plain JSON (`integration_registry.service_metadata`) | Secret exposure in the control DB |

---

## 2. Concepts and data

| Term | Meaning | Stored in |
|---|---|---|
| **SKU / price row** | A provider service with `internal_cost` per `cost_unit` (e.g. `gemini-2.5-flash-in`, $0.30 per million tokens) | `integration_registry` (control) |
| **Usage row** | One charge at base cost, with `raw_quantity`, `sku_id` (or none for fixed prices), `run_id`, `attribution`, metadata | `usage_logs` (control) |
| **Base cost `c`** | Sum of a run's/call's usage rows — what the platform pays providers | `execution_runs.total_cost_usd`, `voice_sessions.total_cost_usd` |
| **Billed amount `TB`** | `c` through the billing formula — what the customer pays | `execution_runs.billed_amount`, `credit_holds.billed_amount` |
| **Billing config** | `mf, pf, spf, d`, default daily credits, telephony/image overrides | `billing_config` (`company_id NULL` = global) |
| **Wallet** | Four buckets: daily, subscription, subscription bonus, top-up balance | `credit_wallets` (one per company) |
| **Hold** | Credit reserved by a running top-level run; also its settlement record | `credit_holds` |
| **Billing event** | Monthly aggregate per company and grouping (formula breakdown, category charges, minutes, counts) | `billing_events` |
| **Payment** | A Razorpay order/payment (top-up or subscription charge) | `payment_transactions` |
| **Tier / subscription** | Plan catalogue and a company's Razorpay subscription | `subscription_tiers`, `subscriptions` |
| **Spend cap** | Max billed per UTC calendar month | `companies.monthly_spend_cap_usd` |

```mermaid
sequenceDiagram
    participant U as User / trigger / call
    participant API as API
    participant L as AgentLoop (worker)
    participant UL as usage_logs
    participant W as Wallet + holds
    participant BE as billing_events
    U->>API: start run
    API->>W: require_credits(entity floor) -> 402 if short
    API->>API: run quota (runs/minute)
    API->>L: enqueue
    L->>W: admit: spend cap, hold = min(max(estimate, floor), free)
    loop every iteration
        L->>UL: LLM / tool / sandbox rows at base cost
        L->>W: breaker: TB(cost so far) vs wallet − others' holds; spend cap
    end
    L->>W: settle: claim once, deduct TB (drain to 0), release hold
    L->>BE: upsert monthly event (grouping "process", entity name)
```

---

## 3. Costing rules — how base cost is computed

### 3.1 Price units (`ai/usage_service.py`)

- **R-C1** A price is `internal_cost` per `cost_unit`. `cost_unit` is parsed: separators and case ignored; optional `per`; a number and a scale (`k`, `m`, `thousand`, `million`, `1k`, `1M`); a noun from a closed list — token, character, call (also request/flat fee), second, minute, image, video, query/search, page, email, message, transaction pct, hour (vCPU hour, GB hour), gb, day. Cost per unit = `internal_cost / quantity`.
- **R-C2** Registry writes reject an unknown unit (LP-01). A row stored before that check is logged as an error and priced **per one unit**.
- **R-C3** Prices are `NUMERIC(18,6)`; computed costs are `Decimal` and **never rounded** (no rounding to cents anywhere in costing or billing; `ROUND_HALF_UP` is imported in `billing_service.py` and unused).

### 3.2 Where a price comes from (lookup order)

| Spender | SKU used | Lookup | No price found → |
|---|---|---|---|
| **LLM text call** (step, planner, critics, judge, alignment, debate, CORTEX summaries, dreaming, Meta-Agent) | `{model_name}-in` (prompt tokens), `{model_name}-out` (completion tokens) | company's own active row → APP (platform) company's row | **No usage row, cost 0**, warning logged (R-C4) |
| **Embeddings** | `{model}-in`, quantity = billable **characters** | same | 0 |
| **Tools** (`ToolCostResolver`, `ai/governance/tool_cost_resolver.py`) | `tool_id`, `TOOL_SKU_MAP[tool_id]`, or the media category's first row | 0) `billing_config.base_cost_image_gen` for `image_generation`; 1) company row; 2) platform row; 3) `TOOL_FIXED_COST`; 4) `FREE_TOOLS` / a synthesized tool's `free_reason` → $0; 5) **unpriced** → a **$0 row marked `cost_source: missing`** and a `tool.cost.missing` event | see 4/5 |
| **Sandbox time** | `SANDBOX_COST_SKU` (`sandbox-runtime`, seeded at $0.00002/s) per second | company → platform | nothing recorded |
| **Telephony** | `tata-tele-voice-in-out` (Tata), `in-out` (Twilio) | company `service_sku` → company `model_name` → platform `service_sku` → platform `model_name` | 0 (warning) |
| **Live voice model audio** | `gemini-3.1-flash-live-preview-in/-out` | same as telephony | 0 |
| **App hosting** | `app-hosting-vcpu-hour`, `app-hosting-gb-hour`, `app-egress-gb` | company → platform | recorded in `app_usage` only |
| **Tenant database** | `tenant-db-pool-share` / `tenant-db-dedicated` per day | — | nothing billed |

- **R-C5** Tool prices are cached **per run** (LRU of 512 runs): a price edited mid-run does not change that run.
- **R-C6** Tool charge = unit price × `units` (a tool's `billable_units`, e.g. seconds of video). Fixed prices: `image_generation` $0.04/image, `video_generate` $0.40/second, `text_to_speech` $0.00045/second, `music_generation` $0.08/clip.
- **R-C7** 45 tools are free on purpose, each with a reason (runs in-process, uses the tenant's own connected account, billed as LLM/sandbox/its own run, Data API). A test fails on a registered tool that is neither priced nor free.
- **R-C8** A company's own registry row **beats** the platform row (for LLMs, tools, telephony). Tenant admins may create rows only in EMAIL, SOCIAL_MEDIA, API_TOOL and OTHER categories; partner admins in any category for their own company. So a business can price its own `API_TOOL` SKUs (e.g. `serp-api-key`) — including at $0 (see B-9).

### 3.3 Voice and video calls (`voice/usage_logger.py`, `gateway/call_spend.py`)

- **R-C9** Telephony is billed **per started minute**: `ceil(seconds / 60)`; 125 s = 3 minutes. The same rounding is used for the usage row and the billing event (BC-12).
- **R-C10** The live model's audio is billed from the **tokens the provider reported** for the call when it reported any; otherwise each direction's audio seconds × **167 tokens/second** (estimate). If the SKU's unit is per minute, the audio is billed per started minute instead.
- **R-C11** Tool calls made during a call are written on the call's run and added to the call's total.
- **R-C12** A video call opens a run on its first model call (frame descriptions every `FRAME_SAMPLE_SECONDS` = 5 s via the `vision` model, plus live audio) and is settled like a run when the call ends.
- **R-C13** `voice_sessions.total_cost_usd` = telephony + model audio + tools.

### 3.4 Hosting and databases (`apps/metering.py`)

- **R-C14** Hourly cron (`:04`): per app, vCPU-hours and GB-hours of what its pods *requested* and egress GB — from managed Prometheus on AKS, else from deployment records (previews count one replica). Recorded once per app and hour in `app_usage`; usage rows written against the hosting SKUs if present.
- **R-C15** Daily cron (`00:20`): each tenant's database share = 1/(tenants on its pool server) of the pool SKU, or the whole dedicated SKU; once per tenant and day.
- **R-C16** App builds record `cost = duration × APP_BUILD_COST_PER_SECOND` ($0.0001/s) on `app_builds` — display only.

### 3.5 A run's cost (`ai/governance/run_cost.py`)

- **R-C17** A run's base cost = **its own usage rows + the recorded totals of its structural children** (`parent_run_id`; retries and refinements are not children). Only the run's owner (the loop or the call) writes it onto the run (`refresh_run_cost`).
- **R-C18** Every usage row carries one of **18 attributions**: planner, actor_step, critic_pre, critic_post, critic_align, critic_super, reformat_retry, meta_review, dreaming, tool, child_run, embedding, meta_spec_critic, test_driver, sandbox, video_frame, voice_call, hosting. Unknown values fall back to `tool`. A $0 row is not written unless it marks an unpriced tool.

---

## 4. Billing formula rules (`billing/billing_service.py`)

- **R-B1** `TB = (c × mf) + (c × mf × pf) + (c × mf × spf) − (c × mf × d)`, i.e. `TB = c·mf·(1 + pf + spf − d)`.
- **R-B2** Validation (`BillingConfigUpdate`): `0 < mf ≤ 100`; `pf, spf, d` are **fractions** in `[0, 1]` (0.15 = 15 %); `default_daily_credits ≥ 0`; overrides `≥ 0` or `null` (clears). Unknown fields (including the retired `base_cost_llm`) → 422.
- **R-B3** Config resolution: the company's active row (latest `updated_at`), else the global row (`company_id NULL`), else the **identity formula** (`mf=1`, others 0 → billed = cost).
- **R-B4** Overrides are applied **where cost is computed**, so the wallet and the billing event see the same base: `base_cost_telephony` ($/minute) **replaces the telephony part** of a call (model audio unchanged); `base_cost_image_gen` ($/image) replaces `image_generation`'s price. `base_cost_llm` exists as a column but is retired (no unit, never applied).
- **R-B5** The formula is the same for runs, calls and video calls. Discount and fees all apply to `c·mf`; with `d = 1` and no fees, work is free.

**Worked example.** `c = $0.40`, `mf = 1.5`, `pf = 0.20`, `spf = 0.10`, `d = 0.05` → `c·mf = 0.60`; platform fee 0.12; partner fee 0.06; discount 0.03; **TB = 0.75**. The wallet loses 0.75 credits; the billing event records base 0.40, multiplied 0.60, fees 0.12/0.06, discount 0.03, total 0.75.

---

## 5. Admission rules — may this work start?

### 5.1 Runs

| # | Rule | Where |
|---|---|---|
| R-A1 | **At the API** (`trigger_execution`): HTTP **402** unless the company's *free* credit ≥ the entity type's minimum; then **429** past `RUNS_STARTED_PER_MINUTE` (60) top-level runs per minute | `ai/service.py:443` |
| R-A2 | Minimum free credit by level: GRAPH $2.00, LOOP $1.00, PROCESS $0.50, AGENT $0.05, SKILL $0.02, ACTION $0.01, other $0.05 | `credit_service.py:39` |
| R-A3 | *Free* = daily + subscription + bonus + top-up − holds of the company's **other unfinished** runs. A hold whose run is finished or gone stops counting even before it is released | `held_by_others` |
| R-A4 | **Whose credit:** a partner or staff member starting a tenant's agent starts the **tenant's** run, paid from the **tenant's** wallet (decision D54); a template runs as the caller's | `ai/service.py:387` |
| R-A5 | **In the worker** (`CreditGuard.admit`), first the entity's own cap: if the plan's estimated base cost > `governance.max_cost_usd`, the run does not start (applies to child runs too) | `credit_guard.py` |
| R-A6 | Then, top-level runs only: refused if the **monthly spend cap** is reached; refused if free credit < the level minimum; otherwise a **hold** of `min(max(estimate, minimum), free)` is placed under the wallet row lock | `governance_service.check_credit_gate`, `place_hold` |
| R-A7 | Estimate = max(the plan's estimated cost **through the TB formula**, the average billed amount of the entity's last **10** finished top-level runs). Plan estimate: fixed-price tools at their price × typical units; other tools from a baseline table (e.g. web_search $0.005, headless_browser $0.05; default $0.01); thinking steps $0.005 × model factor (Flash 1.0 … Opus 8.0); child invocation $0.10; CORTEX ops $0.001 | `credit_guard.estimate`, `cost_estimator.py` |
| R-A8 | An unreadable wallet or cap **refuses** the run (fail closed) | `credit_guard.admit` |
| R-A9 | **Child runs** take no hold; before spawning one, `wallet total − parent's accumulated cost ≤ 0` refuses it. Errors in this check are **logged and ignored** (fail open). Note it ignores other runs' holds | `check_child_credit_gate` |

### 5.2 Calls (one rule for every entry point — `voice/call_admission.py`)

- **R-A10** A call (inbound or outbound, at the provider webhook, the media socket, each campaign dial, the mobile dialer) is admitted only if: the company holds fewer than `LIVE_SESSIONS_PER_COMPANY` (20) live sessions; it is under its monthly spend cap; and its free credit ≥ the **AGENT** minimum ($0.05). An unreadable balance **refuses** the call. Every decision emits `voice.call.admitted/refused`.
- **R-A11** Calls take **no hold**, and there is **no mid-call credit check**: once connected, a call runs to its natural end whatever it costs.

### 5.3 While a run is running — the circuit breaker

- **R-A12** After every iteration of a top-level run: billed-so-far = TB(accumulated base cost); stop with `SpendCapReached` if month-to-date billed + billed-so-far ≥ cap; stop with `CreditExhaustedError` if `wallet total − other runs' holds − billed-so-far ≤ 0`. The run ends `PARTIAL_COMPLETE` with its partial results.
- **R-A13** If the wallet or cap cannot be read, the breaker **lets the run continue** (fail open; settlement still charges).

---

## 6. Settlement rules — turning cost into a charge

### 6.1 Runs (`GovernanceService.settle_billing`)

- **R-S1** Only **top-level** runs settle (child costs roll into the parent via R-C17).
- **R-S2** Base cost ≤ 0 → `billed_amount = 0`, nothing deducted.
- **R-S3** `billed_amount = TB(base cost)` is written on the run; then, in **one control transaction**: claim the settlement on the run's hold row (`settled_at`, `billed_amount`; a run with no hold gets a row) — **only if not already settled**, so a retried finalisation charges nothing; deduct; record the billing event.
- **R-S4** The deduction **drains buckets in spend order and stops at zero** (`consume_incremental`): any shortfall is logged as `BILLING SHORTFALL` and **forgotten** (no negative balance, no debt record).
- **R-S5** Billing event: grouping `process`, grouping value = **the entity's name**, base cost into `other_ai_cost`, the whole TB into `api_charge`.
- **R-S6** The hold is released in `finally` (even if billing failed). Any settlement error is logged and **swallowed** — the run finishes, unbilled.

### 6.2 Phone calls (`voice/websocket_handler.py:1576-1680`)

- **R-S7** At hang-up: log telephony, model audio and tool cost (R-C9–R-C13); apply the telephony override; compute TB.
- **R-S8** Deduct with `CreditService.consume()` — **all or nothing**: if the wallet holds less than TB, it raises, the error is logged, and **nothing is deducted** (B-1).
- **R-S9** Record the billing event regardless: grouping `agent`, value = agent id, category `telephony` (whole TB into `telephony_charge`), billed minutes into `telephony_in_minutes` or `telephony_out_minutes` by direction.
- **R-S10** No settlement claim: a repeated cleanup could charge twice (guarded only by the cleanup running once).
- **R-S11** The call's run is closed with `billed_amount`.

### 6.3 Video calls — settled as runs (R-S1–R-S6) when the call ends.

### 6.4 Everything else — **not settled**

Usage rows with no run — hosting (vCPU/GB/egress), database share, background embeddings (document ingestion), sandbox seconds outside a run, CORTEX maintenance outside a run — are recorded in `usage_logs` and appear in cost-attribution views, but are **never deducted from a wallet and never become billing events** (B-2).

---

## 7. Wallet rules (`billing/credit_service.py`)

| # | Rule |
|---|---|
| R-W1 | One wallet per company, created on first use (insert-if-absent) with a day's credits from the billing config; also queued at sign-up and company creation |
| R-W2 | Four buckets, spent in this order: **daily → subscription → subscription bonus → top-up balance** (soonest-expiring first). `account_model` (pay_as_you_go / subscription) is a **label only** (BC-02) |
| R-W3 | **Daily credits**: amount = `default_daily_credits` of the company's billing config (else global); expire at the next **00:00 UTC**; never carry forward; renewed lazily on any balance read and by the 00:00 UTC cron for **active** companies; renewing twice in a day grants nothing |
| R-W4 | **Top-up balance**: valid **365 days from the latest top-up** (each top-up restarts the validity of the whole balance); an expired balance is zeroed and not revived by a new top-up |
| R-W5 | **Subscription credits + bonus**: replaced (not added) each paid cycle; expire at the end of the cycle paid for |
| R-W6 | Every change happens under a `SELECT … FOR UPDATE` row lock; expiry is applied first |
| R-W7 | Balance view: buckets, `total_available`, `held` (others' holds), `free` = total − held |
| R-W8 | A credit = **$1 USD**; all messages and screens print `$` |

---

## 8. Top-up rules (`credits_router.py`, `payment_service.py`)

| # | Rule |
|---|---|
| R-T1 | Any signed-in user of a company (**any role**) may start a top-up |
| R-T2 | Razorpay keys come from the active `integration_registry` row with SKU `razorpay_keys` (`key_id`, `key_secret`, `webhook_secret` in `service_metadata`); none → 503 |
| R-T3 | Order: `amount × 100` truncated to an integer (cents), **currency `USD`**, receipt `topup_<8 chars of company id>`; a `pending` transaction stores the amount |
| R-T4 | **No server-side minimum or maximum** on the amount; the UI enforces ≥ $1 |
| R-T5 | Verification: HMAC-SHA256 of `order_id|payment_id` with `key_secret`; the **stored** amount is credited (never the caller's); a replay or a second channel credits nothing (unique order/payment ids) |
| R-T6 | Webhook `payment.captured`: credited only if paid amount **and** currency equal the order's; else `amount_mismatch` (not credited) |
| R-T7 | `payment.failed` marks the order failed; the order stays payable — a later success is still credited |
| R-T8 | A pending order older than **24 h** becomes `expired`; money that arrives later is still credited |
| R-T9 | 1 USD paid = 1 credit; no top-up bonus; no tax |

---

## 9. Subscription rules

| # | Rule |
|---|---|
| R-P1 | Tiers: name, unique `tier_level ≥ 1`, `monthly_fee > 0` (USD), `bonus_pct` 0–100 (a **percentage**, unlike the formula's fractions), active flag. Only app_admin writes; everyone signed in lists active tiers. **Delete is a hard delete** |
| R-P2 | Each tier gets a Razorpay **plan** (monthly, USD) on first use; changing the fee clears it so new subscribers get a new plan; existing subscribers keep theirs |
| R-P3 | One live (active / past_due / paused) subscription per company; another → 409 "cancel it first". **No upgrade/downgrade, no proration** |
| R-P4 | Create (any role): Razorpay subscription with **120** cycles, status `pending_payment` until the first charge is verified |
| R-P5 | Verify: HMAC of `payment_id|subscription_id`; grants one cycle: subscription credits = fee, bonus = fee × bonus % (Tier 1 20 %, 2 30 %, 3 40 % by convention); expiry = Razorpay `current_end`, else now + 31 days |
| R-P6 | Each `subscription.charged` webhook (or the 01:30 UTC reconciliation, which reads paid invoices) grants that cycle once per payment id; a payment below the fee grants nothing; an older cycle never replaces a newer one |
| R-P7 | Status mapping from Razorpay: authenticated/active → active; pending/halted → past_due; paused → paused; cancelled/completed/expired → cancelled |
| R-P8 | Cancel (any role): cancels at Razorpay **immediately** (`cancel_at_cycle_end: 0`), then marks cancelled; credits already granted last until they expire; with no other live subscription the wallet is labelled pay-as-you-go |
| R-P9 | A `pending_payment` subscription older than 24 h → `failed` and cancelled at Razorpay |
| R-P10 | Pre-BC-16 subscriptions without a Razorpay id end when the month they paid for ends |

---

## 10. Spend cap and reporting rules

- **R-K1** `companies.monthly_spend_cap_usd`: `> 0` or `NULL` (no cap). Month-to-date spend = sum of the company's `billing_events.total_billing` for the current **UTC** month. Checked at run admission, at call admission, and by the breaker (with the running run's bill so far). Editable by app_admin (any), partner_admin (its tenants, own company) and **tenant_admin (own company — can raise or remove it)**.
- **R-K2** `billing_events`: one row per (company, month, grouping type, grouping value), upserted atomically (`INSERT … ON CONFLICT … SET col = col + excluded`), period = UTC month.
- **R-K3** Costing report and billing report (`/reports/costing`, `/reports/billing`): **app_admin only** (they reveal base cost, i.e. margin); same rows, different totals; filter by month, grouping type, company.
- **R-K4** Partner performance (app_admin): per partner, sum of its tenants' `total_billing` (gross revenue, not commission).
- **R-K5** Tenants and partners have **no statement, invoice, transaction history or billing-event view**. The wallet page shows balances only. Cost-attribution views (`/admin/agent-kernel/cost`, run pages) show tenants their **base cost** (`usage_logs.calculated_cost`), not their billed price.

---

## 11. Configuration — what can be set, where

### 11.1 Configurable today

| Setting | Scope | Backend API | UI |
|---|---|---|---|
| Formula `mf, pf, spf, d` | global; per company | `PUT /api/v1/billing/config` (`company_id` optional) | `/settings/billing` — **global only** |
| Default daily credits | global; per company | same | global only |
| Telephony $/min override, image $/image override | global; per company | same | global only |
| Subscription tiers (name, level, fee, bonus %, active) | platform | `/api/v1/credits/subscription-tiers` CRUD | `/settings/billing` |
| Provider prices (`internal_cost`, `cost_unit`) for every SKU | platform; per company | `/api/v1/config/integrations` | `/integrations` |
| Model per task type (drives which SKU is used) | platform | `/api/v1/config/task-defaults` | `/ai-config` |
| Monthly spend cap | per company | `PATCH /api/v1/companies/{id}` | Platform management (company edit) |
| Entity budget `governance.max_cost_usd`, `critic_cost_share_pct`, execution limits | per agent | entity API | Entity builder |
| Razorpay keys and webhook secret | platform | integration registry row `razorpay_keys` | `/integrations` (as JSON metadata) |
| Feature flag `agent_loop.budget_pressure_threshold` (0.70) | global/company/entity | flags API | Feature flags page |
| Daily credit job, subscription reconciliation (run now) | platform | `POST /api/v1/cron/daily-credits`, `/monthly-billing` | — |

### 11.2 Hard-coded today (should be configuration)

| Value | Where | Proposed |
|---|---|---|
| Minimum free credit per level ($0.01–$2.00) | `credit_service.py:39` | Platform setting, partner/tenant override within bounds |
| Fixed tool prices (image, video, TTS, music) | `tool_cost_resolver.py:180` | Registry SKUs on the APP company |
| Estimator baselines and model factors | `cost_estimator.py` | Derive from registry prices; history-based |
| Audio token estimate 167 tok/s; SKU names for telephony and live audio | `voice/usage_logger.py` | Registry metadata per SKU; task default `speech_to_speech` |
| App build $/second | `Settings.APP_BUILD_COST_PER_SECOND` | Registry SKU `app-build-second` |
| Hold history window (10 runs) | `credit_guard.py` | Platform setting |
| Abandoned checkout 24 h; 120 subscription cycles | `cron_service.py`, `credits_router.py` | Platform settings |
| Currency `USD` (orders, plans, transactions, UI) | `credits_router.py` (×4), `payment_service.py`, `billing_models.py`, all screens | Per-tenant billing currency (§13) |
| Top-up validity 365 days | `credit_service.add_to_wallet_balance` | Platform/plan setting |
| Daily credits expiry at 00:00 **UTC** | `credit_service._next_midnight` | Tenant time zone |
| Telephony per-started-minute rounding | `usage_logger.billed_minutes` | Per SKU (`billing_increment_seconds`, e.g. 60/30/1) |
| Fallback plans $29/$79/$199 | `WalletPage.tsx:44` | Remove; show "no plans" |

### 11.3 Missing configuration (needed, does not exist)

1. **Currency**: tenant billing currency, price books per currency, FX rates, rounding rules per currency (§13).
2. **Tax**: tax registration per company (GSTIN/VAT id), place of supply, rates (GST 18 % for India), reverse charge, tax-inclusive/exclusive display.
3. **Partner pricing**: a partner's own markup/price book for its tenants, its commission rate, payout terms (03).
4. **Per-tenant pricing in the UI**: the per-company billing config exists only in the API.
5. **Plan entitlements**: what a tier includes beyond credits (live sessions, runs/minute, sandbox size, seats, features, minimum floors).
6. **Top-up limits and packs**: minimum/maximum amount, preset packs, top-up bonus %, auto-recharge threshold and amount.
7. **Low-balance and spend alerts**: thresholds (e.g. 20 %/5 % of last top-up, % of cap) and recipients; the dunning e-mail template exists but nothing sends it.
8. **Credit policy for overruns**: allow negative balance up to a limit, or invoice the shortfall, or stop earlier (reserve for safe closure).
9. **Calls**: per-call hold (minutes × price), maximum call length, mid-call credit check interval.
10. **Billing of hosting/DB/storage**: periodic settlement schedule and whether these consume credits or go on an invoice.
11. **Grace and suspension**: what happens at zero (pause automation, block calls, suspend after N days past due).
12. **Invoice settings**: legal entity, invoice numbering series per country, PDF template, e-mail recipients.
13. **Who may pay**: restrict top-up/subscribe/cancel to admins (today any role).

---

## 12. Defects and risks found

| # | Finding | Evidence | Fix direction |
|---|---|---|---|
| B-1 | Call charge is all-or-nothing; if TB > balance nothing is deducted, but the billing event (revenue) is recorded | `websocket_handler.py:1638` uses `consume()`; exception logged | Use `consume_incremental` + debt record; per-call hold; mid-call breaker |
| B-2 | Hosting, DB share, usage with no run never deducted or invoiced; build cost and number rent never billed | `apps/metering.py:_bill`, `sandbox/metering.py`, `embedding_service.py`; no consumer of `run_id IS NULL` rows | A periodic "standalone usage" settlement (hourly/daily) applying TB, deducting, recording events |
| B-3 | Shortfall at settlement is forgotten | `governance_service._charge` → `consume_incremental` | Record a receivable (negative balance or `credit_debts`), block new work until settled |
| B-4 | Model with no price row → no usage row → free (tools at least write a "missing" row) | `usage_service.log_usage` returns None | Write a `cost_source: missing` row + event like tools; refuse task-default assignment to unpriced models |
| B-5 | Run charges go to `api_charge`; `llm/image/video_charge` unused for runs; groupings `partner/tenant/user` never written; runs grouped by **entity name** (renames split, same names merge) | `_charge` passes no `event_category`; `grouping_value=entity_name` | Split TB by attribution category; group by entity id; write per-tenant/partner rows or derive at query time |
| B-6 | Partner fee `spf` is charged on direct tenants too (global config) and is credited to no one | `calculate_tb`; no partner ledger | Partner-scoped pricing and a commission ledger (03) |
| B-7 | USD only; no tax; no invoices; no statements | §8–§10 | §13 |
| B-8 | Razorpay `key_secret` and `webhook_secret` in plain JSONB | `razorpay_gateway.get_razorpay_creds` | `secret_ref` → Key Vault (the registry already supports it) |
| B-9 | A tenant can register its own priced `API_TOOL` SKU (any price, incl. 0) that beats the platform price | `config/router.py` + resolver order | Separate "bring your own key" (no platform charge, explicit) from price ownership; prices only on platform/partner price books |
| B-10 | Settlement failures are swallowed — the run is free | `credit_guard.settle`, `_settle` | Persist a "settlement pending" state; retry job; alert |
| B-11 | Child-run gate fails open and ignores holds | `check_child_credit_gate` | Use `free` (minus holds); fail closed |
| B-12 | Breaker fails open on read errors | `check_credit_circuit_breaker` | Bounded tolerance (e.g. N consecutive failures then stop) |
| B-13 | `custom_daily_credits` on company creation is overwritten at the first balance read; `companies.default_daily_credits` is never read again | `company_router.py:79-96`, `flush_and_inject_daily_credits` | Create a per-company `billing_config` row instead |
| B-14 | Top-up amount has no server-side bounds; `int(amount*100)` truncates sub-cent values | `TopUpRequest` | `Field(ge=min, le=max, decimal_places=2)` |
| B-15 | Any role (incl. `tenant_user`) can top up, subscribe or cancel the subscription | `credits_router.py` uses `get_current_user` | Restrict to admins (configurable "billing manager" permission) |
| B-16 | Tier delete is a hard delete; tier fee edits leave no history | `delete_subscription_tier` | Archive only; versioned price history |
| B-17 | Daily credits expire at 00:00 UTC (05:30 IST) regardless of tenant time zone | `_next_midnight` | Tenant time zone |
| B-18 | `get_billing_config` uses `scalar_one_or_none` after `order_by` — two active rows for a company would raise | `billing_service.py:84` | Unique partial index `(company_id) WHERE is_active` |
| B-19 | Tenants see base cost (margin-revealing) in cost attribution while billing reports are hidden for that reason | `admin.py:546`, run pages | Show billed amounts to tenants; base cost to staff only |
| B-20 | Partner admin dashboard calls the app-admin-only `partner-performance` endpoint (403) and fails as a whole | `PartnerAdminDashboard.tsx:16` | Partner-scoped revenue endpoint (03) |
| B-21 | No rounding policy; amounts carry 6 decimals into wallets and reports | §3.1 | Round billed amounts per currency minor unit at settlement; keep base cost unrounded |
| B-22 | Dunning e-mail exists but is never sent; no low-balance or cap notifications | `common/email.py:196` | Notifications on `past_due`, low balance, cap reached |

---

## 13. Multi-currency and geography — design proposal

Today a tenant in India, the UK and the US all pay in USD, see `$`, and are invoiced nowhere. The product needs each tenant to be billed in its **own currency**, with correct tax, payable through a gateway that supports that currency, while the platform's costs stay in USD.

### 13.1 Principles

1. **Two currencies per amount.** Provider costs are USD and stay USD (*cost currency*). Each company has one **billing currency** (ISO 4217) in which its prices, wallet, payments, invoices and reports are expressed.
2. **Price in the customer's currency, not by naive conversion.** Each billing currency has a **price book**: the formula parameters, tier fees, top-up packs and any fixed prices in that currency. The conversion of base cost uses a published FX rate *with a buffer*, so FX movements do not erode margin.
3. **Lock the rate on every money event.** Each settlement, top-up and invoice line stores the rate id it used. Nothing is re-converted later.
4. **The wallet is in the billing currency.** A credit becomes "one unit of the tenant's currency" (₹1, £1, $1). Holds, floors, caps and alerts are in that currency.
5. **Round once, per currency.** Base costs keep 6 decimals in USD; billed amounts are rounded to the currency's minor unit (INR 2, USD 2, JPY 0) at settlement, half-up, with the remainder tracked.
6. **Geography drives defaults, not code.** Country → default currency, tax regime, time zone, calling-hours rules, phone country code, payment gateway.

### 13.2 Data model changes

```text
companies
  + country_code            CHAR(2)     -- ISO 3166, required for new companies
  + billing_currency        CHAR(3)     -- ISO 4217; immutable once money has moved (migration tool to change)
  + tax_id, tax_id_type     TEXT        -- GSTIN, VAT, EIN …
  + billing_address         JSONB       -- for place of supply and invoices
  + billing_entity_id       UUID        -- which HireBuddha legal entity bills them (IN / US / UK …)

currencies                  (code, minor_units, symbol, active)
fx_rates                    (id, base 'USD', quote, rate, source, fetched_at, valid_from)  -- daily snapshot
price_books                 (id, currency, scope: platform|partner, owner_company_id, version, effective_from, status)
price_book_items            (price_book_id, kind: formula|tier|topup_pack|fixed_sku|floor, key, amount/params)
tax_rules                   (country, region, rate, kind: GST/IGST/CGST+SGST/VAT, b2b/b2c, effective_from)

credit_wallets              + currency CHAR(3)
credit_holds                + currency
billing_events              + currency, + fx_rate_id, + base_cost_usd (keep), billed amounts in currency
payment_transactions        currency already exists → use it; + gateway ('razorpay'|'stripe'), + tax_amount
subscription_tiers          → price_book_items (fee per currency) or tier_prices (tier_id, currency, monthly_fee, gateway_plan_id)
usage_logs                  unchanged (USD base cost)
invoices, invoice_lines     new: number series per billing entity/country, currency, tax breakdown, PDF ref
```

### 13.3 Flow with currencies

1. **Cost** (unchanged): usage rows in USD.
2. **Settle**: `billed_ccy = round_ccy( TB_book(c_usd × fx(USD→ccy) × (1 + fx_buffer)) )`, where `TB_book` uses the formula parameters of the tenant's price book (platform book, or the partner's book for a partner's tenant — 03). Store `c_usd`, `fx_rate_id`, `billed_ccy`.
3. **Deduct** from the wallet in `ccy`.
4. **Admission/floors/caps** compare in `ccy` (floors come from the price book).
5. **Top-up**: the gateway order is created in `ccy` (Razorpay for INR — its native currency; Stripe or Razorpay international for others); the wallet is credited in `ccy`; tax computed on the invoice.
6. **Subscriptions**: one gateway plan per tier *and* currency.
7. **Invoices**: monthly statement per company in `ccy` (usage by category from billing events + top-ups/subscriptions as payments), with tax per `tax_rules` (India: CGST+SGST intra-state, IGST inter-state, 18 % on SaaS; export of services zero-rated with LUT), numbered per billing entity.
8. **Reports**: platform reports convert to a reporting currency (USD) using the locked rates — never sum different currencies.

### 13.4 Choices to decide (with recommendation)

| Decision | Options | Recommendation |
|---|---|---|
| Wallet unit | (a) USD credits shown in local currency; (b) wallet in billing currency; (c) abstract credits with per-currency price | **(b)** — what a customer pays is what they see and spend; no FX surprise between top-up and spend |
| Can a tenant change currency? | free / staff-only migration / never | **Staff-only migration**, which settles and converts the remaining balance at one locked rate |
| Partner currency | same as tenants / partner's own | A partner bills its tenants in **their** currency and is paid commission in the **partner's** currency |
| FX source and cadence | ECB / RBI reference / provider | Daily RBI/ECB reference, staff-overridable, with a configurable buffer (e.g. 2 %) |
| Pricing per currency | pure FX conversion / hand-set price books | Hand-set price books for tiers and packs (round, local prices); FX + buffer for usage |
| Gateway | Razorpay everywhere / per region | Razorpay for INR (and its international cards if enabled), Stripe for other currencies — a `PaymentGateway` interface |

### 13.5 Migration path

1. Add columns with defaults (`billing_currency='USD'`, `country_code` from time zone or onboarding); every existing amount is USD.
2. Introduce `fx_rates` and price books with one platform USD book reproducing today's `billing_config` exactly (no behaviour change).
3. Thread `currency` through wallet, holds, settlement, billing events (all `USD` at first) — tests prove identical numbers.
4. Add INR book + Razorpay INR orders/plans; onboard Indian tenants in INR; GST invoices.
5. Add the gateway interface and the next currency.

---

## 14. Improvements (billing and costing)

Grouped; priorities and order are in [04](04_consolidated_improvements.md).

**Correctness (stop leaks)**
1. Calls: incremental deduction, per-call hold sized on expected minutes, mid-call breaker with a graceful wind-down message (roadmap E04-S04) — B-1.
2. Standalone-usage settlement job for hosting, DB, storage, background embeddings and sandbox time — B-2; bill build seconds and number rent through SKUs.
3. Debt/receivable ledger for shortfalls; block new work until cleared — B-3, B-10.
4. Missing-price rows for LLMs; refuse unpriced models as task defaults — B-4.
5. Fail-closed child gate; bounded fail-open breaker — B-11, B-12.

**Ledger and reporting**
6. A real **credit ledger** (`wallet_entries`: every grant, deduction, expiry, refund, adjustment with its source) so balances are explainable and statements can be produced — today balances are mutable counters with no history.
7. Billing events split by attribution category and keyed by entity id; tenant/partner rollups.
8. Tenant **statements and invoices**; partner commission statements; transaction history UI.
9. Show tenants billed amounts, not base cost.

**Configuration**
10. Per-company pricing UI; plan entitlements; top-up packs/min/max/bonus; auto-recharge; low-balance alerts; dunning — §11.3.
11. Move hard-coded prices and floors into price books/registry — §11.2.
12. Restrict payment actions to admins; tier archive and price history; audit of every billing change.
13. Move Razorpay secrets to Key Vault (`secret_ref`).

**Commercial capability**
14. Multi-currency, tax and invoicing per §13.
15. Partner price books and commission ledger (03).
16. Plan changes with proration; annual plans; enterprise invoiced (post-paid) accounts with credit limits.
17. Budgets per process/agent and reserve envelopes (roadmap E04-F03).
