# HireBuddha — Product Technical Documentation

> **Target Platform Version:** 3.0.0 (road-map target state)
> **Author:** Buddha Cognitive Lab
> **Last Updated:** July 2026 — v3.0.6 (v3.0.1 errata + maturity re-labeling; v3.0.2 adds the §17–§20 road-map designs; v3.0.3 adds §11.3 + §21–§22 designs and legalizes LOOP federation; v3.0.4 owner directives: §10.3 predefined HBS, §10.4 sandbox-resident tenant DB, §10.5 master/tenant segregation, GenUI ground-up frontend; v3.0.5 adds the §23–§24 concurrency and memory designs; v3.0.6 decision 2026-07-19: KB + CORTEX memory live in the **control plane permanently** — §10.4/§10.5/§23.4/§24.4 amended, tenant export bundle includes a KB+memory dump)
> **Status:** Architecture & Systems Manual — **target state**, not shipped state. Phase-2 subsystems carry a status column in §0; the shipped architecture is documented in `docs/current/` (2.0.0) and [codebase_current_state_analysis.md](./codebase_current_state_analysis.md). Maturity legend: ✅ shipped · 🚩 flag-gated · ◐ partial · ⬜ road map.
> **Revision:** Phase 2 — supersedes Phase 1 (2.0.0). Adds the Intelligence Engine & Model Router (BabyBuddha + frontier fleet), multimodal generation services, the Meta Agent build-loop, the Learning System, Generative UI, self-evolving code, the dynamic per-tenant schema, the **Loop** entity tier, and Pragya's account-manager runtime.

---

## 0. Phase 2 Delta (for engineers)

Everything in the Phase 1 technical manual remains valid and is retained below. Phase 2 adds the following subsystems and schema changes. **The Status column (added v3.0.1) records what exists in code as of 2026-07-18** — none of the Phase-2 tables named here exist yet:

| Subsystem | Section | Schema/Service touchpoints | Status (v3.0.1) |
|---|---|---|---|
| Intelligence Engine & Model Router | §3 | `model_registry`, `routing_decisions`, `ai/intelligence/` | ⬜ — today: `ai/llm/` (3 adapters) + `model_task_defaults` static config |
| Multimodal generation (image/video/audio) | §4 | `generation_jobs`, `ai/media/`, `voice/omnibuddha.py` | ◐ — Imagen 4 + Veo 3.1 as synchronous tools in `ai/tools/media/`; async job workers ⬜ |
| **Loop** entity tier | §2.1 | `type` enum on `hierarchical_entities`, `loops` config | ⬜ — shipped enum is ACTION/SKILL/AGENT/PROCESS |
| Meta Agent build-loop | §6 | `ai/meta/`, `entity_build_runs` | ◐ — shipped as the `ai/meta/` Architecture Board (7 roles), a richer design than §6 |
| Learning System | §7 | `learning_signals`, `optimization_runs` | ◐ — dreaming engine, critic calibration, bandit, trust learning shipped; no unified signal store |
| Generative UI | §8 | `ui_manifests`, `/api/v1/ui/manifest` | ⬜ |
| Self-Evolving Code | §9 | `tool_versions`, sandbox promotion pipeline | 🚩 — tool-synthesis pipeline code-complete behind default-OFF flag; `tool_versions` ledger ⬜ |
| Dynamic Per-Tenant Schema | §10 | `tenant_entity_defs`, `tenant_records` (EAV/JSONB) | ⬜ |
| Pragya account-manager runtime | §11 | `account_manager_sessions`, omnichannel adapters | ⬜ |

> **v3.0.2:** approved target-state *designs* now exist for four of these subsystems — **§17 LOOP runtime**, **§18 signal bus & trigger registry**, **§19 object-graph storage**, **§20 governance schema & enforcement** — closing register gaps B1/B2/B3/B5 (and A6 via §20.4) at the design level. Build status remains ⬜; each section ends with build notes.

---

## 1. System Architecture & Topology

The HireBuddha platform uses a multi-process, service-oriented architecture. Traffic routing, reverse proxying, and SSL termination are handled by a front-end Apache HTTP Server.

```
                           Internet (Client Requests)
                                       │
                         ┌─────────────▼─────────────┐
                         │   Apache HTTP (80/443)    │ (mod_ssl, VirtualHosts)
                         └─────────────┬─────────────┘
                                       │ (Reverse Proxy via mod_proxy_wstunnel)
   ┌──────────────┬───────────────────┼───────────────────┬──────────────┐
   ▼              ▼                   ▼                   ▼              ▼
┌──────────┐ ┌────────────┐  ┌─────────────────┐  ┌──────────────┐ ┌──────────────┐
│  React   │ │  FastAPI   │  │ Unified Gateway │  │ Intelligence │ │ Media/Gen    │
│ Frontend │ │   App      │  │  (voice/ws)     │  │   Service    │ │  Workers     │
│ :3000    │ │  :8000     │  │   :8001         │  │   :8010      │ │  (async)     │
└──────────┘ └─────┬──────┘  └────────┬────────┘  └──────┬───────┘ └──────┬───────┘
                   │ (SQL/Cache)      │ (WebSockets)     │ (model calls)  │
                   ▼                  ▼                  ▼                ▼
            ┌────────────┐    ┌──────────────┐   ┌─────────────────┐  ┌──────────────┐
            │ PostgreSQL │    │ Voice Server │   │  Model Fleet    │  │ Image/Video  │
            │  :5433     │    │   :8002      │   │ BabyBuddha +    │  │  providers   │
            │ (+pgvector)│    │ (OmniBuddha/ │   │ Claude/GPT/     │  │ (Nano Banana,│
            │            │    │  Gemini Live/│   │ Gemini/GLM/     │  │  Veo, Kling, │
            │            │    │  GPT Realtime)│  │ Qwen/Mistral)   │  │  SeeDance)   │
            └────────────┘    └──────────────┘   └─────────────────┘  └──────────────┘
```

> **Phase 2 additions to the topology (⬜ road map):** the **Intelligence Service** (`:8010`) and **Media/Gen Workers** do not exist yet — model calls run in-process via `ai/llm/`, and media generation runs as synchronous tools. OmniBuddha is road map; the Voice Server fronts Gemini Live and Azure OpenAI Realtime today.
>
> **Shipped topology note (v3.0.1):** the running system is Apache → frontend `:3000`, backend API `:8000`, unified gateway `:8001`, voice streaming `:8002`, with **Redis `:6379` + an Arq background worker** (omitted from the diagram above) alongside PostgreSQL+pgvector `:5433` — all on a single VM. HA/multi-region topology is an open road-map item (gap register B14).

### 1.1 Apache Proxy Configuration
An example virtual host configuration snippet below details how subdomains are proxied to their respective backend services:

```apache
# App Frontend Proxy
<VirtualHost *:443>
    ServerName app.hirebuddha.com
    SSLEngine on
    SSLCertificateFile /etc/letsencrypt/live/hirebuddha.com/fullchain.pem
    SSLCertificateKeyFile /etc/letsencrypt/live/hirebuddha.com/privkey.pem

    ProxyPreserveHost On
    ProxyPass / http://localhost:3000/
    ProxyPassReverse / http://localhost:3000/
</VirtualHost>

# Unified AI Gateway Proxy (supporting HTTP and WebSockets)
<VirtualHost *:443>
    ServerName api.hirebuddha.com
    SSLEngine on
    SSLCertificateFile /etc/letsencrypt/live/hirebuddha.com/fullchain.pem
    SSLCertificateKeyFile /etc/letsencrypt/live/hirebuddha.com/privkey.pem

    ProxyPreserveHost On

    # WebSockets Handshake Routing
    ProxyPass /stream/audio ws://localhost:8001/stream/audio
    ProxyPassReverse /stream/audio ws://localhost:8001/stream/audio

    # REST Requests Routing
    ProxyPass / http://localhost:8001/
    ProxyPassReverse / http://localhost:8001/
</VirtualHost>
```

### 1.2 Core Directory File Index
*   `backend/src/ai/`: Agent Kernel execution logic.
    *   `core/`: Composes the control loops, state engines, step execution drivers, and scheduling queues.
        *   `agent_loop.py`: The control loop orchestrating perception, strategy, action, reflection, and decisions.
        *   `step_engine.py`: Single-step and parallel DAG execution wrapper.
        *   `agent_state.py`: Typed state envelope and JSON snapshot engine.
        *   `budget.py`: Tracks token caps, USD limits, and run latency.
        *   `feature_flags.py`: Feature flag overrides.
        *   `arq_jobs.py`: Worker tasks definition (`run_execution_recursive`, `resume_parent_run`).
    *   `planning/`: Generates plans and houses the Critic Pipeline and Strategic planners.
        *   `critic_pipeline.py`: Plugs in the pre-critic, post-critic, and supervisor pipelines.
        *   `strategist.py`: Selects next execution frames based on the current state.
        *   `planner_service.py`: Generates the step list for Processes.
    *   `memory/`: CORTEX engine, semantic indexers, and episodic memory.
        *   `cortex_service.py`: Tree memory interface.
        *   `cortex_bridge.py`: Bridges the agent loop to CORTEX node operations.
        *   `assembler.py`: Reconciles memories for prompt injection.
    *   `governance/`: Enforces billing checks, limits, and Human-in-the-loop (HITL) gateways.
        *   `governance_service.py`: Checks credit gates and processes final settlements.
        *   `rate_limiter.py`: Limits API calls using Redis.
    *   **`intelligence/`** *(Phase 2)*: Model fleet abstraction and the Intelligent Router.
        *   `router.py`: Scores each step and selects a model (§3.3).
        *   `model_registry.py`: Registered models, capability profiles, pricing, eligibility.
        *   `providers/`: Adapters — `babybuddha.py`, `claude.py`, `openai.py`, `gemini.py`, `glm.py`, `qwen.py`, `mistral.py`.
        *   `fallback.py`: Provider failover & retry policy.
    *   **`media/`** *(Phase 2)*: Image/video generation brokering.
        *   `image_service.py`: Nano Banana / ChatGPT Image / Kling adapters.
        *   `video_service.py`: Veo / SeeDance adapters.
    *   **`meta/`** *(Phase 2)*: Meta Agent build-loop (`meta_agent.py`, `entity_builder.py`, `tool_synthesizer.py`).
    *   **`learning/`** *(Phase 2)*: Signal capture and self-optimization (`signal_collector.py`, `optimizer.py`).
    *   `orm/`: SQLAlchemy model definitions.
*   `backend/src/gateway/`: Proxy for real-time audio streams, WebRTC, and inbound webhooks.
    *   `dispatcher.py`: Routes inbound webhooks to background tasks.
*   `backend/src/voice/`: Audio processors, session managers, and realtime adapters.
    *   `websocket_handler.py`: Bidirectional audio streaming WebSocket handler.
    *   **`omnibuddha.py`** *(Phase 2)*: Proprietary OmniBuddha realtime speech-to-speech client.
    *   `gemini_live.py`: Real Gemini Live SDK client.
    *   `azure_realtime.py`: Real Azure OpenAI Realtime client.
*   `backend/src/tenant_schema/` *(Phase 2)*: Dynamic per-tenant entity definitions and records (§10).
*   `frontend/src/genui/` *(Phase 2)*: Generative-UI manifest renderer (§8).

> **Index reality note (v3.0.1):** entries marked *(Phase 2)* above — `intelligence/`, `media/` (as a brokering service), `learning/`, `tenant_schema/`, `genui/`, `omnibuddha.py` — do **not exist yet**. What ships instead: `ai/llm/` (provider adapters + task-type resolution), `ai/tools/media/` (Imagen/Veo tools), `ai/meta/` (the Architecture Board — larger than the sketch in §6, including `board/`, tool-synthesis pipeline, anti-sprawl, skill library), `ai/memory/` (CORTEX v2 with four domains + dreaming, extracted to the `hb-cortex-memory` package), and `ai/tools/mcp/` (MCP adapter, previously undocumented). See [codebase_current_state_analysis.md](./codebase_current_state_analysis.md) §3 for the full shipped index.

---

## 2. Database Schema & Core Models

All database models inherit from `src.common.database.Base` and are defined with SQLAlchemy 2.0's strict async `Mapped[]` type annotations.

### 2.1 The Agent Kernel: `hierarchical_entities`

> **Phase 2 change (⬜ road map):** the `type` discriminator gains **`LOOP`** as the top tier. The target hierarchy is `ACTION → SKILL → AGENT → PROCESS → LOOP` (composition rule: Actions wrap Tools; Actions→Skill; Skills→Agent; Agents→Process; Processes→Loop). `parent_id` self-references still model the tree, so a `LOOP` row parents `PROCESS` rows. **Shipped enum today: ACTION, SKILL, AGENT, PROCESS** — and per the A4 decision (gap register), each tenant will have exactly one **root** LOOP row: Sheel. **The composition rule is formally amended (v3.0.3, closes A8): a LOOP row may also parent LOOP rows** — Blueprint §13's federated/holding topologies are first-class; runtime rules in §17.6. The `intelligence` and `loop_config` columns below are likewise road map.

```python
class HierarchicalEntity(Base):
    __tablename__ = "hierarchical_entities"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("hierarchical_entities.id"), nullable=True)
    version: Mapped[str] = mapped_column(String, nullable=False, default="1.0.0")
    type: Mapped[str] = mapped_column(String, nullable=False)  # ACTION, SKILL, AGENT, PROCESS, LOOP
    status: Mapped[str] = mapped_column(String, nullable=False, default="ACTIVE")
    name: Mapped[str] = mapped_column(String, nullable=False)
    display_name: Mapped[str | None] = mapped_column(String, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    goal: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags: Mapped[Any] = mapped_column(JSON, nullable=True)

    # Configuration properties stored as structured JSON
    identity: Mapped[Any] = mapped_column(JSON, nullable=True)         # Tone, Empathy, Humor values
    hierarchy: Mapped[Any] = mapped_column(JSON, nullable=True)        # Linked child entity ids
    logic_gate: Mapped[Any] = mapped_column(JSON, nullable=True)       # Reasoning configuration
    planning: Mapped[Any] = mapped_column(JSON, nullable=True)         # Custom prompts configurations
    capabilities: Mapped[Any] = mapped_column(JSON, nullable=True)     # Bound tools and rate limit limits
    governance: Mapped[Any] = mapped_column(JSON, nullable=True)       # Max cost, timeout, and HITL checkpoints
    io_contract: Mapped[Any] = mapped_column(JSON, nullable=True)      # Input/Output variables schemas
    observability: Mapped[Any] = mapped_column(JSON, nullable=True)    # Trace logs settings

    # Phase 2: per-entity intelligence preferences (consumed by the router, §3.3)
    intelligence: Mapped[Any] = mapped_column(JSON, nullable=True)
    # e.g. {"mode": "auto", "pinned_model": null, "allow_list": ["babybuddha","claude-opus",...],
    #       "max_cost_per_step_usd": 0.02, "latency_class": "standard"}

    # Phase 2: LOOP-tier scheduling/KPI config (null for non-LOOP rows)
    loop_config: Mapped[Any] = mapped_column(JSON, nullable=True)
    # e.g. {"kpis": [...], "schedules": [...cron/triggers...], "process_ids": [...]}
```

### 2.2 Execution Runs & Tracing: `execution_runs`

> **Phase 2 change (⬜ road map):** runs will record the **router decision** (`model_used`, `routing_signals`) so cost and quality are attributable per model. *(Shipped today: per-call model/cost/token attribution exists in `llm_interaction_logs` and trace spans; the run-level rollup columns below do not exist yet. The shipped table also carries `csat_score`, not shown here.)*

```python
class ExecutionRun(Base):
    __tablename__ = "execution_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("hierarchical_entities.id"), nullable=False)
    parent_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("execution_runs.id"), nullable=True)
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    status: Mapped[str] = mapped_column(String, default="PENDING")
    input_data: Mapped[Any] = mapped_column(JSON, nullable=True)
    dynamic_plan: Mapped[Any] = mapped_column(JSON, nullable=True)
    result_data: Mapped[Any] = mapped_column(JSON, nullable=True)
    context_state: Mapped[Any] = mapped_column(JSON, nullable=True)     # Serialized AgentState snapshot
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Costs and Tokens accounting
    total_cost_usd: Mapped[Decimal] = mapped_column(Numeric(10, 4), default=0)
    billed_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 6), nullable=True)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    execution_time_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Phase 2: intelligence attribution (per-step detail lives in routing_decisions)
    model_used: Mapped[Any] = mapped_column(JSON, nullable=True)        # {"babybuddha-fast": 12, "claude-opus": 2, ...}
    routing_signals: Mapped[Any] = mapped_column(JSON, nullable=True)   # last/aggregated routing inputs
```

### 2.3 Wallets & Subscriptions: `credit_wallets`

```python
class CreditWallet(Base):
    __tablename__ = "credit_wallets"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False)
    account_model: Mapped[str] = mapped_column(String, default="pay_as_you_go") # pay_as_you_go, subscription

    # Bucket Credits fields
    daily_credits: Mapped[Decimal] = mapped_column(Numeric(12, 4), default=0)
    daily_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    wallet_balance: Mapped[Decimal] = mapped_column(Numeric(12, 4), default=0)
    wallet_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    subscription_credits: Mapped[Decimal] = mapped_column(Numeric(12, 4), default=0)
    subscription_bonus_credits: Mapped[Decimal] = mapped_column(Numeric(12, 4), default=0)
    sub_credits_expire_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
```

### 2.4 Phase 2 New Models (abridged) — ⬜ road map

> **None of these tables exist yet** (v3.0.1). Closest shipped equivalents: model/task config lives in `model_task_defaults` + `integration_registry`; learning signal lives in the Intelligence/Experience CORTEX domains, `step_health_records`-style critic records, and `source_trust_scores`; Meta-Agent build iterations persist through the Board's own mechanisms; tool registration lives in `tool_registry_entries` (unversioned).

```python
class ModelRegistry(Base):
    """The model fleet the router can choose from."""
    __tablename__ = "model_registry"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    key: Mapped[str] = mapped_column(String, unique=True)   # "babybuddha-fast", "babybuddha-reasoning", "claude-opus", "gpt", "gemini", "glm", "qwen", "mistral"
    provider: Mapped[str] = mapped_column(String)           # internal | anthropic | openai | google | zhipu | alibaba | mistral
    modality: Mapped[Any] = mapped_column(JSON)             # ["text","tools","vision","realtime_audio",...]
    capability_profile: Mapped[Any] = mapped_column(JSON)   # reasoning, tool_reliability, max_context, latency_class
    price_per_1k_input: Mapped[Decimal] = mapped_column(Numeric(12, 6))
    price_per_1k_output: Mapped[Decimal] = mapped_column(Numeric(12, 6))
    enabled: Mapped[bool] = mapped_column(default=True)

class RoutingDecision(Base):
    """One row per reasoning call: what the router chose and why."""
    __tablename__ = "routing_decisions"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("execution_runs.id"))
    step_id: Mapped[str] = mapped_column(String)
    chosen_model: Mapped[str] = mapped_column(String)
    complexity_score: Mapped[float] = mapped_column(Float)
    signals: Mapped[Any] = mapped_column(JSON)             # full router input vector
    fallback_used: Mapped[bool] = mapped_column(default=False)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), default=0)

class LearningSignal(Base):
    """Reflections, outcomes, critic verdicts, human feedback — fed to the optimizer."""
    __tablename__ = "learning_signals"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"))
    entity_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("hierarchical_entities.id"))
    source: Mapped[str] = mapped_column(String)           # reflection | kpi | critic | router | hitl
    payload: Mapped[Any] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class EntityBuildRun(Base):
    """An iteration log of the Meta Agent constructing an entity/tool."""
    __tablename__ = "entity_build_runs"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"))
    goal: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String, default="ITERATING")  # ITERATING, TESTING, PUBLISHED, ABORTED
    iterations: Mapped[Any] = mapped_column(JSON)         # per-iteration draft + critique + test results
    produced_entity_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("hierarchical_entities.id"))

class ToolVersion(Base):
    """Versioned, self-evolving tool code with sandbox test gating (§9)."""
    __tablename__ = "tool_versions"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("companies.id"))  # null = global registry tool
    tool_key: Mapped[str] = mapped_column(String)
    version: Mapped[str] = mapped_column(String)
    source_code: Mapped[str] = mapped_column(Text)
    test_report: Mapped[Any] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String, default="CANDIDATE")  # CANDIDATE, PROMOTED, ROLLED_BACK
    origin: Mapped[str] = mapped_column(String)          # human | meta_agent | self_heal | self_optimize

class TenantEntityDef(Base):
    """Dynamic per-tenant schema: entity types that emerge as the tenant works (§10)."""
    __tablename__ = "tenant_entity_defs"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"))
    name: Mapped[str] = mapped_column(String)            # e.g. "Shipment", "Patient"
    fields: Mapped[Any] = mapped_column(JSON)            # evolving field defs {name,type,constraints}
    version: Mapped[int] = mapped_column(Integer, default=1)

class UIManifest(Base):
    """Generative-UI render manifests, per user/context (§8)."""
    __tablename__ = "ui_manifests"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    context_key: Mapped[str] = mapped_column(String)     # e.g. "invoice_review", "build_employee"
    manifest: Mapped[Any] = mapped_column(JSON)          # component tree + bindings
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
```

---

## 3. The Intelligence Engine & Model Router

> **Phase 2 — new subsystem (⬜ road map).** All reasoning calls flow through `ai/intelligence/`. No agent talks to a model SDK directly; it requests a *capability* and the router binds it to a concrete model. *(Shipped today: `ai/llm/router.py` resolves the configured model per task type from `IntegrationRegistry`/`model_task_defaults` and dispatches to the Gemini / Anthropic / Azure OpenAI adapters — configuration lookup, not complexity scoring.)*

### 3.1 BabyBuddha (flagship hybrid LLM) — ⬜ road map
BabyBuddha is the planned in-house default model family: **post-trained over an open-weight base** (Qwen/Mistral-class, reusing the fleet's serving path) on the platform's own agent traces, for **agentic execution, tool calling, and reasoning** — not a from-scratch pretrain. Admission gate: it must beat the incumbent vendor models on the platform eval harness (`tests/eval/`) before the router may select it. It is exposed to the router as two profiles:
*   `babybuddha-fast` — low-latency/low-cost, for routine, well-structured steps.
*   `babybuddha-reasoning` — extended deliberation, for hard planning/critic stages.

The "hybrid" property is that both profiles share the same model family and memory format, so the router can switch modes mid-run without a context handoff penalty.

### 3.2 The Fleet
Registered in `model_registry` and reachable via `providers/`: `babybuddha-*` (internal), `claude-opus` (Anthropic), `gpt` (OpenAI), `gemini` (Google), `glm` (Zhipu), `qwen` (Alibaba), `mistral`. Each row carries a `capability_profile` (reasoning strength, tool reliability, max context, latency class) and per-1k-token pricing.

### 3.3 The Router

```python
# ai/intelligence/router.py  (abridged)
def route(step: PlanStep, ctx: AgentContext) -> ModelBinding:
    signals = {
        "complexity": score_complexity(step),          # planning/critic = high; extract/format = low
        "tier": step.entity_tier,                       # ACTION..LOOP
        "reasoning_mode": step.reasoning_mode,          # react | cot | debate
        "needs_tools": step.has_tool_calls,
        "context_tokens": estimate_context_tokens(ctx),
        "modality": step.modality,                      # text | vision | realtime_audio
        "latency_class": step.latency_class,            # strict (voice) | standard | batch
        "cost_ceiling": ctx.entity.intelligence.get("max_cost_per_step_usd"),
        "wallet_state": ctx.wallet.headroom(),
        "history": learning.model_success_for(step.signature),  # §7 feedback
    }

    candidates = model_registry.eligible(
        modality=signals["modality"],
        allow_list=ctx.entity.intelligence.get("allow_list"),
        min_context=signals["context_tokens"],
    )

    # 1. Pinned model wins if set and eligible
    if (pinned := ctx.entity.intelligence.get("pinned_model")) in {c.key for c in candidates}:
        return ModelBinding(pinned, reason="pinned")

    # 2. Score candidates on capability fit vs. cost vs. latency, biased by wallet/ceiling
    best = max(candidates, key=lambda m: utility(m, signals))

    # 3. Record decision for billing + learning
    record_routing_decision(ctx.run_id, step.step_id, best, signals)
    return ModelBinding(best.key, reason="auto")
```

**Routing heuristics (defaults):**
*   `complexity < 0.3` and no tools → cheapest eligible (`mistral` / `glm` / `babybuddha-fast`).
*   Planning, Pre-/Post-Critic, legal/financial drafting → `babybuddha-reasoning` or `claude-opus`.
*   `modality == vision` → `gemini` (multimodal grounding).
*   `latency_class == strict` (live voice turns) → realtime-capable profile only (§5).
*   Wallet headroom tight or `cost_ceiling` low → downshift to cheaper tiers before failing.

### 3.4 Fallback & Governance
`fallback.py` retries the next-best eligible model on provider error/rate-limit (`fallback_used=True` is recorded). Tenant/partner `allow_list` and data-residency policy filter candidates *before* scoring, so disallowed providers are never selected. Every decision is in `routing_decisions` for audit.

---

## 4. Multimodal Generation Services

> **Phase 2 — new (◐).** Target: image and video generation as async jobs brokered through provider adapters; realtime audio is handled in the voice path (§5). *(Shipped today: `ai/tools/media/` — Imagen 4 image generation with per-image billing, and Veo 3.1 split into `video_generate`/`video_edit`/`video_add_sound` over ffmpeg — synchronous tools, single provider each, no `generation_jobs` queue.)*

### 4.1 Image & Video (`ai/media/`)
```python
# image_service.py — provider selection mirrors the text router's philosophy
IMAGE_PROVIDERS = {
    "nano_banana": GeminiNanoBananaAdapter(),   # Google Gemini image
    "chatgpt_image": OpenAIImageAdapter(),
    "kling": KlingAdapter(),
}
VIDEO_PROVIDERS = {
    "veo": GoogleVeoAdapter(),                   # Google Veo
    "seedance": SeeDanceAdapter(),
}

async def generate_image(req: ImageRequest) -> GenerationJob:
    provider = pick_image_provider(req)   # by style, fidelity, speed, cost; allow_list-aware
    job = await enqueue_generation_job(kind="image", provider=provider, spec=req)
    return job   # polled/streamed; result stored to tenant workspace + cost ledgered
```
Generation runs as a background job (`generation_jobs`) on the Media/Gen Workers, with the same fallback and cost-attribution discipline as text routing. Results are written to the tenant workspace and billed via the standard formula (§13).

---

## 5. Realtime Audio & the Voice WebSocket Handler

Real-time voice calls are processed by `websocket_handler.py`. **Phase 2 (⬜ road map)** adds **OmniBuddha** — planned as a post-trained open-weight speech-to-speech model (same build philosophy as BabyBuddha, §3.1) — as the default engine alongside Gemini Live and OpenAI Realtime, with the engine chosen by the router using the call's latency/language/persona/cost signals. *(Shipped today: `GeminiLiveClient` + `AzureRealtimeClient` behind `LiveClientFactory`, selected per tenant configuration — not per call; telephony = Twilio + Tata Smartflo stream handlers.)*

```
[Twilio Inbound Connection]
            │ (SIP / RTP Stream)
            ▼
[Unified Gateway (mod_proxy_wstunnel)]
            │ (ws://streaming.hirebuddha.com/stream/audio)
            ▼
[FastAPI / voice/websocket_handler.py]
            │ (PCM Chunks / WebSockets)
            ▼
[ realtime engine selector ]
     ├── omnibuddha.py    (OmniBuddha — default, proprietary)
     ├── gemini_live.py   (Google Gemini Live)
     └── azure_realtime.py(OpenAI/GPT Realtime)
```

### 5.1 Inbound Audio Processing Loop
```python
async def receive_from_twilio(websocket: WebSocket, session: RealtimeSession):
    async for message in websocket.iter_text():
        data = json.loads(message)
        if data.get("event") == "media":
            # Twilio streams Mu-law or A-law compressed packets
            payload = base64.b64decode(data["media"]["payload"])

            # Decompress Mu-law payload to 16kHz linear PCM
            pcm16_data = audio_processor.ulaw_to_pcm(payload)

            # Stream 20ms audio chunks to the selected realtime engine
            # (OmniBuddha by default; Gemini Live / GPT Realtime as routed)
            await session.send_audio(pcm16_data)
```

### 5.2 Outbound Audio Processing Loop
```python
async def send_to_twilio(websocket: WebSocket, session: RealtimeSession):
    async for response in session.receive():
        if response.audio_chunk:                     # uniform interface across engines
            pcm_chunk = response.audio_chunk

            # Compress 16kHz PCM down to Twilio's Mu-law standard
            ulaw_payload = audio_processor.pcm_to_ulaw(pcm_chunk)

            await websocket.send_text(json.dumps({
                "event": "media",
                "media": {"payload": base64.b64encode(ulaw_payload).decode("utf-8")}
            }))
```

> `RealtimeSession` is a thin uniform wrapper so the handler is engine-agnostic; OmniBuddha, Gemini Live, and GPT Realtime each implement `send_audio()` / `receive()`. Pragya (§11) and any voice Agent share this path.

---

## 6. The Meta Agent (Build-Loop)

> **Phase 2 — new (◐, shipped as a richer design).** `ai/meta/` turns a natural-language goal into a published, versioned entity or tool, iterating until acceptance criteria pass. **The shipped implementation is the Architecture Board** — RequirementChat → Curator (REUSE/ADAPT/COMPOSE/CREATE with anti-sprawl + registry search) → Architect → BoardCritic → Validator (8 deterministic checks) → TestDriver (smoke/regression/boundary/hostile suites + goldens) → Promoter (6 gates, optional HITL) — which supersedes the simpler sketch below. This section should be rewritten against `ai/meta/README.md` in the design pass; the pseudo-code below is retained as the conceptual outline.

```python
# meta_agent.py (abridged)
async def build(goal: str, company_id: UUID) -> EntityBuildRun:
    run = EntityBuildRun(company_id=company_id, goal=goal, status="ITERATING")
    spec = await decompose_goal(goal)               # capabilities, channels, data, constraints, acceptance tests

    for _ in range(MAX_ITERATIONS):
        draft = await assemble_entity(spec)         # choose tier(s), charter, personality, tool bindings, IO contract
        draft = await ensure_tools(draft, spec)     # synthesize missing tools via §9 (sandboxed)
        report = await simulate(draft, spec.tests)  # dry-run against representative + self-generated cases
        if report.passes(spec.acceptance):
            entity = await publish_entity(draft, company_id)   # versioned row in hierarchical_entities
            run.produced_entity_id = entity.id
            run.status = "PUBLISHED"
            break
        spec = await critique_and_revise(spec, draft, report)  # close gaps; loop
        run.iterations.append({"draft": draft.summary, "report": report.summary})

    return run
```

The Meta Agent backs both the conversational path (Pragya → "build me X", §11) and the No-Code Architect's generate actions. Output entities are fully editable afterward and tracked in `entity_build_runs`.

---

## 7. The Learning System

> **Phase 2 — new (◐, and a flagship capability).** Target: `ai/learning/` captures signal and continuously optimizes the workforce — the technical backbone of "Week 12 > Week 1." *(Shipped today, distributed rather than centralized: the Reflector promotes run-scoped lessons to entity-scoped Intelligence rules; the Dreaming engine consolidates them cron- and outcome-triggered; critic calibration writes false-pass/false-fail rates weekly; the plan-style bandit learns per `(entity, task_class)`; provenance trust learning updates `source_trust_scores`; the skill library detects repeated successful tool chains; prompt evolution self-modifies the Meta-Agent. Missing: the unified `learning_signals` store, KPI-driven charter tuning, and router feedback.)*

### 7.1 Signal Capture
`signal_collector.py` writes `learning_signals` rows from five sources:
*   **reflection** — the AgentLoop Reflect stage (§12.7 of Phase 1 / retained §12 below) emits per-step lessons into CORTEX *and* the learning store.
*   **kpi** — Process/Loop outcome metrics (conversion, recovery, clean-reconciliation rate).
*   **critic** — Pre-/Post-Critic block/correct patterns.
*   **router** — realized success/cost per `(model, task_signature)` → feeds `learning.model_success_for()` in §3.3.
*   **hitl** — human approvals, edits, rejections.

### 7.2 The Optimizer
`optimizer.py` runs periodically (Chronos-scheduled) per tenant and per entity:
```python
async def optimize(entity: HierarchicalEntity):
    signals = await fetch_signals(entity.id, window="rolling_14d")
    proposal = await synthesize_improvement(signals)   # may touch any of:
    #   - charter/instruction tuning (Self-Optimizing Intelligence Engine)
    #   - router preferences (pinned/allow_list/cost ceilings)
    #   - tool rewrites (-> §9 self-evolving code, sandbox-gated)
    #   - schema promotion (-> §10)
    if proposal.is_high_impact:
        await raise_hitl_checkpoint(entity, proposal)  # require human sign-off
    else:
        await apply_with_versioning(entity, proposal)  # auto-apply, rollbackable
```
The Self-Optimizing Intelligence Engine is the charter-tuning specialization of this optimizer; it adjusts agent instructions from KPI evidence without human intervention for low-risk changes.

---

## 8. Generative & Adaptive UI

> **Phase 2 — new (⬜ road map).** The frontend renders **manifests** produced by the backend rather than fixed screens. *(Nothing of this exists; all 59 shipped screens are hand-built React.)*
>
> **Owner directive (v3.0.4):** Generative UI will be a **completely new frontend built from scratch** — not an extension of the current React app. It is hard-gated behind a dedicated **Design Gate**: a deep, unique design and brainstorming phase that must complete before any development starts (build road map, Increment 6). The manifest flow below is a conceptual sketch, explicitly subject to that design phase.

### 8.1 Manifest Flow
```
GET /api/v1/ui/manifest?context=invoice_review
        │
        ▼
[ genui service ]  ── inputs: user role/expertise, task context, tenant dynamic schema (§10),
        │                      data shape, behavioral history (Learning System §7)
        ▼
{ "manifest": { "layout": "...", "components": [ {type, props, bindings}, ... ] } }  ── stored in ui_manifests
        │
        ▼
[ frontend/src/genui/ Renderer ]  ── maps component descriptors to React components & live data bindings
```
The renderer is a registry of primitive components (tables, forms, cards, charts, approval widgets, build-canvas). The backend chooses *which* components, *in what arrangement*, with *what bindings* — so a novice gets guided simplicity and a power user gets density, from the same code. New fields from the dynamic schema (§10) automatically surface as form/table columns.

---

## 9. Self-Evolving Code

> **Phase 2 — new (🚩 partially shipped).** Tools and agent logic can be synthesized, healed, and optimized — always sandboxed and test-gated. *(Shipped, flag-OFF: the tool-synthesis pipeline — ToolSmith → ToolValidator AST gate → sandbox replay → red-team → DRAFT registration — plus per-tenant sandbox containers with an egress allow-list proxy. Road map: self-heal/self-optimize triggers and the `tool_versions` promote/rollback ledger below.)*

### 9.1 Lifecycle
```
[ trigger ] ── meta_agent (new tool) | self_heal (tool error / API drift) | self_optimize (Learning §7)
     │
     ▼
[ generate/patch source ] ──► [ tool_versions row: status=CANDIDATE, origin=... ]
     │
     ▼
[ sandbox execute + self-generated tests ]  (Sandbox/Terminal isolation, §15 of Phase 1 / retained)
     │
     ├── pass + Pre/Post-Critic OK ──► [ HIGH-IMPACT? ] ── yes ─► HITL approval ─► PROMOTED
     │                                                     no ──────────────────► PROMOTED
     └── fail ──► discard / iterate (origin meta_agent loops back to §6)
```
Promotion flips `tool_versions.status` to `PROMOTED` and atomically swaps the active version; any regression is a single-row `ROLLED_BACK`. Self-healing is triggered by repeated tool failures captured as `critic`/`router` signals; self-optimization is triggered by the optimizer (§7.2). Production is never modified in place — only promoted, versioned artifacts go live.

---

## 10. Dynamic Per-Tenant Schema

> **Phase 2 — new (⬜ road map).** Each tenant has an evolving data model in `tenant_schema/`, isolated by `company_id`. *(Not started in code.)*

### 10.1 Storage Strategy
Tenant entity definitions live in `tenant_entity_defs` (name + evolving JSON `fields`, versioned). Records are stored in a JSONB-backed `tenant_records` table keyed by `(company_id, entity_def_id)`, which keeps physical isolation simple while allowing per-tenant shape:
```python
class TenantRecord(Base):
    __tablename__ = "tenant_records"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"), index=True)
    entity_def_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenant_entity_defs.id"), index=True)
    data: Mapped[Any] = mapped_column(JSONB)             # validated against the def's current fields
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
```

### 10.2 Evolution Triggers
*   **Onboarding** — Pragya's KB ingestion and system connections (§11) seed initial `tenant_entity_defs`.
*   **In use** — when agents repeatedly encounter an unmodeled entity/field (new CRM field, recurring document type), a new field/def is proposed and (auto or HITL) applied; `version` increments.
*   **Learning-driven** — the optimizer (§7) promotes frequently-seen patterns into first-class defs.

Schema changes are additive and versioned; `data` is validated against the def's current `fields`. Generative UI (§8) reads these defs to render the right inputs and views; memory retrieval and reporting use them to structure tenant data.

### 10.3 The Predefined HireBuddha Business Schema (HBS) — v3.0.4 owner directive
Dynamic does not mean empty. Every tenant DB is initialized with the **HireBuddha Business Schema**: a complete, predefined schema deep enough that a tenant with **no external systems runs their entire business on HireBuddha alone** — the platform is their one and only system (§21.3). The 27 canonical objects (Blueprint §3.2) are the spine; each expands into a full functional module:

| HBS module | Coverage (expands canonical objects) |
|---|---|
| CRM | Accounts, contacts, leads, opportunities, quotes, activities, pipeline |
| Accounting | Chart of accounts, journals, ledger entries, invoices/bills, payments, tax, reconciliation |
| HRMS | Employees, contracts, payroll inputs, leave/attendance, appraisals |
| ERP / Operations | Orders, projects, deliverables, inventory, procurement, vendors |
| Legal | Contracts, obligations, disputes, corporate records, policies |
| Marketing & PR | Campaigns, content, channels, audiences, media contacts |
| Planning | Budgets, targets, forecasts, KPIs |

Per-tenant evolution (§10.2) **extends and specializes** this baseline — it never starts from a blank page. Field-level module design is Increment-1 (spine) and Increment-4 (depth) build work in the road map.

### 10.4 Storage Placement — the Tenant Sandbox — v3.0.4 owner directive
The tenant's schema and business data live in a **tenant-scoped database hosted on the tenant's docker-backed persistent sandbox** (the shipped `TenantSandboxManager` + persistent-volume container runtime): `tenant_entity_defs`, `tenant_records`, and `tenant_record_links` (§19) reside in the sandbox volume. This gives hard physical isolation per tenant and makes the exit/portability promise literal — **the tenant's business is a portable volume** *(v3.0.6: plus the control-plane KB+memory dump included in every export, see §10.5)*. Platform services reach it over the sandbox network under the existing egress controls.

> **v3.0.6 (decision 2026-07-19): the knowledge base and CORTEX memory stay in the control plane permanently** — they are on the hot path of every run stage, heartbeat, and Dreaming cron; placing them in the tenant DB would keep it perpetually warm (defeating §23.4 hibernation), add a sandbox network hop to every memory read, and put memory-hungry vector indexes inside the small-footprint tenant containers. The shipped `hb-cortex-memory` + documents/chunks storage is therefore the permanent home; data residency (Inc 7, B14) is served by regional control planes.

**Engineering consequences — settled in §23.4 (v3.0.5):** uniform Postgres+pgvector per tenant sandbox with tiered hibernation; nightly encrypted dumps + weekly volume snapshots; platform-side pooled connections; signals stay control-plane; cross-tenant analytics impossible by construction (opt-in benchmarking deferred to D5). Fleet-scale topology itself remains register B14 (Increment 7).

### 10.5 Master vs Tenant Data Segregation — v3.0.4 owner directive

| Master / common platform DB (control plane) | Tenant DB in the sandbox (data plane) |
|---|---|
| Identity & tenancy: companies, users, auth, partner hierarchy | Business objects: HBS records + dynamic extensions + links (§19) |
| Billing: wallets, cost ledger, SKUs, subscriptions, payments | Artifacts and generated files |
| Registries: models, tools, integrations (credentials in the Key Vault), entity templates, checkpoint defs | Tenant-specific reports and exports |
| Governance config & feature flags; entity definitions (configs, not business data) | |
| Execution fabric: runs, traces, routing decisions, signals* | |
| Knowledge base & memory** — documents, chunks, semantic index; CORTEX trees, episodic history, conversation logs | |

\* Signals and run records stay in the control plane — billing attribution and the `SKIP LOCKED` dispatcher need one operational store (settled with B6, §23.4); tenant portability of business events is served by the export API.

\** v3.0.6 (decision 2026-07-19): KB + memory are **control-plane permanent** — see the §10.4 note for rationale. The tenant export bundle always includes a KB+memory dump alongside the tenant-DB dump, keeping the portability promise whole.

**Rule of thumb: the control plane knows *about* the business and remembers it for the platform's machinery; the tenant DB holds the business's records — and the export bundle reunites the two.**

---

## 11. Pragya — Account-Manager Runtime

> **Phase 2 — new (⬜ road map).** Pragya is a high-privilege, tenant-scoped Agent that orchestrates onboarding, integrations, the Meta Agent, work assignment, and reporting across omnichannel surfaces. *(Not started in code — no runtime, sessions table, or channel adapters.)*

### 11.1 Session & Channels
`account_manager_sessions` holds continuous context per tenant across channels; episodic + CORTEX memory make a conversation portable between channels. Adapters:
*   **Meetings (frontend)** — realtime voice/console via the §5 audio path (OmniBuddha default).
*   **Phone** — Twilio/Smartflo/Exotel inbound to the same realtime path.
*   **WhatsApp / Slack / Teams / Email** — via the messaging connectors and the Rich Communication Broker.

### 11.2 Orchestration Responsibilities
*   **Onboarding/ingest** — drives Knowledge Source Connectors (SharePoint, Notion, Drive, DBs, file uploads) into Semantic + CORTEX memory; seeds the dynamic schema (§10).
*   **Integrations** — guides OAuth connection of CRM/ERP/Accounting/HRMS/Invoicing per captured requirements.
*   **Build/assign** — relays goals to the Meta Agent (§6) to create new employees/tools, or assigns work to existing `hierarchical_entities`.
*   **Monitor/report** — subscribes to run traces and KPIs, surfaces HITL checkpoints to the tenant, and proactively reports status.

> **v3.0.4:** the full engagement protocol is the **nine-stage flow** of functional doc §4.3 (baseline research → working assumptions → deep ingestion → revised analysis → solution engineering with the user → blueprint finalization → integration → test/deploy → operate). Stages 1–5 constitute the as-is discovery protocol (closes register C8); the orchestration responsibilities above are the runtime view of stages 6–9.

Pragya runs at the Agent tier with a tenant-scoped governance profile; she cannot cross tenant isolation boundaries (§16, retained).

### 11.3 Inward-Channel Authentication & Command Authorization — ⬜ road map (design v3.0.3, closes register D1)

> **Decision (2026-07-18): impact-tiered step-up.** Channel identity is a routing hint, never proof; the higher a command's blast radius, the stronger the verification — the inward mirror of Karuna's SKL-X04 counterparty verification.

**Identity binding.** Each tenant user enrolls their channel identities (phone number, WhatsApp, email address) through a verified handshake (OTP at enrollment); bindings live on the user record. An inbound Pragya contact resolves to a bound user or is treated as unauthenticated — polite refusal of anything tenant-specific plus an enrollment path.

**The four command tiers:**

| Tier | Commands | Verification |
|---|---|---|
| T0 | General questions touching no tenant data | none |
| T1 | Reads/reports on tenant state; routine work assignment | bound channel identity + session continuity |
| T2 | Sensitive: payment approvals, autonomy raises, pausing/resuming Processes, bank-detail changes, bulk data operations | **Step-up:** passkey/FIDO2 push to the registered app (TOTP fallback) → elevated session, default 10 minutes |
| T3 | Critical/irreversible: loop kill-switch, above-band payouts, regulatory filings | Step-up **plus out-of-band confirmation** on a second registered channel |

**Mechanics.** Command intents Pragya extracts are classified against the same authority-matrix categories the §20.3 PolicyGate evaluates — one taxonomy, two enforcement points. `account_manager_sessions` gains `auth_level` and `elevated_until`; a successful step-up elevates the session, expiry demotes it. **Pragya can never satisfy her own checkpoint:** HITL approvals raised by the PolicyGate route to the Judgment Desk (HITL cards / Generative UI), never to a confirmation spoken back over the same possibly-compromised channel.

**Anti-spoof posture.** Caller ID, WhatsApp sender, and email `From` are hints only. Voice-print matching may add signal but is never a sole factor. Repeated failed step-ups lock T2+ commands for that user and alert **all** registered channels. Blueprint §9.5's outward threat model now has its inward counterpart.

**Build notes:** channel-binding storage + a rule-based tier classifier over the §20 categories + passkey/OTP step-up + session elevation fields. No new agent machinery.

---

## 12. Core AI Orchestration Engine (The AgentLoop) — retained from Phase 1

The `AgentLoop` coordinates state transitions and execution within the platform. **Phase 2 note:** each reasoning call inside the loop is bound to a concrete model by the router (§3.3).

### 12.1 Control Loop Code Workflow
The execution loop runs inside `AgentLoop._drive` and `AgentLoop._loop` via a state-machine workflow:

```
[BOOTSTRAP RUN]
      │
      ▼
┌──────────────┐
│  Perceive    │ ◄── [Re-read Cancel Status]
└──────┬───────┘
       │ (perception variables)
       ▼
┌──────────────┐
│  Strategize  │ ◄── [Retry Queue Check]
└──────┬───────┘
       │ (chosen_executor, move)
       ▼
┌──────────────┐
│  Pre-Critic  │ ───► [BLOCK] ──► [Consecutive Count >= 3?] ──► [ABORT]
└──────┬───────┘
       │ (PASS / REVISE)
       ▼
┌──────────────┐
│     Act      │ ───► [Awaiting Children?] ──► [SUSPEND STATE] ──► [release worker]
└──────┬───────┘
       │ (ActionResult)
       ▼
┌──────────────┐
│   Observe    │
└──────┬───────┘
       │ (novelty_score, outcome)
       ▼
┌──────────────┐
│ Post-Critics │
└──────┬───────┘
       │ (supervise recommendation)
       ▼
┌──────────────┐
│   Reflect    │ ───► [Write Reflection Node to CORTEX + Learning Signal §7]
└──────┬───────┘
       │
       ▼
┌──────────────┐
│    Decide    │ ───► [REPLAN / CONTINUE / DONE / ABORT]
└──────────────┘
```

1.  **Perceive**: `Perceiver.gather` loads local inputs, semantic chunks, and updates the active context block.
2.  **Strategize**: `Strategist.next_move` selects a step or prompts the planner. It also evaluates if there are queued retries.
3.  **Pre-Critic**: `CriticPipeline.pre_action` audits the selected action. Consecutive rejections increment `consecutive_pre_critic_blocks`. If this reaches `_MAX_CONSECUTIVE_PRE_CRITIC_BLOCKS` (3), a circuit-breaker stops the execution.
4.  **Act**: Resolves and calls the step executor.
5.  **Observe**: `Observer.parse` processes step outputs and checks for runtime blocks.
6.  **Post-Critic**: The supervisor checks alignment, logs token usage, and schedules retries.
7.  **Reflect**: `Reflector.produce` writes logical reflections back to CORTEX tree memories **and emits a learning signal (§7)**.
8.  **Decide**: Checks flags and sets `state.done = True` if complete or aborted.

### 12.2 Async Suspend/Resume Child Dispatch Implementation
When a process triggers a child run, the execution is handled asynchronously to prevent blocking the worker thread:

#### 1. Suspend Event (`ChildEntityExecutor._dispatch_async`)
*   Inserts a new `execution_runs` row with `parent_run_id` set to the parent's run ID.
*   Enqueues the child run via Redis/Arq.
*   Returns an `awaiting_children` list to the loop:
    ```json
    [{"run_id": "child-run-uuid-string", "step_id": "parent-step-id", "status": "PENDING"}]
    ```
*   The parent loop captures the result, serializes the complete `AgentState` object using `state.snapshot()`, stores it in `run.context_state["__agent_state_snapshot__"]`, sets the status to `WAITING_ON_CHILDREN`, and releases the execution worker.

#### 2. Resume Event (`resume_parent_run` worker job)
*   Triggered when the child run reaches a terminal state.
*   Resolves the parent run, checking that its status is `WAITING_ON_CHILDREN`.
*   Deserializes the state snapshot using `AgentState.restore(snapshot)`.
*   Calls `_fold_children` to merge the child's outputs and costs:
    ```python
    # Deduct child cost from parent budget
    state.budget.consume(
        usd=Decimal(str(child_run.total_cost_usd or 0)),
        tokens=int(child_run.total_tokens or 0)
    )
    # Store child output in parent context
    state.context_state[step_id] = child_run.result_data.get("output", "")
    state.mark_step_complete(step_id)
    ```
*   Resumes execution via `AgentLoop._drive`.

---

## 13. Memory System & CORTEX Technical Details — retained from Phase 1

### 13.1 Semantic Query matching (pgvector)
HireBuddha uses `pgvector` for similarity matching:

```sql
SELECT content, 1 - (embedding <=> :query_embedding) AS similarity
FROM document_chunks
WHERE document_id IN (:doc_ids)
  AND 1 - (embedding <=> :query_embedding) > 0.70
ORDER BY similarity DESC
LIMIT 5;
```

### 13.2 CORTEX Context Viewport
CORTEX organizes data into hierarchical trees. A viewport parser limits the size of context injected into the prompt, resolving context window limitations:

```python
def get_viewport_context(tree: CortexTree, cursor_node_id: UUID, max_tokens: int = 8000) -> str:
    # 1. Walk up the parent tree from the cursor node
    path = tree.get_path_to_root(cursor_node_id)

    # 2. Add sibling context nodes based on relevance
    nodes = prune_and_rank_by_relevance(path, target_query=None)

    # 3. Serialize nodes until the max_tokens limit is reached
    serialized = []
    accumulated_tokens = 0
    for node in nodes:
        node_text = f"[{node.type.upper()}] {node.title}: {node.content}\n"
        tokens = count_tokens_fn(node_text)
        if accumulated_tokens + tokens > max_tokens:
            break
        serialized.append(node_text)
        accumulated_tokens += tokens

    return "\n".join(serialized)
```

If the node count exceeds the configured limit, the system summarizes historical nodes and records the output in a `checkpoint` node, freeing up context space.

---

## 14. Billing & Credits Engine — retained from Phase 1

### 14.1 TB Billing Calculation
The system calculates usage costs using the **TB Billing Formula** (✅ shipped as specified). **Phase 2 note (⬜ road map):** `base_cost` will be derived from the actual model the router selected (recorded in `routing_decisions`); today it derives from the configured model's actual usage as recorded per call.

```python
def calculate_tb(
    base_cost: Decimal,
    multiplier_factor: Decimal,
    platform_fee_pct: Decimal,
    sales_partner_fee_pct: Decimal,
    discount_pct: Decimal
) -> dict:
    """
    Calculate final billed amount from base cost.
    Formula:
      billed = (base_cost * multiplier)
             + (base_cost * multiplier * platform_fee)
             + (base_cost * multiplier * partner_fee)
             - (base_cost * multiplier * discount)
    """
    markup = base_cost * multiplier_factor
    platform_charge = markup * (platform_fee_pct / Decimal("100"))
    partner_charge = markup * (sales_partner_fee_pct / Decimal("100"))
    discount_amount = markup * (discount_pct / Decimal("100"))

    total_billing = markup + platform_charge + partner_charge - discount_amount

    return {
        "markup": markup,
        "platform_charge": platform_charge,
        "partner_charge": partner_charge,
        "discount_amount": discount_amount,
        "total_billing": max(total_billing, Decimal("0"))
    }
```

---

## 15. Security & Encryption — retained from Phase 1

### 15.1 AES-256-GCM Symmetric Cipher Implementation
API keys and social media tokens are encrypted before saving to database columns:

```python
import os
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

def encrypt_vault_secret(secret_text: str, key_hex: str) -> str:
    """Encrypt integrations key using the master hex key."""
    key_bytes = bytes.fromhex(key_hex)
    aesgcm = AESGCM(key_bytes)
    nonce = os.urandom(12)  # 12-byte initialization vector

    ciphertext = aesgcm.encrypt(nonce, secret_text.encode("utf-8"), None)

    # Prepend nonce to cipher bytes before saving as hex
    return (nonce + ciphertext).hex()

def decrypt_vault_secret(encrypted_hex: str, key_hex: str) -> str:
    """Decrypt integrations key using the master hex key."""
    key_bytes = bytes.fromhex(key_hex)
    aesgcm = AESGCM(key_bytes)
    raw_data = bytes.fromhex(encrypted_hex)

    nonce = raw_data[:12]
    ciphertext = raw_data[12:]

    decrypted_bytes = aesgcm.decrypt(nonce, ciphertext, None)
    return decrypted_bytes.decode("utf-8")
```

### 15.2 Company Suspension ASGI Middleware
The platform blocks suspended companies using an ASGI middleware layer:

```python
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from src.auth.service import CompanyService

class CompanySuspensionMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # 1. Bypass check for public paths
        if request.url.path in ("/health", "/api/v1/auth/login", "/api/v1/auth/register"):
            return await call_next(request)

        # 2. Extract company_id from request state (populated by auth)
        company_id = request.state.company_id if hasattr(request.state, "company_id") else None

        if company_id:
            # 3. Check suspension status in database
            is_suspended = await CompanyService.is_company_suspended(company_id)
            if is_suspended:
                return JSONResponse(
                    status_code=403,
                    content={"detail": "Access denied: Account is suspended due to unpaid invoice."}
                )

        return await call_next(request)
```

> **Phase 2 note:** the sandbox/test-gating pipeline for self-evolving code (§9) and the model `allow_list`/data-residency filtering (§3.4) are additional security surfaces; all routing, generation, build, and self-modification events are written to the audit log.

---

## 16. Frontend ReactFlow Node Serialization — retained from Phase 1

In the canvas dashboard (`frontend/src/pages/ai/EntityFlow.tsx`), user interactions serialize flows into the entity database schema. **Phase 2 note:** the same canvas now also renders entities the **Meta Agent** generated (§6), and the generative-UI renderer (§8) can surface this canvas as a component within an adaptive layout.

```typescript
interface ReactFlowEdge {
  id: string;
  source: string; // parent step id
  target: string; // child step id
}

interface ReactFlowNode {
  id: string;
  type: string;
  data: {
    label: string;
    stepConfig: {
      type: string;
      target: {
        prompt_template: string;
        tool_id?: string;
      };
    };
  };
}

// Compiles ReactFlow state into the backend hierarchical json schema
function serializeFlow(nodes: ReactFlowNode[], edges: ReactFlowEdge[]): any {
  return nodes.map(node => {
    // 1. Find dependency links pointing to this node
    const inputDependencies = edges
      .filter(edge => edge.target === node.id)
      .map(edge => edge.source);

    // 2. Format structure matching PlanStep schema
    return {
      step_id: node.id,
      name: node.data.label,
      type: node.data.stepConfig.type,
      target: {
        ...node.data.stepConfig.target,
        input_dependencies: inputDependencies,
      }
    };
  });
}
```

---

## 17. LOOP Runtime Architecture — ⬜ road map (design v3.0.2, closes register B1)

> **Design principle: a Loop is a scheduler and an aggregator — never a run.** The shipped AgentLoop's run-based model (finite runs, suspend/resume, per-run billing) is untouched. The LOOP tier is a thin standing layer built from shipped machinery: Arq cron, CORTEX, the CostLedger.

### 17.1 Execution Model
A `LOOP` row in `hierarchical_entities` (`type="LOOP"`; **one root Loop per tenant — Sheel** — enforced by a partial unique index on `(company_id) WHERE type='LOOP' AND parent_id IS NULL`; child Loops may federate beneath it, §17.6) never gets an `execution_runs` row of its own. Instead, a per-tenant **heartbeat job** (Arq cron, default every 120s, configurable) performs four deterministic steps:

1. **Dispatch due schedules** — evaluate `loop_config.schedules` and emit `schedule.*` signals (§18).
2. **Sweep parked signals** — re-evaluate `PARKED` signals whose review timer expired (§18.4).
3. **Roll up** — aggregate child Process costs (from the CostLedger) and KPI inputs into `loop_runtime.stats` and the Loop's CORTEX tree.
4. **Stamp** `last_beat_at`.

All Loop *cognition* (an executive briefing, a budget reallocation proposal) is dispatched as ordinary AGENT/PROCESS runs — so every LLM call the Loop causes flows through the existing run engine, billing, and governance without exception.

### 17.2 State
Long-horizon memory is the Loop's **CORTEX tree** — auto-checkpointing and the Dreaming consolidation engine (both shipped) already solve months-scale state compaction. Operational state is one small row:

```python
class LoopRuntime(Base):
    __tablename__ = "loop_runtime"
    loop_entity_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("hierarchical_entities.id"), primary_key=True)
    enabled: Mapped[bool] = mapped_column(default=True)
    heartbeat_interval_s: Mapped[int] = mapped_column(default=120)
    last_beat_at: Mapped[datetime | None]
    consecutive_missed: Mapped[int] = mapped_column(default=0)
    stats: Mapped[Any] = mapped_column(JSON)   # rolling KPI/cost aggregates per process/arc
```

There is no `AgentState` snapshot for a Loop — nothing to suspend or resume; a crashed heartbeat simply fires again.

### 17.3 Supervision
A platform watchdog cron flags any Loop whose `last_beat_at` is older than 3 intervals: `consecutive_missed` increments, an `incident.platform` signal is emitted (§18), and ops is alerted. Recovery is re-enqueueing the heartbeat — safe because schedule dispatch deduplicates through signal `dedupe_key`s (§18.5), so a double-fired heartbeat cannot double-run a Process.

### 17.4 Billing
Loops create no runs, so **no LOOP minimum-wallet threshold exists — by design, not omission** (functional doc §14.3 amended). The heartbeat is deterministic code billed as a flat platform-overhead SKU (≈ zero); every dollar of real spend occurs in child runs at the existing PROCESS/AGENT/SKILL/ACTION thresholds.

### 17.5 Lifecycle
The entity `status` column carries `ACTIVE | PAUSED | ARCHIVED`. Pausing a Loop stops schedule dispatch and signal claiming, but **protected processes (P14/P17) keep running from their reserved envelope** (§20.4).

### 17.6 Federation (LOOP → LOOP) — legalized v3.0.3 (closes register A8)
The composition rule is formally amended: **a LOOP row may parent LOOP rows** — Blueprint §13's federated and holding topologies are first-class, not a future exception. Rules:

1. Exactly one **root** Loop per tenant (the §17.1 partial index: `parent_id IS NULL`).
2. Only a LOOP may parent a LOOP (deploy-time validation, enforced alongside the §20.5 checks).
3. Every Loop — root or child — gets its own `loop_runtime` heartbeat, trigger subscriptions (§18), and budget envelope (§20.4).
4. A parent's heartbeat rolls up child-Loop `stats` exactly as it rolls up Processes — federation adds no new aggregation machinery.
5. Memory and policy flow **down** (group policy, brand voice), KPIs and risk aggregate **up**, nothing flows sideways by default (Blueprint §13's rule); model allow-lists and data residency are set per child Loop.

**Build notes:** `LOOP` enum value + the root-Loop partial index + `loop_runtime` table + two cron jobs + the parent-of-LOOP validation rule. No changes to the AgentLoop, executors, or billing engine.

---

## 18. Signal Bus & Trigger Registry — ⬜ road map (design v3.0.2, closes register B2)

> **Design principle: Postgres is the bus.** Signals are transactional rows (outbox pattern) claimed with `FOR UPDATE SKIP LOCKED`; Arq is the delivery muscle. No new infrastructure — this is the same Postgres + Redis/Arq pair the platform already runs, and the gateway dispatcher already routes inbound webhooks this way.

### 18.1 Schema

```python
class Signal(Base):
    __tablename__ = "signals"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"), index=True)
    source: Mapped[str]        # karuna_gateway | connector | telemetry | schedule | agent | human
    type: Mapped[str]          # dotted taxonomy: "lead.inbound", "payment.failed", "incident.security"
    urgency: Mapped[str] = mapped_column(default="normal")   # low | normal | high | critical
    confidence: Mapped[float] = mapped_column(default=1.0)
    trust: Mapped[str]         # counterparty | external_verified | internal | platform  (§18.6)
    object_refs: Mapped[Any] = mapped_column(JSON)           # canonical record ids (§19)
    payload: Mapped[Any] = mapped_column(JSON)
    dedupe_key: Mapped[str | None]        # unique partial index (company_id, dedupe_key)
    status: Mapped[str] = mapped_column(default="PENDING")   # PENDING | CONSUMED | PARKED | ESCALATED | DEAD
    owner_process_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("hierarchical_entities.id"))
    consumed_by_run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("execution_runs.id"))
    park_review_at: Mapped[datetime | None]
    attempts: Mapped[int] = mapped_column(default=0)
    replayed_from: Mapped[uuid.UUID | None]
    created_at: Mapped[datetime]
    consumed_at: Mapped[datetime | None]

class TriggerRegistration(Base):
    """The trigger registry: which Process owns which signal types (Blueprint §3.3)."""
    __tablename__ = "trigger_registry"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"), index=True)
    process_entity_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("hierarchical_entities.id"))
    type_pattern: Mapped[str]             # exact type or prefix glob: "lead.*"
    priority: Mapped[int] = mapped_column(default=100)
    enabled: Mapped[bool] = mapped_column(default=True)
```

### 18.2 Producing
Producers insert the signal row **in the same DB transaction as the business write** (outbox pattern), then enqueue `dispatch_signal(id)` after commit. A periodic sweeper re-enqueues any `PENDING` signal older than one sweep interval — this covers a crash between commit and enqueue and is what makes "**no dropped signals**" an auditable property rather than a slogan. Producers: Karuna gateways (via the existing gateway dispatcher), connectors/webhooks, the Loop heartbeat (§17 — scheduled signals), agents (SKL-X01 via an internal API), and humans (UI actions).

### 18.3 Dispatching
The dispatcher claims with `SELECT … WHERE status='PENDING' FOR UPDATE SKIP LOCKED` (the standard Postgres queue pattern — safe under concurrent workers), resolves the **single owning Process** from `trigger_registry` (best match by priority; deterministic tiebreak: priority DESC, then entity id — the Blueprint's "exactly one owner" rule made mechanical), spawns an ordinary Process run with the signal in `input_data`, and marks `CONSUMED` + `consumed_by_run_id`. `urgency="critical"` signals (P17 Incident-to-Resolution) are claimed ahead of the queue.

No matching trigger → `PARKED` with a `park_review_at` timer (re-swept by §17.2); parked past its SLA → `ESCALATED` (HITL card). Dispatch failure → `attempts += 1` with exponential backoff; past `max_attempts` (default 5) → `DEAD` + an `incident.governance` signal + ops alert. Every terminal state is therefore visible.

### 18.4 Delivery Semantics (explicit)
* **At-least-once delivery, idempotent consumption:** the claimed transition PENDING→CONSUMED is atomic; the spawned run records `signal_id`, so a re-delivered signal cannot spawn a second run.
* **Deduplication:** unique partial index on `(company_id, dedupe_key)`; producers set `dedupe_key` from the external event id (webhook id, message SID, schedule slot).
* **Ordering:** best-effort FIFO per company (`created_at`); **no global ordering guarantee** — object state (§19) is the source of truth, signals are triggers, not state.
* **Replay:** signals are immutable; replay inserts a clone with `replayed_from` set.

### 18.5 Completion & Audit
`AgentLoop._finalize` (the same hook that already fires the Dreaming outcome trigger) emits `<type>.completed` for the consumed signal. The Blueprint's Arc-VI **signal-coverage KPI** is then one SQL query over `signals.status` — % of signals neither PENDING nor PARKED beyond SLA.

### 18.6 Trust Hook (feeds register D3)
`trust` is stamped by the producer (`counterparty` for anything a Karuna gateway ingested from the outside world). The §20.3 PolicyGate may refuse high-impact tool categories on runs whose triggering signal is counterparty-trust — the down-payment on full taint tracking (D3 remains open).

**Build notes:** two tables + one Arq job + one sweeper cron + a `_finalize` hook. The gateway dispatcher and Chronos-style crons already exist.

---

## 19. Canonical Object Graph Storage — ⬜ road map (design v3.0.2, closes register B3)

> **Design principle: documents for shape, edges for the graph.** `tenant_records` stays JSONB (per-tenant shape flexibility); the graph the Blueprint's §3.2 lifecycle chains require becomes a first-class, typed **link table** — not JSON references that can dangle.

### 19.1 The Link Table

```python
class TenantRecordLink(Base):
    __tablename__ = "tenant_record_links"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"), index=True)
    src_record_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenant_records.id"), index=True)
    dst_record_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenant_records.id"), index=True)
    rel_type: Mapped[str]     # closed seed vocabulary, extensible per tenant
    created_at: Mapped[datetime]
    # unique (src_record_id, dst_record_id, rel_type)
```

Seed `rel_type` vocabulary: `converted_to` (Signal→Lead→Opportunity→Quote→Contract), `belongs_to` (Contact→Account), `attached_to` (Ticket/Risk/Incident→anything), `fulfilled_by` (Order→Project), `billed_by` (Order→Invoice), `paid_by` (Invoice→Payment), `derived_from` (generic provenance).

### 19.2 Reference Fields
`tenant_entity_defs.fields` gains a ref type: `{"name": "account", "type": "ref", "target": "Account"}`. **All record writes go through one record service** (agents/ACT-30 included — no direct table writes); the service validates refs and materializes each into a `tenant_record_links` row, keeping document and graph in sync with a single write path. *(v3.0.5: the record service also enforces write ownership and compare-and-set versioning — §23.1–§23.2.)*

### 19.3 Indexing
* GIN (`jsonb_path_ops`) on `tenant_records.data` for ad-hoc queries.
* **Promoted expression indexes** for hot fields: when the Learning System observes a field filtered above a threshold, a background job creates a per-def expression index via `CREATE INDEX CONCURRENTLY`. Index promotion is the storage-layer twin of schema promotion (§10.2).
* B-tree on the link table's `(company_id, src_record_id)` / `(company_id, dst_record_id)` for graph traversal.

### 19.4 Evolution Beyond "Additive"
* **Field lifecycle:** `active → deprecated → hidden`. Deprecated fields validate but warn; hidden fields are dropped from generated UI/retrieval but retained in stored data.
* **Renames:** additive aliases — `{"name": "amount", "aliases": ["value"]}`; reads resolve aliases, writes normalize to the canonical name. No in-place mutation, no breakage of stored records.
* **Type changes:** add a new field + background backfill job + deprecate the old one. Never mutate a field's type in place.
* **Versioning:** `tenant_entity_defs.version` increments on any change (audited); each record stamps `def_version` at write. Validation is **write-time against the current def**; old records upgrade lazily on their next write — no mass migrations.

### 19.5 Integrity & Deletion
FKs on the link table; record deletion defaults to soft delete (`deleted_at`) so links never dangle. Hard deletion exists only on the DSAR path (register D6), which cascades links and leaves a tombstone for audit.

**Build notes:** one table + one write service + the ref field type. The GIN index and def versioning land with the base `tenant_schema/` build (§10).

---

## 20. Governance Schema & Enforcement — ⬜ road map (design v3.0.2, closes register B5; §20.4 closes A6)

> **Design principle: deterministic policy before LLM judgment.** Blueprint §9's constructs stop being prose and become: a typed config schema, two small platform tables, a pure-function gate in front of the shipped Pre-Critic, and deploy-time checks in the shipped Board Validator.

### 20.1 Typed Governance Block
The existing `governance` JSON column on `hierarchical_entities` gains a **Pydantic-validated schema** (extends the shipped `ai/schemas/governance.py`) — no new entity columns:

```json
"governance": {
  "autonomy_level": "A1",
  "authority": { "payout_usd": 500, "refund_usd": 200, "discount_pct": 10, "contract_tcv_usd": 2000 },
  "sod_class": "maker | checker | auditor | none",
  "karuna_profile": true,
  "hitl_checkpoints": ["before_outbound_payout_above_band", "..."],
  "budget": { "envelope_ref": "..." }
}
```
Writes that fail schema validation fail the save — governance config can no longer be silently malformed.

### 20.2 Checkpoint Registry
A platform table `hitl_checkpoint_defs` seeds the Blueprint's 18 checkpoints (`key`, `category`, `description`, `default_threshold`, `platform_mandatory`). The shipped `human_approvals` table gains `checkpoint_key`. Tenants tune thresholds per entity in the governance block; `platform_mandatory` checkpoints (e.g., `before_self_evolving_code_promotion`) cannot be removed.

### 20.3 Runtime Enforcement — the PolicyGate
A deterministic, pure-function stage that runs **inside the shipped critic pipeline, before the LLM Pre-Critic**:

```
Act intent → PolicyGate(action_category, amount, counterparty_flags, signal_trust §18.6)
                 │ evaluated against: autonomy_level + authority bands + checkpoint defs + SoD class
                 ├─ PASS        → continue to LLM Pre-Critic (unchanged)
                 ├─ RAISE_HITL  → human_approvals row (checkpoint_key) + run PAUSED  (shipped flow)
                 └─ BLOCK       → step blocked; verdict on the StepHealthRecord      (shipped record)
```

The authority matrix (Blueprint §9.3) is data, not prompt text: an LLM cannot be talked out of a `BLOCK`. Verdicts land on the existing `StepHealthRecord`, so calibration and learning see policy decisions for free.

### 20.4 Budget Hierarchy & the Protected Reserve

```python
class BudgetEnvelope(Base):
    __tablename__ = "budget_envelopes"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"), index=True)
    entity_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("hierarchical_entities.id"))  # LOOP or PROCESS
    cycle: Mapped[str]                        # monthly | weekly
    envelope_usd: Mapped[Decimal]
    reserved_usd: Mapped[Decimal] = mapped_column(default=0)   # protected carve-out (P14/P17)
    spent_usd: Mapped[Decimal] = mapped_column(default=0)      # rolled up from the CostLedger
    downshift_at_pct: Mapped[int] = mapped_column(default=80)
    refreshed_at: Mapped[datetime]
```

The Loop heartbeat (§17.1) refreshes envelopes on cycle and rolls up `spent_usd` from the shipped CostLedger attribution. At `downshift_at_pct` → a notification signal to the owner; at 100% → the Loop stops dispatching that Process's non-critical signals (they park, not drop).

**The protected reserve resolves the register-A6 contradiction:** P14 Guardrails and P17 Incidents are "never paused" because their envelope share is **carved out as `reserved_usd` at cycle refresh — pre-funded, not exempt**. The platform's hard wallet floor (`InsufficientCreditsError`) is unchanged: if the tenant wallet itself is truly empty, protected processes stop too, an emergency HITL + dunning path triggers, and the degraded read-only mode (register C5) applies. No free execution exists.

### 20.5 Deploy-Time Validators
The shipped Meta-Agent Board **Validator** (8 deterministic checks) and the manual entity-publish service gain governance checks that fail closed:

1. **Karuna gate** — an entity with an external channel binding must carry `karuna_profile: true` (Blueprint §2.3's deploy rule, made real).
2. **SoD conflicts** — declarative `sod_rules` seed data (the five Blueprint §9.4 rules: maker≠checker, vendor-create≠vendor-pay, access-granter≠access-user, auditor independence, self-modification quarantine) evaluated as pure functions over the entity graph.
3. **Autonomy caps** — a new entity cannot exceed its tier's default autonomy ceiling; raises route through the `before_autonomy_level_promotion` checkpoint.

### 20.6 Autonomy Transitions
`autonomy_level` changes **only** through checkpoint 17 (`before_autonomy_level_promotion`) — proposed by the Learning System's evidence, ratified by a human, recorded in `human_approvals`. SLO breaches auto-*propose* demotion through the same path (full demotion criteria: register C4, open).

**Build notes & order:** 20.1 + 20.2 first (pure schema), then 20.3 (one new pipeline stage in an existing seam), then 20.5 (extends the shipped Validator), then 20.4 (needs the §17 heartbeat). Nothing here touches the AgentLoop's stage contract.

---

## 21. System of Record & Sync Policy — ⬜ road map (design v3.0.3, closes register B4)

> **Decision (2026-07-18): per-object ownership.** Each canonical object declares its master at onboarding. Objects the tenant already manages in a connected system stay mastered **there** — HireBuddha mirrors, links, and writes back through the connector. Objects with no external home are mastered **in HireBuddha**. One declared rule per object; no big-bang migration.

### 21.1 Declaration
`tenant_entity_defs` gains a `sor` block: `{"master": "hirebuddha" | "external", "connector_id": "...", "write_back": true}`. Pragya's onboarding interview (functional doc §4.3 step 2) proposes the setting per object from the connected systems; the tenant confirms or overrides.

### 21.2 Mirror Semantics (external master)
* **Mirror rows:** `tenant_records` gains `sor` + `external_ref` JSON (`{connector, external_id, version/etag, synced_at}`); unique on `(company_id, connector, external_id)`.
* **Reads** serve the mirror; staleness is bounded by the connector's sync cadence — webhooks where the external system offers them, cron sweeps otherwise. Sync events enter the loop as §18 signals (`object.synced`) with the external event id as `dedupe_key`.
* **Writes go through the connector first** (write-back); the mirror updates only on confirmation. A failed write-back changes nothing locally and retries per §18 backoff.
* **Master wins conflicts:** a divergent concurrent external edit overwrites the mirror and raises a `sync.conflict` signal carrying the losing delta — the owning Process (or HITL) reviews it. No silent merging.

### 21.3 HireBuddha-Master Semantics
Normal records (§19). Optional downstream export to tenant systems is one-way and labeled as such — there is never a second master.

**The standalone case is the norm, not the fallback** *(v3.0.4)*: for a tenant with no external systems, the predefined HBS (§10.3) gives HireBuddha full functional depth — CRM, accounting, HRMS, ERP, legal, marketing, planning — so the platform serves as the tenant's one and only system, mastering everything.

### 21.4 Ownership Migration
Flipping `sor.master` (the tenant retires a CRM, or adopts one later) is an explicit, HITL-gated migration operation with backfill and link rewrite — never implicit.

### 21.5 One Memory, Two Masters
§19 links may point at mirror records, so lifecycle chains span both masters — the invoice mastered in the tenant's accounting system and the ticket mastered in HireBuddha are the *same graph*. The one-memory doctrine constrains the graph, not the mastering.

**Build notes:** `sor`/`external_ref` fields + connector sync jobs + the `sync.conflict` signal type. Depends on §18 (signals) and §19 (records/links).

---

## 22. Evaluation & Release Safety — ◐ (design v3.0.3, closes register B9)

> **This was a documentation gap more than a code gap:** the platform ships more evaluation machinery than any earlier doc admitted. This section documents the shipped layer and specifies the three missing pieces that make autonomous self-modification defensible.

### 22.1 Shipped Today ✅
* **Parity golden gate** (`tests/parity/`) — hermetic engine-behavior comparison against recorded goldens, with chaos (crash/resume/idempotency) and cost-amplification checks; runs in CI.
* **Eval harness** (`tests/eval/`) — pure metrics + delta reports + a DB-gated replay runner.
* **Meta-Agent TestDriver** — smoke/regression/boundary/hostile/comparative suites under a shared budget, with golden-output capture for built entities.
* **Tool-synthesis red team** — an adversarial review step inside the synthesis pipeline (§9).
* **Static gates** — `mypy --strict` over all `ai/` packages, layout/canary lint, the CI matrix.

### 22.2 The Independent-Suite Rule ⬜ — breaks the self-testing circularity
A self-modified artifact (tool, charter, prompt) may **never** be promoted on self-generated tests alone. Promotion requires, in order:
1. **The incumbent's golden suite** — captured from the *current* version's behavior before modification. The exam predates the student.
2. **Platform curated suites** for the artifact's category — seeded and maintained by humans.
3. Self-generated tests — admitted as *additional* coverage, never as the gate.
4. The red-team step — mandatory, not best-effort.

### 22.3 Canary Rollout ⬜
Promoted versions serve a canary slice first — a per-company flag, the exact pattern the sandbox runtime already ships — with automatic rollback on SLO regression (the Blueprint §10.2 agent SLOs). Full rollout only after a clean canary window.

### 22.4 Model-Change Regression Policy ⬜
Any model-fleet change (new model, version bump, provider deprecation, BabyBuddha admission per §3.1) runs the eval-harness delta report against the incumbent on the affected task classes; admission requires **non-inferiority within cost budget**. Router preference learning (§3.3) can never override a failed admission.

**Build notes:** 22.2 is process plus one promotion-pipeline check; 22.3 reuses the shipped per-company canary-flag pattern; 22.4 is an eval-harness invocation wired to model-registry changes.

---

## 23. Concurrency, Consistency & the Tenant Data Plane — ⬜ road map (design v3.0.5, closes register B6 + E3)

> **Design principle: one owner per object, one hold per run, one engine per tenant.** Three decisions (2026-07-18) anchor this section: writes are owner-mediated, wallet exhaustion finishes gracefully with bounded debt, and every tenant runs a uniform Postgres-in-sandbox data plane.

### 23.1 Write Ownership — Owner Writes, Others Propose
Every tenant object type carries an `owner_process_id` (on `tenant_entity_defs`, set at HBS initialization from the canonical Process map — Invoices belong to Order-to-Cash, Vendors to Source-to-Pay). The rules:

* Agents of the **owning Process** write directly through the §19.2 record service.
* Any other agent emits an **`object.change_proposed` signal** (§18) carrying the delta; the owning Process applies, amends, or rejects it (rejection notifies the proposer's run). At A1 autonomy the application step is itself HITL-visible.
* **SoD falls out structurally:** the AR agent cannot quietly edit a Vendor record — it can only propose, and the proposal is an auditable signal. The §20.3 PolicyGate still checks amounts on the owner's write.
* Emergency escape hatch: a direct cross-owner write requires a HITL approval (checkpoint: `before_cross_owner_write`), never silent.

### 23.2 Record Versioning
`tenant_records` gains `version` (int) + `updated_by_run_id`. The record service enforces **compare-and-set**: a write carries the version it read; a stale version triggers one bounded re-read-and-retry, then a `object.write_conflict` signal instead of a blind overwrite. Mirror records (§21.2) keep their stricter master-wins rule — external state never loses to a local write.

### 23.3 Wallet Reservations & Settlement (closes E3)

```python
class WalletHold(Base):
    __tablename__ = "wallet_holds"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"), index=True)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("execution_runs.id"), unique=True)
    amount_held: Mapped[Decimal]           # planner estimate, floored at the tier minimum threshold
    amount_spent: Mapped[Decimal] = mapped_column(default=0)
    status: Mapped[str] = mapped_column(default="ACTIVE")   # ACTIVE | SETTLED | EXHAUSTED
```

* **Admission:** a run starts by placing a hold = the shipped planner cost estimate (floored at the §14.3 tier minimum), debited from *available* balance in one short `SELECT … FOR UPDATE` transaction on the wallet row — concurrent runs can no longer oversubscribe the same dollar (the E3 race).
* **During the run:** steps consume against the hold; at 80% consumed, the run tops the hold up from the wallet (or the budget envelope downshifts it, §20.4). Envelopes (§20.4) and holds compose: the envelope answers *"may this Process spend?"*, the hold answers *"is the cash actually set aside?"*.
* **Mid-run exhaustion — graceful finish, bounded debt (decision):** the run **completes its current step cleanly** (a live call is never dropped mid-sentence), then suspends (`PAUSED`, reason `insufficient_funds`) and notifies the owner. The overage is capped at **max($1, 5% of the hold)** and recorded as `wallet_debt`, settled from the next top-up before any new spending. Protected processes (P14/P17) draw from their reserved envelope (§20.4) before this path ever triggers.
* **Settlement:** run finalize releases the residual hold and writes actuals to the CostLedger as today.

### 23.4 The Tenant Data Plane — Uniform Postgres-in-Sandbox (decision)
Every tenant — including free/Solo — gets a **dedicated PostgreSQL + pgvector container inside their sandbox**, data directory on the persistent volume (§10.4). One engine, one codepath, uniform hard isolation; no tiered embedded-DB variant.

The cost consequence is handled by **lifecycle, not architecture**:
* **Hibernation:** the tenant DB container starts lazily on first activity and hibernates after a per-tier idle window (Solo: aggressive, e.g. 15 min; Growth+: always-on). Cold-start latency is acceptable because the §18 dispatcher parks, never drops, signals for a waking tenant.
* **Small-footprint config:** capped `shared_buffers`/`work_mem` per tier; connection caps per tenant DB with platform-side pooling keyed by tenant.
* The realized idle cost per tier is a **required input to the E1 idle-cost model** (roadmap Increment 2) — the free-tier economics are now a measured number, not a hope.

**Backup/DR:** nightly encrypted logical dump (`pg_dump`) per tenant to object storage + weekly volume snapshot; restore = provision sandbox, restore dump. The tenant-triggerable **export** (the §12 portability promise) is the same dump path, always available — *v3.0.6: the export bundle additionally includes the control-plane KB+memory dump (§10.5), since KB/CORTEX are control-plane permanent.*

**Signal mirroring (the §10.5 open decision — settled):** signals stay **control-plane only** in v1; tenant portability of business events is served by the export API (consumed-signal history filtered by `company_id`). Revisit only if exit-portability audits demand physical co-location.

**Cross-tenant analytics:** none by construction. Platform dashboards read the control plane only; any future benchmarking across tenants requires explicit per-tenant opt-in (with the D5 data-flow disclosure work).

**Build notes:** `wallet_holds` + wallet-row locking in the credit service; `version`/`owner_process_id` columns + CAS in the record service; the `object.change_proposed`/`object.write_conflict` signal types; the DB container image + hibernation lifecycle in `TenantSandboxManager`. All land in Increment 1 with SCH/SIG.

---

## 24. Memory Scoping & Retrieval Architecture — ⬜ road map (design v3.0.5, closes register B8)

> **Design principle (decision 2026-07-18): share knowledge, not habits.** What the business *knows* is tenant-shared; how each agent *works* is its own — promoted upward only when proven.

### 24.1 The Scoping Matrix
The four shipped CORTEX domains get explicit scopes:

| Domain | Scope | Written by | Read by |
|---|---|---|---|
| **Knowledge** (facts, KB, business objects context) | Tenant-shared | Ingestion + agents via the knowledge service | All agents, through need-to-know viewports (§24.3) |
| **Episodic** (conversations, per counterparty — the A7 re-scope) | Tenant-shared, keyed by counterparty | Channel handlers / gateways | All agents, viewport-filtered |
| **Experience** (what worked/failed in runs) | Per-entity | The Reflect stage | The owning entity; promotable |
| **Intelligence** (distilled rules) | Per-entity, inheritable downward | Reflector + Dreaming engine | The entity + its descendants (a Process's rules apply to its Agents) |

### 24.2 Tier Write Rules — Whose Tree Does a Nested Run Write?
* During execution, a run writes only its **run-scoped tree** (shipped behavior).
* At Reflect, durable lessons promote to the **executing entity's** tree — a Skill's lesson lands on the Skill entity, not on whichever Agent happened to invoke it, so the lesson travels with the reusable unit.
* The **Dreaming engine** consolidates upward along `parent_id`: entity rules that prove out across siblings promote Process-ward and, when company-wide, to the Loop tree (which §17.2 already holds). The shipped confirmed-rule lifecycle is the promotion gate.
* Federation (§17.6): child-Loop trees are isolated; a parent Loop sees only aggregated/promoted material — memory follows the down/up-never-sideways rule.

### 24.3 Need-to-Know Viewports (makes Blueprint §9.5's promise mechanical)
Knowledge and episodic nodes carry **domain tags** (e.g., `payroll`, `legal`, `financial`, `general`) stamped at ingestion from the HBS module of origin (§10.3). An entity's governance block gains `memory_domains` (allow-list); the shipped memory assembler's `ScopePolicy` enforces it at viewport-assembly time. A support agent's viewport *cannot contain* payroll nodes — exfiltration is prevented by construction, not by prompt instruction.

### 24.4 Retrieval Stack Upgrade
Replaces the under-specified v2 stack (500-char chunks, top-5 cosine @0.70):
* **Hybrid retrieval:** Postgres full-text (lexical) + pgvector (semantic), fused by reciprocal-rank fusion — both indexes live in the control-plane DB with the KB they index (*v3.0.6 placement decision, §10.5*).
* **Structure-aware chunking:** 1–2k-character chunks split on document structure, carrying heading context; chunk size tunable per source type.
* **Schema-aware filters:** retrieval accepts metadata predicates from the tenant schema (object type, counterparty, date range) so "invoices for Acme since March" filters before it ranks.
* **Optional reranking:** a cross-encoder rerank stage behind a per-tier flag (Growth+), applied to the fused top-50.
* **Evaluated, not assumed:** retrieval golden sets join the eval harness (§22.1) so chunking/fusion changes are regression-gated like any other change.

**Build notes:** domain tags + `memory_domains` allow-list (extends shipped ScopePolicy); Reflect targeting + Dreaming promotion path (both shipped seams); hybrid retrieval + chunking in the knowledge service; retrieval goldens in `tests/eval/`. Lands across Increments 1 (scoping) and 2 (retrieval upgrade).
