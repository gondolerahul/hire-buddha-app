# Phase 15 — Implementation status

> **Updated:** 2026-10-23
> **Where it stands:** **M15.0 Guardrails** done and committed (`3ae2f9a`). **M15.1 Money core** done on this laptop (§2): units are codes and calls are billed per second (WS15-1); currencies, FX in the admin UI and a company's currency from its country (WS15-2); versioned formulas, every usage row rated at write, billing lines, and the shadow comparison (WS15-3). Not deployed. Left for **M15.2** with the wallet rewrite: T2-7, T3-5, T3-6 (T3-8 after the T9 reports).

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

## 2. M15.1 — Money core (WS15-1, WS15-2, WS15-3 in shadow)

Built and tested on this laptop, 23 Oct. Migrations `control_0006` … `control_0014` and `tenant_platform_0005_amounts`.

### WS15-1 — Units and exact metering

| # | Task | State | Where | Proof |
|---|------|-------|-------|-------|
| T1-1 | `Dimension` / `CostUnit` enum, `cost_units` table, parity test | Done | `src/billing/units.py`: 17 dimensions, 25 codes (`UNITS`: dimension, `per_quantity`, label), `unit_spec`, `price_usd`. Table `cost_units` (`CostUnitRow`), `control_0006_cost_units`, seeded from literals in the revision (`COST_UNITS`) | `tests/integration/test_cost_units.py`, `tests/unit/test_cost_units.py` — both fail when a unit is added without a migration (checked) |
| T1-2 | Registry `cost_unit_code` → `cost_units` | Done | `control_0007_registry_unit_codes`: adds the column, fills it from an explicit table of the spellings in use (`LEGACY_SPELLINGS`), **stops with a list** on any unmapped row, adds the FK; `cost_unit` (text) kept nullable one release, then dropped (plan §4 step 10). `python -m src.billing.unit_codes_report` is the dry run (it loads the revision's own table). The registry API takes `cost_unit_code` (a `CostUnit`, 422 otherwise) and `internal_cost ≥ 0`; seeds and `register_app` write codes | local DB: 4 of 4 rows mapped; `tests/unit/test_cost_unit.py` |
| T1-3 | Pricing by code only; meters declare dimensions; missing / mismatched prices visible; unpriced models cannot be defaults | Done | `parse_cost_unit`, `_UNIT_NOUNS`, `unit_divisor` deleted. `UsageService.log_usage(..., dimension=)` — required; `price_at` = quantity × rate ÷ per_quantity; no row → a $0 row `cost_source: missing`, a row in another dimension → `unit_mismatch`, each with a `usage.cost.*` event (A6: it wrote nothing). Every caller declares: LLM calls `TOKEN`, embeddings `CHARACTER`, sandbox `SECOND`, hosting `VCPU_HOUR`/`GB_HOUR`/`GB`/`DAY` (`apps.metering.SKU_DIMENSIONS`). Tools: `TOOL_DIMENSIONS` (a call by default; `web_search` request/query, `image_generation` image, `video_generate`/`text_to_speech` seconds …). A task default or fallback must have priced `-in`/`-out` rows (or a price of its own) — 422 | `tests/unit/test_cost_unit.py`, `test_tool_cost_resolver.py`, `tests/integration/test_billing_formulas.py` (missing row), `test_tool_metering.py` |
| T1-4 | Calls per second | Done | `voice/usage_logger`: telephony = exact seconds × rate ÷ per_quantity (125 s at $0.60/min = $1.25, was $1.80); `billed_minutes` deleted; the call's duration is the media stream's, fractional. Live audio: a per-second/minute SKU bills the audio's seconds; a per-token SKU the provider's tokens, else seconds × the SKU's `tokens_per_second` (default 167). `billing_events.telephony_in/out_minutes` → `_seconds` (× 60 on migration); reports show minutes = seconds ÷ 60 | `tests/unit/test_cost_unit.py`, `tests/integration/test_voice_call_run.py` (expectations moved to per-second), golden suite |
| T1-5 | No rounding; amounts to 10 decimals | Done | `round()` gone from sandbox and hosting meters (DB share is `Decimal(1)/n`). `NUMERIC(24,10)`: `usage_logs` quantities and cost, `integration_registry.internal_cost`, billing events, holds, wallet buckets, spend cap (`control_0008`, `control_0009`); runs' `total_cost_usd` (was **4 decimals — every run was rounded before it was charged**), `billed_amount`, model and trace costs, call/chat sessions, call logs (`tenant_platform_0005_amounts`, which rebuilds `kpi_daily_rollup` around it). Payment amounts stay 2-dp (the gateway edge, K-1) | `tests/unit/test_no_rounding_in_costing.py` — fails on `round`/`ceil`/`quantize`/`ROUND_*` in 11 costing modules |
| T1-6 | Carrier billing increment, reconciliation only | Done | `src/billing/reconciliation.py` (`carrier_seconds`, `call_cost_gap`: 125 s per-minute carrier = $1.80 vs $1.25 billed); `scripts/set_telephony_increments.py` stamps `service_metadata.provider_billing_increment_seconds` (default 60) on telephony SKUs. Nothing in customer billing reads it | `tests/unit/test_call_reconciliation.py` |
| T1-7 | Unit dropdown and ₹ preview | Done | `GET /api/v1/config/cost-units`; the SKU editor picks a unit from it and shows "= $… per token · ₹… per 1M tokens at today's rate"; the integrations list shows the unit's label | browser (below) |

### WS15-2 — Currency, FX and geography

| # | Task | State | Where | Proof |
|---|------|-------|-------|-------|
| T2-1 | `currencies`, `fx_rates`, `country_profiles`, settings | Done | `control_0010_currency`: INR (₹) and USD ($) through Razorpay; rates INR 100, USD 1 (from 2000-01-01); **249 country profiles** from tzdata (India → INR, IN_GST, +91; every other → USD, EXPORT — O-5); `platform_settings` (`src/common/settings_store.py`, audited) with `billing.display_currency` / `billing.default_currency` = INR. `src/billing/currency.py`: `current_rate` (latest in effect), `to_ccy` / `to_usd` (exact), `currency_for_country`, `gateway_minor_units` (the one rounding of a payment) | `tests/integration/test_currency.py` |
| T2-2 | Company geography and billing profile | Done | `control_0011_company_geography`: `country_code` (→ profiles), `billing_currency` (→ currencies), `billing_state`, `gstin`, `legal_name`, `billing_address`; existing companies India/INR. `CompanyUpdate` takes the profile (GSTIN and state validated); country and currency are not updatable there | `test_currency.py` |
| T2-3 | Country at sign-up, onboarding, creation; currency derived (FX-1) | Done | `src/auth/geography.py` `set_geography` — self sign-up (`UserCreate.country_code`), staff/partner creation (`CompanyCreate.country_code`), OAuth (India until onboarding), onboarding's profile step (only while no money has moved — 409 after). Public `GET /api/v1/countries`; `<CountrySelect>` on sign-up, onboarding and "Add company" ("Billed in INR/USD") | `test_currency.py`; browser |
| T2-4 | Admin FX API, settings, audit | Done | `src/billing/currency_router.py`: `/api/v1/admin/currencies`, `/fx-rates` (list, add — reason required, USD refused, no backdating), `/fx-rates/preview`, `/currency-settings`, `/country-profiles`; app_admin only; every write in `admin_audit_log` | `test_currency.py` |
| T2-5 | Money utilities; `/me` currency | Done | `GET /auth/me` adds `country_code`, `billing_currency`; `utils/money.ts` `formatMoney` (₹ with Indian grouping; small amounts keep places), `<Money>`, `<DualMoney>` | `utils/money.test.ts` |
| T2-6 | Currency & FX page | Done (current layout) | `/admin/currency` (`pages/admin/CurrencyPage.tsx`): settings, currencies and rates, add-rate with impact preview, history, country profiles (editable). Moves to `/console/currency` with the console shell (T9-1) | browser |
| T2-7 | Currency-change tool | Not started — **M15.2** | It converts wallet lots and debt (needs T4-1) | |

### WS15-3 — Rating, settlement (shadow) and billing lines

| # | Task | State | Where | Proof |
|---|------|-------|-------|-------|
| T3-1 | Golden suite | Done | `tests/golden/billing/`: 7 runs, 3 calls, 4 payments recorded with the code **before** WS15-3 (`record.py` → `golden.json`); the new path must bill every run the same (exactly), and calls per second (never more than the old rule; equal on whole minutes) | `tests/golden/billing/test_golden_billing.py` (16) |
| T3-2 | Versioned formulas | Done | `billing_formulas` (`control_0012`): append-only versions per platform / company (plan scope with T6-1); `TB = c·mf·(1 + pf − d)`; `src/billing/formulas.py` (`formula_for`: company → platform → identity; `formula_for_run`: one version per run; `set_formula`, audited). The migration folds `spf` into `pf` (prices unchanged) and turns `base_cost_telephony` / `base_cost_image_gen` into company (or platform) registry rows; it **stops** if `pf + spf > 1`. Every reader moved (settlement, breaker, estimate, call settlement, campaign and session reports); `voice_base_cost`, `compute_billed_amount` and the image override step are gone. `/billing/config` reads/writes versions (reason, history), refuses non-zero `spf` and the overrides; daily credits stay in `billing_config` (T5-5) | `tests/integration/test_billing_formulas.py` (incl. the migration's data step on real rows — **it found the start date was bound as text, which would have failed on production's rows; fixed**), `test_billing_overrides.py` (rewritten), golden suite |
| T3-3 | Rating at write | Done | `usage_logs` + `billed_usd`, `formula_id`, `category` (+ `settlement_id`, `currency`, `billed_ccy`, `fx_rate_id` for WS15-4), `control_0013` (existing rows rated and categorised). `src/billing/rating.py` `rate_row` in all three writers (`UsageService`, `CostLedger`, the call meter); categories `src/billing/categories.py` (06 §5.3) | `test_billing_formulas.py`: a run keeps its formula mid-change; property Σ TB(cᵢ) = TB(Σ cᵢ) over 200 random cases |
| T3-4 | Billing lines | Done | `billing_lines` (`control_0014`) per company, day, category, grouping (entity / agent **id**), currency — cost, billed USD, billed in the company's currency at the locked rate. `src/billing/lines.py`; written at run settlement (rows of the run **and its descendants**) and call settlement, beside `billing_events`, in a savepoint (a failure never undoes the charge) | `test_billing_formulas.py` |
| T3-5, T3-6 | Settlement v2 (lots → debt), standalone-usage job | Not started — **M15.2** | They charge wallet lots and debt (T4-1) | |
| T3-7 | Shadow comparison | Done | `billing_shadow_diffs`; `billing.v2_mode` (staff setting, default `shadow`; `on` refused until WS15-4); each settled run and call records the old charge against Σ of its rated rows. `GET /api/v1/admin/billing-shadow`, `PUT …/mode`; page `/admin/billing-shadow` | `test_billing_formulas.py` (two settlements: lines add up, diffs 0) |
| T3-8 | Retire `billing_events` | Not started — after the T9 reports read `billing_lines` | | |

### Decisions taken while building (M15.1)

| # | Decision | Why |
|---|----------|-----|
| I-6 | Migration numbers 0006… instead of 08's `control_0004_cost_units` | 0004 and 0005 were taken |
| I-7 | Two codes beyond 06 §2.1: `PER_VIDEO`, `PER_QUERY` | The old parser accepted them; a row using them needs a code to map to |
| I-8 | No code for "transaction pct" | Nothing writes it; T1-2's report would show a production row that does |
| I-9 | Tools declare the dimensions their units count (`TOOL_DIMENSIONS`), more than one where providers price either way (a search per request or per query) | A call has no single natural unit; refusing a per-query SERP price would be a false mismatch |
| I-10 | A call's billed seconds are the media stream's exact duration; the provider's reported duration is stored for reconciliation | Billing at hang-up cannot wait for the status callback; switching to the provider's figure waits for spike SP-15-3 |
| I-11 | `component_type` stays (not replaced by the dimension, 06 §2.2) | The console uses it to name `-in`/`-out` SKUs; nothing prices with it now |
| I-12 | Country profiles carry no phone codes except India's, and empty calling rules | tzdata has names and zones only; calling rules move with backlog C5. The principal zone of AU, BR, CA, RU, UA, UZ was chosen by hand (tzdata lists another first) |
| I-13 | `platform_settings` created in T2-1 (with platform get/set) rather than T5-1; its writes go to `admin_audit_log` rather than a separate `settings_audit` | T2-1 needed the two currency settings; one audit table serves every staff change |
| I-14 | Billing lines and the shadow row are written in M15.1 from today's settlement (dual-write) | Reports and the shadow period need them before the new settlement exists; they replace `billing_events` at T3-8 |
| I-15 | Existing usage rows were rated with today's formula; none is marked settled | The old settlement still charges; rows are marked when the new path takes over (plan §4 step 5) |
| I-16 | Unit tests price with the identity formula (`tests/unit/conftest.py`) | They run on fake sessions; formula resolution is tested on Postgres |

## 3. Local environment

- 23 Oct: Docker's engine came up empty again; the local stack was rebuilt (`docker compose --profile azure up -d db redis azurite`, `python -m src.common.tenancy.migrate control`, both seeds, `python -m scripts.dev_tenants`). Control tree at `control_0014_billing_lines`, tenant tree at `tenant_platform_0005_amounts` (shared database and both dev tenants).
- The local `backend/.env` has `JWT_SECRET`, which nothing reads: the new start-up check reports it.

## 4. Tests

| Suite | M15.0 (23 Oct) | M15.1 (23 Oct) |
|---|---|---|
| New suites | flags 12, Razorpay secrets 6, payment guardrails 10+, partner portfolio 4, settings hygiene 4 | cost units (unit + integration), cost unit rules 4, no-rounding 2, call reconciliation 3, currency 15, billing formulas / rating / lines / shadow 8, golden billing 16 |
| Unit tier (`tests/unit tests/ai tests/golden`) | 2,591 passed, 2 skipped | **2,604 passed, 2 skipped** |
| Integration + parity (`-m "not docker"`) | 654 passed, 2 skipped | **678 passed, 2 skipped** (after moving tests to codes, seconds and formulas: `test_billing_overrides` rewritten for registry-row prices; `test_voice_call_run` per second; the adoption test re-types later revisions' columns) |
| `mypy --strict` gate (`scripts/typecheck_ai.py`) | pass | pass |
| Frontend `npm run lint`, `tsc`, `vitest`, `vite build` | clean (81) | **clean (87)** |
| Browser (local) | partner dashboard, flags guard, wallet by role | sign-up country list (249, "Billed in INR" → "USD" for the United States); Currency & FX page (rates, history, add-rate preview −16% → ₹1,680 for $20, country profiles); Billing Settings (no `spf`/overrides, reason, history); Billing Shadow page; SKU editor (25 units, "$0.0000025 per token · ₹250 per 1M tokens at today's rate") |
