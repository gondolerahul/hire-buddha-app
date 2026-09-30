# 14. Billing, Costing & Credits — Defect Register

> **What this document is:** defects in how consumption turns into a charge — metering,
> the TB formula, the credit wallet, payments and the cron jobs — plus the improvements
> that would make the money path trustworthy.
> **Source document:** [`14-billing-and-credits.md`](../14-billing-and-credits.md)
> **Compiled:** 2026-09-01, against branch `fresh-main`.
> **Context:** there are **no paying tenants**, which is the only reason this register is
> not an emergency. Every item in T0 must close before the first one.

---

## How to read this file

- **✅ Verified** — the code was read on 2026-09-01 and the claim held.
- **📄 Doc-reported** — from `14-billing-and-credits.md`, not independently re-checked.
- Two findings reframe the whole subsystem and should be read before anything else:
  - **[BC-05](#bc-05--three-of-the-four-credit-gates-have-no-callers)** — the platform
    documents four credit enforcement points. Two of them, including the pre-run gate,
    have **zero callers**.
  - **[BC-01](#bc-01--the-client-chooses-how-much-to-credit-its-own-wallet)** — the wallet
    is credited with an amount supplied in the request body.

---

## Contents

1. [Summary](#1-summary)
2. [T0 — Money moves incorrectly](#2-t0--money-moves-incorrectly)
3. [T1 — Metering that under- or double-counts](#3-t1--metering-that-under--or-double-counts)
4. [T2 — Gates and jobs that never run](#4-t2--gates-and-jobs-that-never-run)
5. [T3 — Schema, access and dead weight](#5-t3--schema-access-and-dead-weight)
6. [Improvements](#6-improvements)
7. [Suggested order of work](#7-suggested-order-of-work)

---

## 1. Summary

| Tier | Theme | Count | When to do it |
|---|---|---|---|
| [T0](#2-t0--money-moves-incorrectly) | Money moves incorrectly | 8 | **Before the first paying tenant** |
| [T1](#3-t1--metering-that-under--or-double-counts) | Metering that under- or double-counts | 8 | Before any margin analysis |
| [T2](#4-t2--gates-and-jobs-that-never-run) | Gates and jobs that never run | 5 | Before relying on the control |
| [T3](#5-t3--schema-access-and-dead-weight) | Schema, access and dead weight | 8 | Now — mostly cheap |

**Total: 29 defects, 10 improvements.**

The three to read first:

- **[BC-01](#bc-01--the-client-chooses-how-much-to-credit-its-own-wallet)** — verify a $1
  payment, claim $1000, replay it indefinitely.
- **[BC-05](#bc-05--three-of-the-four-credit-gates-have-no-callers)** — a normal agent run
  has no pre-execution credit gate and no in-run circuit breaker.
- **[BC-03](#bc-03--subscribing-strands-the-wallet-and-grants-nothing)** — a complete
  pay-and-get-nothing path.

---

## 2. T0 — Money moves incorrectly

### BC-01 — The client chooses how much to credit its own wallet

**✅ Verified · Critical** · **Status: fixed (2026-09-30)** — the stored order amount is
credited, once; the verify request has no amount.

The Razorpay signature check is correct — HMAC-SHA256 over `order_id|payment_id`, compared
with `hmac.compare_digest`. What happens after it is not.

```python
txn.status = "success"
txn.credits_awarded = payload.amount
...
wallet = await credit_svc.add_wallet_credits(
    company_id=current_user.company_id,
    amount=payload.amount,          # ← straight from the request body
)
```

Three problems in six lines:

1. **The amount comes from the request body.** The stored `PaymentTransaction.amount` is
   never read, and Razorpay is never asked. A client can pay $1 and verify with
   `amount: 1000`.
2. **No idempotency.** `txn.status` is not checked. The same valid
   `(order_id, payment_id, signature)` triple credits the wallet again on **every** replay.
3. **No unique constraint** on `razorpay_order_id` — it is indexed, not unique.

There is also no server-to-server webhook. Verification is a browser-initiated callback,
so the client is the only participant in the trust chain.

- [`billing/credits_router.py:146`](../../../backend/src/billing/credits_router.py:146) — `verify_topup`
- Also recorded as **D-01** in the platform register

**Fix:** credit `txn.amount`, reject when `txn.status == "success"`, and add a unique
constraint on `razorpay_order_id`. Then add the server-side webhook.

**Done (2026-09-30).** `billing/payment_service.py` — `PaymentService.credit_topup` — is the
one place a top-up turns into credit; the webhook (BC-I5) will use it too.

- It finds the **caller's** `topup` transaction by order id (404 if there is none — before,
  an order that was never created was credited anyway, as was another company's), locks the
  row, and credits `txn.amount`. A row already `success` is not credited again: the response
  says *Payment already credited* with `credits_added: 0`.
- `TopUpVerify` has no `amount`; the wallet page no longer sends one.
- Migration `bc01_payment_txn_unique`: partial unique indexes on `razorpay_order_id` and
  `razorpay_payment_id` (where not null), replacing the plain order-id index.
- The wallet row is updated under a row lock (`CreditService.lock_wallet`), and a top-up no
  longer revives a balance that had already expired — it used to add to the stale balance
  and restart its 365 days.
- The duplicate `"message"` key in the response is gone (half of BC-25).

The server-to-server webhook is [BC-I5](#bc-i5--add-the-razorpay-webhook).

**Evidence:** `tests/integration/test_topup_verify.py`, 6 cases against the real Postgres in
a rolled-back transaction: a $10 order verified with `amount: 1000` credits 10; three
verifies of one payment credit it once; a bad signature is 400; an invented order and
another company's order are 404 and credit nothing; an expired $40 balance plus a $10
top-up is $10. Five fail on the old code for the reason each describes (1000 credited, the
replay credited again, both foreign orders credited, the expired balance revived); the
signature case passes on both.

---

### BC-02 — Switching to a subscription makes the existing balance unspendable

**✅ Verified · Critical** · **Status: fixed (2026-09-30)** — every bucket is spendable,
soonest-expiring first; `account_model` no longer gates spending.

The deduction path is an `if` / `elif` on `account_model`:

```python
# 2a. PAYG — consume wallet balance
if remaining > 0 and wallet.account_model == "pay_as_you_go":
    ...
# 2b. Subscription — consume subscription credits then bonus
elif remaining > 0 and wallet.account_model == "subscription":
    ...
```

The moment `account_model` flips to `"subscription"`, any remaining `wallet_balance` — real
money the customer paid for — becomes unreachable. It still shows in the balance API and
can never be spent.

- [`billing/credit_service.py:161`](../../../backend/src/billing/credit_service.py:161) and [`:170`](../../../backend/src/billing/credit_service.py:170)

**Fix:** make 2a an independent `if`, or migrate the balance into subscription credits on
switch. The first is one word.

**Done (2026-09-30).** Not quite one word: the same `if`/`elif` also stopped a company that
cancelled from spending its remaining subscription credits, and `consume` checked the
balance across all four buckets and then deducted from only some, so it could return
"success" having taken less than asked. `consume` and `consume_incremental` (two copies of
the branch) now share one `deduct`, which walks `SPEND_ORDER` — daily, subscription,
subscription bonus, wallet balance: soonest to expire first. `account_model` only labels the
account. Found on the way and fixed with it:
[BC-27](#bc-27--concurrent-deductions-overwrite-each-other) (lost updates).

**Evidence:** `tests/integration/test_credit_consumption.py`, 7 cases against the real
Postgres: a subscriber with $5 of subscription credit and a $20 balance spends $15 (was: $5
taken, $15 asked); spending order across all four buckets; a PAYG company spends leftover
subscription credit; `consume` is all-or-nothing; `consume_incremental` drains all four and
reports the shortfall (was: $3 short of $6 with $4 held); expired buckets read as zero; and
the BC-27 race. Five fail on the old code.

---

### BC-03 — Subscribing strands the wallet and grants nothing

**✅ Verified · Critical** · **Status: fixed (2026-09-30)** — subscriptions are Razorpay
Subscriptions; the first payment grants its cycle's credits at verification.

Three confirmed facts compound into a complete pay-and-get-nothing path:

1. `verify_subscription` sets `sub.status = "active"` and
   `wallet.account_model = "subscription"` and **never calls
   `inject_subscription_credits`**.
2. The `if`/`elif` above then makes the existing balance unspendable
   ([BC-02](#bc-02--switching-to-a-subscription-makes-the-existing-balance-unspendable)).
3. The only caller of `inject_subscription_credits` is the monthly cron, which
   **nothing schedules** ([BC-04](#bc-04--the-billing-crons-are-never-scheduled)).

Net effect: a subscriber pays, loses access to their existing balance, and receives no
credits until a human manually POSTs a cron endpoint.

- [`billing/credits_router.py:416`](../../../backend/src/billing/credits_router.py:416) — `verify_subscription`
- [`billing/credit_service.py:204`](../../../backend/src/billing/credit_service.py:204) — `inject_subscription_credits`
- Also recorded as **D-02** in the platform register

**Done (2026-09-30).** Product decision: renewal is a real Razorpay Subscription (a recurring
mandate), not a prepaid month. BC-02 had already made the wallet balance spendable. Now:

- `POST /credits/subscriptions {tier_level}` makes the tier's Razorpay plan on first use
  (stored as `subscription_tiers.razorpay_plan_id`, migration `bc03_tier_razorpay_plan`;
  cleared when the tier's fee changes), creates a Razorpay subscription on it, and stores the
  row `pending_payment` **with** its `razorpay_subscription_id` (BC-16). A company with a live
  subscription gets 409.
- The wallet page opens checkout with `subscription_id`; `POST /credits/subscriptions/verify`
  checks the subscription signature (`payment_id|subscription_id`) and calls
  `PaymentService.record_subscription_charge`, which records the payment
  (`subscription_charge`, keyed on the unique payment id) and grants the fee plus bonus until
  the end of the paid cycle (Razorpay's `current_end`). Each later month arrives as the
  `subscription.charged` webhook and goes through the same function — once per payment
  whichever path brings it; an older payment recorded late cannot replace a newer cycle.
- The other `subscription.*` webhook events copy Razorpay's status (`past_due` on a failed
  charge, `paused`, `cancelled`); cancelling cancels the Razorpay subscription **first** and
  answers 502, changing nothing, if Razorpay refuses. Credits paid for stay until they expire.
- Found on the way: the wallet page sent `plan_tier`, the API required `tier_level`, so
  subscribing had always failed with 422 — [BC-28](#bc-28--subscribing-always-fails-with-422).

**Evidence:** `tests/integration/test_subscriptions.py`, 13 cases with Razorpay replaced by an
in-memory fake (routes, services and Postgres real): the wallet page's request creates a
subscription and plan, and a second subscriber reuses the plan; verification grants
$79 + $23.70 once — a repeat and the `subscription.charged` webhook for the same payment
grant nothing; a bad signature grants nothing; the next month's charge replaces the credits;
halted → `past_due`, cancelled → `cancelled` with the account pay-as-you-go again and the paid
credits kept; a Razorpay cancel failure is a 502 with the row unchanged; one live
subscription per company; the reconciliation cases under BC-04; a fee change retires the
plan. On the old code: the wallet page's request got 422, and verification returned 200
with `account_model: subscription` and **$0** of subscription credit. Live on the local API
(temporary `razorpay_keys` row): a signed `subscription.charged` granted $79 + $23.70, its
replay nothing, `subscription.halted` → `past_due`, `subscription.cancelled` → `cancelled`
and pay-as-you-go. The Razorpay API calls themselves (plan, subscription, cancel, invoices)
were not exercised live — there is no Razorpay test account here.

---

### BC-04 — The billing crons are never scheduled

**✅ Verified · Critical** · **Status: fixed (2026-09-30)** — both jobs are Arq crons; the
daily one renews only expired credits; the monthly one no longer grants unpaid credits.

`WorkerSettings.cron_jobs` registers seven jobs: CORTEX resumption, dreaming, critic
calibration, skill promotion, prompt evolution, KPI rollup and cost-estimator refresh.

It registers **no daily-credit job and no monthly-billing job**. Both exist only as HTTP
endpoints under `/api/v1/cron` that an `app_admin` has to click.

There is no APScheduler, no systemd timer and no crontab anywhere in the repository.
Daily credits work only through a lazy self-heal in `get_balance`; monthly subscription
credits are never injected at all.

Two further problems in the same jobs:

- Re-running the daily job **resets** rather than tops up:
  `wallet.daily_credits = daily_amount` is an assignment.
- The monthly job does not charge anyone. Its Razorpay branch is
  `if razorpay_client and sub.razorpay_subscription_id:` — and
  `razorpay_subscription_id` is **never populated anywhere in the codebase**, so the branch
  is always skipped. Inside it, the `try` block contains only a log line, so the `except`
  that would set `past_due` is unreachable. The job records a `success` transaction and
  grants credits **regardless of whether money moved**.

- [`ai/worker.py`](../../../backend/src/ai/worker.py) — the `cron_jobs` list
- [`billing/cron_service.py:87`](../../../backend/src/billing/cron_service.py:87) — the unreachable branch
- Also recorded as **D-03** in the platform register

**The monthly job (2026-09-30, with BC-03).** Renewal is Razorpay's now, so the job no longer
grants anything by itself. `run_subscription_reconciliation` (the `/cron/monthly-billing`
endpoint still calls it) asks Razorpay for each pending or live subscription's invoices and
grants each cycle whose invoice is `paid` and whose payment is not yet recorded — a
`subscription.charged` webhook that never arrived — then copies Razorpay's status.
Subscriptions from the old one-time-order flow, which nothing can renew, end when the month
they paid for ends. **Evidence:** `test_subscriptions.py` — an active subscription with no
paid invoice gets nothing and no transaction row (the old job, run on the old code, granted
$79 + $23.70 and wrote a `success` transaction with no payment id); a missed paid invoice is
granted once across two runs and a past-due subscription becomes active; an old-flow
subscription past its month is cancelled.

**Scheduling and the daily job (2026-09-30).** `billing/jobs.py` wraps both `CronService`
methods as Arq jobs, registered in `WorkerSettings.cron_jobs`: `billing_daily_credits` at
00:00 UTC and `billing_subscription_reconciliation` at 01:30 UTC. The daily job calls
`CreditService.renew_expired_credits`, which renews only credits that have expired (under the
wallet lock, BC-27), so running it again the same day changes nothing. It also reaps
abandoned checkouts ([BC-18](#4-t2--gates-and-jobs-that-never-run)). **Evidence:**
`tests/integration/test_billing_crons.py` — the worker schedules both; a wallet with $1.25 of
unexpired daily credit still has $1.25 after two runs (the old job: back to $5); expired
credits are renewed; the reaper cases under BC-18. Four of five fail on the old code. Live:
the restarted worker lists `cron:billing_daily_credits` and
`cron:billing_subscription_reconciliation`; the job run twice against the local database
renewed or created all 165 wallets on the first run and changed nothing on the second.

---

### BC-05 — Three of the four credit gates have no callers

**✅ Verified · Critical** · **Status: fixed (2026-09-30)** — every top-level run is admitted on
credit and stopped by a circuit breaker; triggering without free credit is a 402.

`14-billing-and-credits.md` and `01-product-overview.md` both describe credit enforcement
at four points in a run. Grepping for call sites:

| Gate | Purpose | Callers in `backend/src` |
|---|---|---|
| `check_credit_gate` | refuse to start on an empty wallet | **none** |
| `consume_step_cost` | incremental deduction after each step | **none** |
| `check_credit_circuit_breaker` | stop a run mid-flight | **none** |
| `CreditService.require_credits` | assert before spending | **none** |
| `check_child_credit_gate` | before spawning a child | [`step_executor.py:236`](../../../backend/src/ai/step_executor.py:236) ✅ |
| `settle_billing` | final settlement | [`agent_loop.py:1134`](../../../backend/src/ai/core/agent_loop.py:1134) ✅ |

So a normal agent run has **no pre-execution credit gate and no in-run circuit breaker**.
The whole cost of a run accrues and is only debited at the end, and a run started with a
zero wallet runs to completion.

The user-facing message *"Partial results saved. Please top up credits and retry."* comes
from a code path that never executes.

All four unused methods are defined and unit-tested, which is why this survived.

**Fix:** call `check_credit_gate` at run start and `check_credit_circuit_breaker` after each
step, from `AgentLoop`. Both already exist and both are tested.

**Done (2026-09-30), with BC-06.** `ai/core/credit_guard.py` (`CreditGuard`) is the credit
side of an `AgentLoop` run, top-level runs only (a child spends its parent's credit):

- **Admit**, in `AgentLoop.run` before any billable work (before memory assembly and
  planning): `check_credit_gate` now places the run's hold (BC-06) with the entity type's
  floor. Refused → the run ends `FAILED` with the reason, nothing billed. The gate no longer
  swallows errors: a wallet that cannot be read does not let a run start.
- **Check**, after every iteration in `AgentLoop._loop`: `check_credit_circuit_breaker`
  compares the run's bill so far — `state.budget.usd_used`, the same cost settlement bills,
  **through the TB formula** (the old breaker compared raw cost with the balance) — with the
  wallet minus other runs' holds. Exhausted → `CreditExhaustedError` → the run finishes
  `PARTIAL_COMPLETE` with *"… Partial results saved. Please top up credits and retry."*,
  and is billed for the work done.
- **Settle**: `AgentLoop._settle_billing` moved into the guard; settlement releases the hold.
- `AIService.trigger_execution` calls `require_credits` with the floor: a 402 at once instead
  of a run that fails in the worker.
- `consume_step_cost` is deleted: with holds and the breaker the wallet is still debited
  once, at settlement.

**Evidence:** `tests/integration/test_run_credit_guard.py`, 8 cases against the real Postgres:
an empty wallet is refused with no hold; an admitted run holds its estimate and
`GET /balance` reports it as `held`; two runs cannot be admitted on the same $1 (the second
is refused until the first settles and releases); a finished run's unreleased hold stops
counting; the breaker lets a bill under $1 continue and stops one over it; another run's
hold counts against the breaker; child runs are not gated; `trigger_execution` on an empty
wallet is a 402 and writes no run. `tests/unit/test_governance_service.py` covers the gate's
floor, its fail-closed error handling and the breaker's TB arithmetic. The three agent-loop
unit modules, which drive the loop on a fake session, stub admission and the breaker.
Live, through the real worker, on the local `deep-research-v2` process with the company's
wallet set to $0: `trigger_execution` answered 402 (*Required: $0.5000, Free: $0.0000*),
and a run queued without the API check ended `FAILED` in the worker with *Cannot start
execution: $0.0000 of credit is free …*, $0 cost, $0 billed. With $0.55: the run was admitted
and held $0.50 while running, and the hold was released when it ended. That run then failed
for an environmental reason — Vertex ADC had expired, so no LLM call succeeded — so the
breaker stopping a *real* run mid-flight is not yet shown live; the integration tests cover
it.

---

### BC-06 — There are no holds, so one run can overdraw

**📄 Doc-reported · High** · **Status: fixed (2026-09-30)** — a top-level run holds its
estimated bill from admission to settlement; the breaker (BC-05) bounds a single run.

Cost accrues on the run and the wallet is debited only at settlement. With no reservation
and — per [BC-05](#bc-05--three-of-the-four-credit-gates-have-no-callers) — no in-run
breaker either, a single expensive run can spend far beyond the available balance and the
platform discovers it at the end.

`Budget.usd_max` defaults to **$100**, two orders of magnitude above the $0.50 `PROCESS`
credit floor. So the in-loop budget will not stop it either.

- Also recorded as **D-37** in the platform register

**Done (2026-09-30).** Table `credit_holds` (migration `bc06_credit_holds`): one row per
top-level run, placed at admission (`CreditService.place_hold`, under the wallet row lock so
admissions are serialised per company) and released at settlement. The amount is the run's
estimated bill — the larger of its plan estimate through the TB formula and the average
`billed_amount` of the entity's last ten finished top-level runs — at least the floor and at
most what the company can spare (wallet minus other unfinished runs' holds). A hold whose
run has finished stops counting even if it was never released. Overdraw within one run is
bounded by the BC-05 breaker to the cost of the iteration that crossed the line.
**Evidence:** the BC-05 tests above — in particular two runs on one $1 balance.

---

### BC-27 — Concurrent deductions overwrite each other

**✅ Verified · High** · **Status: fixed (2026-09-30)** — found while fixing BC-02.

Every wallet change was read-modify-write in Python with no lock: read `wallet_balance`,
subtract, assign, commit. Two sessions doing it at once each wrote their own result over the
other's. Concurrent runs of one company settling, a voice call deducting while a run
settles, or a top-up landing mid-settlement each lose money for one side — the platform's
when a deduction is lost, the customer's when a top-up is.

- [`billing/credit_service.py`](../../../backend/src/billing/credit_service.py) — `consume`,
  `consume_incremental`, `add_wallet_credits`, `inject_subscription_credits`

**Fix (2026-09-30):** every change goes through `CreditService.lock_wallet` — `SELECT … FOR
UPDATE` with `populate_existing`, so the values changed are the ones read under the lock.
Wallet creation is `INSERT … ON CONFLICT DO NOTHING` (two first requests used to race on the
unique `company_id`).

**Evidence:** `test_concurrent_deductions_are_not_lost` — three sessions each make five $1
deductions from a $100 wallet at once: $85 left. On the old code, $92: seven of the fifteen
deductions were lost.

---

### BC-28 — Subscribing always fails with 422

**✅ Verified · High** · **Status: fixed (2026-09-30)** — found while fixing BC-03.

The wallet page's **Subscribe** button posted `{plan_tier, monthly_fee}` to
`POST /credits/subscriptions`; the API's `SubscriptionCreate` requires `tier_level`. Every
click was a 422 (*Field required: tier_level*), shown as "Subscription initiation failed". No
one could ever subscribe from the UI — which is also why BC-03's pay-and-get-nothing path had
never been hit.

- [`frontend/src/services/credits.service.ts`](../../../frontend/src/services/credits.service.ts) — `createSubscription`

**Fix (2026-09-30):** `createSubscription(tierLevel)` sends `{tier_level}`. **Evidence:**
`test_the_wallet_pages_request_creates_a_razorpay_subscription`; the old payload against the
old code: 422.

---

## 3. T1 — Metering that under- or double-counts

### BC-07 — Fixed-cost tool charges write no `usage_logs` row

**📄 Doc-reported · High** · **Status: fixed (2026-09-30)** — `usage_logs.sku_id` is nullable
(migration `bc07_usage_log_sku_nullable`); the row is written without a SKU, with the tool's
name in `log_metadata`, and the usage-breakdown report outer-joins the registry to show it.
**Evidence:** `tests/integration/test_tool_metering.py`, 7 cases through
`StepExecutorService._charge_tool` on the real Postgres, and
`tests/unit/test_tool_cost_resolver.py` / `test_cost_attribution.py`. `test_a_fixed_cost_tool_is_charged_once_with_a_line_item`,
`test_a_fixed_cost_charge_appears_in_the_usage_breakdown`.

`image_generation` ($0.04) and `video_generate` ($0.05) bump `run.total_cost_usd` directly
but write **no** `usage_logs` row, because `sku_id` is `NOT NULL` and there is no SKU.

So the attribution dashboard and the usage-breakdown report under-report against the
wallet. The money is charged and the line item does not exist, which makes
"why was I charged $X?" unanswerable for exactly those tools.

---

### BC-08 — Image generation is charged twice

**✅ Verified · High** · **Status: fixed (2026-09-30)** — confirmed in the code: the tool
recorded a billing event and called `CreditService.consume` at raw cost, on top of the
executor's charge and the run's settlement at TB. The tool's billing block (and its own price
map) is deleted; the executor charges it once. **Evidence:** `tests/integration/test_tool_metering.py`, 7 cases through
`StepExecutorService._charge_tool` on the real Postgres, and
`tests/unit/test_tool_cost_resolver.py` / `test_cost_attribution.py`. `test_the_image_tool_no_longer_bills_the_wallet_itself`.

`image_generation` self-bills $0.04 inside the tool via `BillingService`, **and** is
charged again by the executor's fixed-cost branch at TB.

A guaranteed double charge on that branch. Recorded in the tool layer as part of
[TL-19](TOOL-LAYER-DEFECTS.md#tl-19--four-price-tables-one-of-which-is-the-unused-source-of-truth).

---

### BC-09 — `attribution="actor_step"` is never written

**✅ Verified · High** · **Status: fixed (2026-09-30)** — `StepExecutorService._log_usage`
passed no attribution, so `UsageService` recorded `tool`. It now tags a step's LLM call
`actor_step` and a tool-input reformat call `reformat_retry`. **Evidence:** `tests/integration/test_tool_metering.py`, 7 cases through
`StepExecutorService._charge_tool` on the real Postgres, and
`tests/unit/test_tool_cost_resolver.py` / `test_cost_attribution.py`. `test_a_steps_llm_spend_is_attributed_to_the_step`.

Step LLM spend — usually the majority of a run's cost — lands under `tool` instead of
`actor_step`.

The Cost Attribution dashboard's entire purpose is to show where money goes. Its largest
bucket is mislabelled, which means every conclusion drawn from it about planner-vs-critic-
vs-tool cost is wrong.

---

### BC-10 — The tool cost path ignores `cost_unit` and has no APP fallback

**✅ Verified · High** · **Status: fixed (2026-09-30)** — `ToolCostResolver` falls back to the
platform (APP) company's row when the tenant has none, and divides a registry price by its
`cost_unit` (`usage_service.unit_divisor`, now shared with the LLM path). **Evidence:** `tests/integration/test_tool_metering.py`, 7 cases through
`StepExecutorService._charge_tool` on the real Postgres, and
`tests/unit/test_tool_cost_resolver.py` / `test_cost_attribution.py`.
`test_a_tenant_without_its_own_row_pays_the_platform_price`,
`test_a_per_thousand_price_is_charged_per_call`.

Two separate gaps in one path:

1. `cost_unit` is ignored, so a per-1M-token SKU is billed as if it were per-unit.
2. There is no fallback to the APP company's SKU, unlike the LLM path.

Net effect: **an unseeded tenant's tools are free.** Nothing warns; the rows simply are not
written.

---

### BC-11 — Four price tables, and the intended source of truth is unused

**✅ Verified · High** · **Status: fixed (2026-09-30)** — `ToolCostResolver` is the one price
lookup: both tool paths in `step_executor` call `_charge_tool`, which calls it and adds the
amount atomically; the two inline tables are deleted, and so is the image tool's own price
map. `cost_estimator` keeps its telemetry-refreshed *estimates* but takes fixed-cost tools'
prices from `TOOL_FIXED_COST`, so an estimate cannot disagree with the charge (it said $0.10
for `video_generate`, which charged $0.05). Found on the way:
[BC-29](#bc-29--any-custom-api-registry-row-prices-every-tool). **Evidence:** `tests/integration/test_tool_metering.py`, 7 cases through
`StepExecutorService._charge_tool` on the real Postgres, and
`tests/unit/test_tool_cost_resolver.py` / `test_cost_attribution.py`.

`ToolCostResolver` was built as the single cached source of truth. It has **zero production
callers**. The live logic is two hand-copied blocks of `_TOOL_SKU_MAP` / `_TOOL_FIXED_COST`
literals in `step_executor.py`, plus a fourth table in `planning/cost_estimator.py`.

The flag intended to switch it on, `tools.cost_resolver_v2_enabled`, defaults to `True` and
**is never read**.

Adding one priced tool means editing four files, and forgetting one produces a silent
mis-charge.

- [`ai/governance/tool_cost_resolver.py`](../../../backend/src/ai/governance/tool_cost_resolver.py) — unused
- [`ai/step_executor.py:452`](../../../backend/src/ai/step_executor.py:452) and [`:923`](../../../backend/src/ai/step_executor.py:923) — the two inline copies
- [`ai/planning/cost_estimator.py`](../../../backend/src/ai/planning/cost_estimator.py) — the fourth table

---

### BC-29 — Any custom-API registry row prices every tool

**✅ Verified · High** · **Status: fixed (2026-09-30)** — found while fixing BC-11.

Both inline tool-cost lookups (and the unused resolver) matched a registry row with
`service_sku = tool_id OR service_category = 'CUSTOM_API' OR …` and `LIMIT 1`. A company with
one custom-API row — say a CRM integration at $0.75 per call — was charged $0.75 for every
`calculator`, `web_search` or other tool call that had no row of its own.

**Fix (2026-09-30):** the lookup matches only the tool's own SKUs (`tool_id` and
`TOOL_SKU_MAP[tool_id]`). **Evidence:** `test_a_custom_api_row_does_not_price_other_tools`
(a $0.75 `CUSTOM_API` row, then `calculator`: $0), and the unit test on the lookup's SQL.

---

### BC-12 — Telephony minutes are rounded two different ways

**✅ Verified · Medium** · **Status: fixed (2026-09-30)** — one rule, per started minute
(`voice/usage_logger.billed_minutes`: 125 s is 3 minutes); the usage log and the billing event
both use it. **Evidence:** `tests/integration/test_billing_overrides.py` —
`test_minutes_are_billed_per_started_minute`, and the event records the 3 minutes it is given.

The **usage log** ceiling-rounds to whole minutes. The **billing event** records a
fractional minute count. The two never agree, so telephony reconciliation between the
ledger and the monthly aggregate always shows a discrepancy.

---

### BC-13 — `base_cost_llm` is read and then ignored; `base_cost_telephony` overwrites

**✅ Verified · High** · **Status: fixed (2026-09-30)** — each override is applied where the cost
is computed, so the charge and the report agree; `base_cost_llm` is retired.

Worse than recorded: the telephony override changed only the *billing event* — the voice
cleanup charged the wallet `TB(total_cost)` before recording it — so the report and the charge
disagreed whenever it was set. And an override, once set, could never be cleared (the page
sent `undefined` for an empty field, and the service ignored `None`).

**Fix (2026-09-30):**

- `VoiceUsageLogger.log_voice_session_usage` returns the call's telephony part and billed
  minutes with its total. `BillingService.voice_base_cost` replaces only the telephony part
  with `base_cost_telephony × minutes`; that one base cost is charged (through TB) and
  recorded. `record_billing_event` no longer applies overrides.
- `base_cost_image_gen` is applied by `ToolCostResolver` to `image_generation` — before, only
  the image tool's own (double) billing event used it, and that is gone (BC-08).
- `base_cost_llm` had no unit and nothing applied it: removed from the API and the Billing
  Settings page; `BillingConfigUpdate` forbids unknown fields, so sending it is a 422. The
  column stays, unused.
- `PUT /billing/config` changes only the fields sent; an override sent as `null` is cleared,
  a formula field sent as `null` is left alone. The page sends `null` for an emptied override.

**Evidence:** `tests/integration/test_billing_overrides.py`, 8 cases on the real Postgres: a
3-minute call of $0.06 carrier + $0.20 speech with a $0.01/min override costs $0.23 (the old
event recorded $0.03); no override leaves $0.26; the event records the base it is given; the
image override prices `image_generation`; an override is cleared by `null` while a formula
field is not; `base_cost_llm` is a 422.

In `record_billing_event`:

- `base_cost_llm` is read and its branch body is `pass`, with the comment *"Assuming base
  cost provided is directly overridden"*. The Billing Settings UI still exposes the field.
- `base_cost_telephony` **replaces** the entire `base_cost`, discarding the voice LLM audio
  cost that was passed in.

So one pricing override does nothing, and the other silently deletes a real cost component.

- [`billing/billing_service.py:126`](../../../backend/src/billing/billing_service.py:126)

---

## 4. T2 — Gates and jobs that never run

| ID | Item | Reality | Status |
|---|---|---|---|
| **BC-14** | `check_credit_gate`, `consume_step_cost`, `check_credit_circuit_breaker`, `require_credits` | Defined, unit-tested, **zero callers**. See [BC-05](#bc-05--three-of-the-four-credit-gates-have-no-callers) | ✅ fixed (2026-09-30) with BC-05 — the gate, breaker and `require_credits` are called; `consume_step_cost` is deleted |
| **BC-15** | The daily and monthly cron jobs | Endpoints only; nothing schedules them. See [BC-04](#bc-04--the-billing-crons-are-never-scheduled) | ✅ fixed (2026-09-30) with BC-04 — Arq crons at 00:00 and 01:30 UTC |
| **BC-16** | `razorpay_subscription_id` | Declared on the model, **never populated**, so the monthly job's charge branch is always skipped | ✅ fixed (2026-09-30) with BC-03 — set when the Razorpay subscription is created; every charge and status change is matched on it |
| **BC-17** | `tools.cost_resolver_v2_enabled` | Declared with default `True`, **never read**. Adding a flag is not the same as wiring a control | ✅ fixed (2026-09-30) with BC-11 — the flag is deleted; the resolver is used unconditionally |
| **BC-18** | Abandoned checkouts and orphaned subscriptions | A `pending` `payment_transactions` row stays forever; a `pending_payment` subscription with no matching payment stays forever. Nothing reaps either, and a failed payment is never recorded | ✅ fixed (2026-09-30) — the daily job marks a top-up order still `pending` after 24 h `expired` and a subscription still `pending_payment` `failed` (cancelling its Razorpay subscription); a payment that arrives later for an expired order is still credited. A failed top-up payment is recorded by the webhook (BC-I5). `test_billing_crons.py` |

---

## 5. T3 — Schema, access and dead weight

### BC-19 — `partner_admin` can edit platform-wide pricing

**✅ Verified · Critical** · **Status: fixed (2026-09-30)** — confirmed: `PUT /billing/config`
allowed `partner_admin` with any `company_id`, `null` included, and the tier create/update
routes allowed it too (tiers are platform-wide). Product decision: pricing is `app_admin` only.
All four write routes now use `RoleChecker(["app_admin"])`. **Evidence:**
`tests/unit/test_billing_config_access.py` (21 cases; 16 fail on the old code). Live on the local API: a `tenant_admin` gets 403 reading and writing `/billing/config` and creating a tier, `app_admin` gets 422 for `platform_fee_pct: 15` (*Input should be less than or equal to 1*) and 200 reading the config, and the tier list is 401 without a token and 200 with one.

`PUT /billing/config` reportedly accepts `company_id: null` from a `partner_admin`, writing
the **global default row that every tenant inherits**.

A reseller can therefore change the platform's pricing for every other reseller's tenants.

- [`billing/billing_router.py`](../../../backend/src/billing/billing_router.py)
- Also recorded as **D-10** in the platform register

**Fix:** `app_admin` only for `company_id: null`. Verify before launch — this is the one
📄 entry in this file that most deserves a re-check.

---

### BC-20 — Two open endpoints on the money surface

**✅ Verified · High** · **Status: fixed (2026-09-30)** — the costing half by PO-04, the tier list
now needs a signed-in user.

| Endpoint | Guard |
|---|---|
| `GET /reports/costing` | `get_current_user` only — **no role check**. Any user reads their company's raw provider cost and infers the markup |
| `GET /credits/subscription-tiers` | `db: AsyncSession = Depends(get_db)` — **no auth at all** |

The sibling POST/PUT/DELETE routes on the subscription-tiers path *are* admin-gated. Only
the read is open.

- [`billing/billing_router.py:148`](../../../backend/src/billing/billing_router.py:148)
- [`billing/credits_router.py:199`](../../../backend/src/billing/credits_router.py:199)
- Also **D-08** and **D-09**; see
  [PO-04](01-PRODUCT-OVERVIEW-DEFECTS.md#po-04--any-logged-in-user-can-read-the-internal-cost-report)

> **Update 2026-09-29:** the costing half is fixed by PO-04 (`682da36`) — `GET /reports/costing`
> and `GET /reports/billing`, which returned the same rows, are `app_admin` only. The open
> `GET /credits/subscription-tiers` still stands. A third open read on the same surface,
> `GET /billing/config`, is recorded as [BC-26](#bc-26--any-user-can-read-the-billing-multiplier-and-base-costs).
>
> **Update 2026-09-30:** fixed. `GET /credits/subscription-tiers` requires a signed-in user
> (any role — the wallet page lists the plans); anonymous is a 401. See BC-19 for the evidence.

---

### BC-21 — Percentages and fractions are mixed, with the wrong label

**✅ Verified · High** · **Status: fixed (2026-09-30)** — `BillingConfigUpdate` range-checks
`platform_fee_pct`, `sales_partner_fee_pct`, `discount_pct` to 0–1, `multiplier_factor` to
(0, 100], daily credits and overrides to ≥ 0; tier `bonus_pct` (a percentage) to 0–100 and the
fee to > 0. Out of range is a 422. The Billing Settings page labels the three as fractions,
limits the inputs to 0–1, shows the percentage under each (*= 15.0%*), and shows a 422's
messages instead of trying to render its `detail` list. **Evidence:** as BC-19 — six
out-of-range bodies are 422 with nothing saved; 0.15 saves.

`pf`, `spf` and `d` are **fractions** (`0.15`). `SubscriptionTier.bonus_pct` is a
**percentage** (`30.0`). The Billing Settings UI labels the first group "%" anyway.

An admin entering `15` where `0.15` is meant configures a **1500% platform fee**. Nothing
validates the range.

**Fix:** validate `0 ≤ pf, spf, d ≤ 1` on write and fix the label. Two minutes, and it
prevents a mis-billing that would be very hard to unwind.

---

### BC-22 — The seeded default is not at cost

**📄 Doc-reported · Medium · not a bug**

The global default is `mf=1.3`, `pf=0.15`, `spf=0.10` — every tenant pays **1.625× raw
cost** by default.

Recorded because any pricing analysis assuming `mf=1.0` is wrong, and because the
"identity formula" fallback (`mf=1, pf=spf=d=0`) applies only when **no** config row
exists at all.

---

### BC-23 — `subscription_tiers` has no migration

**✅ Verified · High**

Referenced by the ORM, the credits router and the seed path; created by nothing in
`backend/migrations/`. A database built purely from Alembic lacks the table and every
subscription route fails.

Same as [DM-01](03-DATA-MODEL-DEFECTS.md#dm-01--subscription_tiers-has-no-migration) and
**D-06**.

---

### BC-24 — `billing_events` has no unique constraint

**✅ Verified · High** · **Status: fixed (2026-09-30, `80b22ed`)** — as DM-04: unique key
`uq_billing_events_period_grouping`, duplicates merged by the migration, and
`record_billing_event` is one `INSERT … ON CONFLICT DO UPDATE`. See
[DM-04](03-DATA-MODEL-DEFECTS.md#dm-04--billing_events-has-no-unique-constraint).

No `__table_args__`, no `UniqueConstraint` on
`(company_id, period_month, grouping_type, grouping_value)`. Concurrent settlements
duplicate rows and every report summing the table over-counts.

Same as [DM-04](03-DATA-MODEL-DEFECTS.md#dm-04--billing_events-has-no-unique-constraint) and
**D-07**.

---

### BC-25 — Stripe is a dependency with no code, and `verify_topup` returns a duplicate key

**✅ Verified · Low**

`stripe = "^7.0.0"` is declared in `pyproject.toml`. There is no `import stripe` anywhere
under `backend/src/`, and the Stripe-era tables (`invoices`, `payment_methods`,
`ledger_entries`) were dropped by migration `a804c0db1551`.

Anyone looking for an invoice table will not find one — `billing_events` is the closest
artefact and it is a monthly aggregate.

Separately, `verify_topup`'s return dict contains the key `"message"` **twice**. Harmless,
and a fair indicator of how much of that file has been reviewed.

> **Update 2026-09-30:** the duplicate key went with the BC-01 rewrite of `verify_topup`.

- [`backend/pyproject.toml:32`](../../../backend/pyproject.toml:32)
- [`billing/credits_router.py`](../../../backend/src/billing/credits_router.py) — the duplicate key

---

### BC-26 — Any user can read the billing multiplier and base costs

**✅ Verified · High** · **Status: fixed (2026-09-30)** — `GET /billing/config` is `app_admin`
only (`RoleChecker`); the five other roles get 403. Evidence as BC-19. Found 2026-09-29 while
fixing PO-04.

`GET /billing/config` depends on `get_current_user` only. It returns the caller's effective
`BillingConfig` — `multiplier_factor`, `platform_fee_pct`, `sales_partner_fee_pct`,
`discount_pct` and the `base_cost_*` fields. For a tenant that is the global default row: the
platform's markup, stated directly. PO-04 closed the two reports that let a user *infer* it;
this endpoint hands it over.

The only frontend caller is the `app_admin`-gated Billing Settings page, so gating the read
breaks nothing in the UI.

- [`billing/billing_router.py`](../../../backend/src/billing/billing_router.py) — `get_billing_config`

**Fix:** `app_admin` only, like the write. If a partner needs its own `sales_partner_fee_pct`,
return that field alone.

---

## 6. Improvements

### BC-I1 — Call the credit gates that already exist

**Status: done (2026-09-30)** — see [BC-05](#bc-05--three-of-the-four-credit-gates-have-no-callers).

**Effect: the largest single change in this register, and most of the code is written.**
[BC-05](#bc-05--three-of-the-four-credit-gates-have-no-callers). Two call sites in
`AgentLoop`: `check_credit_gate` at run start, `check_credit_circuit_breaker` after each
step. Both methods exist and are unit-tested.

This restores the pre-run gate and the mid-run breaker the product already claims to have,
and it makes the user-facing "top up and retry" message reachable.

### BC-I2 — Credit holds instead of settle-at-the-end

**Status: done (2026-09-30)** — see [BC-06](#bc-06--there-are-no-holds-so-one-run-can-overdraw).
The wallet is still debited at settlement; the hold reserves credit until then.

**Effect: large.** [BC-06](#bc-06--there-are-no-holds-so-one-run-can-overdraw). Reserve an
estimate at dispatch, release the difference at settlement. The estimator already exists in
`planning/cost_estimator.py` and is refreshed nightly from telemetry.

This is what makes overdraw structurally impossible rather than caught late.

### BC-I3 — One cost write path

**Status: done for tools (2026-09-30)** — BC-07…BC-11: every tool charge is one resolver
lookup and one attributed `usage_logs` row, and the image tool no longer charges on its own.
LLM calls already wrote attributed rows through `UsageService`. `run.total_cost_usd` is still
maintained alongside the ledger rather than derived from it.

**Effect: large.** [BC-07](#bc-07--fixed-cost-tool-charges-write-no-usage_logs-row),
[BC-08](#bc-08--image-generation-is-charged-twice),
[BC-09](#bc-09--attributionactor_step-is-never-written) and
[BC-11](#bc-11--four-price-tables-and-the-intended-source-of-truth-is-unused) are all the
same problem: several code paths write cost in several ways.

Make every spender write **one attributed `usage_logs` row** and nothing else. Then
`run.total_cost_usd` is a sum, the attribution dashboard is correct by construction, and
double-charging becomes impossible.

Wire `ToolCostResolver` as the single price lookup in the same change and delete the other
three tables.

### BC-I4 — Schedule the crons

**Status: done (2026-09-30)** — see [BC-04](#bc-04--the-billing-crons-are-never-scheduled).

**Effect: large.** [BC-04](#bc-04--the-billing-crons-are-never-scheduled). Two entries in
`WorkerSettings.cron_jobs`, next to the seven that are already there. Also change the daily
job from an assignment to a top-up so re-running it is safe.

### BC-I5 — Add the Razorpay webhook

**Status: done (2026-09-30)** — `POST /api/v1/credits/razorpay/webhook`
(`billing/razorpay_webhook.py`). The signature is an HMAC-SHA256 of the raw body under
`razorpay_keys.webhook_secret` (503 when unset, 400 when wrong). `payment.captured` credits a
top-up through the same `PaymentService.credit_topup` as the browser callback — so either
may arrive first and the second credits nothing — after checking the paid amount and
currency against the stored order; `payment.failed` records the failure on the row, and the
order stays payable. Other events and payments for orders that are not top-ups are ignored
with a 200. The subscription events are handled since BC-03.
**Evidence:** `tests/integration/test_razorpay_webhook.py`, 7 cases (credit once on replay;
webhook then browser callback credits once; bad signature; no secret; wrong amount; a failed
attempt recorded and a later success credited; unrelated events ignored). Live on the local
API with a temporary `razorpay_keys` row: bad signature 400, a 100-cent payment for a $12.50
order `amount_mismatch`, the right payment `credited` ($12.50 in the wallet), its replay
`already_credited`.

**Effect: large.** [BC-01](#bc-01--the-client-chooses-how-much-to-credit-its-own-wallet).
Browser-initiated verification cannot be trusted, whatever the signature check does. A
server-to-server webhook with the delivery id recorded gives amount validation and replay
protection at once.

Even before the webhook, credit `txn.amount` and check `txn.status`. That is two lines and
it closes the worst of it.

### BC-I6 — Validate pricing inputs on write

**Status: done (2026-09-30)** — see BC-19 and BC-21.

**Effect: medium, prevents a very expensive mistake.**
[BC-21](#bc-21--percentages-and-fractions-are-mixed-with-the-wrong-label). Range-check
`pf`, `spf` and `d` to `[0, 1]`, fix the UI label, and gate `company_id: null` to
`app_admin` ([BC-19](#bc-19--partner_admin-can-edit-platform-wide-pricing)).

### BC-I7 — Reap abandoned payments and subscriptions

**Status: done (2026-09-30)** — see BC-18.

**Effect: small.** [BC-18](#4-t2--gates-and-jobs-that-never-run). One query in the daily
job: mark `pending` transactions older than 24 hours as `expired`, and orphaned
`pending_payment` subscriptions as `failed`. Without it, the payments table is a growing
pile of rows that mean nothing.

### BC-I8 — Make cost queryable per run without a join storm

**Effect: medium.** Answering "why was I charged $X?" today means joining `usage_logs`,
`llm_interaction_logs`, `tool_interaction_logs` and `billing_events`, none of which are
indexed on the columns used
([DM-05](03-DATA-MODEL-DEFECTS.md#dm-05--execution_runs-has-no-index-on-company_id-or-entity_id),
[DM-06](03-DATA-MODEL-DEFECTS.md#dm-06--log-tables-have-no-indexes-at-all)).

A single per-run cost breakdown endpoint, backed by `usage_logs` alone once BC-I3 lands,
turns a support investigation into one call.

### BC-I9 — Reconcile telephony rounding

**Status: done (2026-09-30)** — see BC-12.

**Effect: small.**[BC-12](#bc-12--telephony-minutes-are-rounded-two-different-ways). Pick
one rounding rule and use it in both places. Today every telephony reconciliation shows a
difference that is not a real difference.

### BC-I10 — Remove the Stripe dependency

**Effect: small.** [BC-25](#bc-25--stripe-is-a-dependency-with-no-code-and-verify_topup-returns-a-duplicate-key).
A payment SDK in the dependency list with no code behind it is a maintenance and audit
liability, and it implies a payment path that does not exist.

---

## 7. Suggested order of work

| Step | Work | Why here |
|---|---|---|
| **1** | BC-01 (credit `txn.amount`, check `txn.status`) | Two lines. Closes the worst hole in the platform |
| **2** | BC-02 (`elif` → `if`), BC-03 (inject on activation) | Two more small changes; together they fix the pay-and-get-nothing path |
| **3** | BC-I1 / BC-05 | Call the two credit gates that already exist and are already tested |
| **4** | BC-I4 / BC-04 | Schedule the crons; make the daily job a top-up, not a reset |
| **5** | BC-20, BC-19, BC-I6 / BC-21 | Close the two open endpoints and validate pricing inputs |
| **6** | BC-23, BC-24 | The two schema fixes — a migration and a constraint |
| **7** | BC-I3 / BC-07 to BC-11 | One cost write path. The big one, and it fixes five defects at once |
| **8** | BC-I5, BC-I2 | The payment webhook, then credit holds |

---

## Where to go next

- [14 — Billing, costing & credits](../14-billing-and-credits.md) — the source document.
- [`DEFECT-REGISTER.md`](../DEFECT-REGISTER.md) — BC-01 is D-01, BC-03 is D-02, BC-04 is
  D-03, BC-23 is D-06, BC-24 is D-07, BC-20 is D-08/D-09, BC-19 is D-10, BC-06 is D-37.
- [03 — Data model](03-DATA-MODEL-DEFECTS.md) — DM-01 and DM-04 for the schema half.
- [10 — LLM providers](10-LLM-PROVIDERS-DEFECTS.md) — LP-01 (the 1000× `cost_unit` bug)
  and LP-06 (uncounted thinking tokens) are upstream of everything here.
- [`TOOL-LAYER-DEFECTS.md`](TOOL-LAYER-DEFECTS.md) — TL-19 and TL-20 for tool costing.
- [15 — Governance & HITL](15-GOVERNANCE-AND-HITL-DEFECTS.md) — the service that owns the
  unused credit gates.
