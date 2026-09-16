# 12. Voice, Telephony & Messaging — Defect Register

> **What this document is:** defects in how a phone call or a WhatsApp message becomes a
> conversation with an LLM — the webhooks, the live-audio path, campaigns, guardrails and
> voice billing — plus the improvements that would make calls cheaper and more reliable.
> **Source document:** [`12-voice-and-telephony.md`](../12-voice-and-telephony.md)
> **Compiled:** 2026-09-01, against branch `fresh-main`.
> **Context:** voice does **not** run through `AgentLoop`. It has no planner, no critics,
> no memory write-back, no HITL and no per-turn token accounting. Several defects below
> follow directly from that.

---

## How to read this file

- **✅ Verified** — the code was read on 2026-09-01 and the claim held.
- **📄 Doc-reported** — from `12-voice-and-telephony.md`, not independently re-checked.
- Three whole features in this subsystem are **broken end to end**: the inbound credit
  gate, Azure Realtime voice, and WhatsApp AI replies. Each fails in a way that produces a
  plausible-looking log line rather than an error.

---

## Contents

1. [Summary](#1-summary)
2. [T0 — Broken end to end](#2-t0--broken-end-to-end)
3. [T1 — Money and metering](#3-t1--money-and-metering)
4. [T2 — Controls that are stored and ignored](#4-t2--controls-that-are-stored-and-ignored)
5. [T3 — Correctness and dead ends](#5-t3--correctness-and-dead-ends)
6. [Improvements](#6-improvements)
7. [Suggested order of work](#7-suggested-order-of-work)

---

## 1. Summary

| Tier | Theme | Count | When to do it |
|---|---|---|---|
| [T0](#2-t0--broken-end-to-end) | Broken end to end | 4 | **Now** — each is a whole feature |
| [T1](#3-t1--money-and-metering) | Money and metering | 4 | Before charging for calls |
| [T2](#4-t2--controls-that-are-stored-and-ignored) | Controls that are stored and ignored | 5 | Before relying on the control |
| [T3](#5-t3--correctness-and-dead-ends) | Correctness and dead ends | 8 | When the area is next touched |

**Total: 21 defects, 10 improvements.**

The three to read first:

- **[VT-01](#vt-01--the-inbound-credit-gate-has-never-run)** — a `NameError` swallowed by
  a broad `except`, logged as a transient blip. Inbound calls have never been credit-gated.
- **[VT-02](#vt-02--azure-realtime-returns-a-tuple-where-a-session-belongs)** — the whole
  Azure voice provider cannot work.
- **[VT-03](#vt-03--every-whatsapp-ai-reply-is-an-apology)** — a wrong call signature means
  every customer gets the fallback string.

---

## 2. T0 — Broken end to end

### VT-01 — The inbound credit gate has never run

**✅ Verified · Critical**

Both inbound handlers do this:

```python
credit_svc = CreditService(db)
```

Neither function has `db` as a parameter. `twilio_incoming_call` takes only `request`,
`session_manager` and `number_router`; `tata_incoming_call` takes the same three.

The resulting `NameError` is caught by the surrounding `except`, logged as
*"Pre-call credit check failed (allowing call)"*, and **the call proceeds**.

So the pre-call balance check on inbound calls has never executed once. A company with a
zero wallet can receive unlimited inbound calls, each of which costs real telephony and
LLM money.

- [`voice/webhook_router.py:74`](../../../backend/src/voice/webhook_router.py:74) — inside `twilio_incoming_call` (signature at [`:34`](../../../backend/src/voice/webhook_router.py:34))
- [`voice/webhook_router.py:615`](../../../backend/src/voice/webhook_router.py:615) — inside `tata_incoming_call` (signature at [`:497`](../../../backend/src/voice/webhook_router.py:497))
- Also recorded as **D-11** in the platform register

**Fix:** use `session_manager.db`, which is already in scope. One line each. Then narrow
the `except` so a coding error cannot masquerade as a transient failure again — that broad
catch is the reason this survived.

---

### VT-02 — Azure Realtime returns a tuple where a session belongs

**✅ Verified · High**

`LiveClientFactory.get_live_client` documents its return as:

> `live_client: GeminiLiveClient or AzureRealtimeClient (already connected session)`

The Gemini branch honours that. The Azure branch does not:

```python
client = AzureRealtimeClient(...)
return client, config  # Return both so caller can call client.connect(config)
```

so the factory returns `((client, config), "azure_openai")` — a **tuple**, un-connected,
where the caller expects a live session.

`azure_realtime.py` itself is correct: `connect()` builds a proper `AzureRealtimeSession`
and initialises it. Nothing calls it.

The same path in `web_audio_adapter.py` calls
`self.audio_processor.pcm24_to_pcm16(audio_data)`. `AudioProcessor` has `pcm24_to_mulaw`
and `pcm16_to_mulaw` — **there is no `pcm24_to_pcm16`**. That is an `AttributeError` at
the first audio frame.

So Azure OpenAI Realtime is configurable in the admin UI and cannot work.

- [`voice/live_client_factory.py:175`](../../../backend/src/voice/live_client_factory.py:175) — the tuple return
- [`voice/azure_realtime.py:204`](../../../backend/src/voice/azure_realtime.py:204) — the correct, uncalled path
- [`gateway/web_audio_adapter.py:172`](../../../backend/src/gateway/web_audio_adapter.py:172) — the missing method
- Also recorded as **D-18** in the platform register

**Fix:** `await client.connect(config)` in the factory and return the session. Add
`pcm24_to_pcm16` to `AudioProcessor`, or convert through mu-law.

---

### VT-03 — Every WhatsApp AI reply is an apology

**✅ Verified · High**

The handler calls:

```python
gemini_service = GeminiTextServiceFactory.get_service(
    api_key=agent_context.api_key,
    system_instruction=agent_context.system_instruction,
    model="gemini-2.0-flash"
)
```

The factory's signature is:

```python
def get_service(cls, service_metadata: Dict[str, Any], model=None, system_instruction=None, **kwargs)
```

`service_metadata` is a **required positional** parameter and is not supplied. `api_key` is
absorbed by `**kwargs`. The call raises `TypeError: get_service() missing 1 required
positional argument: 'service_metadata'`, which is caught, and every customer receives the
fallback apology string instead of a generated reply.

- [`voice/whatsapp_handler.py:210`](../../../backend/src/voice/whatsapp_handler.py:210) — the call
- [`voice/gemini_text.py:170`](../../../backend/src/voice/gemini_text.py:170) — the signature
- Also recorded as **D-19** in the platform register

**Fix:** pass `service_metadata` from the resolved integration. The agent context already
carries what is needed.

---

### VT-04 — Port 8002 is a ghost that Apache still points at

**✅ Verified · High**

`voice/main.py` is a complete FastAPI app with the three streaming WebSocket endpoints and
even a helpful HTTP 426 diagnostic for a missing `mod_proxy_wstunnel`. Nothing starts it.

The gateway on 8001 serves the real WebSockets. But
`streaming.hirebuddha.com-le-ssl.conf` still rewrites to `ws://127.0.0.1:8002/` and
proxies to `http://localhost:8002/`, and `STREAMING_HOST` still defaults to
`localhost:8002`.

So an unconfigured deployment hands telephony a `wss://` URL pointing at nothing.

- [`voice/main.py`](../../../backend/src/voice/main.py)
- [`deploy/apache/streaming.hirebuddha.com-le-ssl.conf`](../../../deploy/apache/streaming.hirebuddha.com-le-ssl.conf)
- [`common/config.py:10`](../../../backend/src/common/config.py:10)
- Same as [SA-01](02-SYSTEM-ARCHITECTURE-DEFECTS.md#sa-01--streaming_host-defaults-to-a-service-that-does-not-run)
  and **W-1** in the platform register

---

## 3. T1 — Money and metering

### VT-05 — Voice tokens are estimated at a flat 167 per second

**📄 Doc-reported · High**

There is no real token accounting for voice. When the SKU is not per-minute, cost is:

```python
tokens_per_second = Decimal("167")
estimated_tokens = tokens_per_second * Decimal(str(audio_seconds))
```

Both LLM rows — audio in and audio out — default to the **entire** call duration, because
in a speech-to-speech session both directions are nominally open the whole time.

So a call where the customer talks for 90% of the time is billed the same as one where the
agent does. The estimate may be roughly right on average and it is not right for any
individual call, and there is no way to reconcile it against the provider's bill.

- [`voice/usage_logger.py`](../../../backend/src/voice/usage_logger.py)

---

### VT-06 — Voice tool calls are unattributed and unbilled

**✅ Verified · High**

The voice handler builds `extra_context` with only `company_id` and `user_id` — no
`run_id`, no `agent_id` — and runs no cost block at all.

A voice agent can call `whatsapp_send_tenant` and `crm_update_lead` with no run linkage and
no ledger entry. Every `ToolInteractionLog` from this path is unlinkable to a run.

- [`voice/websocket_handler.py:993`](../../../backend/src/voice/websocket_handler.py:993)–1000
- Recorded in full as [TL-20](TOOL-LAYER-DEFECTS.md#tl-20--voice-tool-calls-are-unattributed-and-unbilled)

---

### VT-07 — Recording-artifact lookup can attach the wrong file

**📄 Doc-reported · Medium**

When the exact match fails, recording lookup falls back to **time proximity**. If several
calls end together — which is the normal case during a campaign — the fallback can attach
one call's WAV to another call's record.

That is a privacy problem as well as a data-quality one: a customer listening to their call
recording may hear a different customer's call.

---

### VT-08 — The outbound and inbound credit gates disagree by design

**📄 Doc-reported · Medium**

At `_setup_live_and_run`, an **outbound** call with insufficient credit is blocked and the
WebSocket closed with code `4002`. An **inbound** call is allowed through with a warning,
"so nobody misses an important call".

That is a defensible product decision. It is recorded here because combined with
[VT-01](#vt-01--the-inbound-credit-gate-has-never-run) — where the earlier inbound gate
never fires either — it means there is **no working credit control on inbound calls at
all**, at either checkpoint.

---

## 4. T2 — Controls that are stored and ignored

| ID | Control | Reality | Status |
|---|---|---|---|
| **VT-09** | `max_calls_per_hour` | Stored on the campaign, shown in the UI, **never enforced**. The only real throttles are `max_concurrent_calls` and a flat 2-second sleep between calls | 📄 Doc-reported |
| **VT-10** | `CampaignCall.max_retries` | Stored and displayed, never enforced | 📄 Doc-reported |
| **VT-11** | `speaking_rate` and `pitch` | Parsed off `VoiceConfig` by `GeminiLiveClient` and then dropped — the `speech_config` it builds contains only `voice_name` | 📄 Doc-reported |
| **VT-12** | `_create_native_audio_config` vs `_create_standard_config` | Both return the **same dict**. The capability registry that selects between them changes nothing | 📄 Doc-reported |
| **VT-13** | DTMF | Completely unimplemented on both providers. There is no digit collection anywhere in the voice package — so no IVR, no menu, no keypad confirmation | 📄 Doc-reported |

---

## 5. T3 — Correctness and dead ends

### VT-14 — The lead queue is written and never drained

**✅ Verified · Medium**

`lead_queue_worker.py` has zero importers, is in no `WorkerSettings.functions`, and is
started by no script. The docs add that its call signature is wrong.

The gateway dispatcher writes leads into `lead_queue`. They accumulate and are never
dialled.

- [`ai/lead_queue_worker.py`](../../../backend/src/ai/lead_queue_worker.py)
- Also [SA-08](02-SYSTEM-ARCHITECTURE-DEFECTS.md#sa-08--the-lead-queue-fills-up-and-is-never-drained) and **D-21/D-26**

---

### VT-15 — `"sucess"` is a real key on the wire

**📄 Doc-reported · Low · accept**

Both Tata voice webhook responses return `{"sucess": ...}`. It is misspelled and it is an
**external contract**. Correcting it is a breaking change that needs coordination with the
provider.

Recorded so nobody "fixes" it in passing. Also **D-42** in the platform register.

---

### VT-16 — Agent edits take up to five minutes to reach new calls

**📄 Doc-reported · Medium**

`AgentContextLoader` TTL-caches persona, tools, context-source extraction and the API key
for `VOICE_AGENT_CACHE_TTL_SECONDS` (default 300), because a cold load took 4.5–5 seconds
on the call-setup hot path.

The trade is sound. The cost is that an operator fixing a bad prompt mid-campaign watches
the old prompt keep dialling for up to five minutes, with nothing in the UI explaining
why.

**Fix:** invalidate the cache entry when the entity is updated. The company id is known at
both ends.

---

### VT-17 — `ensure_chunk_size` pads with the wrong byte

**📄 Doc-reported · Low**

It pads with `0x00`, which in mu-law is **maximum negative amplitude**, not silence
(`0xFF` is). Padding therefore appends a burst of full-scale noise rather than quiet.

It is harmless today only because the single caller passes exactly 32,000 bytes — a clean
multiple of 160 — so the padding branch never runs. Any new caller with a different size
gets audible clicks.

---

### VT-18 — A campaign's company comes from the agent, not the user

**📄 Doc-reported · Low · correct as-is**

Deliberate, and worth knowing: otherwise an `app_admin` creating a campaign would dial from
the wrong tenant's caller ID and bill the wrong wallet.

Recorded so it is not "fixed" into a bug.

---

### VT-19 — Silence is measured against the playback horizon

**📄 Doc-reported · Low · correct as-is**

Also deliberate. The model can emit a 30-second reply in a 2-second burst; measuring
silence from send time would declare silence while the lead is still listening.

Recorded because it looks wrong on first reading and someone will try to simplify it.

---

### VT-20 — Muted audio is sent as zeros rather than dropped

**📄 Doc-reported · Low · correct as-is**

Gaps break Gemini's end-of-turn detection, so the mute path sends silence frames instead of
sending nothing. Same note: it looks like a bug and is not.

---

### VT-21 — A voice call has no run record, so nothing about it is auditable the usual way

**📄 Doc-reported · Medium**

A voice call produces a `VoiceSession`, not an `ExecutionRun`. It has no
`ExecutionStep` rows, no planner, no critics, no CORTEX write-back beyond a
`context_state.call_summary`, no per-turn token accounting and no HITL gates.

That is the intended architecture. The consequences are worth stating plainly:

- Voice work is invisible to every run-based report and dashboard.
- A voice agent that misbehaves cannot be inspected with the trace viewer.
- Nothing a voice call learns reaches the agent's memory.
- Governance checkpoints configured on the entity do not apply to its calls.

An entity that is used both as a text agent and as a voice agent therefore behaves under
two different sets of rules, and only one of them is documented in the builder.

---

## 6. Improvements

### VT-I1 — Reconcile voice billing against the provider

**Effect: large.** [VT-05](#vt-05--voice-tokens-are-estimated-at-a-flat-167-per-second).
Both LLM rows bill the full call duration at a flat 167 tokens/second estimate. Gemini Live
reports real usage; capture it and bill from that, keeping the estimate only as a fallback
when the provider does not report.

Until then, voice margin is unknown in both directions.

### VT-I2 — Enforce `max_calls_per_hour`

**Effect: medium.** [VT-09](#4-t2--controls-that-are-stored-and-ignored). The current
throttle is `max_concurrent_calls` plus a flat 2-second sleep, which for 5 concurrent calls
is roughly 9,000 calls per hour. A tenant who sets 200/hour and gets thousands has a
compliance problem, not a performance one.

### VT-I3 — Invalidate the agent cache on entity update

**Effect: medium.** [VT-16](#vt-16--agent-edits-take-up-to-five-minutes-to-reach-new-calls).
Publish an invalidation on Redis when an entity is saved. Keeps the 5-second cold-load
saving and removes the five-minute surprise.

### VT-I4 — Attribute voice tool calls to a run

**Effect: large for auditability.** [VT-06](#vt-06--voice-tool-calls-are-unattributed-and-unbilled).
Create a lightweight `ExecutionRun` per call — or at minimum stamp `run_id` and `agent_id`
into `extra_context` — so tool calls made on the phone are billed and traceable like every
other tool call.

This is also the smallest step towards fixing
[VT-21](#vt-21--a-voice-call-has-no-run-record-so-nothing-about-it-is-auditable-the-usual-way).

### VT-I5 — Attach recordings by call id only

**Effect: medium.** [VT-07](#vt-07--recording-artifact-lookup-can-attach-the-wrong-file).
Delete the time-proximity fallback. A missing recording is better than the wrong customer's
recording.

### VT-I6 — Write the call summary into CORTEX

**Effect: medium.** Today a call produces one summary stored on
`context_state.call_summary` and nothing else. Writing it as an episodic node would let a
returning caller be recognised, and would make voice history available to the text agents
that share the same entity.

This depends on [MC-I1](08-MEMORY-AND-CORTEX-DEFECTS.md#mc-i1--wire-the-read-path) — there
is no point writing more memory until something reads it.

### VT-I7 — Cache the Tata auth token across workers

**Effect: small.** `TATA_AUTH_TOKEN_TTL_SECONDS` defaults to 43,200 (12 hours), but the
cache is per process. Every worker performs its own Smartflo login. Moving it to Redis
makes it one login per 12 hours across the fleet.

### VT-I8 — Report campaign throughput honestly

**Effect: medium.** The dialer's real behaviour is `max_concurrent_calls` plus a flat
2-second sleep. The UI presents `max_calls_per_hour` and `max_retries` as controls
([VT-09](#4-t2--controls-that-are-stored-and-ignored),
[VT-10](#4-t2--controls-that-are-stored-and-ignored)). Either enforce them or show the
actual expected throughput on the campaign form, so an operator can plan.

### VT-I9 — Implement DTMF, or say it is not supported

**Effect: medium.** [VT-13](#4-t2--controls-that-are-stored-and-ignored). No digit
collection means no IVR, no "press 1 to speak to sales", no keypad confirmation of a
booking. For an outbound sales product that is a real functional gap, and today a customer
discovers it only after building a campaign around it.

### VT-I10 — One place that decides whether a call may proceed

**Effect: medium.** Credit gating happens at three points with three different behaviours,
and two of them are broken or inconsistent
([VT-01](#vt-01--the-inbound-credit-gate-has-never-run),
[VT-08](#vt-08--the-outbound-and-inbound-credit-gates-disagree-by-design)). One
`can_start_call(company_id, direction)` used by all three would make the policy explicit
and testable.

---

## 7. Suggested order of work

| Step | Work | Why here |
|---|---|---|
| **1** | VT-01 | One line per handler. Restores a credit gate the platform already believes it has |
| **2** | VT-03 | One argument. Restores WhatsApp AI replies entirely |
| **3** | VT-02 | Connect the Azure session and add the missing converter, or remove the provider from the UI |
| **4** | VT-04 | Repoint or delete the 8002 vhosts and the `STREAMING_HOST` default — **W-1** |
| **5** | VT-I1 / VT-05, VT-I4 / VT-06 | Voice billing that reconciles, and tool calls that are attributed |
| **6** | VT-I3 / VT-16, VT-I5 / VT-07 | Cache invalidation and correct recording attachment |
| **7** | VT-I2 / VT-09, VT-10, VT-14 | Enforce the campaign throttles; decide the lead queue's fate |
| **8** | VT-I9 / VT-13 | DTMF, if the product needs it |

---

## Where to go next

- [12 — Voice, telephony & messaging](../12-voice-and-telephony.md) — the source document.
- [`DEFECT-REGISTER.md`](../DEFECT-REGISTER.md) — VT-01 is D-11, VT-02 is D-18, VT-03 is
  D-19, VT-14 is D-21/D-26, VT-04 is W-1.
- [13 — Gateway & real-time](13-GATEWAY-AND-REALTIME-DEFECTS.md) — the WebSocket handshake
  and the dispatcher behind these handlers.
- [14 — Billing & credits](14-BILLING-AND-CREDITS-DEFECTS.md) — the ledger VT-05 and VT-06
  feed.
- [02 — System architecture](02-SYSTEM-ARCHITECTURE-DEFECTS.md) — SA-01 and SA-02 for the
  port-8002 removal.
