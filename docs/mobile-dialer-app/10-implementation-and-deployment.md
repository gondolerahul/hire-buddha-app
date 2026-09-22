# 10. Implementation Status & Deployment Runbook

> **Covers:** what has been built on branch `feature/mobile-dialer`, where the code lives, how it was tested, and the exact steps to deploy the backend, web and Android app safely.
> **Last updated:** 2026-09-17

---

## 1. What is built

| Area | Status | Code |
|------|--------|------|
| Contact upload (.csv/.xlsx) with row-level validation, 24 h storage | ✅ | [`contact_parser.py`](../../backend/src/mobile/contact_parser.py), [`campaign_setup.py`](../../backend/src/mobile/campaign_setup.py), `POST /campaigns/upload-contacts` |
| Campaign `execution_mode`, rep assignees; server dialer refuses mobile campaigns | ✅ | [`campaign_router.py`](../../backend/src/ai/campaign_router.py), [`campaign_executor.py`](../../backend/src/ai/campaign_executor.py) |
| Devices + caller-ID verification call | ✅ | [`service.py`](../../backend/src/mobile/service.py), [`identification.py`](../../backend/src/mobile/identification.py) |
| Runs, lead leasing (`SKIP LOCKED`), calling-hours window, per-rep daily cap, do-not-call exclusion | ✅ | `service.py` |
| Call attempts, DTMF tokens, idempotent event ingestion | ✅ | `service.py`, [`router.py`](../../backend/src/mobile/router.py) |
| Identification: CLI match in Tata/Twilio webhooks + Tata direct WS; DTMF bind/confirm/override | ✅ | `identification.py`, [`webhook_router.py`](../../backend/src/voice/webhook_router.py) |
| Gated AI start, silence until merge, greeting on merge, merge timeout, guardrail changes | ✅ | [`stream_controller.py`](../../backend/src/mobile/stream_controller.py), [`websocket_handler.py`](../../backend/src/voice/websocket_handler.py) |
| Conference persona addendum + AI/recording disclosure | ✅ | `stream_controller.py`, [`agent_loader.py`](../../backend/src/voice/agent_loader.py) |
| Redis control channel (API → gateway) and user push (`WS /mobile/ws`), FCM fallback (optional) | ✅ | [`realtime.py`](../../backend/src/mobile/realtime.py), [`push_gateway.py`](../../backend/src/mobile/push_gateway.py) |
| Housekeeping cron: expire stale attempts, reconcile unidentified sessions, close stuck calls | ✅ | [`reconciler.py`](../../backend/src/mobile/reconciler.py), [`worker.py`](../../backend/src/ai/worker.py) |
| Analytics API (campaign, summary, paged calls, attempt timeline) | ✅ | [`analytics.py`](../../backend/src/mobile/analytics.py), [`analytics_router.py`](../../backend/src/mobile/analytics_router.py) |
| Inbound credit-gate `NameError` fixed (Tata + Twilio) | ✅ | `webhook_router.py` |
| Smartflo reply key made configurable (`TATA_STREAM_SUCCESS_KEY`, default unchanged `sucess`) | ✅ | `webhook_router.py`, `config.py` |
| Web: xlsx upload, execution mode, rep assignment, mobile analytics panel, "Run from mobile app" on list | ✅ | [`CampaignCreateModal.tsx`](../../frontend/src/pages/streaming/CampaignCreateModal.tsx), [`MobileAnalyticsPanel.tsx`](../../frontend/src/pages/streaming/MobileAnalyticsPanel.tsx), `CampaignDetailPage.tsx`, `CampaignsPage.tsx` |
| Android app (Kotlin/Compose): login, onboarding (permissions, default dialer, SIM, verification call), campaigns, create + upload report, AI-first run orchestrator with auto-mute/unmute/take-over, event outbox, push socket, analytics, call detail, settings, minimal dial pad + incoming-call UI | ✅ | [`mobile/android`](../../mobile/android) |
| **v2 UI on the Buddha Cognitive Lab design system** (brand theme, fonts, logos, icon set, splash, all 26 screens) | ✅ | [`ui/theme`](../../mobile/android/app/src/main/java/com/hirebuddha/dialer/ui/theme), [`ui/common`](../../mobile/android/app/src/main/java/com/hirebuddha/dialer/ui/common), [11](11-ux-and-visual-design.md) |
| **Skip from any run phase** (FR-E7 — the command existed but nothing sent it) | ✅ | [`CallOrchestrator.kt`](../../mobile/android/app/src/main/java/com/hirebuddha/dialer/run/CallOrchestrator.kt) |
| **Pre-flight check** before a run (dialer role, battery, SIM, window, cap, credits, DID) | ✅ | [`PreflightSheet.kt`](../../mobile/android/app/src/main/java/com/hirebuddha/dialer/ui/campaigns/PreflightSheet.kt), `GET /mobile/preflight` |
| **Rep wrap-up** — disposition, note, callback, do-not-call | ✅ | [`RunSheets.kt`](../../mobile/android/app/src/main/java/com/hirebuddha/dialer/ui/run/RunSheets.kt), `PATCH /mobile/campaign-calls/{id}/disposition` |
| **Callbacks** — held out of leasing until due, surfaced on Today | ✅ | `service.callbacks_due`, `GET /mobile/callbacks`, `_LEASE_SQL` |
| **Live transcript** on the run screen during the conversation | ✅ | `stream_controller.on_transcript` → `attempt.transcript` push |
| **Today tab**, run summary, paused screen, notification with controls | ✅ | [`TodayScreen.kt`](../../mobile/android/app/src/main/java/com/hirebuddha/dialer/ui/home/TodayScreen.kt), [`RunSummary.kt`](../../mobile/android/app/src/main/java/com/hirebuddha/dialer/ui/run/RunSummary.kt), [`RunService.kt`](../../mobile/android/app/src/main/java/com/hirebuddha/dialer/run/RunService.kt) |
| Assisted mode (no default-dialer role) | ⏳ not built | docs 05 §3 |
| FCM on the device (needs a Firebase project + `google-services.json`) | ⏳ not built | backend side is ready and no-ops without config |
| Stand-alone web page `/streaming/mobile-analytics` | ⏳ not built | the API exists (`GET /mobile/analytics/summary`) |
| Device spikes S1–S6 on real SIMs | ⏳ must run in the pilot | docs 08 §3 |

### Deviations from the design docs

- The Android app is a single `app` module with packages instead of the multi-module layout in 05 §2. This keeps the build light on the shared build host.
- `mobile_call_attempts.agent_id` was added (not in 06 §1) so a session can load the campaign's agent even when the DID falls back to a company-level number.
- Extra endpoints beyond 06 §2: `GET /mobile/me`, `GET /mobile/app-version` (private-APK update check), `GET /mobile/agents`, `GET /mobile/reps`.
- Unidentified-lead "skip" returns the lead to `pending` (event `ai_failed`) instead of marking it `skipped`, so it's retried later.

## 2. Tests

| Suite | What | Result |
|-------|------|--------|
| `backend/tests/unit/test_mobile_pure_logic.py` | phone normalization/validation, DTMF collector, csv/xlsx parsing | 40 passed |
| `backend/tests/integration/mobile/` | schema script idempotency, upload→campaign, RBAC scoping, verification, concurrent leasing, CLI bind + DTMF confirm/override, unbound→DTMF, genuine inbound untouched, events + Redis publish, supersede, expiry, calling hours + daily cap, run completion, stream controller (pre-model phase, verification, fallback inbound, hang-up, ready→merge→greeting→cleanup, merge timeout, DTMF `#` fallback, late conflict), handler silence gate, analytics | 26 passed |
| existing `test_call_guards.py`, `test_campaign_report_helpers.py`, `test_imports.py` | regression | passed |
| `mobile/android` unit tests (`CallOrchestratorTest`) | happy path order, busy, no answer, AI not answering, merge failure, unidentified skip / merge anyway, ready timeout, push-miss polling, DTMF merge fallback, unmute + lead hang-up, run pause/complete | see §4 |

The integration suite **only runs against a database whose name ends in `_test`** (it rebuilds the schema). It skips itself otherwise.

```bash
cd backend && .venv/bin/python -m pytest tests/unit/test_mobile_pure_logic.py tests/integration/mobile -q
```

## 3. Deployment runbook

> The live API (:8000) and gateway (:8001) run `uvicorn --reload` from the main checkout, so **merging the code applies it immediately**. The live DB's Alembic revision (`agency001`) is not on this repo's history. Follow the order below.

### Step 1 — schema (before any code reaches the main checkout)

```bash
psql "$DATABASE_URL_SYNC" -v ON_ERROR_STOP=1 -f backend/db-scripts/mobile_dialer_001.sql
psql "$DATABASE_URL_SYNC" -v ON_ERROR_STOP=1 -f backend/db-scripts/mobile_dialer_002.sql
```

`mobile_dialer_002.sql` adds the rep-captured outcome columns and `callback_at` to
`campaign_calls`. Every column is nullable with no default, so on PostgreSQL 11+ each
`ALTER` is catalogue-only — but it still needs `ACCESS EXCLUSIVE` for an instant, and an
ALTER that *queues* blocks every later query on the table behind it. The script sets
`lock_timeout = '5s'` so it fails fast instead. If it times out, clear the idle-in-transaction
sessions holding `campaign_calls` first:

```bash
psql "$DATABASE_URL" -c "select pid, state, age(clock_timestamp(), xact_start), left(query,60) from pg_stat_activity where state like 'idle in transaction%';"
```

The script is idempotent and additive: new tables, plus defaulted/nullable columns on `campaigns` and `campaign_calls`. It is safe for the currently running code. Take a backup first, as usual.

### Step 2 — configuration (`backend/.env`)

The defaults in `config.py` are sensible. Set these explicitly anyway, because `.env` has drifted before:

```
MOBILE_CALLING_HOURS_START=09:30
MOBILE_CALLING_HOURS_END=19:30
MOBILE_REP_DAILY_ATTEMPT_CAP=150
MOBILE_APP_LATEST_VERSION_CODE=1
MOBILE_APP_LATEST_VERSION_NAME=1.0.0
MOBILE_APP_MIN_SUPPORTED_VERSION_CODE=1
MOBILE_APP_DOWNLOAD_URL=https://<where you host the signed APK>
# TATA_STREAM_SUCCESS_KEY=sucess   # switch to "success" only after verifying on the live Smartflo account (spike S6)
# MOBILE_FCM_SERVICE_ACCOUNT_FILE=/path/to/firebase-service-account.json  # optional
```

### Step 3 — Apache

Add the `/mobile/ws` WebSocket rule (already in `deploy/apache/gateway.hirebuddha.com-le-ssl.conf`) to the live vhost, then:

```bash
sudo apachectl configtest
sudo systemctl reload apache2
```

### Step 4 — code

Merge `feature/mobile-dialer`. The API and gateway reload by themselves. **Restart the Arq worker** so it picks up the housekeeping cron and the executor guard (it does not auto-reload).

### Step 5 — Smartflo (spike S6)

1. Reactivate the account. The hangup API currently returns `success:false`.
2. Confirm the agent DID uses the dynamic endpoint `https://gateway.hirebuddha.com/webhooks/voice/tata/incoming`.
3. Place one verification call from the app and check the gateway log for `[Mobile]` lines and `dtmf` events.

### Step 6 — Android release APK (private distribution)

```bash
# one time: create the release key (keep it safe — losing it forces reinstalls)
keytool -genkeypair -v -keystore hirebuddha-release.jks -alias hirebuddha -keyalg RSA -keysize 4096 -validity 10000
```

Create `mobile/android/keystore.properties` (gitignored):

```
storeFile=/abs/path/hirebuddha-release.jks
storePassword=...
keyAlias=hirebuddha
keyPassword=...
```

```bash
cd mobile/android && ./gradlew :app:assembleRelease
```

Host `app/build/outputs/apk/release/app-release.apk` at `MOBILE_APP_DOWNLOAD_URL`. For each new release, bump `versionCode`/`versionName` in `app/build.gradle.kts` and `MOBILE_APP_LATEST_VERSION_*` in `.env`.

## 4. Production state (2026-09-18)

| Step | Status |
|------|--------|
| 1 Schema | ✅ applied 2026-09-17 after a `pg_dump` to `/home/rahul/workspace/backup/db-backups/hirebuddha-before-mobile-dialer-20260917.dump` |
| 2 `.env` | ✅ calling hours 09:00–21:00, cap 150, `MOBILE_APP_DOWNLOAD_URL=https://app.hirebuddha.com/download/app/` |
| 3 Apache | ✅ `/mobile/ws` rule live on the gateway vhost (backup `…-le-ssl.conf.bak-20260918`) |
| 4 Code | ✅ `fresh-main` at `3e5fbef`; API, gateway and Arq worker restarted |
| 5 Smartflo | ⏳ account reactivation + DID dynamic endpoint must be done in the Smartflo portal; `GET /webhooks/voice/tata/incoming` answers publicly |
| 6 APK | ✅ signed **1.1.0 (6)**, v2 scheme, 4.0 MB; earlier 1.0.1 hosted at `https://app.hirebuddha.com/download/app/` — static files in `/var/www/hirebuddha-downloads/app/`, Apache `Alias` ahead of the Vite proxy on the app vhost |

Release key: `~/.hirebuddha-secrets/hirebuddha-release.jks` (+ `keystore.properties.backup`). **Back both up off this server** — losing them means every rep must uninstall to update.

Publishing a new version: bump `versionCode`/`versionName`, `./gradlew :app:assembleRelease`, copy the APK to `/var/www/hirebuddha-downloads/app/hirebuddha-dialer.apk` (and a versioned copy), update `SHA256SUMS`/`index.html`, then bump `MOBILE_APP_LATEST_VERSION_*` in `.env` and restart the API.

## 5. Reading the app's logs

The app has no adb access on a rep's phone, so it ships structured logs to the server
(`mobile_client_logs`, kept indefinitely). Every step is recorded: call states and
capabilities from Android Telecom, each merge attempt and what it chose, disconnect
causes, push messages, API failures, crashes, and a carrier/device snapshot per run.
Lead numbers are masked (`+91••••5678`).

From the API (a rep sees their own logs, a tenant admin the whole company):

```bash
TOKEN=$(curl -s -X POST https://gateway.hirebuddha.com/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"rep@tenant.com","password":"..."}' | python3 -c 'import json,sys;print(json.load(sys.stdin)["access_token"])')

# last 60 minutes, warnings and errors only
curl -s -H "Authorization: Bearer $TOKEN" \
  "https://gateway.hirebuddha.com/api/v1/mobile/logs?level=WARN&since_minutes=60&limit=100" | python3 -m json.tool

# everything for one call attempt (id comes from the call list or the app)
curl -s -H "Authorization: Bearer $TOKEN" \
  "https://gateway.hirebuddha.com/api/v1/mobile/logs?attempt_id=<uuid>&limit=500" | python3 -m json.tool
```

Filters: `device_id`, `attempt_id`, `run_id`, `level` (floor: `WARN` also returns `ERROR`),
`search` (text in the message), `since_minutes`, `limit` (max 1000). Newest first.

Straight from the database on the server:

```bash
psql "$DATABASE_URL" -c "select received_at, level, tag, message, fields
  from mobile_client_logs order by received_at desc limit 50;"
```

For a merge problem, look for `tag='CallRegistry'` (`Merge attempt` shows the chosen
action and both calls' capabilities; `Call state` shows what telecom did next) and
`tag='Device'` (`Run environment` — carrier, model, Android version).

Delivery: entries are written to a local database first, then uploaded in batches —
immediately on errors and at the end of each attempt, retried by WorkManager when the
phone is offline, and swept every 30 minutes. Nothing is lost if the app is killed.

## 6. Pilot checklist

- [x] Steps 1–4 and 6 done on production
- [ ] One tenant with an ACTIVE voice agent + assigned Tata DID + credits
- [ ] 2 reps on different carriers install the APK, complete onboarding (verification call succeeds)
- [ ] Spikes S1–S5 (docs 08 §3) run with the real app; results written to `spike-results.md`
- [ ] Watch `identification_conflict` rate and merge success per carrier in the web analytics panel
