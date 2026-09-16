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
| [T0](#2-t0--money-moves-incorrectly) | Money moves incorrectly | 6 | **Before the first paying tenant** |
| [T1](#3-t1--metering-that-under--or-double-counts) | Metering that under- or double-counts | 7 | Before any margin analysis |
| [T2](#4-t2--gates-and-jobs-that-never-run) | Gates and jobs that never run | 5 | Before relying on the control |
| [T3](#5-t3--schema-access-and-dead-weight) | Schema, access and dead weight | 7 | Now — mostly cheap |

**Total: 25 defects, 10 improvements.**

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

**✅ Verified · Critical**

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

---

### BC-02 — Switching to a subscription makes the existing balance unspendable

**✅ Verified · Critical**

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

---

### BC-03 — Subscribing strands the wallet and grants nothing

**✅ Verified · Critical**

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

---

### BC-04 — The billing crons are never scheduled

**✅ Verified · Critical**

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

---

### BC-05 — Three of the four credit gates have no callers

**✅ Verified · Critical**

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

---

### BC-06 — There are no holds, so one run can overdraw

**📄 Doc-reported · High**

Cost accrues on the run and the wallet is debited only at settlement. With no reservation
and — per [BC-05](#bc-05--three-of-the-four-credit-gates-have-no-callers) — no in-run
breaker either, a single expensive run can spend far beyond the available balance and the
platform discovers it at the end.

`Budget.usd_max` defaults to **$100**, two orders of magnitude above the $0.50 `PROCESS`
credit floor. So the in-loop budget will not stop it either.

- Also recorded as **D-37** in the platform register

---

## 3. T1 — Metering that under- or double-counts

### BC-07 — Fixed-cost tool charges write no `usage_logs` row

**📄 Doc-reported · High**

`image_generation` ($0.04) and `video_generate` ($0.05) bump `run.total_cost_usd` directly
but write **no** `usage_logs` row, because `sku_id` is `NOT NULL` and there is no SKU.

So the attribution dashboard and the usage-breakdown report under-report against the
wallet. The money is charged and the line item does not exist, which makes
"why was I charged $X?" unanswerable for exactly those tools.

---

### BC-08 — Image generation is charged twice

**📄 Doc-reported · High**

`image_generation` self-bills $0.04 inside the tool via `BillingService`, **and** is
charged again by the executor's fixed-cost branch at TB.

A guaranteed double charge on that branch. Recorded in the tool layer as part of
[TL-19](TOOL-LAYER-DEFECTS.md#tl-19--four-price-tables-one-of-which-is-the-unused-source-of-truth).

---

### BC-09 — `attribution="actor_step"` is never written

**📄 Doc-reported · High**

Step LLM spend — usually the majority of a run's cost — lands under `tool` instead of
`actor_step`.

The Cost Attribution dashboard's entire purpose is to show where money goes. Its largest
bucket is mislabelled, which means every conclusion drawn from it about planner-vs-critic-
vs-tool cost is wrong.

---

### BC-10 — The tool cost path ignores `cost_unit` and has no APP fallback

**📄 Doc-reported · High**

Two separate gaps in one path:

1. `cost_unit` is ignored, so a per-1M-token SKU is billed as if it were per-unit.
2. There is no fallback to the APP company's SKU, unlike the LLM path.

Net effect: **an unseeded tenant's tools are free.** Nothing warns; the rows simply are not
written.

---

### BC-11 — Four price tables, and the intended source of truth is unused

**✅ Verified · High**

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

### BC-12 — Telephony minutes are rounded two different ways

**📄 Doc-reported · Medium**

The **usage log** ceiling-rounds to whole minutes. The **billing event** records a
fractional minute count. The two never agree, so telephony reconciliation between the
ledger and the monthly aggregate always shows a discrepancy.

---

### BC-13 — `base_cost_llm` is read and then ignored; `base_cost_telephony` overwrites

**📄 Doc-reported · High**

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
| **BC-14** | `check_credit_gate`, `consume_step_cost`, `check_credit_circuit_breaker`, `require_credits` | Defined, unit-tested, **zero callers**. See [BC-05](#bc-05--three-of-the-four-credit-gates-have-no-callers) | ✅ Verified |
| **BC-15** | The daily and monthly cron jobs | Endpoints only; nothing schedules them. See [BC-04](#bc-04--the-billing-crons-are-never-scheduled) | ✅ Verified |
| **BC-16** | `razorpay_subscription_id` | Declared on the model, **never populated**, so the monthly job's charge branch is always skipped | ✅ Verified |
| **BC-17** | `tools.cost_resolver_v2_enabled` | Declared with default `True`, **never read**. Adding a flag is not the same as wiring a control | ✅ Verified |
| **BC-18** | Abandoned checkouts and orphaned subscriptions | A `pending` `payment_transactions` row stays forever; a `pending_payment` subscription with no matching payment stays forever. Nothing reaps either, and a failed payment is never recorded | 📄 Doc-reported |

---

## 5. T3 — Schema, access and dead weight

### BC-19 — `partner_admin` can edit platform-wide pricing

**📄 Doc-reported · Critical**

`PUT /billing/config` reportedly accepts `company_id: null` from a `partner_admin`, writing
the **global default row that every tenant inherits**.

A reseller can therefore change the platform's pricing for every other reseller's tenants.

- [`billing/billing_router.py`](../../../backend/src/billing/billing_router.py)
- Also recorded as **D-10** in the platform register

**Fix:** `app_admin` only for `company_id: null`. Verify before launch — this is the one
📄 entry in this file that most deserves a re-check.

---

### BC-20 — Two open endpoints on the money surface

**✅ Verified · High**

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

---

### BC-21 — Percentages and fractions are mixed, with the wrong label

**📄 Doc-reported · High**

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

**✅ Verified · High**

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

- [`backend/pyproject.toml:32`](../../../backend/pyproject.toml:32)
- [`billing/credits_router.py`](../../../backend/src/billing/credits_router.py) — the duplicate key

---

## 6. Improvements

### BC-I1 — Call the credit gates that already exist

**Effect: the largest single change in this register, and most of the code is written.**
[BC-05](#bc-05--three-of-the-four-credit-gates-have-no-callers). Two call sites in
`AgentLoop`: `check_credit_gate` at run start, `check_credit_circuit_breaker` after each
step. Both methods exist and are unit-tested.

This restores the pre-run gate and the mid-run breaker the product already claims to have,
and it makes the user-facing "top up and retry" message reachable.

### BC-I2 — Credit holds instead of settle-at-the-end

**Effect: large.** [BC-06](#bc-06--there-are-no-holds-so-one-run-can-overdraw). Reserve an
estimate at dispatch, release the difference at settlement. The estimator already exists in
`planning/cost_estimator.py` and is refreshed nightly from telemetry.

This is what makes overdraw structurally impossible rather than caught late.

### BC-I3 — One cost write path

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

**Effect: large.** [BC-04](#bc-04--the-billing-crons-are-never-scheduled). Two entries in
`WorkerSettings.cron_jobs`, next to the seven that are already there. Also change the daily
job from an assignment to a top-up so re-running it is safe.

### BC-I5 — Add the Razorpay webhook

**Effect: large.** [BC-01](#bc-01--the-client-chooses-how-much-to-credit-its-own-wallet).
Browser-initiated verification cannot be trusted, whatever the signature check does. A
server-to-server webhook with the delivery id recorded gives amount validation and replay
protection at once.

Even before the webhook, credit `txn.amount` and check `txn.status`. That is two lines and
it closes the worst of it.

### BC-I6 — Validate pricing inputs on write

**Effect: medium, prevents a very expensive mistake.**
[BC-21](#bc-21--percentages-and-fractions-are-mixed-with-the-wrong-label). Range-check
`pf`, `spf` and `d` to `[0, 1]`, fix the UI label, and gate `company_id: null` to
`app_admin` ([BC-19](#bc-19--partner_admin-can-edit-platform-wide-pricing)).

### BC-I7 — Reap abandoned payments and subscriptions

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

**Effect: small.** [BC-12](#bc-12--telephony-minutes-are-rounded-two-different-ways). Pick
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
