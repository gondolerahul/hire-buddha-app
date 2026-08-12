# HireBuddha — Codebase Current-State Analysis

> **Document Class:** Engineering Baseline / Current-State Assessment
> **Author:** Buddha Cognitive Lab (analysis by Claude)
> **Analysis Date:** 2026-07-18
> **Branch analyzed:** `phase12/stage1-consolidation` (with uncommitted working-tree changes, see §8)
> **Purpose:** The factual "as-is" baseline that the road-map documents must be measured against. Feeds finding **F1** (capability maturity matrix) of the [roadmap_gap_register.md](./roadmap_gap_register.md). Companion docs: [product_functional_documentation.md](./product_functional_documentation.md) · [product_technical_documentation.md](./product_technical_documentation.md) · [Unified Business Process & Agent Template Blueprint v2](./Unified%20Business%20Process%20%26%20Agent%20Template%20Blueprint%20v2.md)

---

## 1. Executive Summary

The repository contains a **working, well-engineered multi-tenant agentic platform** — substantially more mature in its *core kernel* than a prototype, and substantially less built-out than the Phase-2 road-map docs describe. In one paragraph:

> A FastAPI + PostgreSQL/pgvector + Redis/Arq backend (~75k lines of Python) runs a **4-tier entity hierarchy** (ACTION → SKILL → AGENT → PROCESS, **no LOOP tier**) through a **completed 8-stage AgentLoop** (perceive → strategize → pre-critic → act → observe → post-critic → reflect → decide) with async suspend/resume child dispatch as the *sole* execution engine (the legacy engine was deleted in Phase 12). Memory is a genuinely advanced **CORTEX v2** (4 typed domains, dreaming/consolidation engine, provenance trust scores, scope policies), already extracted into a pip package (`hb-cortex-memory 0.1.0`, publish pending). A **Meta-Agent Architecture Board** (7 roles: RequirementChat → Curator → Architect → Critic → Validator → TestDriver → Promoter) builds entities, with a full **tool-synthesis pipeline** (AST validation → sandbox replay → red-team → DRAFT registration) behind default-OFF flags. Voice (Gemini Live + Azure OpenAI Realtime over Twilio + Tata Smartflo), WhatsApp, email (IMAP/SMTP), outbound campaigns, 3-bucket wallet billing with the TB formula, 4-level tenancy (app-admin/partner/tenant/user), HITL, and a React 18 frontend (~25k lines, 59 pages) are all live. **What does not exist at all:** the LOOP tier, BabyBuddha/OmniBuddha, the complexity-based Intelligent Model Router, Pragya, Karuna, Generative UI, the dynamic per-tenant schema, the signal/trigger contract, and nearly the entire §6.6 third-party tool catalog (Plaid, Stripe Payouts, DocuSign, Avalara, HRIS, calendar, etc.).

Rough completion against the Phase-2 functional doc, by pillar: **kernel/loop ~90%, memory ~85%, billing/governance ~80%, voice/channels ~70%, meta-agent ~70% (flag-gated), tools ~40%, intelligence engine ~25%, learning system ~50%, Pragya/GenUI/dynamic-schema/Loop-tier ~0%.**

---

## 2. Repository Layout & Stack

```
hb-proto-3/
├── backend/            FastAPI monolith + workers (Python 3.11, Poetry)
│   ├── src/ai/         Agent kernel — 247 files, ~55.3k lines
│   ├── src/voice/      Voice/telephony/WhatsApp — 28 files, ~11.1k lines
│   ├── src/gateway/    Unified gateway (:8001) — 13 files, ~3.2k lines
│   ├── src/billing/    Wallets, TB billing, Razorpay — ~1.8k lines
│   ├── src/auth/       4-level tenancy, JWT, onboarding, partner portal — ~1.5k lines
│   ├── src/config/     IntegrationRegistry + per-task model defaults
│   ├── src/common/     DB, AES-GCM security, suspension middleware, telemetry
│   ├── migrations/     53 Alembic revisions
│   ├── docker/         hb-sandbox image (4.52 GB, built) + egress-proxy image
│   ├── cortex_memory_moved_to_pypi_repo/   (extracted package; delete after PyPI publish)
│   └── tests/          130 test files: unit (746 green), parity goldens, eval, chaos, e2e
├── frontend/           React 18 + TypeScript + Vite — 114 files, ~25.3k lines
├── deploy/apache/      Reverse-proxy vhosts (app/api/gateway/streaming subdomains)
├── infra/dashboards/   Grafana/Metabase panel JSON (phase12)
├── docs/               phase1..phase12 history, DECISIONS.md, current/, product-road-map/
└── setup_production_vm.sh, start_services.sh, stop_services.sh
```

**Runtime topology (matches the technical doc §1 in shape):** Apache (SSL, vhosts) → frontend :3000, backend API :8000, unified gateway :8001, voice streaming :8002; PostgreSQL+pgvector :5433; Redis :6379; Arq background worker. Single-VM GCP deployment with a Vertex-AI service account (ADC via metadata server). CI: GitHub workflow + `run_ci_matrix.sh` (unit, parity, layout/canary lint in `error` mode, `mypy --strict` gate).

**Development history:** 12 documented phases (`docs/phase1`–`phase12`). Phase 11 built the AgentLoop/critics/memory-v2/meta-board; Phase 12 (current) completed "Stage 1 consolidation": the legacy `ExecutionEngine.execute_run` was **deleted** — the AgentLoop is the sole engine — plus `mypy --strict` across all six `ai/` packages, sandbox container runtime, tool synthesis, MCP adapter, eval harness, and CORTEX package extraction. Per `docs/phase12/HANDOFF.md`: *"Nothing is in production"* as of that writing; ops go-live steps were in progress in recent commits.

---

## 3. Backend Deep Dive

### 3.1 Agent Kernel (`src/ai/core/`) — the strongest subsystem

- **The 8-stage loop is real and is the only engine.** `agent_loop.py` implements perceive → strategize → pre-critic → act → observe → post-critic → reflect → decide, exactly as the functional doc §7 describes — including the 3-consecutive-pre-critic-block circuit breaker. Typed `AgentState` envelope (subgoals, hypotheses, blockers, verdicts), snapshot-per-iteration.
- **Async suspend/resume child dispatch** (`WAITING_ON_CHILDREN` → `resume_parent_run`) matches technical doc §12.2, with a concurrency cap (`governance.max_concurrent_children`, default 8) and chaos/cost-amplification test coverage.
- **Executors:** `DAG`, `Recursive`, `SingleStep`, `ChildEntity`, `Debate` (multi-candidate + independent LLM judge, writes a `debate` subtree to CORTEX). `Dialog` / `ToolBurst` / `Skill` executors are **stubs behind default-OFF flags** — notable because the functional doc's tier table (§2) names Dialog and ToolBurst as the Agent/Skill executors.
- **Reasoning:** per-step `reasoning_hint` (REACT default, CHAIN_OF_THOUGHT); Tree-of-Thoughts was retired in favor of the Debate executor. Budget-aware REACT (budget pressure injected into step prompts) is ON.
- **Budget:** first-class tokens/USD/wall-clock/iterations tracker with pressure signals — per **run**, not hierarchical (no Loop→Process→Agent envelopes).
- **Feature flags:** DB + `AI_FLAG_*` env + defaults, admin UI page. Master switches (board routing, critic v2, supervisor v2, bandit) default ON in dev.

### 3.2 Planning & Critics (`src/ai/planning/`)

Multi-candidate planner (`PlanGenerator`, varied-temperature parallel candidates) + **8 pure-function plan invariants** + LLM `PlanJudge` best-of-N selection + ε-greedy **plan-style bandit** keyed by `(entity_id, task_class)`. Four-stage critic pipeline (pre / post / alignment / supervisor) with `StepHealthRecord` per step, a closed `FailureTag` enum, deterministic retry strategies, and **weekly critic calibration** (false-pass/false-fail rates written to the IntelligenceTree). This exceeds what the road-map docs describe for critics.

### 3.3 Memory (`src/ai/memory/` → `hb-cortex-memory` package)

- **CORTEX v2:** tree memory with 7 operations, viewport slicing, checkpoint/summarization, **scope policies** (strict by default) and **provenance-aware writes** with source trust scores (`source_trust_scores` + trust learning).
- **Four typed domains** as views over CORTEX: Knowledge, Episodic, Experience, Intelligence trees — each with per-domain retrieval weights (semantic/recency/user-match/success). Richer than the functional doc's 4-tier description.
- **Dreaming engine:** cron + outcome-triggered consolidation that writes confirmed Intelligence *rules*; rule lifecycle with confirmed-only planner gating (flag).
- **Semantic/RAG:** `documents` + `document_chunks` with pgvector, per-company embedding-model resolver, Knowledge Base upload UI.
- **Extraction:** the whole substrate was moved to a host-free package (`hb-cortex-memory = "0.1.0"` pinned in `pyproject.toml`; `mypy --strict` clean, 85% coverage). PyPI publish is the only remainder; the in-repo copy sits in `cortex_memory_moved_to_pypi_repo/` awaiting deletion.

### 3.4 Meta-Agent (`src/ai/meta/`) — further along than the road-map describes

The **Architecture Board** (7 roles): `RequirementChat` (request → typed Spec) → `Curator` (REUSE/ADAPT/COMPOSE/CREATE, wrapping registry search + **anti-sprawl guard** + meta-intelligence audit) → `Architect` → `BoardCritic` (max-2 revise loop) → `Validator` (8 deterministic checks) → `TestDriver` (smoke/regression/boundary/hostile/comparative suites under shared budget, **golden-output capture**) → `Promoter` (6 gates, DRAFT → ACTIVE, optional HITL). Plus: platform-scoped `MetaIntelligenceTree` (anti-patterns, tool reliability, prompt candidates), **skill library** (detects repeated successful tool chains → HITL promotion), **prompt evolution** (LLM-diff self-modification of the meta-agent's own prompts, cron-wired), version-aware reseed. **Tool synthesis** (§3.5) is its marquee capability. Notably, the road-map's simpler "draft → simulate → critique" loop (functional §5) *undersells* what exists; what's missing is the Pragya conversational front-end and `entity_build_runs`-style tracking table (the board persists via its own mechanisms).

### 3.5 Tools (`src/ai/tools/`)

- **Registry** with `ToolStatus` (ACTIVE/EXPERIMENTAL/DEPRECATED [+DRAFT pending]), per-company visibility, `ToolResilience` (reformat-retry + fallback chains), and an **MCP adapter** (`tools/mcp/`, transport-agnostic) — MCP is *not* mentioned in the road-map docs at all.
- **Implemented tool suites:** core (calculator, web search, batch search, scraper, file writer), documents (PDF, DOCX, PPTX, Excel + xlsx engine, document save + templates), media (image generation via **Imagen 4** tiers; video via **Veo 3.1** split into generate/edit/add-sound over ffmpeg), email (**IMAP ingest / classify / draft / SMTP send** — matches functional §6.2 exactly), sandbox (code executor, terminal, **Playwright browser**), CRM tools, meta-tools (introspect, reflect, entity create/execute, registry search, spec critic, schema validator, tool synthesis).
- **Sandbox isolation is production-grade in design:** subprocess runtime + `ContainerRuntime`/`TenantSandboxManager` (per-tenant containers, built `hb-sandbox` image), **egress proxy with allow-list** (`NetworkPolicy.ALLOWLIST`, Docker-verified), persistent browser profiles, sandbox cost SKU, and a written security review — all behind default-OFF flags awaiting CVE scan + registry publish + canary.
- **Social/ads:** 15 platform integrations (LinkedIn, X, Facebook, Instagram, YouTube, TikTok, Reddit, Quora, Pinterest + 6 ads variants) exist but are **EXPERIMENTAL, unfinished, and wired to no production entity**.
- **Tool synthesis** (self-evolving-code precursor): ToolSmith → `ToolValidator` (AST gate) → sandbox replay → **red-team** → DRAFT registration, kill-switched by `meta_agent.tool_synthesis_enabled` (OFF).
- **Missing vs functional doc §6.6:** essentially the whole third-party catalog — no Plaid/Yodlee, Stripe Payouts/Wise, Avalara/TaxJar, DocuSign, Middesk/Persona KYB, Slack/Teams broker, Jira/Linear, Apollo/Clearbit enrichment, Google/MS calendar, HRIS, ShipStation/Shopify, SharePoint/Notion/Drive connectors, or a Chronos scheduling *tool* (Arq delayed jobs exist as substrate only).

### 3.6 LLM Layer (`src/ai/llm/`) — the biggest doc-vs-code divergence

Three provider adapters: **Gemini** (Vertex), **Anthropic Claude** (via Vertex), **Azure OpenAI (GPT-4o)**. Model selection is **static configuration per task type** (`model_task_defaults` table + per-company `IntegrationRegistry` with AES-GCM-encrypted keys) — *not* the complexity/cost/latency-scoring Intelligent Model Router of functional §3.3. There is no BabyBuddha, no GLM/Qwen/Mistral, no `model_registry`/`routing_decisions` tables, no wallet-aware downshifting, no capability scoring. The one router-adjacent behavior that exists: the critic pipeline can use a **different model** than the actor (`critic_pipeline.different_model_critic`), and per-call cost/tokens/model are traced (`llm_interaction_logs`, trace spans).

### 3.7 Governance & Billing (`src/ai/governance/`, `src/billing/`)

- **HITL:** `human_approvals` table, trigger types, pause/resume (`PAUSED` run status), frontend approval panel. (A handful of trigger types — not the Blueprint's 18-checkpoint catalog.)
- **Credit gating matches the docs to the cent:** `MINIMUM_EXECUTION_THRESHOLDS = PROCESS $0.50 / AGENT $0.05 / SKILL $0.02 / ACTION $0.01` + `InsufficientCreditsError` (functional §14.3 ✅, and no LOOP threshold — consistent with no LOOP tier).
- **TB billing formula implemented as documented** (`calculate_tb`: markup + platform fee + partner fee − discount). 3-bucket wallet (daily / PAYG / subscription+bonus) with expiry semantics, **Razorpay** top-ups + subscription auto-debit cron, `payment_transactions`, `billing_events`, SKU-based rates (`docs/current/billing_rates_by_primitive.md`), per-run/tool/sandbox **cost attribution ledger**, rate limiter (Redis).
- **Security:** AES-256-GCM key vault (`common/security.py`), JWT (30-min access — docs say 15 — + refresh tokens), `CompanySuspensionMiddleware` ✅.

### 3.8 Voice, Campaigns & Messaging (`src/voice/`, `src/gateway/`)

- **Realtime engines:** `GeminiLiveClient` + `AzureRealtimeClient` behind a `LiveClientFactory` selected per company config, with a uniform base class — matching functional §8.1's engines #2 and #3. **No OmniBuddha.** Audio pipeline: μ-law ↔ 16kHz PCM, VAD, barge-in handling in the websocket handlers.
- **Telephony:** **Twilio** and **Tata Smartflo** stream handlers (`TwilioStreamHandler`, `TataStreamHandler`, `tata_auth.py` JWT auth for hangup — recently hardened). **Exotel appears in comments only.** Phone-number pool management + routing, voice sessions, transcripts, conversation logging, usage logging.
- **Campaigns:** outbound engine (campaigns, `campaign_calls`, lead queue + worker, retry counts, and in-progress **disposition/disposition-reason tracking + call guards** — the current working-tree changes), campaign dashboard/detail pages.
- **WhatsApp:** Twilio *and* Tata Tele WhatsApp Business providers, session tracking, messaging router.
- **Gateway (:8001):** inbound webhook dispatcher → background tasks, event bus, audio WebSocket proxy, **video gateway (WebRTC)**, auth middleware.

### 3.9 Data Model — 35 tables

`hierarchical_entities` (4-type enum, JSON config blocks: identity/hierarchy/logic_gate/planning/capabilities/governance/io_contract/observability — **no `intelligence` or `loop_config` columns**), `execution_runs` (+ CSAT score; **no `model_used`/`routing_signals`**), `execution_trace_events`, `llm_interaction_logs`, `tool_interaction_logs`, `usage_logs`, CORTEX trees/nodes, `episodic_memories` (legacy), `documents`/`document_chunks`, `source_trust_scores`, `human_approvals`, `tool_registry_entries`, `integration_registry`, `model_task_defaults`, `credit_wallets`, `subscriptions`/`subscription_tiers`, `payment_transactions`, `billing_config`/`billing_events`, `companies`/`users`/`refresh_tokens`, `campaigns`/`campaign_calls`/`lead_queue`, `call_logs`/`call_content`/`voice_sessions`/`whatsapp_sessions`/`conversation_history`, `phone_numbers`, `email_connections`, `social_connections`, `artifacts`.
**Absent (road-map Phase-2 tables):** `model_registry`, `routing_decisions`, `learning_signals`, `entity_build_runs`, `tool_versions`, `tenant_entity_defs`, `tenant_records`, `ui_manifests`, `account_manager_sessions`, `generation_jobs`.

---

## 4. Frontend Inventory (React 18 + TS + Vite; reactflow, three.js)

59 pages across: **auth** (login/register/reset/OAuth callback), **onboarding wizard**, **role dashboards** (app-admin, app-user, partner-admin, partner-user, tenant-admin, tenant-user + KPI dashboard), **AI builder** (EntityLibrary, EntityBuilder, EntityFlow reactflow canvas, configuration tabs, execution pages + history + detail with SSE traces, **HITL panel**, **template marketplace**, tool management), **CORTEX explorer** (tree browser + detail), **admin/agent-kernel** (KPI, meta-intelligence, cost attribution, feature flags, risk-and-exit), **billing** (wallet, billing settings) + 8 report pages, **streaming** (campaigns list/detail/create, call detail, sessions, phone numbers), **knowledge base**, **integrations**, **artifacts/assets**, **platform management**, **partner portal**, **AI model config**. Services layer (23 API clients), typed `agentKernel.ts` domain model. No generative-UI machinery — all screens are hand-built (as expected; GenUI doesn't exist server-side either).

---

## 5. Quality Infrastructure (better than the road-map docs claim)

The gap register's **B9** ("no evaluation layer anywhere") is true *of the documents* but partially false of the code — worth correcting in the register's resolution notes:

- **Parity golden gate** (`tests/parity/`): hermetic legacy-vs-loop comparison with deterministic mock LLM, in-process worker drainer, chaos (crash/recovery/idempotency) and cost-amplification checks. Caught real bugs during the C4 cut.
- **Eval harness** (`tests/eval/`): pure metrics + delta report + DB-gated replay runner.
- **TestDriver goldens** for meta-built entities; regression compare.
- **746 green unit tests**, integration/e2e/chaos suites, `mypy --strict` gate over all 100 `ai/` files, layout/canary/comment-narration lints in `error` mode, layered CI matrix.
- What's still missing for the road-map's autonomy ambitions: *behavioral* golden sets per production agent, canary rollout machinery, model-upgrade regression policy — i.e., B9's resolution shrinks but does not close.

---

## 6. Capability Maturity Matrix (road-map docs vs code)

Status: ✅ Shipped · ◐ Partial · 🚩 Built but flag-OFF / not GA · ⬜ Missing. "Doc §" = Phase-2 functional doc unless noted.

| Doc § | Road-map capability | Status | Evidence / delta |
|---|---|---|---|
| §2 | 5-tier hierarchy incl. **LOOP** | ◐ | 4 tiers in `EntityType` enum; **no LOOP**, no `loop_config`, no perpetual runtime |
| §2.2 | Reasoning modes (ReAct/CoT/Debate) | ✅ | Per-step `reasoning_hint`; Debate is a Strategist-selected executor with LLM judge |
| §3.1 | **BabyBuddha** hybrid LLM | ⬜ | No trace anywhere in code or infra |
| §3.2 | Frontier fleet (6 vendors) | ◐ | 3 adapters: Gemini, Claude (Vertex), Azure GPT-4o. No GLM/Qwen/Mistral |
| §3.3 | **Intelligent Model Router** | ⬜ | Static per-task-type defaults (`model_task_defaults`); no complexity/cost scoring, no `routing_decisions` |
| §3.4 | Model governance/fallback/attribution | ◐ | Per-company integration config + full per-call cost/model tracing; no allow-list policy engine, no auto-failover across providers |
| §3.5/§6.4 | Image / video generation | ◐ | Imagen 4 (3 tiers, billed per image); Veo 3.1 + ffmpeg edit/sound tools. No Nano-Banana/ChatGPT-Image/Kling/SeeDance, no `generation_jobs` worker |
| §4 | **Pragya** account manager | ⬜ | Zero references in code |
| §5 | **Meta Agent** | 🚩✅ | Board v4 (7 roles) is *richer* than the doc; board routing ON in dev; tool synthesis OFF |
| §6.1–6.5 | Built-in tool suites | ✅ | Web, email (IMAP/SMTP), docs (PDF/DOCX/PPTX/XLSX), calculator, sandbox+terminal+browser — all present |
| §6.6 | Third-party tool catalog (14 rows) | ⬜ | None of Plaid/Stripe-payouts/Avalara/DocuSign/KYB/Slack-broker/Jira/enrichment/calendar/HRIS/inventory/knowledge-connectors/enterprise-connectors/Chronos-as-tool exist. CRM tools + MCP adapter (undocumented) are the exceptions |
| §7 | 8-stage AgentLoop | ✅ | Implemented verbatim, incl. pre-critic circuit breaker; sole engine after C4 |
| §8.1 | Realtime voice (3 engines) | ◐ | Gemini Live + Azure Realtime ✅; **no OmniBuddha**; Twilio + Tata Smartflo ✅; **no Exotel** |
| §8.2 | Outbound campaigns | ✅ | Campaign engine + lead queue + dashboards; disposition analytics in flight |
| §9.1 | 4-tier memory | ✅ | Exceeds doc: 4 CORTEX domains + dreaming + trust + scope policy; pip-extracted |
| §9.2 | Personality matrix | ◐ | `identity` JSON on entities + persona service; slider set differs from doc |
| §10 | **Learning System** | ◐ | Real pieces: reflection→Intelligence rules, dreaming, critic calibration, plan bandit, trust learning, skill-library promotion, prompt evolution (meta-agent only). No KPI-driven charter tuning, no `learning_signals` store, no router feedback (no router) |
| §11 | **Generative/Adaptive UI** | ⬜ | No `ui_manifests`, no genui renderer; all screens hand-built |
| §12 | **Self-evolving code** | 🚩◐ | Tool *synthesis* (new tools) full pipeline behind OFF flag; ToolResilience fallbacks; prompt self-evolution for the meta-agent. No self-*healing* patches to existing tools, no `tool_versions` promote/rollback table |
| §13 | **Dynamic per-tenant schema** | ⬜ | No `tenant_entity_defs`/`tenant_records` |
| §14 | Wallets, TB formula, thresholds | ✅ | Implemented exactly (incl. $0.50/$0.05/$0.02/$0.01); Razorpay live |
| §15 | Tenancy, key vault, JWT, suspension, HITL, credit breaker | ✅ | All present (JWT access = 30 min vs doc's 15) |
| Blueprint | Sheel/Karuna/signal contract/canonical objects/A0–A4/SoD/budget hierarchy/19 processes/100 agents | ⬜ | Entirely aspirational; no supporting schema or services. Template marketplace exists as a seed mechanism for shipping agent templates |
| Tech doc §0 | Phase-2 schema additions (9 rows) | ⬜ | None of the 10 Phase-2 tables exist (see §3.9) |

**Reverse deltas — real capabilities the road-map docs don't credit:** MCP tool adapter; Debate executor; dreaming/consolidation engine; provenance trust learning; plan-style bandit + plan invariants + LLM plan judge; critic calibration; anti-sprawl guard; skill library; per-tenant sandbox containers with egress allow-listing; eval harness + parity golden gate; template marketplace; artifact system; CSAT capture; video-gateway WebRTC; WhatsApp via two providers; strict-typing/lint CI regime.

---

## 7. Notable Engineering Risks in the Current Code (for road-map planning)

1. **Single-VM topology** — all services, DB, and Redis co-located behind Apache; no HA/scaling story (road-map gap B14 confirmed in code).
2. **Voice engine coupling** — realtime engine choice is per-company config, not per-call routing; adding OmniBuddha/latency-based selection means reworking `LiveClientFactory`.
3. **Flag debt** — several finished capabilities (sandbox containers, tool synthesis, board GA on AgentLoop, Dialog/ToolBurst/Skill executors) are parked behind default-OFF flags awaiting canary/ops steps (`docs/phase12/OPS_REMAINDER.md`); the road map should not count them as "shipped" until flipped.
4. **Social tool sprawl** — 15 experimental, unwired integrations carrying maintenance surface with zero production use.
5. **Legacy shims with deadlines** — phase-11 redirect shims (backend + frontend routes) carry a **2026-09-01 removal date**; migration names and `docs/phase11` pointers are intentionally retained.
6. **In-repo cortex copy** — `cortex_memory_moved_to_pypi_repo/` must be deleted once `hb-cortex-memory 0.1.0` is on PyPI; until then the pinned dependency and the stale copy coexist.
7. **`docs/current/` vs `docs/product-road-map/`** — `docs/current` holds the **2.0.0 (Phase 1)** functional/technical docs, which describe the shipped system far more accurately than the 3.0.0 road-map versions; the road-map docs present Phase-2 vision as GA (gap F1). Anyone onboarding should read `docs/current` first.

## 8. In-Flight Work (uncommitted at analysis time)

Working tree on `phase12/stage1-consolidation`: campaign **call-disposition + disposition-reason** columns (2 new migrations) with ranked-disposition reporting, new `call_guards.py` (+ unit tests), new `twilio_api.py` and `tata_auth.py` (Smartflo login-JWT for hangup), campaign executor/router updates, `CampaignDetailPage` styling, billing-service and config touches, and the cortex-memory directory move. Recent commits: phase-12 ops go-live (sandbox enabled globally, feature-flag defaults), TestDriver golden capture, ops-guide fixes.

---

## 9. What This Baseline Means for the Road Map

1. **The kernel bet has already paid** — loop, critics, memory, meta-board, and billing are solid foundations; the road map should *build on* them rather than re-specify them (several road-map sections describe weaker versions of what exists).
2. **The three largest green-field builds** in the Phase-2 docs are the Intelligence Engine/router (§3), Pragya (§4), and the Loop tier (§2) — nothing in the code starts them. Dynamic schema (§13) and GenUI (§11) are similarly zero-based.
3. **The fastest doc-credibility wins** are re-labeling: the docs claim GA for ~10 subsystems that are 0%-built, while omitting ~15 shipped capabilities (see §6 reverse deltas). Correcting both directions turns the docs from aspiration into a plannable roadmap — this is gap register **F1/F2/F3**.
4. **Flag-gated ≠ shipped:** sandbox containers, tool synthesis, and board GA need their ops/canary steps before the road map can treat them as delivered.

---

## Change Log

| Date | Change |
|---|---|
| 2026-07-18 | Initial analysis of `phase12/stage1-consolidation` (backend + frontend full sweep). |
