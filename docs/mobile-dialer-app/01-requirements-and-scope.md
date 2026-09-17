# 01. Requirements & Scope

> **Covers:** the functional brief, actors, requirements with IDs (referenced by later docs), non-functional requirements, constraints from the existing platform, and explicit non-goals.

---

## 1. Actors

| Actor | Platform role (`users.role`) | Can do in the app |
|-------|------------------------------|-------------------|
| Tenant admin | `tenant_admin` | Everything a tenant user can, plus create campaigns for other reps, assign reps, see all reps' analytics |
| Tenant user (rep) | `tenant_user` | Log in, create own campaigns, run campaigns assigned to them, see own analytics |
| AI agent | `hierarchical_entities` row, voice-enabled, `ACTIVE` | Answers calls on the tenant DID assigned to it |
| Lead | — | Receives the call on their phone |

Partner and app roles (`partner_admin`, `app_admin`, …) are **not** supported in the mobile app for v1. They keep using the web app.

## 2. Functional requirements

### Authentication

| ID | Requirement |
|----|-------------|
| FR-A1 | User logs in with email + password against the existing `POST /api/v1/auth/login`. |
| FR-A2 | Only `tenant_admin` and `tenant_user` may use the app; other roles see a "use the web app" message. |
| FR-A3 | Session persists with the refresh token (`POST /api/v1/auth/refresh`, 7-day rotation); access token is 30 min. |
| FR-A4 | On first login on a device, the device is registered and its caller number verified (see [ADR-001](03-adr-001-lead-identification.md)). A device can't run campaigns until verification succeeds. |

### Campaign creation

| ID | Requirement |
|----|-------------|
| FR-C1 | User picks a `.csv` or `.xlsx` file from device storage / Drive (Android Storage Access Framework). |
| FR-C2 | File is uploaded to the backend, which parses and validates it (the server decides; the app doesn't parse). |
| FR-C3 | Validation report shows: total rows, valid, invalid (with row number + reason), duplicates removed, detected columns, preview of first 20 valid rows. |
| FR-C4 | A `phone` column is required (case-insensitive; accepted aliases: `phone`, `mobile`, `phone_number`, `contact`, `number`). Other columns become contact data available to the AI prompt as `{{column}}`. |
| FR-C5 | User picks the AI agent (only voice-enabled `ACTIVE` agents with an assigned DID), names the campaign, and (admin only) assigns reps. |
| FR-C6 | Campaign is created with `execution_mode = mobile_conference`. |

### Campaign execution

| ID | Requirement |
|----|-------------|
| FR-E1 | User can Start, Pause, Resume, Stop a campaign run from the app. |
| FR-E2 | The app works through leads one at a time, leased from the server so two reps never call the same lead. |
| FR-E3 | For each lead the app places **two carrier calls** from the rep's SIM (lead + tenant DID) and **merges** them into a conference. |
| FR-E4 | The AI agent knows which lead it is speaking to (name, CSV fields, campaign) **before it speaks**. |
| FR-E5 | Unanswered / busy / failed lead calls are recorded with a reason and the app moves to the next lead after a configurable gap (default 5 s). |
| FR-E6 | When the AI ends the conversation (goodbye or voicemail), the app disconnects both legs. |
| FR-E7 | The rep can mute/unmute themselves, skip the current lead, hang up the lead, or take over (drop the AI leg). |
| FR-E8 | The rep can leave the running screen; a foreground notification keeps the run alive. |

### Analytics

| ID | Requirement |
|----|-------------|
| FR-N1 | Per campaign: funnel (leads → dialed → answered → AI connected → merged → conversation ≥ 30 s), dispositions (interested / not interested / voicemail / neutral), talk time. |
| FR-N2 | Per rep: calls made, answer rate, merge success rate, interested count. |
| FR-N3 | Per call: status timeline, transcript, AI summary, recording (reuses existing call detail). |
| FR-N4 | Same numbers visible in the web frontend (`/streaming/campaigns/:id`) and the app. |

## 3. Non-functional requirements

| ID | Requirement | Target |
|----|-------------|--------|
| NFR-1 | Identification accuracy (session bound to the correct lead) | ≥ 99.5 % of merged calls; 0 cross-tenant mis-binds |
| NFR-2 | Lead hears the AI within … of answering | ≤ 3 s (AI-first order) |
| NFR-3 | Identification must never delay the AI leg more than | 10 s after AI leg answer, then fall back to unidentified |
| NFR-4 | App works on | Android 10 (API 29)+, dual-SIM devices, Jio / Airtel / Vi |
| NFR-5 | Event delivery | Call events persisted locally and delivered at-least-once, idempotent server-side |
| NFR-6 | Security | Tokens in Android Keystore-backed storage; TLS only; no lead PII persisted on device beyond the active lease |
| NFR-7 | Tenancy | Every new table carries `company_id`; all queries company-scoped as in [04](../current/04-auth-rbac-tenancy.md) |

## 4. Constraints inherited from the existing platform

These come from [12 — Voice](../current/12-voice-and-telephony.md) and the backend code. Every design choice has to respect them.

| Constraint | Consequence for this project |
|-----------|------------------------------|
| Voice audio runs in the **gateway** (:8001); HTTP webhooks + API in the **backend** (:8000) | "Lead answered" signals from the app reach the live call handler via Redis pub/sub, not in-process. |
| Call setup (agent load + credit check + model connect) measured at **5–27 s** | Motivates AI-first dial order and pre-warming. |
| Smartflo dynamic endpoint must answer in **≤ 2 s** | Identification in the webhook must be one indexed DB lookup. |
| Gemini Live is the only working speech-to-speech provider (Azure path broken) | No change; gating logic lives in `BaseStreamHandler`. |
| DTMF is **not implemented** anywhere in `backend/src/voice/` | Must add `dtmf` event handling for Tata and Twilio. |
| CSV only (`POST /campaigns/upload-csv`); `openpyxl` already a dependency | Add `.xlsx` parsing. |
| Campaign dialer is server-side (Arq worker) | `mobile_conference` campaigns must be **excluded** from the Arq executor. |
| Tata Smartflo account currently inactive (hangup API returns `success:false`) | Must be reactivated before any spike. |
| Tata webhook responses use the key `"sucess"`; current Smartflo docs require exactly `"success"` | Verify during spike S6 — possibly return both. |

## 5. Non-goals (v1)

- iOS app. iOS gives no API to merge calls or send DTMF programmatically.
- Predictive/parallel dialing. One rep = one lead at a time.
- Recording the conference on the device. Android blocks call-audio capture for third-party apps, and the backend already records the AI leg, which carries the full conference mix.
- In-app agent/persona editing, number purchase, billing top-up. These stay in the web app.
- Offline campaign execution. Placing calls needs the backend for leases and identification.
