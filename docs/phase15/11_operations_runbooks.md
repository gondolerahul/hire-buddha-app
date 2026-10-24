# Phase 15 — Money operations runbooks

> **Task:** T10-5. Day-to-day procedures for staff after the cutover ([10_cutover_runbook.md](10_cutover_runbook.md)). Every action below is an `app_admin` action, takes a reason, and is written to the admin audit log (**Console → Audit log**, report R-A24). Support, sales and finance staff (`app_user` with those functions) can see the pages but not change them.

---

## 1. Changing an FX rate

**When:** the rate a currency is billed at drifts from the market rate by more than the agreed band, or finance asks.

1. **Console → Money → Currency & FX** (`/console/currency`). Pick the currency and enter the new units per USD.
2. Read the **preview** before saving (`GET /api/v1/admin/fx-rates/preview?currency=INR&units_per_usd=…`): what a sample of prices becomes and how much each changes.
3. Save with a reason (`POST /api/v1/admin/fx-rates`). Rates are append-only: the new row applies **from its effective time**; earlier events keep the rate they were converted at (FX-6). Wallet balances, already in the company's currency, do not move.
4. Plan prices in that currency change **at each subscription's renewal**, not mid-cycle.
5. Check **R-A15 FX impact** the next day.
6. If the change is large (over 5 %), send customers a notice first (add a template to `src/billing/cutover_notices.py`, see the cutover runbook §5).

**Do not** delete or edit an old rate; correct a wrong one by adding another with an earlier effective time than any event since.

---

## 2. Refunding a payment

**When:** a customer asks within policy, a duplicate payment, a failed delivery.

1. **Console → Finance → Payments & invoices** (`/console/finance/payments`): find the payment (company, invoice number, date).
2. **Refund**: the net amount (all that is left by default; GST is refunded with it) and a reason (`POST /api/v1/admin/payments/{id}/refund`).
3. What happens, in one transaction: the gateway refund; a **credit note** against the invoice; the credit that payment added is **taken back** from the wallet (into debt if it was spent); partner commissions on it are **clawed back** (a negative ledger entry on the partner's next statement).
4. If the gateway refuses (unavailable, already refunded) nothing is changed: retry later or refund in the Razorpay dashboard and then record it here.
5. Only a captured payment refunds; a pending checkout is left to expire (`checkout.abandoned_after_hours`).

---

## 3. Paying partners (monthly)

**When:** every month after `partners.statement_day` (5th by default), for the month before.

1. The statement job builds last month's statements automatically; to build again by hand: **Console → Finance → Partner payouts** → *Build* for the month (`POST /api/v1/admin/partners/statements/build`). Earnings still in their holdback (`partners.holdback_days`, longer on probation) wait for a later month; a partner under the minimum payout (`partners.payout_min_usd`) carries forward.
2. The **margin guard** holds commissions on a tenant's usage that exceed `partners.max_margin_share_pct` of its margin that month; review the held lines on the statement.
3. Review each draft; a partner can **dispute** it (it shows disputed with the reason). Fix with an adjustment on Partner 360 (with a reason), then rebuild.
4. **Approve** (`…/statements/{id}/approve`): refused until the partner's KYC and bank account are verified. TDS (`partners.tds_pct`) is already deducted on the statement.
5. Pay from the bank (export: `…/statements/export.csv`), then **Mark paid** with the bank reference (`…/statements/{id}/paid`). A partner registered for GST uploads its GST invoice on its statement before payment.
6. A paid statement is final; a mistake is corrected by an adjustment on the next one (**Reopen** only an approved, unpaid one).

---

## 4. A business in debt, over its limit, or suspended

The wallet moves `ok` → `in_debt` (any debt) → `over_tolerance` (debt over `wallet.negative_tolerance_usd`) → `suspended` (over the tolerance for `billing.suspend_after_days`). While enforcement is on, `in_debt` stops new work, `over_tolerance` also stops running work and holds numbers after `numbers.hold_after_days_over_tolerance`, apps stop after `billing.app_stop_grace_hours`, and `suspended` makes sign-in read-only. Repaying the debt returns the wallet to `ok` at once: automation and apps resume, held numbers are released.

**Support's options**, in order:

1. Tell the customer what they owe and how to recharge (**Company 360** shows balance, owed, state; the customer sees the same banner).
2. **More time:** raise the company's tolerance (Console → Settings, `wallet.negative_tolerance_usd` for that company, with a reason and an end date in the reason). `billing.suspend_after_days` is platform-wide only.
3. **Goodwill credit:** **Console → Finance → Receivables** → the company → *Adjust* with a positive amount and a reason (`POST /api/v1/admin/wallets/{id}/adjust`). An adjustment is not a payment: it does not repay debt by itself and is never invoiced.
4. **Write-off** of a debt: an adjustment for the amount owed, reason "write-off", approved by finance.

A **platform-wide** problem (a billing bug making good customers owe) is handled by turning `billing.enforcement_enabled` off (Console → Settings → Rollout) while it is fixed: debt is still recorded, nothing is blocked.

---

## 5. A partner to suspend or end

1. **Console → Partners** → Partner 360 → *Status* with a reason (`POST /api/v1/admin/partners/{id}/status`).
2. **Suspended**: earns nothing new, its earnings on hold are forfeited, and its people are refused in its tenants (its grants stay, unused, until it is reactivated). Reactivate the same way (earnings held for a lapsed fee are released then).
3. **Terminated**: its tenants pass to HireBuddha direct, its grants are revoked and unpaid earnings are forfeited — say so to the partner in writing first.
4. A partner whose annual fee lapses is suspended automatically after `partners.fee_grace_days`.

---

## 6. Where to look

| Question | Report or page |
|---|---|
| What changed, who, why | R-A24 Admin audit log (Console → Audit log) |
| Usage not settled, unrated, shadow differences | R-A21 Billing exceptions |
| Who owes what, for how long | R-A06 Receivables |
| Credit sold but not used, breakage | R-A05 Wallet liability |
| What a staff desk has waiting | Console home (R-A25 Work queues) |
| Is the cutover ready | `python -m src.billing.cutover` |
