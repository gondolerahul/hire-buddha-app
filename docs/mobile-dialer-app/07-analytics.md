# 07. Analytics — Web & Mobile

> **Covers:** metric definitions, where each number comes from (app events vs. voice session vs. LLM disposition), the analytics API shared by web and app, and UI changes in the existing frontend and the Android app.

---

## 1. Principle

**One API, two clients.** Every number is computed server-side from `mobile_call_attempts`, `campaign_calls` and `voice_sessions`. The web frontend and the Android app render the same responses, so they can't disagree.

The backend **can't observe the lead leg** (it never touches our infrastructure). Everything about lead dialing, ringing and answering comes from **app events**. Everything about the conversation comes from the **voice session**. Each metric states its source below.

## 2. Metric definitions

### 2.1 Funnel (per campaign, per rep, per date range)

| Stage | Definition | Source |
|-------|-----------|--------|
| Leads | `campaign_calls` in campaign | DB |
| Attempted | distinct `campaign_call_id` with ≥ 1 attempt | attempts |
| AI ready | attempts reaching `ai_ready` or `unidentified_ready` | attempts (GW) |
| Lead answered | attempts with `lead_answered_at` | app events |
| Merged | attempts with `merged_at` | app events |
| Conversation | merged attempts with `conversation_seconds ≥ 30` | voice session |
| Interested | `campaign_calls.disposition = 'interested'` | post-call LLM (existing) |

### 2.2 Rates

| Metric | Formula |
|--------|---------|
| Answer rate | Lead answered ÷ attempts that reached lead dialing |
| Merge success rate | Merged ÷ Lead answered |
| Identification rate | attempts with method ∈ {cli, dtmf, cli+dtmf} ÷ AI ready |
| DTMF confirmation rate | method = `cli+dtmf` ÷ method ∈ {cli, cli+dtmf} (carrier health signal) |
| Identification conflict rate | `identification_conflict = true` ÷ AI ready (**must be ~0**; alert if > 0.5 %) |
| Conversion | Interested ÷ Conversation |

### 2.3 Timing

| Metric | Formula |
|--------|---------|
| AI ready latency | `ai_ready_at − created_at` (p50/p95) |
| Lead ring time | `lead_answered_at − lead_dialed_at` |
| Time to first AI word | first agent `conversation_history` turn − `merged_at` (NFR-2 ≤ 3 s) |
| Avg conversation | mean `conversation_seconds` for Conversation stage |
| Idle AI minutes | Σ (`ended_at − ai_answered_at`) for attempts that never merged (cost of AI-first) |

### 2.4 Outcomes

| Bucket | Values |
|--------|--------|
| Lead failures | `busy`, `no_answer`, `rejected`, `unreachable`, `invalid` (from Android `DisconnectCause`) |
| AI/system failures | `ai_leg_failed`, `merge_failed`, `merge_timeout`, `abandoned` |
| Dispositions | `interested`, `not_interested` (+ reason), `voicemail`, `neutral` (existing `parse_disposition`) |

### 2.5 Cost

| Metric | Source |
|--------|--------|
| Telephony minutes (AI leg, inbound) | `usage_logs` via existing `VoiceUsageLogger` |
| LLM audio minutes | `usage_logs` |
| Billed amount | existing TB formula (`BillingService.calculate_tb`) |
| Cost per interested lead | billed ÷ interested |

Rep SIM costs are not visible to us and are out of scope.

## 3. API

Mounted in the existing `campaign_router` / a new `mobile_analytics` module. Scoping: tenant users get their own data only (the `user_id` filter is forced); tenant admins can filter by any rep in the company.

### `GET /api/v1/campaigns/{id}/mobile-analytics`

```json
{
  "campaign_id": "uuid",
  "execution_mode": "mobile_conference",
  "funnel": {"leads": 250, "attempted": 180, "ai_ready": 176, "lead_answered": 98,
             "merged": 95, "conversation": 81, "interested": 17},
  "rates": {"answer": 0.557, "merge_success": 0.969, "identification": 0.994,
            "dtmf_confirmation": 0.97, "identification_conflict": 0.0, "conversion": 0.21},
  "timing": {"ai_ready_p50_s": 6.1, "ai_ready_p95_s": 11.8, "first_ai_word_p50_s": 1.9,
             "avg_conversation_s": 142, "idle_ai_minutes": 38.5},
  "outcomes": {"busy": 21, "no_answer": 52, "rejected": 6, "merge_failed": 3,
               "interested": 17, "not_interested": 49, "voicemail": 4, "neutral": 11},
  "cost": {"billed_amount": 1234.50, "currency": "INR", "per_interested": 72.62},
  "by_rep": [
    {"user_id": "uuid", "name": "Ravi", "attempted": 90, "answer_rate": 0.58,
     "merge_success": 0.98, "interested": 9, "talk_minutes": 101}
  ]
}
```

### `GET /api/v1/mobile/analytics/summary?from=&to=&user_id=`

Same shape without `campaign_id`, aggregated across `mobile_conference` campaigns, plus `daily: [{date, attempted, merged, interested}]`.

### `GET /api/v1/campaigns/{id}/calls?status=&disposition=&user_id=&limit=&offset=`

Paged call list for both clients (the current `GET /campaigns/{id}` returns every row, which is too heavy for mobile). Each row: `{campaign_call_id, contact_name, phone_masked, rep_name, attempt_status, identification_method, disposition, conversation_seconds, called_at, voice_session_id}`.

### `GET /api/v1/mobile/call-attempts/{id}/timeline`

Merged view of app events and session milestones for the call-detail timeline.

Existing and reused for call detail: `GET /api/v1/streaming/voice-sessions/{id}` (transcript, summary, recording).

**Performance.** Compute on read with SQL aggregates over indexed columns, which is fine up to roughly 100k attempts per company. If p95 exceeds 500 ms, add a `campaign_daily_stats` rollup refreshed by the Arq cron.

## 4. Web frontend changes

| Where | Change |
|-------|--------|
| [`CampaignsPage.tsx`](../../frontend/src/pages/streaming/CampaignsPage.tsx) | "Mode" badge (Server dialer / Mobile). Hide the Start button for mobile campaigns and show "Run from the mobile app". |
| [`CampaignCreateModal.tsx`](../../frontend/src/pages/streaming/CampaignCreateModal.tsx) | Accept `.xlsx`; switch to `/upload-contacts`; execution mode selector; assignee multi-select (admins). |
| [`CampaignDetailPage.tsx`](../../frontend/src/pages/streaming/CampaignDetailPage.tsx) | For mobile campaigns: funnel chart, rate tiles (answer, merge, identification, conversion), timing tiles, outcome breakdown, per-rep table, paged call list with identification badge; keep the existing Excel download (add mobile columns). |
| [`CallDetailPage.tsx`](../../frontend/src/pages/streaming/CallDetailPage.tsx) | If the session has `attempt_id`: show rep, identification method, and an attempt timeline above the transcript. |
| New: `/streaming/mobile-analytics` | Company summary across mobile campaigns with rep + date filters. |

Follow the repo `dataviz` conventions for charts. Polling stays at 5 s while a mobile run is active, as on the existing campaign pages.

## 5. Android analytics screens

| Screen | Content |
|--------|---------|
| Analytics tab | Date range chips (Today / 7 d / 30 d); funnel; tiles: calls, answer rate, conversations, interested; daily bar chart; admins get a rep picker |
| Campaign detail | Same funnel for the campaign, outcome breakdown, paged call list (filter: interested / not interested / failed) |
| Call detail | Timeline, AI summary, disposition, next action, transcript bubbles, recording playback (`/api/v1/artifacts/{id}/download` with bearer header) |

Charts: Vico (Compose charting) or a simple Canvas implementation. There is no offline analytics; show last-fetched data with its timestamp.

## 6. Excel export additions

Add to the "Call Details" sheet for mobile campaigns: `Rep`, `Identification`, `Lead Ring (s)`, `Merged At`, `Failure Cause`, `Assisted`.
