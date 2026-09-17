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

## 4. Pilot checklist

- [ ] Steps 1–6 done on production
- [ ] One tenant with an ACTIVE voice agent + assigned Tata DID + credits
- [ ] 2 reps on different carriers install the APK, complete onboarding (verification call succeeds)
- [ ] Spikes S1–S5 (docs 08 §3) run with the real app; results written to `spike-results.md`
- [ ] Watch `identification_conflict` rate and merge success per carrier in the web analytics panel
