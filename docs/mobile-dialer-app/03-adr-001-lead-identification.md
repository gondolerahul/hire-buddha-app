# ADR-001: Lead Identification for Phone-Merged AI Conference Calls

| Field | Value |
|-------|-------|
| Status | **Accepted** — 2026-09-17 by product. Device spikes S1–S3/S6 still run during the pilot as validation; Option H remains the documented fallback if they fail ([08](08-risks-compliance-and-spikes.md)) |
| Date | 2026-09-17 |
| Deciders | Engineering lead, Product |
| Supersedes | — |
| Options analysis | [02](02-lead-identification-options.md) |

---

## Context

The Android app merges two carrier calls placed from the rep's SIM: one to the lead, one to the tenant DID answered by the AI agent. The AI leg reaches our backend as an inbound call from the rep's number, and nothing on it identifies the lead. The AI still has to know the lead's details before it speaks, and the transcript has to be attributed to the right `campaign_call`.

## Decision

We will identify the lead with **two independent signals, a gated AI start, and a post-call safety net**, and use an **AI-first dial order** by default.

### 1. Device verification (once per device)

- On first login, the app registers the device (`POST /mobile/devices`) and receives a verification DID + 6-digit code.
- The app calls the DID and sends the code as DTMF. The backend records the `fromNumber` Smartflo presents as `user_devices.verified_cli`.
- If no CLI arrives (withheld), the device is still verified. It is flagged `cli_available = false` and will rely on DTMF only.

### 2. Call attempt (per lead)

- Before dialing, the app creates an attempt: `POST /mobile/call-attempts {campaign_call_id, device_id}` → `{attempt_id, did, dtmf_token, expires_at}`.
- Invariant: **at most one open attempt per device**. A new attempt supersedes any open one. `dtmf_token` is unique among open attempts on the same DID.

### 3. Signal 1 — CLI match in the webhook

In `POST /webhooks/voice/tata/incoming` (and the Twilio equivalent), a new resolution step runs **before** the generic inbound DID lookup:

```
open attempt WHERE device_cli IN normalize_candidates(fromNumber)
              AND did IN normalize_candidates(toNumber)
              AND status = 'pending' AND expires_at > now()
```

On match, the voice session is created with `session_metadata.mode = "mobile_conference"`, `attempt_id`, `contact_data`, `campaign_id`, and `identification = {method: "cli", at}`.

### 4. Signal 2 — DTMF token on the stream

- On `STATE_ACTIVE` of the AI leg, the app always sends `*<token>#` with `Call.playDtmfTone`.
- The gateway handler buffers `dtmf` events between `*` and `#`:
  - Session already CLI-bound and token matches → `method = "cli+dtmf"` (confirmed).
  - Session already CLI-bound and token matches a **different** open attempt on the same DID and company → **DTMF wins**. Rebind, log `identification_conflict`.
  - Session unbound → bind by token, `method = "dtmf"`.

### 5. Gated start

For `mode = mobile_conference` sessions the handler:

- **Doesn't connect the speech model** until the session is bound, or until `MOBILE_IDENT_TIMEOUT_SECONDS` (default 10 s) passes after stream start. The existing agent load + contact injection path then runs unchanged.
- **Doesn't forward inbound audio to the model, or trigger the greeting,** until the app reports `merged` (in both dial orders). This covers carrier hold tones, DTMF tones, and the rep saying "hello".
- On timeout, starts the agent **without** contact data (`method = "unidentified"`), and notifies the app, which shows "AI couldn't identify lead" and lets the rep decide whether to merge.

### 6. Safety net — post-call reconciliation

Any `unidentified` session is reconciled after the call. The backend matches it to the device's attempt whose app-reported `ai_answered_at` is within ±15 s of the session's `started_at`. It then back-fills `campaign_call.voice_session_id` with `method = "reconciled"`, so analytics stay complete.

### 7. Dial order: AI-first (decided)

AI-first: create attempt → dial DID → AI leg active → DTMF token → wait for `ai_ready` push → **hold** AI leg → dial lead → on lead `ACTIVE` → merge → app reports `merged` → backend lifts audio gate and triggers the greeting.

The original brief described lead-first. With 5–27 s of AI setup (C7), lead-first would leave the answered lead on hold for that long, and many would hang up. AI-first moves the setup cost to *before* the lead answers. The price is AI-leg minutes (up to the ~30 s ring timeout) for leads who don't answer; the app hangs up the AI leg as soon as the lead leg fails. **Decision (2026-09-17): AI-first is the only dial order built for v1.** Lead-first is not implemented; the `dial_order` field is kept in the API for future use.

## Consequences

**Positive**

- The AI has full lead context before its first word in the normal case. Either signal alone suffices, and both together detect mis-binds.
- No recurring cost (no extra DIDs); reuses the session cascade, agent loader, transcripts, recording, summary and disposition code.
- The same mechanism works for Twilio numbers.

**Negative / accepted costs**

- The app **must be the default dialer** (`ROLE_DIALER`) for pickup detection, hold/merge and DTMF. That means building incoming-call UI. Distribution is private (no Play Store), so no Play Console declaration is needed.
- New backend work: DTMF event handling (none exists), a Redis control channel from API (:8000) to gateway handler (:8001), a `mobile_conference` gate in `BaseStreamHandler`, and new tables.
- AI-leg minutes are consumed while the lead rings. Mitigated by the app hanging up the AI leg on no-answer, and measured in analytics.

**Risks carried into the plan**

- Carrier conference support on Jio/Airtel/Vi VoLTE (S3). If merge is unreliable, **switch to the server-side bridge (Option H)**; login, upload, analytics and backend identification tables remain valid.
- TRAI 2025 TCCCPR restrictions on commercial calls from 10-digit numbers (D1). **Product confirmed on 2026-09-17 that reps may call from personal SIMs.** The in-app guardrails in [08 §1.1](08-risks-compliance-and-spikes.md#11-trai-tcccpr--commercial-calls-from-10-digit-numbers--blocking) stay in scope.

## Alternatives rejected

| Option | Reason |
|--------|--------|
| C — DID per rep | Recurring cost; kept only as a per-tenant remedy when CLI and DTMF both fail |
| D — DID per call | Cost + pool exhaustion, no gain over A+B |
| E — post-call only | Fails FR-E4 (AI must know the lead in-call); kept as safety net |
| F — AI asks the lead | Poor UX, ASR error-prone |
| G — VoIP AI leg | Can't be merged with a carrier call; apps can't bridge call audio |
| I — audio watermark / voiceprint | Apps can't inject call audio; no enrolled voiceprints |
| J — call-through IVR | Variant of H with worse latency |

## Validation during pilot

| Spike | Pass criterion |
|-------|----------------|
| S1 CLI fidelity | ≥ 95 % of calls from Jio/Airtel/Vi/BSNL SIMs present a stable `fromNumber` equal to the verified CLI |
| S2 DTMF pass-through | ≥ 98 % of `*NNNN#` tokens decoded exactly on Smartflo streams, VoLTE and 2G/3G |
| S3 Carrier merge | Programmatic merge succeeds ≥ 95 % across 3 carriers × 4 OEMs, both parties hear the AI clearly |
| S6 Smartflo readiness | Account active; dynamic endpoint accepted with our response body; `dtmf` events observed |

Details and test procedure: [08 §3](08-risks-compliance-and-spikes.md#3-validation-spikes-must-run-before-build).
