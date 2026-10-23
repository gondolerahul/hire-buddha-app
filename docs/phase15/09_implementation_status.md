# Phase 15 — Implementation status

> **Updated:** 2026-10-23
> **Where it stands:** milestone **M15.0 Guardrails (WS15-0) is written and tested on this laptop** — all seven tasks T0-1…T0-7 of [08 §2](08_implementation_plan.md). Not committed, not deployed. The next milestone is M15.1 (WS15-1 units and metering, WS15-2 currency and FX, WS15-3 rating and settlement in shadow).

---

## 1. WS15-0 — Guardrails

| # | Task | State | Where | Proof |
|---|------|-------|-------|-------|
| T0-1 | Feature flags staff-only (Q6, C-1, C-2) | Done | `PUT`/`DELETE /api/v1/ai/admin/feature_flags/{key}` and `POST /ai/admin/admin/tools/{tool}/experimental` are `app_admin` only (the last takes `company_id`); a key must be declared — `DEFAULTS`, `NUMERIC_DEFAULTS` or `tools.experimental.<tool>` (`feature_flags.flag_kind`) — else 422; `enabled` must be a boolean, a numeric flag's `value_json` a number. Every write adds an **`admin_audit_log`** row (new control table, migration `control_0005_admin_audit`, `src/common/admin_audit.py`): actor, role, acting company, object, scope, old → new, reason. Reads (`/me`, `/explain`, `/admin`) unchanged. `python -m src.ai.core.flag_rows` reports rows written before (undeclared keys; customers' company/entity rows with no staff write in the audit) and removes them with `--delete-undeclared` / `--reset-customer`, audited. Frontend: the Feature Flags route and menu link are `app_admin` only; the create form suggests declared keys and takes a reason | `tests/integration/test_feature_flags_staff_only.py` (12) |
| T0-2 | Razorpay secrets to the vault (B-8, D5) | Done | `razorpay_keys`: key secret = the row's `secret_ref` (or the console's encrypted API key); webhook secret = vault name in `service_metadata.webhook_secret_ref`. `get_razorpay_creds` returns `None` without a key id and secret. The registry API refuses `key_secret`/`webhook_secret` in the metadata (422). `python -m src.config.move_secrets --apply` moves an old row's plain-text secrets to `registry-razorpay-keys` / `registry-razorpay-keys-webhook`. **Transitional:** an old row that still holds them in plain text keeps working and logs an error each read, until the mover runs — remove that fallback once production has moved | `tests/integration/test_razorpay_secrets.py` (6); `test_razorpay_webhook.py` unchanged and green |
| T0-3 | Payments by company admins (B-15, F1) | Done | `POST /credits/topup`, `/topup/verify`, `/subscriptions`, `/subscriptions/verify`, `DELETE /subscriptions/{id}`: `tenant_admin`, `partner_admin`, `app_admin` (`billing_admin`); the Gold partner joins in WS15-8. `GET /credits/topup-options` says `can_pay`; the wallet page shows the balance to everyone and the pay/subscribe/cancel controls only to admins | `tests/integration/test_payment_guardrails.py` |
| T0-4 | Top-up bounds and 2 decimals (B-14, F2) | Done | `TopUpRequest.amount`: USD 5 … 10,000, at most 2 decimals (422 otherwise) — interim constants in `credits_router.py` (`TOPUP_MIN_USD`, `TOPUP_MAX_USD`, `TOPUP_PRESETS_USD`), to become the settings `wallet.topup_*` in T5-2; served by `GET /credits/topup-options`, which the wallet page uses for its presets and checks | `test_payment_guardrails.py` (bounds, sub-cent, exact cents to Razorpay) |
| T0-5 | No invented plans (C-12, F3) | Done | `WalletPage.tsx` shows only the tiers the API returns, and "No plans are available at the moment" when there are none | `tsc`, `eslint` |
| T0-6 | Partner dashboard (P-23, P-25, P-27, C-13, E1) | Done | New `GET /api/v1/partner/analytics/revenue?months=` — the partner's tenants' **billed** amounts (`billing_events.total_billing`) per tenant and month; `PartnerAdminDashboard.tsx` uses it with `/partner/tenants` (no longer the staff-only `partner-performance`), each part loading on its own. `/partner/analytics/summary` sums top-level runs only (a child's cost is in its parent's) and every wallet bucket. **One health score** (`src/auth/tenant_health.py`: activity, reliability, balance, adoption, with reasons) for `/partner/tenants` and `/reports/analytics/tenant-health`, signals read in one batch | `tests/integration/test_partner_portfolio.py` (4); `test_report_fanout.py`, `test_tenant_routing.py` green |
| T0-7 | Settings hygiene (C-3, C-7, C-8, F7, F8) | Done | `FRONTEND_URL` read only through `Settings` (the e-mails used `os.getenv` with `:5173`); `GOOGLE_/MICROSOFT_CLIENT_ID/SECRET` are settings; the raw IP left the default `CORS_ORIGINS`; the API warns at start-up about each variable that nothing reads (`config.unknown_env_keys`: names in `.env`, and process variables one typo away from a setting), with a guess. `.env.example` lists the OAuth settings | `tests/unit/test_settings_hygiene.py` (4) |

### Not done in WS15-0 (and where it goes)

- `usage-breakdown` for a partner still shows the partner company's own usage at cost (P-28); the partner dashboard no longer uses it. Billed-only money views for every endpoint are T9-3.
- `/partner/analytics/summary` and `/partner/tenants/{id}/details` still return `total_cost_usd` (provider cost) to partners (P-34) — T9-3.
- `TRACE_MAX_FIELD_BYTES` and `APPS_NODE_POOL` are still read with `os.environ` (allow-listed by the unknown-key check) — with the settings catalogue (T5-1).
- `TATA_STREAM_SUCCESS_KEY="sucess"` (C-9) still awaits verification against a live Tata call.

### Decisions taken while building

| # | Decision | Why |
|---|----------|-----|
| I-1 | The control audit table is `admin_audit_log`, not `audit_log` (06 §17) | In `TENANCY_MODE=single` the shared database already has the tenant plane's `audit_log` (Data API record changes) |
| I-2 | Flag reads stay open to company admins; only writes are staff-only | The engineering flags' values are not secret, and `/me` feeds the frontend's `useFeatureFlag` |
| I-3 | A plain-text Razorpay row keeps working (with an error per read) until `move_secrets` runs | Production's payments must not stop between the deploy and the move |
| I-4 | Interim health score weights: activity 30, reliability 30 (15 with no runs), balance 25, adoption 15 | Takes the signals both old scores had; the integrations count is dropped (integrations are becoming connections). R-P03 replaces it |
| I-5 | The partner revenue view reads `billing_events` (monthly) | It is the billed amount today; it moves to `billing_lines` with T3-4 |

## 2. Local environment

- 23 Oct: Docker's engine came up empty again; the local stack was rebuilt (`docker compose --profile azure up -d db redis azurite`, `python -m src.common.tenancy.migrate control`, both seeds, `python -m scripts.dev_tenants`). Control tree at `control_0005_admin_audit`, tenant tree at `tenant_platform_0004_kpi_refresh`.
- The local `backend/.env` has `JWT_SECRET`, which nothing reads: the new start-up check reports it.

## 3. Tests

| Suite | Result (23 Oct) |
|---|---|
| New: flags, Razorpay secrets, payment guardrails, partner portfolio, settings hygiene | 12 + 6 + 10 (+ params) + 4 + 4 — all pass |
| Existing touched suites: `test_razorpay_webhook`, `test_subscriptions`, `test_topup_verify`, `test_billing_config_access`, `test_flag_explain_endpoint`, `test_report_fanout`, `test_tenant_routing` | pass |
| Unit tier (`tests/unit tests/ai`) | 2,591 passed, 2 skipped (after updating `test_flag_announcements`, the Appendix A table list and `docs/reference/api-routes.md` for the new routes and roles) |
| Integration + parity (`-m "not docker"`) | 654 passed, 2 skipped |
| Frontend `tsc --noEmit`, `eslint` on changed files, `vitest` (81), `vite build` | clean |
| Browser (local) | Partner admin: the dashboard loads (both partner calls 200), billed totals and health right; the Feature Flags URL redirects and its link is gone; a flag `PUT` answers 403. Tenant user: wallet without pay controls, "No plans are available". App admin: top-up form with the API's presets; Feature Flags page |
