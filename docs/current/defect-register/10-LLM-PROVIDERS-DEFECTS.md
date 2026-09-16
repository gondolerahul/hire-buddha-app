# 10. LLM Providers, Routing & Integrations — Defect Register

> **What this document is:** defects in which model runs, with whose credentials, and at
> what cost — the integration registry, credential resolution, the adapters and token
> accounting — plus the improvements that would make the layer resilient and correctly
> priced.
> **Source document:** [`10-llm-providers.md`](../10-llm-providers.md)
> **Compiled:** 2026-09-01, against branch `fresh-main`.
> **Context:** this layer has **no retry, no timeout, no fallback and no circuit
> breaker**, despite being named "Router". Every LLM failure propagates straight to the
> caller.

---

## How to read this file

- **✅ Verified** — the code was read on 2026-09-01 and the claim held.
- **📄 Doc-reported** — from `10-llm-providers.md`, not independently re-checked.
- Two groups matter most: [§2](#2-t0--money-and-availability) is money and availability,
  [§3](#3-t1--configuration-that-cannot-work) is configuration a user can set that cannot
  work.

---

## Contents

1. [Summary](#1-summary)
2. [T0 — Money and availability](#2-t0--money-and-availability)
3. [T1 — Configuration that cannot work](#3-t1--configuration-that-cannot-work)
4. [T2 — Delete](#4-t2--delete)
5. [T3 — Correctness in the adapters](#5-t3--correctness-in-the-adapters)
6. [Improvements](#6-improvements)
7. [Suggested order of work](#7-suggested-order-of-work)

---

## 1. Summary

| Tier | Theme | Count | When to do it |
|---|---|---|---|
| [T0](#2-t0--money-and-availability) | Money and availability | 6 | Before the first paying tenant |
| [T1](#3-t1--configuration-that-cannot-work) | Configuration that cannot work | 6 | Before anyone follows the setup guide |
| [T2](#4-t2--delete) | Delete | 4 | **Now** — free |
| [T3](#5-t3--correctness-in-the-adapters) | Correctness in the adapters | 8 | When the provider is next touched |

**Total: 24 defects, 10 improvements.**

The three to read first:

- **[LP-01](#lp-01--cost_unit-per_1k_tokens-over-bills-by-1000)** — a `cost_unit` value
  used in the platform's own credentials guide multiplies every bill by 1000.
- **[LP-03](#lp-03--there-is-no-retry-timeout-or-fallback-anywhere-in-the-llm-layer)** — a
  single 429 from a provider fails the run.
- **[LP-07](#lp-07--any-claude-integration-fails-on-its-first-call)** — the adapter is
  complete, the docs explain how to configure it, and the package is not installed.

---

## 2. T0 — Money and availability

### LP-01 — `cost_unit: per_1k_tokens` over-bills by 1000×

**✅ Verified · Critical**

The divisor is chosen by substring matching on `cost_unit`:

```python
if "1m token" in unit_lower or "per_million" in unit_lower or "million" in unit_lower:
    divisor = Decimal("1000000.0")
elif "1k token" in unit_lower:
    divisor = Decimal("1000.0")
elif "1000 char" in unit_lower:
    divisor = Decimal("1000.0")
```

Note the asymmetry. The million branch accepts `per_million` — the underscore form. The
thousand branch matches only `"1k token"` **with a space**.

So `cost_unit = "per_1k_tokens"` matches nothing, `divisor` stays `1.0`, and the cost is
computed as `internal_cost × token_count` instead of `internal_cost × token_count / 1000`
— a **1000× over-charge** on every row.

The credentials guide uses the underscore form in its examples.

- [`ai/usage_service.py:89`](../../../backend/src/ai/usage_service.py:89)–100

**Fix:** normalise the unit string before matching, and add a validator on the
integration-create endpoint that rejects any `cost_unit` the divisor logic does not
recognise. Silently defaulting to a divisor of 1 is the wrong failure mode for a pricing
field.

---

### LP-02 — `LLMResponse.cost_usd` is hardcoded to zero

**✅ Verified · High**

```python
@property
def cost_usd(self) -> float:
    """Estimated cost — placeholder for future per-model pricing."""
    return 0.0
```

The property exists on every LLM response, is named exactly what a caller would reach for,
and always returns `0.0`. Anything that bills from it silently charges nothing.

Real cost comes from `usage_service` writing an attributed `usage_logs` row from the SKU
lookup. Nothing enforces that a caller uses that path instead of the property.

- [`ai/llm/types.py:76`](../../../backend/src/ai/llm/types.py:76)

**Fix:** delete the property. A missing attribute is an immediate error; a zero is a silent
one.

---

### LP-03 — There is no retry, timeout or fallback anywhere in the LLM layer

**📄 Doc-reported · Critical**

| Concern | Status |
|---|---|
| Provider fallback | not implemented — one task type, one integration, one provider |
| Retry on 429 / 5xx | not implemented — no backoff, exceptions propagate |
| Request timeout | not set — each SDK's own default applies |
| Circuit breaking | not implemented |
| Streaming (text) | not implemented |

A single rate-limit response from Azure or Vertex fails the step, which fails the
iteration, which — depending on the retry strategy — can fail the run. For the most common
transient failure in the entire system, the platform has no handling at all.

The naming actively misleads: the module is `ai/llm/router.py` and the class is
`LLMRouter`. There is also a `routing_mode` setting with a `"router"` value that does
nothing ([LP-08](#lp-08--routing_mode-is-stored-returned-and-never-read)).

- [`ai/llm/router.py`](../../../backend/src/ai/llm/router.py)

**Fix:** wrap `adapter.generate` in a bounded retry with jitter on 429 and 5xx, and set an
explicit timeout. That is perhaps thirty lines and it changes the reliability of every run
on the platform.

---

### LP-04 — The one error handler logs a retry it does not perform

**📄 Doc-reported · High**

The only error handling in the layer is a Gemini SDK-version workaround:

```python
logger.warning(f"SDK finish_reason validation error (non-fatal), retrying with raw HTTP: {e}")
raise RuntimeError(...)
```

The log says "retrying with raw HTTP". The next line re-raises. There is no raw-HTTP retry
anywhere.

In the ReAct loop the same condition is treated as **end of turn** (`break`) instead —
so the loop silently truncates and returns whatever it had, with no error and no flag.

- [`ai/llm/gemini_adapter.py`](../../../backend/src/ai/llm/gemini_adapter.py)

---

### LP-05 — An entity `model_override` changes the model but not the provider

**📄 Doc-reported · High**

`model_override` replaces the model id and leaves the resolved provider and credentials in
place. Overriding a Gemini default with `gpt-4o` therefore sends `gpt-4o` **to Vertex AI**.

It gets worse at billing time: the `-in` / `-out` SKUs are string-concatenated from
whatever model name the adapter reports. An override with no matching SKU **bills zero**
and only logs a warning.

So a single mis-set field in the builder produces a run that either fails at the provider
or succeeds and is not charged.

**Fix:** resolve the override through the integration registry like any other model, and
refuse an override with no matching integration.

---

### LP-06 — Gemini thinking tokens are not counted

**📄 Doc-reported · High**

`thoughts_token_count` is ignored in token accounting. For reasoning models, thinking
tokens are frequently the majority of the spend.

So the platform under-reports and under-bills exactly the models it routes the `thinking`
task type to.

- [`ai/llm/gemini_adapter.py`](../../../backend/src/ai/llm/gemini_adapter.py) — token accounting

---

## 3. T1 — Configuration that cannot work

### LP-07 — Any Claude integration fails on its first call

**✅ Verified · High**

`pyproject.toml` declares `google-genai` and `openai`. It does **not** declare `anthropic`.
`AnthropicAdapter._build_client` starts with:

```python
try:
    import anthropic
except ImportError:
    raise RuntimeError("anthropic package not installed. Run: pip install anthropic")
```

The adapter is complete, the provider factory wires it up, and the credentials guide
explains how to configure it. An admin can follow that guide, register an `anthropic`
integration, point the `thinking` task at it — and every call raises before reaching
Vertex AI.

Five of the nine critic-ladder entries route to Claude models.

- [`ai/llm/anthropic_adapter.py`](../../../backend/src/ai/llm/anthropic_adapter.py) — `_build_client`
- [`backend/pyproject.toml:34`](../../../backend/pyproject.toml:34)–35
- Also recorded as **D-12** in the platform register

**Fix:** add the dependency, or remove the adapter, the factory entry and the guide section
so nobody can configure a path that cannot work.

---

### LP-08 — `routing_mode` is stored, returned, and never read

**✅ Verified · Medium**

`ModelTaskDefault.routing_mode` is a real column with values `single` and `router`. It is
accepted by the create endpoint, persisted, and returned by the read endpoint. The
frontend renders it.

**No code reads it.** There is no fallback router to switch to. `router` and `single`
behave identically.

- [`config/models.py:76`](../../../backend/src/config/models.py:76) — the column
- [`config/router.py:225`](../../../backend/src/config/router.py:225) — write
- [`config/router.py:240`](../../../backend/src/config/router.py:240) — read

---

### LP-09 — Three task types the code uses are rejected by the API

**✅ Verified · High**

`TASK_TYPES` contains eleven values. It does **not** contain `embedding`, `vision` or
`goal_validation`. All three are used as task types in live code:

| Task type | Used at |
|---|---|
| `embedding` | [`ai/memory/embedding_service.py`](../../../backend/src/ai/memory/embedding_service.py) — model resolution step 1 |
| `vision` | [`gateway/video_gateway.py:312`](../../../backend/src/gateway/video_gateway.py:312) |
| `goal_validation` | [`ai/planning/planner_service.py:231`](../../../backend/src/ai/planning/planner_service.py:231) |

The write endpoint validates against `TASK_TYPES` and 422s on all three. So the AI Config
page renders an `Embedding` card that **can never be saved**, and the embedding service's
first resolution step can never find a row.

- [`config/models.py:11`](../../../backend/src/config/models.py:11)–23 — `TASK_TYPES`

**Fix:** add the three values. They are already in use; the list is simply out of date.

---

### LP-10 — Nothing is seeded, so a fresh install cannot run an agent

**📄 Doc-reported · High**

`model_task_defaults` starts empty. Until an `app_admin` configures `text_generation`,
every run fails with "No model configured".

Combined with [PO-03](01-PRODUCT-OVERVIEW-DEFECTS.md#po-03--nothing-pushes-a-new-user-into-onboarding)
— nothing forces a new user into the onboarding wizard that would tell them this — a new
tenant's first experience is an agent that fails with an error that does not say what to do.

**Fix:** seed a sensible default in the same script that seeds the admin user, or make the
error message name the exact page to visit.

---

### LP-11 — `service_category` is free text and the code queries for different values

**📄 Doc-reported · Medium**

`service_category` is a plain string column. The values named in the model's own column
comment — `IMAGE_GEN`, `VIDEO_GEN` — are not the values the resolution code queries for.

So an admin who follows the comment creates a row that the resolver will never find, and
gets "No model configured" for a model that is plainly configured on the screen.

**Fix:** make it an enum, and validate on write.

---

### LP-12 — Vertex requires a placeholder API key it then ignores

**📄 Doc-reported · Low**

Vertex AI authenticates with application default credentials and ignores the stored key —
but `encrypted_api_key` is non-nullable, so the admin must store something. The
recommended value is the literal string `vertex-ai-service-account`.

Harmless, and worth recording because it looks exactly like a misconfiguration during
debugging.

---

## 4. T2 — Delete

| ID | Delete | Notes | Status |
|---|---|---|---|
| **LP-13** | `src/ai/core/reasoning/` | Registers `REACT` and `CHAIN_OF_THOUGHT` strategies. `get_reasoning` is defined and exported and has **no callers** — the step executor branches on the mode string directly. The adapters also pass a `config=` kwarg the router silently swallows | ✅ Verified |
| **LP-14** | `LLMResponse.cost_usd` | See [LP-02](#lp-02--llmresponsecost_usd-is-hardcoded-to-zero). Deleting it is the fix | ✅ Verified |
| **LP-15** | `routing_mode` | See [LP-08](#lp-08--routing_mode-is-stored-returned-and-never-read). Remove the column, the schema fields and the disabled UI control — or build the fallback router it implies | ✅ Verified |
| **LP-16** | The `_scrub_internal_keys` reference in `INTERNAL_KEYS.md` | `prompt_utils._scrub_internal_keys` does not exist. Scrubbing is inline in the step executor only. The doc sends readers to a function that was never written | 📄 Doc-reported |

---

## 5. T3 — Correctness in the adapters

### LP-17 — Tool results are paired to calls by name on two of three providers

**📄 Doc-reported · High**

Gemini and Anthropic pair a tool result back to its call by **tool name**. Only Azure uses
a real call id.

Two parallel calls to the same tool — which is the normal case for `web_search` or
`batch_web_search` — mis-pair. The model then reasons over results attributed to the wrong
query, with no error anywhere.

**Fix:** carry an internal call id through the translation layer on all three providers,
and pair on that.

---

### LP-18 — Gemini's tool-schema translation is lossy

**📄 Doc-reported · Medium**

`oneOf`, `pattern`, `default`, `format` and numeric bounds are all discarded, and integer
`enum` values become strings.

So a tool that carefully constrains its inputs presents a much weaker contract to Gemini
than to Azure, and the model produces arguments the tool then has to rescue — which is a
large part of why so much tool code is defensive parsing
([TX-I2](09-TOOLS-DEFECTS.md#tx-i2--one-dispatch-path-schema-derived-from-the-params-model)).

---

### LP-19 — A ReAct loop that hits the turn cap returns normally

**📄 Doc-reported · Medium**

`MAX_REACT_TURNS = 12`. On exhaustion the loop returns normally, with possibly-empty
output and **no flag**.

The caller cannot distinguish "the model finished" from "the model was cut off mid-task".
Every downstream critic and status decision treats them the same.

---

### LP-20 — `top_p` is silently dropped in every ReAct path

**📄 Doc-reported · Low**

Only the single-turn `generate()` honours it. Setting it in the builder and using `REACT`
— the default reasoning mode — has no effect.

---

### LP-21 — `_get_app_company_id` is `LIMIT 1` with no ordering

**📄 Doc-reported · Medium**

The APP-company credential fallback picks a row with no `ORDER BY`. Two APP companies
means a non-deterministic fallback — a run could use either one's key, and therefore
either one's cost basis.

Related: `get_integration_by_provider` uses `ILIKE '%name%'`, a substring match that can
pick up an unrelated provider whose name contains the search term.

---

### LP-22 — The API-key cache is per process and busted only locally

**📄 Doc-reported · Medium**

The TTL cache is in-process with a 60-second TTL, and invalidation on key rotation only
clears the local copy. After a rotation, **other workers keep serving the old key for up
to 60 seconds** — and the old key is usually the one that was just revoked.

So a key rotation produces up to a minute of failing runs on every worker that did not
handle the rotation request.

---

### LP-23 — The FinishReason monkey-patch mutates the installed SDK at import

**📄 Doc-reported · Medium**

Importing `src.ai.llm.types` patches `google-genai`'s `FinishReason` enum in place. It is
a workaround for an SDK validation bug, and it is invisible from the call site.

Anyone upgrading `google-genai` will not know it exists until something behaves oddly, and
any other library in the process that reads that enum gets the patched version.

---

### LP-24 — Multimodal input does not work

**📄 Doc-reported · Medium**

The adapters only build text parts. The video gateway works around this by base64-encoding
a JPEG **into the user prompt string** and requesting `task_type="vision"` — a task type
that does not exist ([LP-09](#lp-09--three-task-types-the-code-uses-are-rejected-by-the-api)).

So the vision path is broken twice over, and the workaround puts a large base64 blob into
the prompt and therefore into `llm_interaction_logs.input_prompt`.

- [`gateway/video_gateway.py:312`](../../../backend/src/gateway/video_gateway.py:312)

---

## 6. Improvements

### LP-I1 — Add retry, timeout and jitter

**Effect: the largest reliability win available in the platform.**
[LP-03](#lp-03--there-is-no-retry-timeout-or-fallback-anywhere-in-the-llm-layer). One
bounded retry loop with exponential backoff and jitter on 429 and 5xx, plus an explicit
request timeout, in `LLMRouter.generate`.

Every agent run on the platform passes through this function. Thirty lines here is worth
more than any amount of retry logic further up the stack.

### LP-I2 — Then add provider fallback

**Effect: large.** Once retry exists, fallback is the natural next step: a second
integration per task type, used when the first is exhausted or unavailable. The data model
already supports it — `model_task_defaults` is per company per task, and `routing_mode`
has a `"router"` value waiting for exactly this
([LP-08](#lp-08--routing_mode-is-stored-returned-and-never-read)).

Either build it and make `routing_mode` real, or delete the setting. Do not leave it.

### LP-I3 — Validate `cost_unit` on write

**Effect: large for billing correctness.**
[LP-01](#lp-01--cost_unit-per_1k_tokens-over-bills-by-1000). A closed list of accepted
units, validated at the integration-create endpoint, plus normalisation before matching.
A pricing field that silently defaults to "no divisor" is the single most dangerous shape
in the billing path.

### LP-I4 — Count thinking tokens

**Effect: medium, and it is revenue.** [LP-06](#lp-06--gemini-thinking-tokens-are-not-counted).
The field is on the response; it is simply not read. For reasoning models this can be most
of the spend, so the platform is currently absorbing that cost.

### LP-I5 — Cache the resolved model per run, not per call

**Effect: medium.** Every LLM call resolves the model through `model_task_defaults` and
`integration_registry`. For a 30-iteration run with four critic stages, that is well over a
hundred resolutions of a value that cannot change mid-run.

Resolve once at run start and thread it through. The API-key cache
([LP-22](#lp-22--the-api-key-cache-is-per-process-and-busted-only-locally)) partly hides
this today at the cost of correctness.

### LP-I6 — Make the key cache invalidation cross-process

**Effect: medium.** [LP-22](#lp-22--the-api-key-cache-is-per-process-and-busted-only-locally).
Publish an invalidation message on Redis when a key rotates; every worker drops its entry.
Redis is already a dependency and already used for pub/sub.

### LP-I7 — Stream text responses

**Effect: medium for perceived speed.** Streaming exists only in the voice path. For a
long generation, the user watches a spinner for the entire call even though the SSE trace
infrastructure to relay tokens already exists.

### LP-I8 — Pair tool calls by id everywhere

**Effect: medium.** [LP-17](#lp-17--tool-results-are-paired-to-calls-by-name-on-two-of-three-providers).
Azure already does it correctly. Making Gemini and Anthropic match removes a silent
wrong-answer path that gets more likely as parallel tool use increases.

### LP-I9 — Write an `LLMInteractionLog` for every call

**Effect: medium.** Only the step executor writes these rows. Planner and critic spend
appears in `usage_logs` and `run.total_cost_usd` with **no interaction row**, so the "what
did the model actually see" view is missing for the calls most likely to need debugging —
the ones the user did not directly cause.

### LP-I10 — Flag a truncated ReAct loop

**Effect: small, prevents wrong conclusions.**
[LP-19](#lp-19--a-react-loop-that-hits-the-turn-cap-returns-normally). One boolean on the
response. The critics and `_final_status` can then tell "finished" from "ran out of turns",
which today they cannot.

---

## 7. Suggested order of work

| Step | Work | Why here |
|---|---|---|
| **1** | LP-I3 / LP-01 | A 1000× billing error, with the wrong value in the platform's own guide |
| **2** | LP-I1 / LP-03 | Retry and timeout. The biggest reliability change available anywhere |
| **3** | LP-09, LP-07 | Add the three missing task types; decide Anthropic's fate |
| **4** | LP-02 / LP-14, LP-13, LP-16 | Delete the zero-cost property and the dead reasoning registry |
| **5** | LP-I4 / LP-06, LP-05 | Close the two under-billing paths |
| **6** | LP-I5, LP-I6 / LP-22 | Model resolution caching and cross-process key invalidation |
| **7** | LP-I2 / LP-08 | Build the fallback router, or delete `routing_mode` |
| **8** | LP-I8 / LP-17, LP-18 | Adapter-level correctness for tool calling |

---

## Where to go next

- [10 — LLM providers, routing & integrations](../10-llm-providers.md) — the source
  document.
- [`DEFECT-REGISTER.md`](../DEFECT-REGISTER.md) — LP-07 is D-12.
- [14 — Billing & credits](14-BILLING-AND-CREDITS-DEFECTS.md) — for LP-01, LP-02 and
  LP-06 in the billing context.
- [07 — Planning & critics](07-PLANNING-AND-CRITICS-DEFECTS.md) — the critic ladder that
  routes to Claude.
- [08 — Memory & CORTEX](08-MEMORY-AND-CORTEX-DEFECTS.md) — for the `embedding` task type
  in LP-09.
