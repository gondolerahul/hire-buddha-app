# HireBuddha — Billing Rates by Primitive

> **Source of Truth**: All costs below are derived from the codebase as of July 2026.
> Internal costs are stored as `internal_cost` in the `integration_registry` table (per-company, with APP-company fallback).
> Final user-facing cost is calculated via the **TB Formula** applied on top of the base cost (see §6).

---

## Table of Contents

1. [LLM Text Generation (Input / Output Tokens)](#1-llm-text-generation)
2. [LLM Thinking / Reasoning](#2-llm-thinking--reasoning)
3. [Image Generation](#3-image-generation)
4. [Video Generation & Editing](#4-video-generation--editing)
5. [Voice / Telephony (Real-Time Calling)](#5-voice--telephony)
6. [Web Search](#6-web-search)
7. [Web Scraping](#7-web-scraping)
8. [Headless Browser](#8-headless-browser)
9. [Embedding (Memory / Cortex)](#9-embedding)
10. [Sandbox Execution](#10-sandbox-execution)
11. [Document Generation (PDF, DOCX, PPTX, Excel)](#11-document-generation)
12. [Email](#12-email)
13. [Payment Gateway (Razorpay)](#13-payment-gateway)
14. [Other / Utility Tools](#14-other--utility-tools)
15. [TB Formula (Total Billing)](#15-tb-formula-total-billing)
16. [Credit System & Wallet](#16-credit-system--wallet)
17. [Cost Attribution Tags](#17-cost-attribution-tags)

---

## 1. LLM Text Generation

**Service Category**: `LLM`  
**Billing Mechanism**: Token-based, split into separate input (`-in`) and output (`-out`) SKUs.  
**Cost Unit**: `1M Tokens` (per million tokens) — divisor of 1,000,000 applied automatically; or `1K Tokens` — divisor of 1,000.

### SKU Naming Convention

Each LLM model registers **two** SKUs in the Integration Registry:

| SKU Pattern | Direction | Example |
|---|---|---|
| `{model_name}-in` | Input (prompt) tokens | `gemini-2.5-flash-in` |
| `{model_name}-out` | Output (completion) tokens | `gemini-2.5-flash-out` |

### Reference Pricing (from Cost Estimator baselines)

| Model | Price Factor (relative to Flash baseline) | Est. Cost per Thinking Step |
|---|---|---|
| `gemini-2.5-flash` | 1.0× | $0.005 |
| `gemini-2.5-flash-lite` | 0.5× | $0.0025 |
| `gemini-2.5-pro` | 3.0× | $0.015 |
| `gemini-3.1-pro-preview` | 4.0× | $0.020 |
| `claude-haiku` / `claude-haiku-4-5` | 1.0× | $0.005 |
| `claude-sonnet` / `claude-sonnet-4-5` | 2.5× | $0.0125 |
| `claude-opus` / `claude-opus-4-1` | 8.0× | $0.040 |
| `gpt-4o` | 2.0× | $0.010 |
| `gpt-4o-mini` | 0.5× | $0.0025 |
| `gpt-5` | 5.0× | $0.025 |

### Cost Calculation

```
calculated_cost = (internal_cost × raw_token_count) / divisor
```

Where `divisor` = 1,000,000 for `1M Tokens`, 1,000 for `1K Tokens`, or 1.0 for other units.

### Code References

- [usage_service.py — log_usage()](file:///home/rahul/workspace/hb-proto-3/backend/src/ai/usage_service.py#L30-L133)
- [step_executor.py — _log_usage()](file:///home/rahul/workspace/hb-proto-3/backend/src/ai/step_executor.py#L1103-L1130)
- [attributed_usage.py — log_llm_response_usage()](file:///home/rahul/workspace/hb-proto-3/backend/src/ai/services/attributed_usage.py#L22-L59)
- [cost_estimator.py — MODEL_PRICE_FACTOR](file:///home/rahul/workspace/hb-proto-3/backend/src/ai/planning/cost_estimator.py#L51-L65)

---

## 2. LLM Thinking / Reasoning

**Service Category**: `LLM`  
**Task Type**: `thinking`  
**Billing Mechanism**: Same token-based billing as text generation (§1). Uses the same `{model}-in` / `{model}-out` SKU pattern. "Thinking" models typically generate more output tokens due to chain-of-thought.

### Base Thinking Step Cost

| Metric | Value |
|---|---|
| Base cost per thinking step (Flash baseline) | **$0.005** |
| Default fallback step cost (unknown model) | **$0.010** |
| Child entity invocation cost (nested run) | **$0.100** |

### Code References

- [cost_estimator.py — _BASE_THINKING_COST](file:///home/rahul/workspace/hb-proto-3/backend/src/ai/planning/cost_estimator.py#L69)
- [config/models.py — TASK_TYPES](file:///home/rahul/workspace/hb-proto-3/backend/src/config/models.py#L11-L23)

---

## 3. Image Generation

**Service Category**: `IMAGE_GEN`  
**Task Type**: `text_to_image`, `image_to_image`  
**Billing Mechanism**: Flat fee per generation call.

| Metric | Value |
|---|---|
| Registry SKU | `imagen-4.0-generate-001` |
| Tool ID | `image_generation` |
| **Fixed cost per generation** (fallback) | **$0.04** |
| Cost estimator baseline | **$0.04** |

### Cost Resolution Priority

1. `IntegrationRegistry` entry with `service_sku = 'imagen-4.0-generate-001'` → uses `internal_cost`
2. Fixed fallback → **$0.04** per call
3. If neither found → $0.00 (with warning)

### Billing Config Override

The `BillingConfig` table supports a `base_cost_image_gen` override per company, applied as:
```
base_cost = base_cost_image_gen × image_gen_count
```

### Code References

- [tool_cost_resolver.py — TOOL_FIXED_COST](file:///home/rahul/workspace/hb-proto-3/backend/src/ai/governance/tool_cost_resolver.py#L52-L58)
- [tool_cost_resolver.py — TOOL_SKU_MAP](file:///home/rahul/workspace/hb-proto-3/backend/src/ai/governance/tool_cost_resolver.py#L40-L47)
- [billing_service.py — record_billing_event()](file:///home/rahul/workspace/hb-proto-3/backend/src/billing/billing_service.py#L112-L113)

---

## 4. Video Generation & Editing

**Service Category**: `VIDEO_GEN` / `VIDEO_GENERATION`  
**Task Types**: `text_to_video`, `image_to_video`, `audio_to_video`

The legacy `video_generation` mega-tool has been split into three composable tools:

| Tool | Description | Fixed Cost (fallback) | Baseline Est. |
|---|---|---|---|
| `video_generate` | AI generation of a single segment (Veo) | **$0.05** | **$0.10** |
| `video_edit` | Concat, trim, extend (ffmpeg-based, CPU) | — (billed via sandbox) | **$0.01** |
| `video_add_sound` | Add audio/music overlay (CPU) | — (billed via sandbox) | **$0.01** |
| `video_generation` | **DEPRECATED** shim → delegates to above | **$0.05** | **$0.10** |

### Key Notes

- `video_generate` carries the model cost (Veo API call). `video_edit` and `video_add_sound` are compute-only and bill via the **sandbox SKU** (see §10).
- Cost estimator uses a higher $0.10 baseline for budget planning (conservative).
- Estimated latency: 60 seconds per generation, 10 seconds per edit/sound operation.

### Code References

- [tool_cost_resolver.py — TOOL_FIXED_COST](file:///home/rahul/workspace/hb-proto-3/backend/src/ai/governance/tool_cost_resolver.py#L54-L57)
- [cost_estimator.py — TOOL_BASELINE_COST](file:///home/rahul/workspace/hb-proto-3/backend/src/ai/planning/cost_estimator.py#L38-L41)
- [video_generate.py](file:///home/rahul/workspace/hb-proto-3/backend/src/ai/tools/media/video/video_generate.py)

---

## 5. Voice / Telephony

**Service Category**: `COMMUNICATION` / `LLM_LIVE`  
**Task Type**: `speech_to_speech`

Voice sessions incur **three cost components** logged separately:

### 5a. Telephony (Call Minutes)

| Provider | Registry SKU | Billing Unit | Cost Basis |
|---|---|---|---|
| Tata Tele | `tata-tele-voice-in-out` | Per minute (ceiling-rounded) | `internal_cost × ceil(seconds/60)` |
| Twilio | `in-out` | Per minute (ceiling-rounded) | `internal_cost × ceil(seconds/60)` |

### 5b. LLM Audio Input (User Speech → Model)

| SKU (default fallback) | Billing Mode | Cost Basis |
|---|---|---|
| `gemini-3.1-flash-live-preview-in` | Token-based (`1M Tokens`) or `per_minute` | See below |

- **Token mode**: `internal_cost × (167 tokens/sec × audio_seconds) / 1,000,000`
- **Per-minute mode**: `internal_cost × ceil(audio_seconds / 60)`

### 5c. LLM Audio Output (Model Speech → User)

| SKU (default fallback) | Billing Mode | Cost Basis |
|---|---|---|
| `gemini-3.1-flash-live-preview-out` | Same as input | Same formula |

### Key Notes

- Both audio input and output default to the **full call duration** when not explicitly measured.
- Audio → token estimation: **167 tokens per second** of audio.
- SKUs are resolved dynamically from the `speech_to_speech` task default in `ModelTaskDefault`; the hardcoded SKUs above are fallback-only.

### Billing Config Override

The `BillingConfig` table supports `base_cost_telephony` override per company:
```
base_cost = base_cost_telephony × total_minutes
```

### Code References

- [voice/usage_logger.py — VoiceUsageLogger](file:///home/rahul/workspace/hb-proto-3/backend/src/voice/usage_logger.py#L27-L335)
- [voice/usage_logger.py — TELEPHONY_SKU_MAP](file:///home/rahul/workspace/hb-proto-3/backend/src/voice/usage_logger.py#L37-L40)
- [voice/usage_logger.py — _log_llm_audio_usage()](file:///home/rahul/workspace/hb-proto-3/backend/src/voice/usage_logger.py#L191-L256)

---

## 6. Web Search

**Service Category**: `API_TOOL`  
**Tool ID**: `web_search`, `batch_web_search`

| Metric | Value |
|---|---|
| Registry SKU | `serp-api-key` |
| Billing Unit | Per call (flat fee) |
| Cost estimator baseline — `web_search` | **$0.005** |
| Cost estimator baseline — `batch_web_search` | **$0.015** |

### Search Backend Priority

1. **SerpAPI** (Google Search) — uses API key from Integration Registry (`service_sku = 'serp-api-key'` or `provider_name = 'serpapi'`)
2. **duckduckgo-search** library — free, no key required
3. **DuckDuckGo Instant Answers API** — minimal fallback

> When SerpAPI is not configured, DuckDuckGo fallbacks are free but the registry cost still applies if a `serp-api-key` SKU exists.

### Code References

- [tools/core/search.py — WebSearchTool](file:///home/rahul/workspace/hb-proto-3/backend/src/ai/tools/core/search.py#L33-L412)
- [tool_cost_resolver.py — TOOL_SKU_MAP](file:///home/rahul/workspace/hb-proto-3/backend/src/ai/governance/tool_cost_resolver.py#L41-L42)

---

## 7. Web Scraping

**Service Category**: `API_TOOL`  
**Tool ID**: `scraper_tool`

| Metric | Value |
|---|---|
| Registry SKUs | `firecrawl-api`, `firecrawl` |
| Billing Unit | Per call (flat fee) |
| Cost estimator baseline | **$0.02** |

Cost is resolved from the Integration Registry entry for `firecrawl-api` or `firecrawl`. If neither exists, $0 is charged (with a warning logged).

### Code References

- [tool_cost_resolver.py — TOOL_SKU_MAP](file:///home/rahul/workspace/hb-proto-3/backend/src/ai/governance/tool_cost_resolver.py#L43)
- [cost_estimator.py — TOOL_BASELINE_COST](file:///home/rahul/workspace/hb-proto-3/backend/src/ai/planning/cost_estimator.py#L37)

---

## 8. Headless Browser

**Service Category**: `API_TOOL`  
**Tool ID**: `headless_browser`, `browser_tool`

| Metric | Value |
|---|---|
| Registry SKU | `headless-browser` |
| Billing Unit | Per call (flat fee) |
| Cost estimator baseline | **$0.05** |
| Estimated latency | 10 seconds |

### Code References

- [tool_cost_resolver.py — TOOL_SKU_MAP](file:///home/rahul/workspace/hb-proto-3/backend/src/ai/governance/tool_cost_resolver.py#L44)
- [cost_estimator.py — TOOL_BASELINE_COST](file:///home/rahul/workspace/hb-proto-3/backend/src/ai/planning/cost_estimator.py#L32)

---

## 9. Embedding

**Service Category**: `LLM`  
**Billing Mechanism**: Input-only token/character billing using the `-in` SKU convention.

| Metric | Value |
|---|---|
| SKU Pattern | `{embedding_model_name}-in` |
| Billing Unit | Characters (passed as `raw_quantity`) |
| Attribution Tag | `embedding` |

### Cost Calculation

Same as LLM tokens (§1) — `internal_cost × billable_characters / divisor` — where the divisor is determined by `cost_unit` (e.g., 1,000,000 for `1M Tokens`).

### Code References

- [memory/embedding_service.py — embedding cost logging](file:///home/rahul/workspace/hb-proto-3/backend/src/ai/memory/embedding_service.py#L345-L369)

---

## 10. Sandbox Execution

**Service Category**: `SANDBOX`  
**Tool ID**: `sandbox_executor`

| Metric | Value |
|---|---|
| Registry SKU | `sandbox-runtime` (configurable via `SANDBOX_COST_SKU` env) |
| Billing Unit | **Per second** of runtime |
| Default cost per second | **$0.000020** |
| Cost estimator baseline (per call) | **$0.02** |

### Cost Calculation

```
calculated_cost = internal_cost × duration_seconds
```

### Seeding

The SKU must be seeded once per environment:
```bash
.venv/bin/python -m scripts.seed_sandbox_sku
SANDBOX_SKU_COST_PER_SECOND=0.00005 .venv/bin/python -m scripts.seed_sandbox_sku
```

### What Bills Through Sandbox

- Python code execution
- Headless browser sessions (persistent Chromium)
- `video_edit` (ffmpeg concat/trim)
- `video_add_sound` (audio overlay)

### Code References

- [tools/sandbox/metering.py — meter_sandbox_usage()](file:///home/rahul/workspace/hb-proto-3/backend/src/ai/tools/sandbox/metering.py#L23-L66)
- [scripts/seed_sandbox_sku.py](file:///home/rahul/workspace/hb-proto-3/backend/scripts/seed_sandbox_sku.py)
- [common/config.py — SANDBOX_COST_SKU](file:///home/rahul/workspace/hb-proto-3/backend/src/common/config.py#L26)

---

## 11. Document Generation

**Service Category**: `API_TOOL`  
**Billing Mechanism**: Per call (flat fee from Integration Registry or estimator baseline).

| Tool ID | Registry SKU | Baseline Cost | Description |
|---|---|---|---|
| `pdf_generator` | `pdf-generator` | **$0.01** | PDF document generation |
| `docx_tool` | — | **$0.01** | Word document generation |
| `pptx_tool` | — | **$0.01** | PowerPoint generation |
| `excel` | — | **$0.005** | Excel spreadsheet generation |
| `xlsx_engine` | — | **$0.01** | Advanced Excel generation |

### Code References

- [tool_cost_resolver.py — TOOL_SKU_MAP](file:///home/rahul/workspace/hb-proto-3/backend/src/ai/governance/tool_cost_resolver.py#L45)
- [cost_estimator.py — TOOL_BASELINE_COST](file:///home/rahul/workspace/hb-proto-3/backend/src/ai/planning/cost_estimator.py#L22-L44)

---

## 12. Email

**Service Category**: `COMMUNICATION`

| Tool ID | Registry SKU | Baseline Cost | Description |
|---|---|---|---|
| `email_ingest` | — | **$0.001** | Ingest/parse incoming email |
| `email_classify` | — | **$0.002** | AI classification of email content |
| `email_draft` | — | **$0.01** | AI-drafted email response |
| SMTP system | `smtp-system` | — | System email delivery (credentials from registry) |

### Code References

- [cost_estimator.py — TOOL_BASELINE_COST](file:///home/rahul/workspace/hb-proto-3/backend/src/ai/planning/cost_estimator.py#L27-L29)
- [common/email.py — SMTP config](file:///home/rahul/workspace/hb-proto-3/backend/src/common/email.py#L16-L63)

---

## 13. Payment Gateway

**Service Category**: `PAYMENT`

| SKU | Purpose |
|---|---|
| `razorpay_keys` | Razorpay API credentials stored in `service_metadata` (`key_id`, `key_secret`) |

This is a credential-only entry; no per-transaction cost is metered through the Integration Registry. Transaction fees are handled by Razorpay directly.

### Code References

- [credits_router.py — _get_razorpay_creds()](file:///home/rahul/workspace/hb-proto-3/backend/src/billing/credits_router.py#L29-L44)

---

## 14. Other / Utility Tools

| Tool ID | Baseline Cost | Description |
|---|---|---|
| `calculator` | **$0.001** | Mathematical calculations |
| `file_writer` | **$0.001** | File write operations |
| Unknown / unregistered tool | **$0.01** | Fallback default (per call) |

### CORTEX Memory Operations

| Operation Type | Baseline Cost |
|---|---|
| `READ` / `NAVIGATE` / `WRITE` | **$0.001** (negligible; embedding cost dominates) |

### Code References

- [cost_estimator.py — TOOL_BASELINE_COST](file:///home/rahul/workspace/hb-proto-3/backend/src/ai/planning/cost_estimator.py#L22-L46)

---

## 15. TB Formula (Total Billing)

All base costs from §1–§14 are transformed into the final **Total Billing (TB)** amount using a configurable formula stored in the `billing_config` table:

```
TB = (c × mf) + (c × mf × pf) + (c × mf × spf) − (c × mf × d)
```

| Symbol | Field | Default | Description |
|---|---|---|---|
| **c** | `base_cost` | — | Raw internal cost from the Integration Registry |
| **mf** | `multiplier_factor` | 1.0 | Cost markup multiplier |
| **pf** | `platform_fee_pct` | 0.0 | Platform fee (e.g., 0.15 = 15%) |
| **spf** | `sales_partner_fee_pct` | 0.0 | Sales/channel partner fee |
| **d** | `discount_pct` | 0.0 | Discount percentage |

### Configuration Levels

1. **Global default**: `billing_config` row where `company_id IS NULL`
2. **Company-specific override**: `billing_config` row where `company_id = {uuid}`

Company-specific settings take priority; global is the fallback.

### Base Cost Overrides (per company)

| Field | Applies To |
|---|---|
| `base_cost_telephony` | Telephony (replaces registry cost × minutes) |
| `base_cost_llm` | LLM usage |
| `base_cost_image_gen` | Image generation (replaces registry cost × count) |

### Code References

- [billing_service.py — calculate_tb()](file:///home/rahul/workspace/hb-proto-3/backend/src/billing/billing_service.py#L24-L49)
- [billing_models.py — BillingConfig](file:///home/rahul/workspace/hb-proto-3/backend/src/billing/billing_models.py#L15-L43)

---

## 16. Credit System & Wallet

### Account Models

| Model | Description |
|---|---|
| `pay_as_you_go` | Credits purchased via Razorpay top-up; 365-day validity |
| `subscription` | Monthly auto-debit; credits reset each month (no carry-forward) |

### Credit Buckets (Consumption Priority)

| Priority | Bucket | Expiry | Carry-Forward |
|---|---|---|---|
| 1 | **Daily Credits** | Midnight UTC (next day) | ❌ Never |
| 2a (PAYG) | **Wallet Balance** | 365 days from last top-up | ✅ Within validity |
| 2b (Sub) | **Subscription Credits** | End of billing month | ❌ Never |
| 2b (Sub) | **Subscription Bonus Credits** | End of billing month | ❌ Never |

### Subscription Tier Bonuses

| Tier | Bonus Credits |
|---|---|
| Tier 1 | 20% of monthly fee |
| Tier 2 | 30% of monthly fee |
| Tier 3 | 40% of monthly fee |

### Minimum Execution Thresholds

Execution is blocked if available balance falls below:

| Entity Type | Minimum Balance Required |
|---|---|
| `PROCESS` (Deep Research, etc.) | **$0.50** |
| `AGENT` (Single-agent runs) | **$0.05** |
| `SKILL` (Lightweight skills) | **$0.02** |
| `ACTION` (Atomic actions) | **$0.01** |
| Default | **$0.05** |

### Code References

- [credit_service.py — CreditService](file:///home/rahul/workspace/hb-proto-3/backend/src/billing/credit_service.py#L40-L220)
- [billing_models.py — CreditWallet](file:///home/rahul/workspace/hb-proto-3/backend/src/billing/billing_models.py#L46-L78)
- [cron_service.py — daily/monthly jobs](file:///home/rahul/workspace/hb-proto-3/backend/src/billing/cron_service.py)

---

## 17. Cost Attribution Tags

Every usage row in `usage_logs` is tagged with an **attribution** value for cost breakdown reporting:

| Attribution | Description |
|---|---|
| `planner` | Planning LLM calls |
| `actor_step` | Agent action steps |
| `critic_pre` | Pre-execution critic pipeline |
| `critic_post` | Post-execution critic pipeline |
| `critic_align` | Alignment critic |
| `critic_super` | Supervisor critic |
| `reformat_retry` | Output reformatting retries |
| `meta_review` | Meta-review LLM calls |
| `dreaming` | Dreaming / background learning |
| `tool` | Tool invocations (default) |
| `child_run` | Nested child entity runs |
| `embedding` | Embedding generation |
| `meta_spec_critic` | Meta-specification critic |
| `test_driver` | Test-driver framework calls |
| `sandbox` | Sandbox runtime metering |
| `mcp` | MCP (Model Context Protocol) calls |

Unknown attributions automatically fall back to `tool` with a logged warning, ensuring no charge is ever silently dropped.

### Code References

- [services/cost_attribution.py — CostAttribution enum](file:///home/rahul/workspace/hb-proto-3/backend/src/ai/services/cost_attribution.py#L29-L48)
- [services/cost_attribution.py — CostLedger](file:///home/rahul/workspace/hb-proto-3/backend/src/ai/services/cost_attribution.py#L54-L153)

---

## Quick Reference — All Integration Registry SKUs

| SKU | Provider | Category | Component Type | Cost Unit | Notes |
|---|---|---|---|---|---|
| `{model}-in` | google / anthropic / azure_openai | LLM | `input_token` | 1M Tokens | Per-model, auto-generated |
| `{model}-out` | google / anthropic / azure_openai | LLM | `output_token` | 1M Tokens | Per-model, auto-generated |
| `imagen-4.0-generate-001` | google | IMAGE_GEN | `image` | flat_fee | Image generation |
| `tata-tele-voice-in-out` | tata_tele | COMMUNICATION | `minute` | per_minute | India telephony |
| `in-out` | twilio | COMMUNICATION | `minute` | per_minute | Twilio telephony |
| `gemini-3.1-flash-live-preview-in` | google | LLM_LIVE | `input_token` | 1M Tokens / per_minute | Voice LLM input |
| `gemini-3.1-flash-live-preview-out` | google | LLM_LIVE | `output_token` | 1M Tokens / per_minute | Voice LLM output |
| `serp-api-key` | serpapi | API_TOOL | `flat_fee` | per_call | Web search API |
| `firecrawl-api` / `firecrawl` | firecrawl | API_TOOL | `flat_fee` | per_call | Web scraping |
| `headless-browser` | hirebuddha | API_TOOL | `flat_fee` | per_call | Browser automation |
| `pdf-generator` | hirebuddha | API_TOOL | `flat_fee` | per_call | PDF generation |
| `sandbox-runtime` | hirebuddha | SANDBOX | `sandbox` | second | Code sandbox metering |
| `smtp-system` | hirebuddha | COMMUNICATION | `flat_fee` | — | SMTP credentials only |
| `razorpay_keys` | razorpay | PAYMENT | `flat_fee` | — | Payment gateway credentials |

---

## Cost Resolution Priority (Per-Tool)

For every tool invocation, cost is resolved in this order (first match wins):

```
1. IntegrationRegistry.service_sku == tool_id           → registry internal_cost
2. IntegrationRegistry.service_sku ∈ TOOL_SKU_MAP[tool] → registry internal_cost
3. TOOL_FIXED_COST[tool_id]                             → hardcoded fallback
4. $0.00 (with one-time warning per process)
```

### SKU Lookup Fallback Chain

For all SKU lookups, the system searches:

```
1. Company-specific SKU (tenant's own integration)
2. APP company SKU (platform-level, shared across all tenants)
```

This ensures platform-level pricing applies across all tenants unless explicitly overridden.

---

*Document generated from codebase analysis — July 2026*
