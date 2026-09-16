# 03. Database & Data Model

> **What this document covers:** every table, column, enum, index and migration in the HireBuddha PostgreSQL database, plus how multi-tenancy, soft deletes and pgvector search work on top of them.
> **Who should read it:** any developer who needs to answer "where is X stored?", add a column, or write a query.
> **Prerequisites:** [02 — System architecture](02-system-architecture.md) for the service topology. Read [04 — Auth, RBAC & tenancy](04-auth-rbac-tenancy.md) next for the enforcement side of `company_id`.

---

## Table of contents

1. [The 60-second version](#1-the-60-second-version)
2. [Schema conventions](#2-schema-conventions)
3. [Identity and tenancy tables](#3-identity-and-tenancy-tables)
4. [AI entity and execution tables](#4-ai-entity-and-execution-tables)
5. [Inside the entity JSON columns](#5-inside-the-entity-json-columns)
6. [Memory tables: CORTEX, episodic, documents](#6-memory-tables-cortex-episodic-documents)
7. [Configuration and billing tables](#7-configuration-and-billing-tables)
8. [Voice, telephony and campaign tables](#8-voice-telephony-and-campaign-tables)
9. [Artifacts and external integration tables](#9-artifacts-and-external-integration-tables)
10. [Ops tables, views and legacy tables](#10-ops-tables-views-and-legacy-tables)
11. [Enumerations and lifecycles](#11-enumerations-and-lifecycles)
12. [Multi-tenancy: how company_id scoping works](#12-multi-tenancy-how-company_id-scoping-works)
13. [pgvector: embeddings and similarity search](#13-pgvector-embeddings-and-similarity-search)
14. [Migrations with Alembic](#14-migrations-with-alembic)
15. [Seed and utility scripts](#15-seed-and-utility-scripts)
16. [Where is X stored? Quick lookup](#16-where-is-x-stored-quick-lookup)

---

## 1. The 60-second version

One PostgreSQL database. ~40 live tables plus one materialised view. Everything is
async SQLAlchemy 2.0 over `asyncpg`, and every schema change goes through Alembic.

Five things to internalise:

1. **`companies` is the tenant root.** Almost every table carries a `company_id`
   foreign key to it. Companies also form a tree (`companies.parent_id`) for the
   APP → PARTNER → TENANT hierarchy.
2. **`hierarchical_entities` is the single table for all agents.** An ACTION, a
   SKILL, an AGENT and a PROCESS are all rows in the same table, distinguished by
   `type`. Their entire configuration — persona, prompts, tools, planning, HITL
   rules — lives in nine JSON columns on that row.
3. **`execution_runs` is the single table for all executions**, with child runs
   pointing at parents via `parent_run_id`. Every log table (`llm_interaction_logs`,
   `tool_interaction_logs`, `usage_logs`, `execution_trace_events`,
   `human_approvals`) hangs off it.
4. **Memory lives in the CORTEX tables** (`cortex_trees` / `cortex_nodes` /
   `cortex_edges`), which are owned by a separate installed Python package
   (`cortex_memory`) with its own declarative `Base` but stored in the same
   database. `documents` / `document_chunks` and `episodic_memories` are the older
   v1 memory tables and are still read.
5. **Cost lands in two places**: a running total on `execution_runs.total_cost_usd`
   and one attributed row per chargeable event in `usage_logs`. Credits are
   deducted from `credit_wallets`.

```mermaid
graph TB
  subgraph Identity["Identity and tenancy"]
    CO["companies"]
    US["users"]
    RT["refresh_tokens"]
  end
  subgraph Brain["Agent definition and execution"]
    HE["hierarchical_entities"]
    ER["execution_runs"]
    LOGS["llm_interaction_logs - tool_interaction_logs - execution_trace_events"]
    HA["human_approvals"]
    TR["tool_registry_entries"]
  end
  subgraph Mem["Memory"]
    CT["cortex_trees"]
    CN["cortex_nodes"]
    CE["cortex_edges"]
    EM["episodic_memories"]
    DOC["documents - document_chunks"]
    STS["source_trust_scores"]
  end
  subgraph Money["Config and billing"]
    IR["integration_registry"]
    MTD["model_task_defaults"]
    UL["usage_logs"]
    CW["credit_wallets"]
    BILL["billing_config - billing_events - subscriptions - payment_transactions - subscription_tiers"]
  end
  subgraph Voice["Voice and outbound"]
    VS["voice_sessions"]
    WS["whatsapp_sessions"]
    CH["conversation_history"]
    PN["phone_numbers"]
    CMP["campaigns - campaign_calls"]
    LQ["lead_queue"]
    CL["call_logs - call_content"]
  end
  subgraph Ext["Files and external accounts"]
    ART["artifacts"]
    EC["email_connections"]
    SC["social_connections"]
  end

  CO --> US --> RT
  CO --> HE --> ER --> LOGS
  ER --> HA
  ER --> UL --> IR
  CO --> CT --> CN --> CE
  HE --> DOC
  ER --> EM
  CO --> CW
  CO --> BILL
  HE --> VS --> CH
  HE --> CMP
  CO --> PN
  CMP --> CL
  ER --> ART
  CO --> EC
  CO --> SC
  IR --> MTD
  CO --> STS
  CO --> TR
```

---

## 2. Schema conventions

| Convention | Rule | Exceptions worth knowing |
|---|---|---|
| Primary keys | `UUID(as_uuid=True)`, Python-side `default=uuid.uuid4` | `cortex_edges.id` and `feature_flags.id` were created with a `gen_random_uuid()` server default in their migrations |
| Timestamps | `created_at = DateTime, default=datetime.utcnow`; `updated_at` adds `onupdate=datetime.utcnow` | Naive `DateTime` — **no timezone**. Everything is UTC by convention, not by type. `usage_logs` calls its column `timestamp`, `conversation_history` too |
| Soft delete | Only `hierarchical_entities` has one: `deleted_at` + `status='DELETED'` | Everything else is a hard delete or never deleted |
| JSON | `JSON` (generic) on older tables, `JSONB` on newer ones | `execution_trace_events.payload`, all CORTEX JSON, all voice/campaign JSON are JSONB |
| Reserved-word dodges | SQLAlchemy reserves `metadata` on the declarative class, so models map a differently-named attribute onto a `metadata` column | `Campaign.campaign_metadata`, `CampaignCall.call_metadata`, `CortexEdge.edge_metadata` all map to a DB column literally called `metadata`. `EpisodicMemory.metadata_info`, `UsageLog.log_metadata`, `Artifact.artifact_metadata` use distinct column names |
| Money | `Numeric` with explicit scale, never float | `Numeric(10,4)` run cost, `Numeric(18,6)` usage cost, `Numeric(14,6)` billed amount |
| Declarative base | `src.common.database.Base` for host tables; `cortex_memory.db.Base` for the three CORTEX tables | Alembic's `target_metadata` is a **list** of both — see [§14](#14-migrations-with-alembic) |

Engine configuration lives in [common/database.py:18](../../backend/src/common/database.py:18):

```python
# backend/src/common/database.py
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    pool_size=20,
    max_overflow=40,     # total cap = 60 connections
    pool_timeout=60,
    pool_recycle=1800,
    pool_pre_ping=True,
)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)
```

The comment above it explains why the pool is that large: a single Deep Research run
spawns a process, agents, skills and parallel steps that each hold their own session.

---

## 3. Identity and tenancy tables

```mermaid
erDiagram
  companies ||--o{ companies : "parent_id"
  companies ||--o{ users : "employs"
  users ||--o{ refresh_tokens : "issues"
  companies ||--o{ hierarchical_entities : "owns"
  companies ||--o{ credit_wallets : "has one"
  companies ||--o{ integration_registry : "configures"
```

### 3.1 `companies`

Purpose: one row per organisation; also the tenant boundary for every scoped table.
Defined at [auth/models.py:10](../../backend/src/auth/models.py:10).

| Column | Type | Nullable | Default | Meaning |
|---|---|---|---|---|
| `id` | UUID | no | `uuid4` | PK |
| `name` | String | no | — | Display name |
| `type` | String | no | — | `APP`, `PARTNER` or `TENANT` |
| `parent_id` | UUID FK→companies.id | yes | — | Parent in the org tree; NULL for the APP root |
| `logo_url` | String | yes | — | Branding |
| `status` | String | yes | `active` | `active` or `suspended`. Login is rejected for suspended companies ([dependencies.py](../../backend/src/auth/dependencies.py)) |
| `onboarding_status` | String | yes | `pending` | `pending` / `in_progress` / `completed` |
| `onboarding_metadata` | JSONB | yes | — | Which onboarding steps were completed and their config |
| `default_daily_credits` | String | yes | — | Per-tenant override of the daily credit grant. Stored as **text**, not numeric |
| `created_at` / `updated_at` | DateTime | yes | utcnow | |

Relationships: self-referencing `parent`/`children`; one-to-many `users`. Almost every
other table points here.

### 3.2 `users`

Purpose: one login. Defined at [auth/models.py:28](../../backend/src/auth/models.py:28).

| Column | Type | Nullable | Default | Meaning |
|---|---|---|---|---|
| `id` | UUID | no | `uuid4` | PK |
| `email` | String | no | — | **Unique + indexed** (`ix_users_email`). Globally unique, not per-company |
| `full_name` | String | no | — | |
| `hashed_password` | String | no | — | bcrypt hash via `common/security.py` |
| `company_id` | UUID FK→companies.id | no | — | Tenant |
| `role` | String | yes | `tenant_user` | See [§11.3](#113-user-roles) |
| `is_active` | Boolean | yes | `True` | |
| `is_verified` | Boolean | yes | `False` | |
| `profile_picture_url` | String | yes | — | |
| `created_at` / `updated_at` | DateTime | yes | utcnow | |

### 3.3 `refresh_tokens`

Purpose: opaque refresh tokens for JWT rotation.
Defined at [auth/models.py:46](../../backend/src/auth/models.py:46).

| Column | Type | Nullable | Default | Meaning |
|---|---|---|---|---|
| `id` | UUID | no | `uuid4` | PK |
| `user_id` | UUID FK→users.id | no | — | Owner |
| `token` | String | no | — | **Unique + indexed** (`ix_refresh_tokens_token`) |
| `expires_at` | DateTime | no | — | |
| `revoked` | Boolean | yes | `False` | Logout sets this rather than deleting |
| `created_at` | DateTime | yes | utcnow | |

---

## 4. AI entity and execution tables

```mermaid
erDiagram
  hierarchical_entities ||--o{ hierarchical_entities : "parent_id"
  hierarchical_entities ||--o{ execution_runs : "runs"
  execution_runs ||--o{ execution_runs : "parent_run_id"
  execution_runs ||--o{ llm_interaction_logs : "llm calls"
  execution_runs ||--o{ tool_interaction_logs : "tool calls"
  execution_runs ||--o{ execution_trace_events : "spans"
  execution_runs ||--o{ human_approvals : "checkpoints"
  execution_runs ||--o{ usage_logs : "charges"
  users ||--o{ execution_runs : "started by"
  companies ||--o{ tool_registry_entries : "custom tools"
```

### 4.1 `hierarchical_entities`

Purpose: the definition of every agent-like thing on the platform — an ACTION, SKILL,
AGENT or PROCESS. Defined at [orm/entity.py:22](../../backend/src/ai/orm/entity.py:22).

| Column | Type | Nullable | Default | Meaning |
|---|---|---|---|---|
| `id` | UUID | no | `uuid4` | PK |
| `company_id` | UUID FK→companies.id | no | — | Tenant. NOT NULL even for templates |
| `parent_id` | UUID FK→self | yes | — | Composition parent |
| `version` | String | no | `1.0.0` | Semantic version string |
| `type` | String | no | — | `ACTION` / `SKILL` / `AGENT` / `PROCESS` |
| `status` | String | no | `ACTIVE` | `DRAFT` / `ACTIVE` / `DEPRECATED` / `ARCHIVED` / `DELETED` |
| `name` | String | no | — | Machine-ish name; plan steps can reference an entity by name |
| `display_name` | String | yes | — | UI label |
| `description` | Text | yes | — | |
| `goal` | Text | yes | — | The objective; injected into generated prompts |
| `tags` | JSON | yes | — | Array of strings. `tags[0]` is the "primary tag" used by the KPI rollup |
| `is_template` | Boolean | yes | `False` | Blueprint, not executable |
| `template_source_id` | UUID FK→self | yes | — | Which template this was cloned from |
| `created_by` | UUID FK→users.id | yes | — | |
| `identity` | JSON | yes | — | Persona. See [§5](#5-inside-the-entity-json-columns) |
| `hierarchy` | JSON | yes | — | Children + composition |
| `logic_gate` | JSON | yes | — | Model, retry, review, context policy |
| `planning` | JSON | yes | — | Static plan + dynamic planning + loop control |
| `capabilities` | JSON | yes | — | Tools, memory, context engineering, meta-cognition |
| `governance` | JSON | yes | — | Cost/time caps and HITL checkpoints |
| `io_contract` | JSON | yes | — | Input/output JSON schemas |
| `observability` | JSON | yes | — | Log level and cost-tracking toggles |
| `metadata_extensions` | JSON | yes | — | Free-form; holds per-entity feature-flag overrides and `is_meta_agent` |
| `created_at` / `updated_at` | DateTime | yes | utcnow | |
| `deleted_at` | DateTime | yes | — | Soft-delete timestamp; NULL means live |

Indexes: `ix_hierarchical_entities_is_template` on `is_template`
([m1n2o3p4q5r6](../../backend/migrations/versions/m1n2o3p4q5r6_add_goal_and_template_fields.py:52)) and
`idx_entities_not_deleted` on `(company_id, type)`
([w1x2y3z4a5b6](../../backend/migrations/versions/w1x2y3z4a5b6_add_deleted_at_to_hierarchical_entities.py:30)).

Relationships in: `execution_runs`, `documents`, `voice_sessions`, `whatsapp_sessions`,
`conversation_history`, `phone_numbers`, `campaigns`, `lead_queue`, `artifacts`,
`call_logs`, `episodic_memories`. Out: `companies`, `users` (creator), itself twice.

### 4.2 `execution_runs`

Purpose: one row per invocation of an entity, including recursive child invocations.
Defined at [orm/execution.py:38](../../backend/src/ai/orm/execution.py:38).

| Column | Type | Nullable | Default | Meaning |
|---|---|---|---|---|
| `id` | UUID | no | `uuid4` | PK |
| `entity_id` | UUID FK→hierarchical_entities.id | no | — | What ran |
| `parent_run_id` | UUID FK→self | yes | — | Set for child runs; used to exclude children from billing settlement |
| `company_id` | UUID FK→companies.id | no | — | Tenant |
| `user_id` | UUID FK→users.id | yes | — | Who triggered it |
| `status` | String | yes | `PENDING` | See [§11.2](#112-run-status-lifecycle) |
| `input_data` | JSON | yes | — | The request payload handed to the entity |
| `dynamic_plan` | JSON | yes | — | The plan the planner produced (list of plan steps); falls back to the static plan when absent |
| `result_data` | JSON | yes | — | `{"output": "...", "steps": [...]}` — written in [agent_loop.py:1119](../../backend/src/ai/core/agent_loop.py:1119) |
| `context_state` | JSON | yes | — | Carried-forward step outputs; a suspended run stores its resumable snapshot under key `__agent_state_snapshot__` |
| `error_message` | Text | yes | — | Truncated to 1000 chars |
| `total_cost_usd` | Numeric(10,4) | yes | `0` | Internal provider cost |
| `billed_amount` | Numeric(14,6) | yes | — | Result of the TB billing formula — the user-facing charge |
| `total_tokens` | Integer | yes | `0` | Rolled up across the run subtree |
| `execution_time_ms` | Integer | yes | — | |
| `trace_id` | UUID | yes | — | Opaque tracing id (no FK) |
| `span_id` | String | yes | — | |
| `idempotency_key` | String(255) | yes | — | Step-level dedup; partial index `idx_exec_runs_idemp` where NOT NULL |
| `started_at` / `completed_at` / `created_at` | DateTime | yes | — / — / utcnow | |
| `csat_score` | Integer | yes | — | `+1` thumbs up, `-1` thumbs down, NULL unrated |
| `csat_comment` | Text | yes | — | Free-text feedback |

Note there is **no index on `company_id` or `entity_id`** here — only the idempotency
partial index. Large-tenant list queries scan.

### 4.3 `llm_interaction_logs`

Purpose: one row per LLM call, with the full prompt and response.
Defined at [orm/execution.py:81](../../backend/src/ai/orm/execution.py:81).

| Column | Type | Nullable | Default | Meaning |
|---|---|---|---|---|
| `id` | UUID | no | `uuid4` | PK |
| `run_id` | UUID FK→execution_runs.id | no | — | |
| `model_provider` | String | no | — | `google`, `anthropic`, `azure_openai`, … |
| `model_name` | String | no | — | |
| `input_prompt` | Text | no | — | Full prompt text |
| `output_response` | Text | no | — | Full completion |
| `prompt_tokens` / `completion_tokens` | Integer | yes | `0` | |
| `latency_ms` | Integer | yes | — | |
| `cost_usd` | Numeric(10,6) | yes | `0` | |
| `reasoning_mode` | String | yes | — | `REACT` / `CHAIN_OF_THOUGHT` / deprecated modes |
| `step_name` | String | yes | — | Ties the call to a plan step |
| `log_metadata` | JSON | yes | — | Free-form extras |
| `created_at` | DateTime | yes | utcnow | |

No indexes beyond the PK. Queries filter on `run_id`.

### 4.4 `tool_interaction_logs`

Purpose: one row per tool invocation.
Defined at [orm/execution.py:102](../../backend/src/ai/orm/execution.py:102).

| Column | Type | Nullable | Default | Meaning |
|---|---|---|---|---|
| `id` | UUID | no | `uuid4` | PK |
| `run_id` | UUID FK→execution_runs.id | no | — | |
| `tool_id` | String | no | — | Registry id, e.g. `web_search` |
| `tool_name` | String | no | — | |
| `provider` | String | yes | — | Backing vendor |
| `input_parameters` | JSON | yes | — | Arguments as sent |
| `output_result` | JSON | yes | — | Raw tool return |
| `success` | Boolean | yes | `True` | |
| `error_message` | Text | yes | — | |
| `latency_ms` | Integer | yes | — | |
| `log_metadata` | JSON | yes | — | |
| `idempotency_key` | String(255) | yes | — | Partial index `idx_tool_logs_idemp` where NOT NULL |
| `created_at` | DateTime | yes | utcnow | |

### 4.5 `human_approvals`

Purpose: one row per HITL checkpoint that paused a run.
Defined at [orm/execution.py:122](../../backend/src/ai/orm/execution.py:122).

| Column | Type | Nullable | Default | Meaning |
|---|---|---|---|---|
| `id` | UUID | no | `uuid4` | PK |
| `run_id` | UUID FK→execution_runs.id | no | — | |
| `checkpoint_trigger` | String | no | — | One of the `HITLTriggerType` values |
| `status` | String | yes | `PENDING` | `PENDING` / `APPROVED` / `REJECTED` / `TIMEOUT` |
| `requested_by` | String | yes | — | Free text (component name), not a FK |
| `responded_by` | UUID FK→users.id | yes | — | Reviewer |
| `context_snapshot` | JSON | yes | — | What the reviewer was shown |
| `reviewer_notes` | Text | yes | — | |
| `notification_channels` | JSON | yes | — | e.g. `["email","dashboard"]` |
| `timeout_ms` | Integer | yes | — | |
| `requested_at` | DateTime | yes | utcnow | |
| `responded_at` | DateTime | yes | — | |

### 4.6 `execution_trace_events`

Purpose: append-only span tree giving per-iteration transparency into a run. Purely
observability — deliberately kept out of CORTEX memory so it can be pruned
independently. Defined at [orm/trace.py:53](../../backend/src/ai/orm/trace.py:53).

| Column | Type | Nullable | Default | Meaning |
|---|---|---|---|---|
| `id` | UUID | no | `uuid4` | PK |
| `run_id` | UUID FK→execution_runs.id ON DELETE CASCADE | no | — | |
| `company_id` | UUID | yes | — | Denormalised, **no FK** |
| `span_id` | UUID | no | — | Stable identity used by the close-update |
| `parent_span_id` | UUID | yes | — | NULL for run-root (iteration) spans |
| `iteration` | Integer | yes | — | Loop iteration number |
| `kind` | String(16) | no | — | `iteration` / `executor` / `step` / `child` / `tool` / `llm` / `critic` |
| `name` | String(512) | yes | — | Tool id, model name or step name |
| `status` | String(16) | no | `running` | `running` / `success` / `error` |
| `seq` | BigInteger | no | `0` | Monotonic order within a run |
| `started_at` | DateTime | no | utcnow | |
| `ended_at` / `duration_ms` | DateTime / Integer | yes | — | Filled by the close-update |
| `cost_usd` | Numeric(12,6) | yes | — | |
| `tokens_in` / `tokens_out` | Integer | yes | — | |
| `child_run_id` | UUID | yes | — | Links a `child` span to the sub-run |
| `payload` | JSONB | yes | — | Inputs, outputs, prompts, responses. Each field is capped at `TRACE_MAX_FIELD_BYTES` and replaced with a truncation marker |
| `error_message` | Text | yes | — | |
| `created_at` | DateTime | yes | utcnow | |

Indexes: `ix_execution_trace_events_run_seq (run_id, seq)`,
`..._run_iter (run_id, iteration)`, `..._run_parent (run_id, parent_span_id)`,
`..._span (span_id)`.

The read path is `GET /ai/executions/{id}/trace`, which returns rows ordered by `seq`;
the frontend reassembles the tree from `span_id` / `parent_span_id`.

### 4.7 `tool_registry_entries`

Purpose: persistent registry of built-in and custom tools.
Defined at [orm/tools.py:26](../../backend/src/ai/orm/tools.py:26).

| Column | Type | Nullable | Default | Meaning |
|---|---|---|---|---|
| `id` | UUID | no | `uuid4` | PK |
| `company_id` | UUID FK→companies.id | yes | — | **NULL means system-wide** |
| `name` | String | no | — | **Unique globally**, indexed (`ix_tool_registry_entries_name`) |
| `display_name` | String | yes | — | |
| `description` | Text | yes | — | |
| `category` | String | yes | — | `browser`, `social`, `document`, `utility`, … |
| `tool_type` | String | no | `BUILT_IN` | `BUILT_IN` or `CUSTOM`; indexed |
| `function_schema` | JSON | yes | — | OpenAI-compatible function-calling schema |
| `is_enabled` | Boolean | yes | `True` | |
| `configuration` | JSON | yes | — | Custom config (credential refs etc.) |
| `created_by` | UUID FK→users.id | yes | — | |
| `created_at` / `updated_at` | DateTime | yes | utcnow | |

The global uniqueness of `name` combined with a nullable `company_id` means two
tenants cannot both define a custom tool with the same name. Built-in rows are seeded
at startup and are the master data `clean_db.sql` deliberately preserves.

---

## 5. Inside the entity JSON columns

The nine JSON columns on `hierarchical_entities` are not free-form. Each one is the
serialised form of a Pydantic model in [`backend/src/ai/schemas/`](../../backend/src/ai/schemas/).
This is the single most important thing to know when debugging an agent.

```mermaid
classDiagram
  class HierarchicalEntity {
    identity : AgentPersona
    hierarchy : Hierarchy
    logic_gate : LogicGate
    planning : Planning
    capabilities : Capabilities
    governance : Governance
    io_contract : IOContract
    observability : Observability
    metadata_extensions : dict
  }
  class AgentPersona {
    role
    bio
    system_prompt
    behavioral_constraints
    few_shot_examples
    personality : PersonalityMatrix
    voice : VoiceConfig
    greeting_template
    escalation_message
    closing_message
  }
  class LogicGate {
    reasoning_config : ReasoningConfig
    retry_policy : RetryPolicy
    review_mechanism : ReviewMechanism
    context_policy : ContextPolicy
  }
  class Planning {
    static_plan : StaticPlan
    dynamic_planning : DynamicPlanning
    loop_control : LoopControl
  }
  class Capabilities {
    tools : ToolReference[]
    memory : MemoryConfig
    context_engineering : ContextEngineering
    meta_cognition : MetaCognitionConfig
  }
  class Governance {
    max_cost_usd
    timeout_ms
    max_recursion_depth
    hitl_checkpoints : HITLCheckpoint[]
  }
  HierarchicalEntity --> AgentPersona
  HierarchicalEntity --> LogicGate
  HierarchicalEntity --> Planning
  HierarchicalEntity --> Capabilities
  HierarchicalEntity --> Governance
```

| Column | Pydantic model | File | Notable inner keys |
|---|---|---|---|
| `identity` | `AgentPersona` (legacy `Persona` also accepted) | [schemas/persona.py](../../backend/src/ai/schemas/persona.py) | `role`, `system_prompt`, `behavioral_constraints[]`, `few_shot_examples[]`, `personality{tone,verbosity,empathy_level,humor_level,formality,decision_confidence}`, `voice{voice_name,language_code,speaking_rate,pitch,custom_voice_id}`, `greeting_template`, `escalation_message`, `closing_message` |
| `hierarchy` | `Hierarchy` | [schemas/entity.py:40](../../backend/src/ai/schemas/entity.py:40) | `parent_id`, `children[]{child_id,child_type,relationship,condition}`, `is_atomic`, `composition_depth` |
| `logic_gate` | `LogicGate` | [schemas/reasoning.py](../../backend/src/ai/schemas/reasoning.py) | `reasoning_config{task_type,model_provider,model_name,temperature,top_p,max_tokens,reasoning_mode,execution_mode,goal_validation_interval,confidence_threshold,max_replanning_attempts,self_reflection_enabled}`, `retry_policy{max_retries,backoff_strategy,backoff_multiplier,retry_on[]}`, `review_mechanism{enabled,review_prompt,review_system_prompt,success_criteria[],on_failure}`, `context_policy{type,n,max_chars,summarize_threshold,explicit_keys[],preserve_keys[]}` |
| `planning` | `Planning` | [schemas/planning.py](../../backend/src/ai/schemas/planning.py) | `static_plan{enabled,steps[],fallback_behavior}`, `dynamic_planning{enabled,planning_prompt,planning_system_prompt,constraints[],reconciliation_strategy,allowed_deviations{}}`, `loop_control{max_iterations,convergence_criteria[],iteration_context_mode,summary_every_n_iterations}` |
| `capabilities` | `Capabilities` | [schemas/capabilities.py](../../backend/src/ai/schemas/capabilities.py) | `tools[]{tool_id}`, `memory{enabled,mode,memory_scope,episodic_memory_count,semantic_search_enabled,semantic_top_k,cortex_config{}}`, `context_engineering{context_sources[],inject_episodic_memory,inject_semantic_context,inject_cortex_viewport,no_truncation}`, `meta_cognition{platform_awareness,registry_search,self_modification,max_runtime_creations,max_registry_searches}` |
| `governance` | `Governance` | [schemas/governance.py](../../backend/src/ai/schemas/governance.py) | `max_cost_usd`, `timeout_ms`, `max_recursion_depth`, `execution_limits{max_recursion_depth,max_tool_calls}`, `hitl_checkpoints[]{trigger_type,step_ref,tool_ref,threshold,expression,timeout_ms,notification_channels[],message,auto_approve_on_timeout}` |
| `io_contract` | `IOContract` | [schemas/io_contract.py](../../backend/src/ai/schemas/io_contract.py) | `input_schema` and `output_schema`, both JSON Schema objects defaulting to `{"type":"object","properties":{}}` |
| `observability` | `Observability` | [schemas/io_contract.py:19](../../backend/src/ai/schemas/io_contract.py:19) | `log_level`, `log_thoughts`, `track_cost` |
| `metadata_extensions` | plain `dict` | — | Known keys: `feature_flags.<key>` (tier 1 of flag resolution), `is_meta_agent` (read at [platform_schema_compiler.py:883](../../backend/src/ai/meta/platform_schema_compiler.py:883)), `max_call_duration_seconds` (read at [voice/agent_loader.py:248](../../backend/src/voice/agent_loader.py:248)) |

A plan step inside `planning.static_plan.steps[]` / `execution_runs.dynamic_plan` has
this shape ([schemas/planning.py](../../backend/src/ai/schemas/planning.py)):

```python
# backend/src/ai/schemas/planning.py
class PlanStep(BaseModel):
    step_id: Optional[str] = None
    order: int = 0
    name: str = ""
    description: Optional[str] = None
    type: StepType = StepType.ACTION
    target: Optional[PlanStepTarget] = None      # entity_id | tool_id | prompt_template
    required: bool = True
    exit_conditions: List[ExitCondition] = []
    reasoning_hint: Optional[str] = None
```

`PlanStepTarget` has a validator worth knowing: if an LLM planner emits a **name**
instead of a UUID in `entity_id`, the value is moved to `entity_name_hint` and
`entity_id` is set to `None`, so the executor can resolve it by name later.

---

## 6. Memory tables: CORTEX, episodic, documents

```mermaid
erDiagram
  cortex_trees ||--o{ cortex_nodes : "contains"
  cortex_nodes ||--o{ cortex_nodes : "parent_id"
  cortex_nodes ||--o{ cortex_edges : "source"
  cortex_nodes ||--o{ cortex_edges : "target"
  cortex_trees ||--o{ episodic_memories : "tree_id"
  documents ||--o{ document_chunks : "chunks"
  hierarchical_entities ||--o{ documents : "attached to"
  companies ||--o{ source_trust_scores : "learns"
```

### 6.1 `cortex_trees`

Purpose: one persistent cognitive tree — the agent's complete memory state for a task
or domain. The context window is just a viewport onto it.

Defined in the **installed package** at `cortex_memory/models.py:51`
(`backend/.venv/lib/python3.12/site-packages/cortex_memory/models.py`), re-exported by
[ai/memory/cortex_models.py](../../backend/src/ai/memory/cortex_models.py). Created by
[k1l2m3n4o5p6](../../backend/migrations/versions/k1l2m3n4o5p6_add_cortex_tables.py:42) and
extended by [x1y2z3a4b5c6](../../backend/migrations/versions/x1y2z3a4b5c6_add_unified_cortex_memory_v2.py:70).

| Column | Type | Nullable | Default | Meaning |
|---|---|---|---|---|
| `id` | UUID | no | `uuid4` | PK |
| `entity_id` | UUID | yes | — | Owning entity. **Opaque — the ORM declares no FK**; the original migration did create one and later made it nullable |
| `user_id` | UUID | yes | — | Opaque |
| `company_id` | UUID | no | — | Tenant. Opaque in the ORM |
| `task_description` | Text | yes | — | |
| `status` | enum `cortex_tree_status` | no | `active` | `active` / `suspended` / `complete` / `archived` |
| `total_nodes` | Integer | yes | `0` | Denormalised count |
| `root_node_id` | UUID | yes | — | Entry node |
| `output_root_id` | UUID | yes | — | Root of the output document subtree |
| `resume_cursor_id` | UUID | yes | — | Last node worked on — enables deterministic resume |
| `max_children` | Integer | yes | `12` | MAX_CHILDREN invariant |
| `page_size_tokens` | Integer | yes | `8000` | |
| `context_budget_pct` | Integer | yes | `40` | Percent of the window given to the root run |
| `resume_schedule` | String(100) | yes | — | Cron-ish schedule for scheduled resumption |
| `next_resume_at` | DateTime | yes | — | |
| `memory_domain` | enum `memory_domain` | no | `knowledge` | `knowledge` / `experience` / `intelligence` / `episodic` |
| `scope_level` | enum `scope_level` | no | `runtime` | `app` / `partner` / `tenant` / `user` / `entity` / `runtime` |
| `app_id` / `partner_id` / `run_id` | UUID | yes | — | Scope-hierarchy references. Opaque in the ORM; the v2 migration did add FKs |
| `tree_category` | String(100) | yes | — | |
| `expires_at` | DateTime | yes | — | |
| `is_persistent` | Boolean | yes | `true` | |
| `last_consolidated_at` | DateTime | yes | — | Set by the dreaming/consolidation pass |
| `consolidation_generation` | Integer | yes | `0` | |
| `source_run_ids` | JSONB | yes | — | Runs that contributed to this consolidated tree |
| `created_at` / `last_active_at` | DateTime | yes | utcnow | |

Indexes: `ix_cortex_trees_entity_id`, `..._company_id`, `..._status`,
`..._domain_scope (memory_domain, scope_level)`, `..._scope_company (scope_level, company_id)`,
plus two partial indexes created only in the migration:
`ix_cortex_trees_scope_entity` (where `entity_id IS NOT NULL`) and
`ix_cortex_trees_scope_user` (where `user_id IS NOT NULL`).

### 6.2 `cortex_nodes`

Purpose: every unit of memory — an ingested chunk, a finding, a sub-task, an output
section, a distilled rule. `cortex_memory/models.py:129`.

| Column | Type | Nullable | Default | Meaning |
|---|---|---|---|---|
| `id` | UUID | no | `uuid4` | PK |
| `tree_id` | UUID FK→cortex_trees.id ON DELETE CASCADE | no | — | |
| `parent_id` | UUID FK→self ON DELETE SET NULL | yes | — | |
| `node_type` | enum `cortex_node_type` | no | — | 21 values — see [§11.6](#116-cortex-node-types) |
| `title` | String(500) | no | — | |
| `summary` | Text | yes | — | Preferred text for embedding |
| `content` | Text | yes | — | Full body |
| `content_tokens` | Integer | yes | `0` | |
| `status` | enum `cortex_node_status` | no | `pending` | `pending` / `active` / `complete` / `summarised` |
| `source_ref` | JSONB | yes | — | Provenance: where this came from |
| `execution_run_id` | UUID | yes | — | Opaque run reference |
| `depth` / `sibling_order` | Integer | yes | `0` | Tree position |
| `created_at` / `updated_at` | DateTime | yes | utcnow | |
| `metadata_extra` | JSONB | yes | — | |
| `embedding` | `vector(768)` | yes | — | pgvector column |
| `embedding_model` | String(100) | yes | — | Which model produced the vector |
| `cross_refs` | JSONB | yes | — | Non-edge cross references |
| `access_count` | Integer | yes | `0` | Incremented on retrieval |
| `last_accessed_at` | DateTime | yes | — | |
| `importance_score` | Numeric(5,3) | yes | `0.500` | Used for pruning/ranking |

Indexes: `ix_cortex_nodes_tree_id`, `..._parent_id`, `..._tree_parent`, `..._tree_type`,
`..._status`, `..._tree_type_status`, plus migration-only
`ix_cortex_nodes_importance (importance_score DESC)`, `ix_cortex_nodes_created_at`, and
the HNSW vector index `ix_cortex_nodes_embedding`.

### 6.3 `cortex_edges`

Purpose: the semantic graph layer — weighted, typed links between nodes.
`cortex_memory/models.py:201`.

| Column | Type | Nullable | Default | Meaning |
|---|---|---|---|---|
| `id` | UUID | no | `uuid4` (server `gen_random_uuid()`) | PK |
| `source_node_id` | UUID FK→cortex_nodes.id CASCADE | no | — | |
| `target_node_id` | UUID FK→cortex_nodes.id CASCADE | no | — | |
| `edge_type` | String(50) | no | — | Free-form relation label |
| `weight` | Numeric(5,4) | yes | `0.5000` | |
| `traversal_count` | Integer | yes | `0` | |
| `last_traversed_at` | DateTime | yes | — | |
| `created_by` | String(50) | yes | — | Which subsystem created the edge |
| `metadata` (attr `edge_metadata`) | JSONB | yes | — | |
| `created_at` | DateTime | yes | utcnow | |

Unique constraint `uq_cortex_edges_src_tgt_type (source_node_id, target_node_id, edge_type)`.
Indexes on source, target, and `(edge_type, weight DESC)`.

### 6.4 `episodic_memories`

Purpose: **legacy v1** short-term memory — one row per completed top-level run.
Defined at [orm/memory.py:22](../../backend/src/ai/orm/memory.py:22). New writes go to
Episodic CORTEX trees instead; this table is still read by
[legacy_episodic_reader.py](../../backend/src/ai/memory/legacy_episodic_reader.py).

| Column | Type | Nullable | Default | Meaning |
|---|---|---|---|---|
| `id` | UUID | no | `uuid4` | PK |
| `entity_id` | UUID FK→hierarchical_entities.id | no | — | |
| `company_id` | UUID FK→companies.id | no | — | |
| `user_id` | UUID FK→users.id | yes | — | |
| `run_id` | UUID FK→execution_runs.id | yes | — | |
| `input_summary` / `output_summary` | Text | yes | — | |
| `status` | String(50) | yes | — | Mirror of the run status |
| `total_cost_usd` | **String(20)** | yes | — | Stored as text, not numeric — a known wart |
| `total_tokens` / `execution_time_ms` | Integer | yes | — | |
| `metadata_info` | JSON | yes | — | Named to avoid the reserved `metadata` |
| `channel` | String(50) | yes | — | `api`, `voice`, … |
| `tree_id` | UUID FK→cortex_trees.id ON DELETE SET NULL | yes | — | Link to the replacement CORTEX tree |
| `created_at` | DateTime | yes | utcnow | |

### 6.5 `documents`

Purpose: an uploaded file that has been chunked for retrieval.
Defined at [orm/document.py:23](../../backend/src/ai/orm/document.py:23).

| Column | Type | Nullable | Default | Meaning |
|---|---|---|---|---|
| `id` | UUID | no | `uuid4` | PK |
| `company_id` | UUID FK→companies.id | no | — | |
| `entity_id` | UUID FK→hierarchical_entities.id | yes | — | Owning agent; nulled out when the entity is soft-deleted |
| `filename` | String | no | — | |
| `file_type` | String | no | — | `pdf`, `docx`, `txt` |
| `file_size` | **String** | yes | — | Text, not integer |
| `upload_status` | String | yes | `processing` | `processing` / `completed` / `failed` |
| `created_at` / `updated_at` | DateTime | yes | utcnow | |

Relationship out: `chunks` with `cascade="all, delete-orphan"` — deleting a document
deletes its chunks.

### 6.6 `document_chunks`

Purpose: one embedded text chunk of a document.
Defined at [orm/document.py:41](../../backend/src/ai/orm/document.py:41).

| Column | Type | Nullable | Default | Meaning |
|---|---|---|---|---|
| `id` | UUID | no | `uuid4` | PK |
| `document_id` | UUID FK→documents.id | no | — | |
| `chunk_index` | **String** | no | — | Position in the document, stored as text |
| `content` | Text | no | — | |
| `embedding` | `vector(768)` | yes | — | Gemini/Vertex embedding |
| `created_at` | DateTime | yes | utcnow | |

**There is no vector index on this column.** Compare with `cortex_nodes`, which gets an
HNSW index. Document similarity search is a sequential scan.

### 6.7 `source_trust_scores`

Purpose: learned, per-tenant trust in a knowledge source. The static prior lives in the
CORTEX package; this table records how that prior moved based on outcomes.
Defined at [orm/trust.py:30](../../backend/src/ai/orm/trust.py:30).

| Column | Type | Nullable | Default | Meaning |
|---|---|---|---|---|
| `id` | UUID | no | `uuid4` | PK |
| `company_id` | UUID FK→companies.id | no | — | |
| `source_key` | String(255) | no | — | e.g. `tool:web_search`, `external_link:example.com` |
| `observations` | Integer | no | `0` | Number of outcomes seen |
| `successes` | Float | no | `0.0` | Accumulated positive weight (fractional allowed) |
| `prior` | Float | no | `0.5` | Static per-source-type prior at first observation |
| `learned_trust` | Float | no | `0.5` | Smoothed estimate blended with the prior |
| `updated_at` | DateTime | no | utcnow | |

Constraints: `uq_source_trust_company_key (company_id, source_key)` and index
`ix_source_trust_company`.

---

## 7. Configuration and billing tables

```mermaid
erDiagram
  companies ||--o{ integration_registry : "SKUs and keys"
  integration_registry ||--o{ model_task_defaults : "routes to"
  integration_registry ||--o{ usage_logs : "priced by"
  execution_runs ||--o{ usage_logs : "charges"
  companies ||--|| credit_wallets : "one wallet"
  companies ||--o{ subscriptions : "plan"
  companies ||--o{ payment_transactions : "payments"
  companies ||--o{ billing_events : "monthly rollup"
  companies ||--o{ billing_config : "formula override"
```

### 7.1 `integration_registry`

Purpose: the master price + credential list. Every purchasable unit — an LLM input
token SKU, a telephony minute, a tool call, even the Razorpay and SMTP credentials —
is a row here. Defined at [config/models.py:27](../../backend/src/config/models.py:27).

| Column | Type | Nullable | Default | Meaning |
|---|---|---|---|---|
| `id` | UUID | no | `uuid4` | PK |
| `company_id` | UUID FK→companies.id | no | — | Owner. Cost-bearing SKUs are owned by the **APP** company and inherited by tenants |
| `provider_name` | String | no | — | `google`, `anthropic`, `azure_openai`, … |
| `model_name` | String | yes | — | `gemini-2.5-flash`, `claude-sonnet-4-5`, … |
| `service_sku` | String | no | — | The billing key, e.g. `gemini-2.5-flash-in`, `razorpay_keys`, `smtp-system`, `sandbox-runtime` |
| `service_category` | String | no | `LLM` | `LLM`, `LLM_LIVE`, `IMAGE_GEN`, `AUDIO_GEN`, `VIDEO_GEN`, `3D_GEN`, `API_TOOL`, `COMMUNICATION`, plus `EMBEDDING` and `CUSTOM_API` used in code |
| `component_type` | String | no | — | `input_token`, `output_token`, `analysis`, `minute`, `character`, `flat_fee`, `image`, `video_second` |
| `encrypted_api_key` | Text | yes | — | AES-256-GCM ciphertext via `common/security.py` |
| `internal_cost` | Numeric(18,6) | no | — | Provider cost per `cost_unit` |
| `cost_unit` | String | no | — | Drives the divisor: strings containing `1m token`/`million` → 1e6, `1k token` or `1000 char` → 1e3, otherwise 1 ([usage_service.py:91](../../backend/src/ai/usage_service.py:91)) |
| `service_metadata` | JSON | yes | — | Provider-specific. Vertex: `{"project_id","region"}`. AI Studio: `{"use_ai_studio": true}`. Azure: `{"azure_endpoint","api_version","deployment_name"}` |
| `status` | String | yes | `active` | Only `active` rows are used for pricing |
| `created_at` / `updated_at` | DateTime | yes | utcnow | |

Unique constraint `uq_integration_company_sku (company_id, service_sku)`.

### 7.2 `model_task_defaults`

Purpose: maps an AI task type to the integration that should serve it, per company.
Defined at [config/models.py:67](../../backend/src/config/models.py:67).

| Column | Type | Nullable | Default | Meaning |
|---|---|---|---|---|
| `id` | UUID | no | `uuid4` | PK |
| `company_id` | UUID FK→companies.id | no | — | Indexed |
| `task_type` | String(50) | no | — | One of `TASK_TYPES` ([config/models.py:11](../../backend/src/config/models.py:11)); code also uses `embedding` |
| `integration_id` | UUID FK→integration_registry.id | no | — | Which model |
| `routing_mode` | String(20) | no | `single` | `single` (use this model) or `router` (let the LLM router decide) |
| `is_default` | Boolean | no | `True` | |
| `created_at` / `updated_at` | DateTime | yes | utcnow | |

Unique constraint `uq_task_defaults_company_task (company_id, task_type)`; indexes on
`company_id` and `task_type`.

### 7.3 `usage_logs`

Purpose: the billing ledger. One row per chargeable event, tagged with what part of the
system caused it. Defined at [orm/usage.py:24](../../backend/src/ai/orm/usage.py:24).

| Column | Type | Nullable | Default | Meaning |
|---|---|---|---|---|
| `id` | UUID | no | `uuid4` | PK |
| `timestamp` | DateTime | yes | utcnow | Event time |
| `company_id` | UUID FK→companies.id | no | — | Tenant being charged |
| `run_id` | UUID FK→execution_runs.id | yes | — | NULL for non-run charges (cron, voice) |
| `sku_id` | UUID FK→integration_registry.id | no | — | What was consumed |
| `raw_quantity` | Numeric(18,6) | no | — | Tokens, seconds, characters, calls |
| `calculated_cost` | Numeric(18,6) | no | — | `internal_cost * raw_quantity / divisor` |
| `log_metadata` | JSON | yes | — | Free-form context, e.g. `embedding_phase: ingestion\|retrieval` |
| `attribution` | String(40) | no | server `tool` | Closed enum — see [§11.7](#117-cost-attribution-tags) |

Index `ix_usage_logs_attribution`.

### 7.4 `billing_config`

Purpose: the tunable parameters of the TB (total billing) formula
`TB = (c*mf) + (c*mf*pf) + (c*mf*spf) - (c*mf*d)`.
Defined at [billing_models.py:21](../../backend/src/billing/billing_models.py:21).

| Column | Type | Nullable | Default | Meaning |
|---|---|---|---|---|
| `id` | UUID | no | `uuid4` | PK |
| `company_id` | UUID FK→companies.id | yes | — | **NULL = global default**; a company row overrides it |
| `config_name` | String(100) | no | `default` | |
| `multiplier_factor` | Numeric(10,4) | no | `1.0` | `mf` |
| `platform_fee_pct` | Numeric(10,4) | no | `0.0` | `pf` (0.15 = 15%) |
| `sales_partner_fee_pct` | Numeric(10,4) | no | `0.0` | `spf` |
| `discount_pct` | Numeric(10,4) | no | `0.0` | `d` |
| `default_daily_credits` | Numeric(10,4) | no | `0` | Daily grant injected into wallets |
| `base_cost_telephony` / `base_cost_llm` / `base_cost_image_gen` | Numeric(14,6) | yes | — | Optional base-cost overrides |
| `is_active` | Boolean | no | `True` | |
| `created_at` / `updated_at` | DateTime | no | utcnow | |

### 7.5 `credit_wallets`

Purpose: one wallet per company, holding three credit buckets consumed in priority
order. Defined at [billing_models.py:51](../../backend/src/billing/billing_models.py:51).

| Column | Type | Nullable | Default | Meaning |
|---|---|---|---|---|
| `id` | UUID | no | `uuid4` | PK |
| `company_id` | UUID FK→companies.id | no | — | **UNIQUE** — one wallet per company |
| `account_model` | String(30) | no | `pay_as_you_go` | `pay_as_you_go` or `subscription` |
| `daily_credits` | Numeric(10,4) | no | `0` | Free daily grant; expires and is re-injected |
| `daily_expires_at` | DateTime | yes | — | |
| `wallet_balance` | Numeric(12,4) | no | `0.0` | PAYG top-ups, 365-day validity |
| `wallet_expires_at` | DateTime | yes | — | |
| `subscription_credits` | Numeric(12,4) | no | `0.0` | Monthly allocation, no carry-forward |
| `subscription_bonus_credits` | Numeric(12,4) | no | `0.0` | Tier bonus |
| `sub_credits_expire_at` | DateTime | yes | — | |
| `updated_at` | DateTime | no | utcnow | |

Deduction order is implemented in [credit_service.py:120](../../backend/src/billing/credit_service.py:120):
daily → then `wallet_balance` (PAYG) **or** `subscription_credits` then
`subscription_bonus_credits` (subscription). Expired buckets are zeroed first.

```mermaid
flowchart LR
  A["deduct amount"] --> B{"daily expired?"}
  B -- yes --> C["flush and re-inject daily"]
  B -- no --> D
  C --> D{"daily > 0?"}
  D -- yes --> E["take from daily"]
  D -- no --> F
  E --> F{"account_model"}
  F -- pay_as_you_go --> G["take from wallet_balance"]
  F -- subscription --> H["take from subscription_credits"]
  H --> I["then subscription_bonus_credits"]
  G --> J["commit"]
  I --> J
```

### 7.6 `subscription_tiers`

Purpose: app-admin-configured plans. **Global — no `company_id`.**
Defined at [billing_models.py:85](../../backend/src/billing/billing_models.py:85).

| Column | Type | Nullable | Default | Meaning |
|---|---|---|---|---|
| `id` | UUID | no | `uuid4` | PK |
| `name` | String(50) | no | — | |
| `tier_level` | Integer | no | — | **Unique** |
| `monthly_fee` | Numeric(10,2) | no | — | |
| `bonus_pct` | Numeric(5,2) | no | `0.0` | Extra credits granted |
| `is_active` | Boolean | no | `True` | |
| `created_at` / `updated_at` | DateTime | no | utcnow | |

Master data — preserved by `clean_db.sql`.

### 7.7 `subscriptions`

Purpose: an active plan with a Razorpay mandate.
Defined at [billing_models.py:103](../../backend/src/billing/billing_models.py:103).

| Column | Type | Nullable | Default | Meaning |
|---|---|---|---|---|
| `id` | UUID | no | `uuid4` | PK |
| `company_id` | UUID FK→companies.id | no | — | |
| `plan_tier` | Integer | no | `1` | 1, 2 or 3 |
| `monthly_fee` | Numeric(10,2) | no | — | |
| `bonus_pct` | Numeric(5,2) | no | `20.0` | Tier 1=20, 2=30, 3=40 |
| `status` | String(20) | no | `active` | `active` / `cancelled` / `past_due` |
| `razorpay_subscription_id` / `razorpay_plan_id` | String(200) | yes | — | |
| `next_billing_date` | DateTime | yes | — | |
| `cancelled_at` | DateTime | yes | — | |
| `created_at` / `updated_at` | DateTime | no | utcnow | |

### 7.8 `payment_transactions`

Purpose: every Razorpay payment.
Defined at [billing_models.py:127](../../backend/src/billing/billing_models.py:127).

| Column | Type | Nullable | Default | Meaning |
|---|---|---|---|---|
| `id` | UUID | no | `uuid4` | PK |
| `company_id` | UUID FK→companies.id | no | — | |
| `razorpay_order_id` / `razorpay_payment_id` | String(200) | yes | — | |
| `razorpay_signature` | String(500) | yes | — | HMAC used for verification |
| `amount` | Numeric(10,2) | no | — | |
| `currency` | String(10) | no | `USD` | |
| `transaction_type` | String(30) | no | — | `topup` or `subscription_charge` |
| `status` | String(20) | no | `pending` | `pending` / `success` / `failed` |
| `credits_awarded` | Numeric(12,4) | yes | — | |
| `transaction_metadata` | JSON | yes | — | |
| `created_at` / `updated_at` | DateTime | no | utcnow | |

The `wallet` relationship is a **viewonly** join on `company_id` — there is no FK
between these two tables.

### 7.9 `billing_events`

Purpose: monthly aggregated billing rows for reporting.
Defined at [billing_models.py:158](../../backend/src/billing/billing_models.py:158).

| Column | Type | Nullable | Default | Meaning |
|---|---|---|---|---|
| `id` | UUID | no | `uuid4` | PK |
| `company_id` | UUID FK→companies.id | no | — | |
| `period_month` | Date | no | — | 1st of the month |
| `grouping_type` | String(30) | yes | — | `partner` / `tenant` / `user` / `process` / `agent` |
| `grouping_value` | String(500) | yes | — | ID or name of the group |
| `base_cost`, `multiplied_cost`, `platform_fee_amount`, `partner_fee_amount`, `discount_amount`, `total_billing` | Numeric(14,6) | no | `0` | TB formula breakdown |
| `telephony_charge`, `llm_charge`, `image_charge`, `video_charge`, `api_charge` | Numeric(14,6) | no | `0` | User-facing category split |
| `telephony_in_minutes`, `telephony_out_minutes` | Numeric(10,2) | no | `0` | |
| `image_gen_count`, `video_gen_count` | Integer | no | `0` | |
| `other_ai_cost` | Numeric(14,6) | no | `0` | |
| `created_at` / `updated_at` | DateTime | no | utcnow | |

---

## 8. Voice, telephony and campaign tables

```mermaid
erDiagram
  companies ||--o{ voice_sessions : "calls"
  hierarchical_entities ||--o{ voice_sessions : "agent"
  voice_sessions ||--o{ campaign_calls : "one per call"
  campaigns ||--o{ campaign_calls : "contains"
  companies ||--o{ whatsapp_sessions : "chats"
  companies ||--o{ conversation_history : "turns"
  companies ||--o{ phone_numbers : "owns"
  companies ||--o{ lead_queue : "CRM leads"
  voice_sessions ||--o{ lead_queue : "resulting call"
  call_logs ||--|| call_content : "transcript"
```

### 8.1 `voice_sessions`

Purpose: one live or completed voice call.
Defined at [voice/models.py:18](../../backend/src/voice/models.py:18).

| Column | Type | Nullable | Default | Meaning |
|---|---|---|---|---|
| `id` | UUID | no | `uuid4` | PK |
| `company_id` | UUID FK→companies.id | no | — | |
| `customer_id` | UUID | no | — | Opaque customer identifier, **no FK** |
| `agent_id` | UUID FK→hierarchical_entities.id | no | — | |
| `phone_number` | String(20) | no | — | |
| `provider` | String(20) | no | — | `twilio` or `tata_tele` |
| `call_sid` | String(100) | no | — | **Unique** provider call id |
| `stream_sid` | String(100) | yes | — | Media-stream id |
| `direction` | String(20) | yes | — | `inbound` / `outbound` |
| `status` | String(20) | no | `initiated` | `initiated` → `active` → `ended` |
| `started_at` | DateTime | no | utcnow | |
| `ended_at` | DateTime | yes | — | |
| `duration_seconds` | Integer | yes | — | |
| `total_cost_usd` | Numeric(10,4) | no | `0` | |
| `context_state` | JSONB | yes | — | Conversation context carried across turns |
| `conversation_log` | JSONB | yes | — | Full transcript blob |
| `session_metadata` | JSONB | yes | — | |
| `created_at` | DateTime | no | utcnow | |

Indexes on `customer_id`, `agent_id`, `call_sid`, `status`, `company_id`.

### 8.2 `whatsapp_sessions`

Purpose: a WhatsApp conversation within the 24-hour messaging window.
Defined at [voice/models.py:54](../../backend/src/voice/models.py:54).

| Column | Type | Nullable | Default | Meaning |
|---|---|---|---|---|
| `id` | UUID | no | `uuid4` | PK |
| `company_id` | UUID FK→companies.id | no | — | |
| `customer_id` | UUID | no | — | No FK |
| `agent_id` | UUID FK→hierarchical_entities.id | no | — | |
| `phone_number` | String(20) | no | — | |
| `provider` | String(20) | no | — | `twilio` / `tata_tele` |
| `conversation_id` | String(100) | no | — | **Unique** |
| `status` | String(20) | no | `active` | |
| `session_window_expires` | DateTime | yes | — | The 24-hour window deadline |
| `started_at` | DateTime | no | utcnow | |
| `last_message_at` | DateTime | yes | — | |
| `message_count` | Integer | no | `0` | |
| `total_cost_usd` | Numeric(10,4) | no | `0` | |
| `conversation_log` / `session_metadata` | JSONB | yes | — | |
| `created_at` | DateTime | no | utcnow | |

### 8.3 `conversation_history`

Purpose: one row per conversational turn, unified across voice and WhatsApp.
Defined at [voice/models.py:87](../../backend/src/voice/models.py:87).

| Column | Type | Nullable | Default | Meaning |
|---|---|---|---|---|
| `id` | UUID | no | `uuid4` | PK |
| `company_id` | UUID FK→companies.id | no | — | |
| `customer_id` | UUID | no | — | |
| `agent_id` | UUID FK→hierarchical_entities.id | no | — | |
| `session_id` | UUID | yes | — | Points at `voice_sessions.id` **or** `whatsapp_sessions.id`; polymorphic, so no FK |
| `channel` | String(20) | no | — | `voice` / `whatsapp` |
| `turn_number` | Integer | no | — | |
| `speaker` | String(20) | no | — | `customer` / `agent` |
| `message_type` | String(20) | yes | — | `text` / `audio` / `image` |
| `content` | Text | yes | — | |
| `audio_duration_ms` | Integer | yes | — | |
| `timestamp` | DateTime | no | utcnow | |
| `message_metadata` | JSONB | yes | — | |

Indexes: `idx_conversation_customer_agent (customer_id, agent_id, timestamp)`,
`idx_conversation_session`, `idx_conversation_company`.

### 8.4 `phone_numbers`

Purpose: the unified phone-number inventory: provider stock, tenant ownership and
agent assignment in one table.
Defined at [voice/phone_pool_models.py:26](../../backend/src/voice/phone_pool_models.py:26).

| Column | Type | Nullable | Default | Meaning |
|---|---|---|---|---|
| `id` | UUID | no | `uuid4` | PK |
| `phone_number` | String(20) | no | — | **Unique** |
| `provider` | String(20) | no | — | `twilio` / `tata_tele` |
| `country_code` | String(5) | no | `+91` | |
| `status` | String(20) | no | `available` | `available` → `claimed` → `assigned` → `retired` |
| `company_id` | UUID FK→companies.id | yes | — | Set when claimed |
| `claimed_by_user_id` | UUID FK→users.id | yes | — | |
| `claimed_at` | DateTime | yes | — | |
| `agent_id` | UUID FK→hierarchical_entities.id | yes | — | Set when assigned; calls route to this agent |
| `customer_id` | UUID | yes | — | |
| `customer_name` | String(255) | yes | — | |
| `customer_metadata` | JSONB | yes | — | |
| `assigned_at` | DateTime | yes | — | |
| `provider_sid` | String(100) | yes | — | From provider sync |
| `capabilities` | JSONB | yes | — | `{"voice": true, "sms": false}` |
| `monthly_cost_usd` | Numeric(10,4) | yes | — | |
| `label` / `notes` | String | yes | — | |
| `added_by_user_id` | UUID FK→users.id | yes | — | |
| `is_active` | Boolean | no | `True` | |
| `created_at` / `updated_at` | DateTime | yes | utcnow | |

Six indexes: phone, status, company, agent, customer, provider.

**This table has no Alembic migration.** It is created by the standalone script
[migrations/merge_phone_tables.py:49](../../backend/migrations/merge_phone_tables.py:49),
which merges the legacy `phone_number_pool` and `customer_phone_numbers` tables. On a
brand-new database built purely from `alembic upgrade head`, `phone_numbers` will be
missing.

### 8.5 `campaigns`

Purpose: a bulk outbound calling campaign.
Defined at [campaign_models.py:52](../../backend/src/ai/campaign_models.py:52).

| Column | Type | Nullable | Default | Meaning |
|---|---|---|---|---|
| `id` | UUID | no | `uuid4` | PK |
| `company_id` | UUID FK→companies.id | no | — | |
| `created_by` | UUID FK→users.id | no | — | |
| `agent_id` | UUID FK→hierarchical_entities.id | no | — | Which agent makes the calls |
| `name` | String(255) | no | — | |
| `description` | Text | yes | — | |
| `total_contacts` | Integer | no | `0` | |
| `contact_list` | JSONB | no | — | Array of contact objects |
| `provider` | String(20) | no | `twilio` | |
| `call_script_template` | Text | yes | — | |
| `scheduled_start` / `scheduled_end` | DateTime | yes | — | |
| `max_concurrent_calls` | Integer | no | `5` | |
| `max_calls_per_hour` | Integer | yes | — | |
| `status` | String(20) | no | `draft` | See [§11.4](#114-campaign-status-lifecycle) |
| `started_at` / `completed_at` | DateTime | yes | — | |
| `calls_initiated` / `calls_completed` / `calls_failed` | Integer | no | `0` | Counters updated by webhooks |
| `outcome_distribution` | JSONB | yes | — | `{"success": 10, "no_answer": 5, ...}` |
| `metadata` (attr `campaign_metadata`) | JSONB | yes | — | |
| `created_at` / `updated_at` | DateTime | no | utcnow | |

Indexes on `company_id`, `agent_id`, `status`, `created_by`.

### 8.6 `campaign_calls`

Purpose: one contact attempt within a campaign.
Defined at [campaign_models.py:105](../../backend/src/ai/campaign_models.py:105).

| Column | Type | Nullable | Default | Meaning |
|---|---|---|---|---|
| `id` | UUID | no | `uuid4` | PK |
| `campaign_id` | UUID FK→campaigns.id | no | — | |
| `voice_session_id` | UUID FK→voice_sessions.id | yes | — | |
| `contact_data` | JSONB | no | — | Phone, name, custom fields |
| `status` | String(20) | no | `pending` | `pending` / `calling` / `completed` / `completed-voicemail` / `failed` / `skipped` |
| `call_sid` | String(100) | yes | — | |
| `outcome` | String(50) | yes | — | `success` / `no_answer` / `busy` / `failed` / `refused` / `voicemail` |
| `outcome_notes` | Text | yes | — | |
| `disposition` | String(30) | yes | — | LLM-classified: `interested`, `not_interested`, `voicemail`, `rejected`, `busy`, `no_answer`, `failed`. Indexed |
| `disposition_reason` | String(30) | yes | — | Only when `not_interested`: `budget_low`, `not_suitable`, `not_investing`, `already_bought`, `other` |
| `scheduled_at` / `called_at` / `completed_at` | DateTime | yes | — | |
| `duration_seconds` | Integer | yes | — | |
| `retry_count` | Integer | no | `0` | |
| `max_retries` | Integer | no | `2` | |
| `metadata` (attr `call_metadata`) | JSONB | yes | — | |
| `created_at` | DateTime | no | utcnow | |

Report ordering uses a SQL `CASE` built from `DISPOSITION_PRIORITY`
([campaign_models.py:17](../../backend/src/ai/campaign_models.py:17)) — positive
responses first, in-flight calls last.

### 8.7 `lead_queue`

Purpose: a durable queue of CRM leads awaiting an outbound call.
Defined at [lead_queue_model.py:22](../../backend/src/ai/lead_queue_model.py:22).

| Column | Type | Nullable | Default | Meaning |
|---|---|---|---|---|
| `id` | UUID | no | `uuid4` | PK |
| `company_id` | UUID FK→companies.id | no | — | |
| `agent_id` | UUID FK→hierarchical_entities.id | no | — | |
| `lead_id` | String(255) | no | — | The CRM's external id |
| `phone` | String(20) | no | — | |
| `lead_data` | JSONB | no | — | Full CRM webhook payload |
| `ad_source` | String(100) | yes | — | `google_ads`, `facebook`, `instagram` |
| `project_id` | String(100) | yes | — | Tenant's project identifier |
| `status` | String(20) | no | `pending` | `pending` → `queued` → `calling` → `completed` / `failed` |
| `priority` | Integer | no | `5` | 1 = highest, 10 = lowest |
| `attempt_count` | Integer | no | `0` | |
| `max_attempts` | Integer | no | `3` | |
| `last_error` | Text | yes | — | |
| `correlation_id` | String(100) | yes | — | |
| `voice_session_id` | UUID FK→voice_sessions.id | yes | — | |
| `call_outcome` | JSONB | yes | — | `{"outcome","summary","next_action","lead_temperature","duration_seconds"}` |
| `created_at` / `updated_at` / `processed_at` | DateTime | no / no / yes | utcnow | |

Constraints: `uq_lead_queue_company_lead (company_id, lead_id)` deduplicates CRM
re-posts. Partial index `idx_lead_queue_pending` on
`(company_id, status, priority, created_at) WHERE status = 'pending'` is what makes the
worker's "pick the next lead" query fast.

### 8.8 `call_logs`

Purpose: telephony call metadata for reporting, independent of the streaming session.
Defined at [artifact_models.py:75](../../backend/src/ai/artifact_models.py:75).

| Column | Type | Nullable | Default | Meaning |
|---|---|---|---|---|
| `id` | UUID | no | `uuid4` | PK |
| `company_id` | UUID FK→companies.id | no | — | |
| `voice_session_id` | UUID | yes | — | References `voice_sessions.id` but **deliberately has no FK** (different module) |
| `agent_id` | UUID FK→hierarchical_entities.id | yes | — | |
| `direction` | String(20) | yes | — | `inbound` / `outbound` |
| `status` | String(30) | yes | — | `completed` / `failed` / `no-answer` |
| `duration_seconds` | Integer | yes | — | |
| `from_number` / `to_number` | String(30) | yes | — | |
| `provider` | String(30) | yes | — | |
| `call_cost_usd` | Numeric(10,6) | yes | — | |
| `created_at` | DateTime | no | utcnow | |

### 8.9 `call_content`

Purpose: transcript, summary and sentiment for a call, plus a link to the recording.
Defined at [artifact_models.py:102](../../backend/src/ai/artifact_models.py:102).

| Column | Type | Nullable | Default | Meaning |
|---|---|---|---|---|
| `id` | UUID | no | `uuid4` | PK |
| `call_log_id` | UUID FK→call_logs.id | no | — | One-to-one with the call |
| `audio_artifact_id` | UUID FK→artifacts.id | yes | — | The recording file |
| `transcript_text` | Text | yes | — | |
| `summary_text` | Text | yes | — | |
| `sentiment` | String(20) | yes | — | `positive` / `neutral` / `negative` |
| `content_metadata` | JSON | yes | — | |
| `created_at` | DateTime | no | utcnow | |

---

## 9. Artifacts and external integration tables

```mermaid
erDiagram
  companies ||--o{ artifacts : "files"
  execution_runs ||--o{ artifacts : "produced"
  hierarchical_entities ||--o{ artifacts : "agent or campaign"
  artifacts ||--o{ call_content : "audio"
  companies ||--o{ email_connections : "mailboxes"
  companies ||--o{ social_connections : "OAuth accounts"
```

### 9.1 `artifacts`

Purpose: every file the platform stores, uploaded or generated. Files live on disk under
`artificate/{origin}/{company_id}/{YYYY-MM-DD}/{file_name}`; this table is the index.
Defined at [artifact_models.py:34](../../backend/src/ai/artifact_models.py:34).

| Column | Type | Nullable | Default | Meaning |
|---|---|---|---|---|
| `id` | UUID | no | `uuid4` | PK |
| `company_id` | UUID FK→companies.id | no | — | |
| `campaign_id` | UUID FK→hierarchical_entities.id | yes | — | Note: points at an **entity**, not the `campaigns` table |
| `agent_id` | UUID FK→hierarchical_entities.id | yes | — | |
| `run_id` | UUID FK→execution_runs.id | yes | — | |
| `origin` | String(30) | no | — | `user-uploads` or `system-generated` |
| `file_category` | String(50) | no | — | `recordings` / `images` / `videos` / `documents` / `text` |
| `file_name` | String(500) | no | — | |
| `file_path` | Text | no | — | Absolute path on disk |
| `file_size` | BigInteger | yes | — | Bytes |
| `duration_seconds` | Integer | yes | — | Audio/video |
| `mime_type` | String(100) | yes | — | |
| `purpose` | Text | yes | — | Human-readable reason |
| `generated_by` | String(200) | yes | — | Tool/agent name, e.g. `image_generation` |
| `artifact_metadata` | JSON | yes | — | Dimensions, call SID, model used, … |
| `created_at` | DateTime | no | utcnow | |

Indexes: company, campaign, agent, origin, file_category, created_at.

### 9.2 `email_connections`

Purpose: an IMAP/SMTP mailbox an agent can read and send from.
Defined at [email_models.py:21](../../backend/src/ai/email_models.py:21).

| Column | Type | Nullable | Default | Meaning |
|---|---|---|---|---|
| `id` | UUID | no | `uuid4` | PK |
| `company_id` | UUID FK→companies.id | no | — | |
| `email_address` | String | no | — | |
| `encrypted_app_password` | Text | no | — | AES-256-GCM ciphertext |
| `imap_host` / `imap_port` | String / Integer | no | `imap.gmail.com` / `993` | |
| `smtp_host` / `smtp_port` | String / Integer | no | `smtp.gmail.com` / `587` | |
| `provider_type` | String | no | `gmail` | `gmail` / `outlook` / `custom` |
| `folder_prefix` | String | yes | — | e.g. `[Gmail]/` |
| `is_active` | Boolean | no | `True` | |
| `last_connected_at` | DateTime | yes | — | |
| `status` | String | no | `active` | `active` / `auth_failed` / `disconnected` |
| `created_at` / `updated_at` | DateTime | yes | utcnow | |

### 9.3 `social_connections`

Purpose: OAuth 2.0 tokens for social platforms.
Defined at [social_models.py:25](../../backend/src/ai/social_models.py:25).

| Column | Type | Nullable | Default | Meaning |
|---|---|---|---|---|
| `id` | UUID | no | `uuid4` | PK |
| `company_id` | UUID FK→companies.id | no | — | |
| `platform` | String(50) | no | — | `linkedin`, `twitter`, `facebook`, `instagram`, `google_ads`, … |
| `account_name` | String(255) | yes | — | Human label |
| `encrypted_access_token` | Text | no | — | |
| `encrypted_refresh_token` | Text | yes | — | Some platforms do not issue one |
| `token_expires_at` | DateTime | yes | — | NULL = never expires |
| `platform_user_id` | String(255) | yes | — | e.g. LinkedIn URN |
| `platform_page_id` | String(255) | yes | — | Page/org id for page-level tokens |
| `scopes` | JSON | yes | `list` | Granted OAuth scopes |
| `oauth_metadata` | JSON | yes | — | Platform extras, e.g. `ad_account_id` |
| `is_active` | Boolean | no | `True` | |
| `status` | String(50) | no | `active` | `active` / `token_expired` / `revoked` / `error` |
| `last_used_at` | DateTime | yes | — | |
| `created_at` / `updated_at` | DateTime | yes | utcnow | |

Unique constraint `uq_social_connection_company_platform_user (company_id, platform, platform_user_id)`;
index `ix_social_connections_company_platform`.

---

## 10. Ops tables, views and legacy tables

### 10.1 `feature_flags`

Purpose: runtime toggles at global / company / entity scope. **Has no SQLAlchemy model** —
it exists only in the migration
[p11t02_feature_flags.py:57](../../backend/migrations/versions/p11t02_feature_flags.py:57)
and is queried with raw SQL from
[core/feature_flags.py](../../backend/src/ai/core/feature_flags.py).

| Column | Type | Nullable | Default | Meaning |
|---|---|---|---|---|
| `id` | UUID | no | `gen_random_uuid()` | PK |
| `company_id` | UUID | yes | — | NULL = global. No FK |
| `entity_id` | UUID | yes | — | NULL = not entity-scoped. No FK |
| `flag_key` | String(128) | no | — | e.g. `agent_loop.budget_aware_react` |
| `enabled` | Boolean | no | `false` | |
| `value_json` | JSON | yes | — | For numeric/complex flags |
| `created_at` / `updated_at` | DateTime | no | `now()` | |

Three **partial unique indexes** enforce one row per (flag, scope) tier, which is needed
because Postgres before 15 treats each NULL in a multi-column unique index as distinct:

| Index | Predicate |
|---|---|
| `ix_feature_flags_global (flag_key)` | `company_id IS NULL AND entity_id IS NULL` |
| `ix_feature_flags_company (flag_key, company_id)` | `company_id IS NOT NULL AND entity_id IS NULL` |
| `ix_feature_flags_entity (flag_key, entity_id)` | `entity_id IS NOT NULL` |

Plus `ix_feature_flags_company_lookup (company_id)`.

Resolution order (first hit wins), per the module docstring:

```mermaid
flowchart TD
  A["flag lookup"] --> B["entity.metadata_extensions.feature_flags[key]"]
  B -->|miss| C["feature_flags row with entity_id = e"]
  C -->|miss| D["feature_flags row with company_id = c and entity_id NULL"]
  D -->|miss| E["feature_flags row with both NULL - global"]
  E -->|miss| F["env var AI_FLAG_KEY"]
  F -->|miss| G["DEFAULTS dict in feature_flags.py"]
```

The table is optional: if the migration has not run, lookups fall through to env vars
and code defaults rather than raising.

### 10.2 `kpi_daily_rollup` (materialised view)

Purpose: pre-aggregated dashboard data so admin endpoints never scan `execution_runs`.
Created by [p11t09_kpi_daily_rollup.py:25](../../backend/migrations/versions/p11t09_kpi_daily_rollup.py:25).

```sql
-- backend/migrations/versions/p11t09_kpi_daily_rollup.py
CREATE MATERIALIZED VIEW IF NOT EXISTS kpi_daily_rollup AS
SELECT date_trunc('day', er.completed_at) AS day,
       er.company_id,
       COALESCE((e.tags::jsonb)->>0, 'untagged') AS primary_tag,
       COUNT(*) AS runs_total,
       SUM(CASE WHEN er.status = 'COMPLETED' THEN 1 ELSE 0 END) AS runs_completed,
       SUM(CASE WHEN er.status = 'FAILED'    THEN 1 ELSE 0 END) AS runs_failed,
       SUM(CASE WHEN er.status = 'PAUSED'    THEN 1 ELSE 0 END) AS runs_paused,
       COALESCE(SUM(er.total_cost_usd), 0)::numeric(18, 6) AS cost_usd,
       COALESCE(SUM(er.total_tokens), 0) AS tokens
FROM execution_runs er
JOIN hierarchical_entities e ON e.id = er.entity_id
WHERE er.completed_at IS NOT NULL
GROUP BY 1, 2, 3
```

The unique index `kpi_daily_rollup_uniq(day, company_id, primary_tag)` is what allows
`REFRESH MATERIALIZED VIEW CONCURRENTLY`. It is refreshed hourly by
`core/arq_jobs.kpi_rollup_refresh` and read by
[api/admin.py:582](../../backend/src/ai/api/admin.py:582).

### 10.3 `alembic_version`

Created and maintained by Alembic. Single column `version_num`. Holds the current head.

### 10.4 Legacy and dead tables

| Table | Status | Evidence |
|---|---|---|
| `assets` | **Superseded by `artifacts`, but never dropped.** The migration explicitly says "Leaves 'assets' table in place (dropped last after verification)" | [h1i2j3k4l5m6:11](../../backend/migrations/versions/h1i2j3k4l5m6_create_artifacts_table_and_migrate_from_assets.py:11) |
| `phone_number_pool` | Legacy; merged into `phone_numbers` by the standalone script, which drops it | [merge_phone_tables.py](../../backend/migrations/merge_phone_tables.py) |
| `customer_phone_numbers` | Legacy; same merge | same |
| `partners`, `tenants` | Dropped — replaced by the single `companies` table | [c3e80da7ca0a](../../backend/migrations/versions/c3e80da7ca0a_remove_legacy_partner_and_tenant_tables.py) |
| `agents`, `workflows`, `executions` | Dropped — replaced by `hierarchical_entities` + `execution_runs` | [09e4d21677b1](../../backend/migrations/versions/09e4d21677b1_refactor_ai_models_to_hierarchical_.py) |
| `ai_models`, `system_configs`, `system_rates`, `partner_rates`, `invoices`, `payment_methods`, `ledger_entries` | Dropped by the costing refactor — replaced by `integration_registry` + `usage_logs` | [a804c0db1551](../../backend/migrations/versions/a804c0db1551_refactor_costing_system.py) |

---

## 11. Enumerations and lifecycles

### 11.1 Entity types and statuses

All in [schemas/enums.py](../../backend/src/ai/schemas/enums.py).

| Enum | Values |
|---|---|
| `EntityType` | `ACTION`, `SKILL`, `AGENT`, `PROCESS` |
| `EntityStatus` | `DRAFT`, `ACTIVE`, `DEPRECATED`, `ARCHIVED`, `DELETED` |
| `RelationshipType` | `SEQUENTIAL`, `PARALLEL`, `CONDITIONAL` |
| `ReasoningMode` | `REACT`, `CHAIN_OF_THOUGHT`, plus deprecated `REFLECTION` and `TREE_OF_THOUGHTS` |
| `BackoffStrategy` | `LINEAR`, `EXPONENTIAL`, `NONE` |
| `ValidationType` | `REGEX`, `SCHEMA`, `LLM_JUDGE`, `FUNCTION` |
| `HITLTriggerType` | `BEFORE_STEP`, `AFTER_STEP`, `COST_THRESHOLD`, `TOOL_CALL`, `CUSTOM` |
| `StepType` | `THOUGHT`, `ACTION`, `TOOL_CALL`, `CHILD_ENTITY_INVOCATION`, `NAVIGATE`, `READ`, `WRITE`, `RECURSE`, `AWAIT_CHILDREN` |
| `ExecutionMode` | `STANDARD`, `AUTONOMOUS` |
| `ContextSourceType` | `DOCUMENT`, `KNOWLEDGE_BASE`, `CORTEX_TREE`, `DB_RECORDS` |

`DEPRECATED_REASONING_MODES` is a frozenset of the two deprecated modes; the step
executor emits a warning when it sees them.

```mermaid
stateDiagram-v2
  [*] --> DRAFT
  DRAFT --> ACTIVE
  ACTIVE --> DEPRECATED
  DEPRECATED --> ARCHIVED
  ACTIVE --> ARCHIVED
  ACTIVE --> DELETED : soft delete
  DRAFT --> DELETED : soft delete
  DELETED --> [*] : row kept for FK integrity
```

### 11.2 Run status lifecycle

`RunStatus` and `VALID_TRANSITIONS` are both in
[schemas/enums.py:34](../../backend/src/ai/schemas/enums.py:34).

```mermaid
stateDiagram-v2
  [*] --> PENDING
  PENDING --> RUNNING
  PENDING --> REFINING
  PENDING --> CANCELLED
  RUNNING --> PAUSED
  RUNNING --> COMPLETED
  RUNNING --> FAILED
  RUNNING --> PARTIAL_COMPLETE
  RUNNING --> CANCELLED
  RUNNING --> WAITING_ON_CHILDREN
  PAUSED --> RUNNING
  PAUSED --> RESUMING
  PAUSED --> FAILED
  PAUSED --> CANCELLED
  RESUMING --> RUNNING
  RESUMING --> FAILED
  RESUMING --> CANCELLED
  PARTIAL_COMPLETE --> RUNNING
  PARTIAL_COMPLETE --> COMPLETED
  PARTIAL_COMPLETE --> FAILED
  REPAIRING --> RUNNING
  REPAIRING --> FAILED
  REFINING --> RUNNING
  REFINING --> COMPLETED
  REFINING --> FAILED
  WAITING_ON_CHILDREN --> RESUMING
  WAITING_ON_CHILDREN --> RUNNING
  WAITING_ON_CHILDREN --> FAILED
  WAITING_ON_CHILDREN --> CANCELLED
  COMPLETED --> [*]
  FAILED --> [*]
  CANCELLED --> [*]
```

Enforcement is **lenient**: `validate_transition()` logs a warning and returns `False`
for an invalid transition, but nothing stops the write.

```python
# backend/src/ai/schemas/enums.py
def validate_transition(current: str, target: str) -> bool:
    allowed = VALID_TRANSITIONS.get(current, set())
    if target not in allowed:
        logging.getLogger(__name__).warning(
            f"Invalid state transition: {current} → {target} "
            f"(allowed: {allowed or 'none'})"
        )
        return False
    return True
```

Also note `REPAIRING` has no inbound edge in `VALID_TRANSITIONS` — nothing can legally
transition *into* it.

### 11.3 User roles

Stored as a plain string on `users.role` and checked by `RoleChecker`
([auth/dependencies.py](../../backend/src/auth/dependencies.py)).

| Role | Scope |
|---|---|
| `app_admin` | Platform-wide; the only role allowed to cross tenant boundaries |
| `partner_admin` | Partner org |
| `tenant_admin` | Single tenant |
| `app_user` / `partner_user` / `tenant_user` | Non-admin variants; `tenant_user` is the default |

Company types: `APP`, `PARTNER`, `TENANT` (`companies.type`), forming the same three
tiers via `companies.parent_id`.

### 11.4 Campaign status lifecycle

```mermaid
stateDiagram-v2
  [*] --> draft
  draft --> scheduled
  draft --> running
  scheduled --> running
  running --> paused
  paused --> running
  running --> completed
  running --> failed
  completed --> running : retry failed calls
  completed --> [*]
  failed --> [*]
```

Transitions are driven by `PUT /campaigns/{id}/status`
([campaign_router.py:581](../../backend/src/ai/campaign_router.py:581)) and by the
executor ([campaign_executor.py:87](../../backend/src/ai/campaign_executor.py:87)). The
router also computes an *effective* status: a campaign marked `completed` with pending
calls is reported as `running` ([campaign_router.py:232](../../backend/src/ai/campaign_router.py:232)).

Per-call lifecycle:

```mermaid
stateDiagram-v2
  [*] --> pending
  pending --> calling
  pending --> skipped
  calling --> completed
  calling --> completed_voicemail : "completed-voicemail"
  calling --> failed
  failed --> pending : retry_count < max_retries
  completed --> [*]
  skipped --> [*]
```

### 11.5 Call, phone and lead lifecycles

```mermaid
stateDiagram-v2
  state "voice_sessions.status" as VS {
    [*] --> initiated
    initiated --> active : media stream opens
    active --> ended : webhook completed/busy/failed/no-answer/canceled
    initiated --> ended : never answered
    ended --> [*]
  }
```

```mermaid
stateDiagram-v2
  state "phone_numbers.status" as PN {
    [*] --> available
    available --> claimed : tenant claims
    claimed --> assigned : agent configured
    assigned --> claimed : agent unassigned
    claimed --> available : released
    assigned --> retired
    claimed --> retired
    available --> retired
    retired --> [*]
  }
```

```mermaid
stateDiagram-v2
  state "lead_queue.status" as LQ {
    [*] --> pending
    pending --> queued : worker picks it up
    queued --> calling
    calling --> completed
    calling --> failed
    failed --> pending : attempt_count < max_attempts
    completed --> [*]
    failed --> [*] : retries exhausted
  }
```

Approval lifecycle:

```mermaid
stateDiagram-v2
  [*] --> PENDING
  PENDING --> APPROVED : reviewer approves
  PENDING --> REJECTED : reviewer rejects
  PENDING --> TIMEOUT : timeout_ms elapsed
  APPROVED --> [*]
  REJECTED --> [*]
  TIMEOUT --> [*]
```

`auto_approve_on_timeout` on the checkpoint config decides whether a `TIMEOUT` resumes
or fails the run.

### 11.6 CORTEX node types

`cortex_node_type` is a real Postgres enum with 21 values, defined in
`cortex_memory/enums.py` and extended twice by migrations.

| Group | Values |
|---|---|
| v1 | `root`, `knowledge`, `finding`, `task`, `output`, `checkpoint` |
| v2 (added by [x1y2z3a4b5c6](../../backend/migrations/versions/x1y2z3a4b5c6_add_unified_cortex_memory_v2.py:34)) | `group`, `document`, `section`, `chunk`, `observation`, `pattern`, `suggestion`, `instruction`, `strategy`, `preference`, `episode`, `episode_group` |
| agent-loop (added by [p11t_cortex_loop_node_types](../../backend/migrations/versions/p11t_cortex_loop_node_types.py)) | `snapshot`, `health_record`, `health_root` |

Other CORTEX enums:

| Enum type | Values |
|---|---|
| `cortex_tree_status` | `active`, `suspended`, `complete`, `archived` |
| `cortex_node_status` | `pending`, `active`, `complete`, `summarised` |
| `memory_domain` | `knowledge`, `experience`, `intelligence`, `episodic` |
| `scope_level` | `app`, `partner`, `tenant`, `user`, `entity`, `runtime` |

Postgres cannot remove enum values, so downgrades leave the added values behind — the
v2 migration says so explicitly.

### 11.7 Cost attribution tags

`usage_logs.attribution` is a closed set defined by `CostAttribution`
([services/cost_attribution.py](../../backend/src/ai/services/cost_attribution.py)):

`planner`, `actor_step`, `critic_pre`, `critic_post`, `critic_align`, `critic_super`,
`reformat_retry`, `meta_review`, `dreaming`, `tool`, `child_run`, `embedding`,
`meta_spec_critic`, `test_driver`, `sandbox`, `mcp`.

Unknown values are logged and silently rewritten to `tool` so a charge is never lost.

### 11.8 Trace span kinds and statuses

From [orm/trace.py:44](../../backend/src/ai/orm/trace.py:44):

```python
# backend/src/ai/orm/trace.py
TRACE_KINDS = ("iteration", "executor", "step", "child", "tool", "llm", "critic")
TRACE_STATUSES = ("running", "success", "error")
```

These are plain Python tuples, **not** DB constraints — nothing stops an invalid `kind`
being written.

---

## 12. Multi-tenancy: how company_id scoping works

There is **no row-level security and no global query filter**. Tenant isolation is
enforced by hand, in every service method, by adding
`WHERE company_id = :current_user_company_id`.

```mermaid
flowchart TD
  A["HTTP request with Bearer JWT"] --> B["get_current_user - decodes JWT, loads User with Company"]
  B --> C{"company.status == suspended?"}
  C -- yes --> D["403"]
  C -- no --> E["router handler receives user"]
  E --> F["service method called with company_id = user.company_id"]
  F --> G["query adds .where(Model.company_id == company_id)"]
  G --> H["rows returned"]
  E --> I{"app_admin?"}
  I -- yes --> J["_company_scope returns the requested company_id or None for all"]
```

The two enforcement points to know:

1. [`get_current_user` / `get_current_user_and_company`](../../backend/src/auth/dependencies.py) —
   resolves the caller and eagerly loads `user.company`. It rejects suspended companies
   at the door.
2. Each service adds the filter explicitly. `AIService` does this in a dozen places, for
   example [service.py:63](../../backend/src/ai/service.py:63) and
   [service.py:438](../../backend/src/ai/service.py:438).

Admin endpoints widen the scope through a small helper
([api/admin.py:568](../../backend/src/ai/api/admin.py:568)):

```python
# backend/src/ai/api/admin.py
def _company_scope(user: User, requested_company: Optional[UUID]) -> Optional[UUID]:
    if user.role == "app_admin":
        return requested_company
    return user.company_id
```

`None` means "all companies" and is only reachable by an `app_admin`.

### Which tables are tenant-scoped

| Scoping | Tables |
|---|---|
| **NOT NULL `company_id`** | `users`, `hierarchical_entities`, `execution_runs`, `episodic_memories`, `documents`, `source_trust_scores`, `integration_registry`, `model_task_defaults`, `usage_logs`, `credit_wallets` (also UNIQUE), `subscriptions`, `payment_transactions`, `billing_events`, `voice_sessions`, `whatsapp_sessions`, `conversation_history`, `campaigns`, `lead_queue`, `call_logs`, `artifacts`, `email_connections`, `social_connections`, `cortex_trees` |
| **Nullable `company_id`** (NULL = platform-wide) | `tool_registry_entries` (NULL = built-in system tool), `billing_config` (NULL = global default), `feature_flags` (NULL = global flag), `phone_numbers` (NULL = unclaimed inventory) |
| **Denormalised, no FK** | `execution_trace_events.company_id` |
| **Reached only via a parent** | `refresh_tokens` (via user), `llm_interaction_logs`, `tool_interaction_logs`, `human_approvals` (via run), `document_chunks` (via document), `campaign_calls` (via campaign), `call_content` (via call_log), `cortex_nodes`, `cortex_edges` (via tree) |
| **Global master data** | `subscription_tiers`, `alembic_version` |

Consequence: any query on `llm_interaction_logs` or `cortex_nodes` that does not join
through its parent has **no tenant filter at all**. Always join.

---

## 13. pgvector: embeddings and similarity search

The `vector` extension is enabled by the second-ever migration
([093ffa970086](../../backend/migrations/versions/093ffa970086_add_pgvector_extension.py:23)):
`CREATE EXTENSION IF NOT EXISTS vector`.

| Table | Column | Dimension | ANN index | Notes |
|---|---|---|---|---|
| `document_chunks` | `embedding` | 768 | **none** | Legacy v1 RAG path. Sequential scan on every search |
| `cortex_nodes` | `embedding` | 768 | `ix_cortex_nodes_embedding` — HNSW, `vector_cosine_ops`, `m=16, ef_construction=64` | The v2 memory path. `embedding_model` records which model produced the vector |

768 is the Gemini/Vertex embedding width. The default model is
`text-embedding-005` (`EMBEDDING_MODEL_FALLBACK` in
[ai/constants.py:19](../../backend/src/ai/constants.py:19)).

### How the model is chosen

[embedding_service.py](../../backend/src/ai/memory/embedding_service.py) resolves it
per company in this order:

1. `model_task_defaults` row with `task_type="embedding"`.
2. `integration_registry` row with `service_category="EMBEDDING"`.
3. `integration_registry` Google row where `model_name LIKE '%embed%'`.
4. The `EMBEDDING_MODEL_FALLBACK` constant.

`EmbeddingService.BATCH_SIZE = 100` (the Vertex per-call limit). Every `embed_batch`
writes one attributed `usage_logs` row with `attribution="embedding"` and
`log_metadata.embedding_phase` set to `ingestion` or `retrieval`, on its own short-lived
session so a billing failure can never abort the caller's transaction.

### How search is issued

All similarity search is **raw SQL with the pgvector `<=>` cosine-distance operator**,
never the ORM. Two representative call sites:

```python
# backend/src/ai/memory/memory_service.py  (v1 document search)
stmt = text("""
    SELECT dc.content,
           1 - (dc.embedding <=> CAST(:vec AS vector)) AS score
    FROM   document_chunks dc
    JOIN   documents d ON d.id = dc.document_id
    WHERE  d.entity_id = :entity_id
    ORDER  BY dc.embedding <=> CAST(:vec AS vector)
    LIMIT  :top_k
""")
```

```sql
-- cortex_memory/knowledge_tree.py  (v2 CORTEX chunk search)
SELECT cn.id, cn.title, cn.content, cn.source_ref,
       1 - (cn.embedding <=> CAST(:vec AS vector)) AS score,
       parent.title AS section_title,
       grandparent.title AS document_title
FROM cortex_nodes cn
LEFT JOIN cortex_nodes parent ON cn.parent_id = parent.id
LEFT JOIN cortex_nodes grandparent ON parent.parent_id = grandparent.id
WHERE cn.tree_id = :tree_id
  AND cn.node_type = 'chunk'
  AND cn.embedding IS NOT NULL
ORDER BY cn.embedding <=> CAST(:vec AS vector)
LIMIT :top_k
```

Note the vector parameter is passed as a **JSON-serialised list** (`json.dumps(vector)`)
and cast with `CAST(:vec AS vector)` for asyncpg compatibility. One older call site in
[service.py:960](../../backend/src/ai/service.py:960) uses `str(query_embedding)` and
`:query_embedding::vector` instead — same effect, different style.

```mermaid
sequenceDiagram
  participant C as Caller
  participant ES as EmbeddingService
  participant IR as integration_registry
  participant V as Vertex AI
  participant UL as usage_logs
  participant PG as Postgres pgvector

  C->>ES: embed_query(text)
  ES->>IR: resolve model for company
  IR-->>ES: model name plus credentials
  ES->>V: embed batch max 100
  V-->>ES: vectors plus billable_character_count
  ES->>UL: insert row attribution=embedding
  ES-->>C: vector
  C->>PG: SELECT ... ORDER BY embedding <=> CAST(:vec AS vector) LIMIT k
  PG-->>C: ranked rows with cosine score
  C->>PG: UPDATE cortex_nodes SET access_count = access_count + 1
```

After a CORTEX search, the service bumps `access_count` and `last_accessed_at` on the
returned nodes — retrieval is itself a signal.

---

## 14. Migrations with Alembic

### Configuration

| File | What it does |
|---|---|
| [backend/alembic.ini](../../backend/alembic.ini) | `script_location = %(here)s/migrations`, `prepend_sys_path = .`, logging config. The `sqlalchemy.url` in the file is the placeholder `driver://user:pass@localhost/dbname` and is **always overridden** at runtime |
| [backend/migrations/env.py](../../backend/migrations/env.py) | Imports every model module so `Base.metadata` is complete, sets `target_metadata`, and overrides the URL from settings |
| [backend/migrations/script.py.mako](../../backend/migrations/script.py.mako) | Template for new revision files |

The two things in `env.py` a newcomer must know:

```python
# backend/migrations/env.py
target_metadata = [Base.metadata, cortex_memory.metadata]
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)
```

`target_metadata` is a **list** because the CORTEX tables live on the `cortex_memory`
package's own `Base`. If you drop that second entry, autogenerate will happily emit
`DROP TABLE cortex_trees`.

Migrations run **online and async** — `run_migrations_online()` builds an
`async_engine_from_config` with `NullPool` and calls `connection.run_sync`.

### Running and creating migrations

```bash
cd backend
source .venv/bin/activate

alembic current                      # what the DB is stamped at
alembic heads                        # should print exactly one head
alembic history --verbose            # the chain

alembic upgrade head                 # apply everything
alembic downgrade -1                 # roll back one

alembic revision --autogenerate -m "add_widget_table"   # diff models vs DB
alembic revision -m "backfill_widgets"                  # empty, hand-written
```

Add every new model module to the import block at the top of `env.py`, or autogenerate
will not see it (and may propose dropping its table).

### The migration chain

52 revision files, one root (`fd743ae4b9ee`) and — importantly — **one head**
(`z9b0c1d2e3f4`). Four merge revisions stitch together branches that were developed in
parallel.

```mermaid
flowchart TD
  R1["fd743ae4b9ee initial"] --> R2["093ffa970086 pgvector"] --> R3["e3bbbefdc5b9 documents"] --> R4["6fdc110c5698 billing v1"] --> R5["c830b1839465 companies"] --> R6["c3e80da7ca0a drop partners/tenants"] --> R7["a804c0db1551 costing refactor"] --> R8["f4bdb8730f25 log_metadata"] --> R9["9bf859b51116 usage exec id"]
  R9 --> R10["54b608877f40 unique sku"] --> R11["09e4d21677b1 hierarchical entities"] --> R12["9bc12d4c6cc6 approvals + tool logs"] --> R13["a1b2c3d4e5f6 voice tables"] --> R14["b2c3d4e5f6a7 campaigns"]
  R9 --> E1["e1a2b3c4d5e6 email_connections"]
  R14 --> M1["g1h2i3j4k5l6 assets + billing + credits"]
  E1 --> M1
  M1 --> R16["39b85529e254 merge"]
  M1 --> R17["h1i2j3k4l5m6 artifacts"]
  R16 --> M2["i1j2k3l4m5n6 merge"]
  R17 --> M2
  M2 --> R18["j1k2l3m4n5o6 model_task_defaults"] --> R19["k1l2m3n4o5p6 CORTEX v1"] --> R20["l1m2n3o4p5q6 social"] --> R21["m1n2o3p4q5r6 goal + templates"] --> R22["n1o2p3q4r5s6 tool registry"] --> R23["o1p2q3r4s5t6 service_category"] --> R24["p1q2r3s4t5u6 run user_id"] --> R25["q1r2s3t4u5v6 episodic"]
  R25 --> B1["2999001a9221 billing config fix"]
  R25 --> B2["r1s2t3u4v5w6 cortex scheduling"] --> B3["s1t2u3v4w5x6 drop legacy fields"]
  B1 --> M3["t1u2v3w4x5y6 merge"]
  B3 --> M3
  M3 --> R27["u1v2w3x4y5z6 lead_queue"] --> R28["v1w2x3y4z5a6 templates no-op"]
  M3 --> R29["w1x2y3z4a5b6 deleted_at"] --> R30["p3_idempotency_001"]
  R28 --> M4["x1y2z3a4b5c6 CORTEX v2"]
  R30 --> M4
  M4 --> R31["p11t08 usage attribution"] --> R32["p11t09 kpi rollup"] --> R33["p11t02 feature_flags"] --> R34["p11t05 meta-cognition"] --> R35["p11t06 intel status"] --> R36["p11t09 drop flags"]
  M4 --> R37["y2z3a4b5c6d7 onboarding + phone pool"]
  R36 --> M5["p11_merge_2026_05_28"]
  R37 --> M5
  M5 --> R38["p11t cortex loop node types"] --> R39["p11t10 cortex entity nullable"] --> R40["p11 execution_trace_events"] --> R41["p12 retire reasoning modes"] --> R42["p12 source_trust_scores"] --> R43["p12 run csat"] --> R44["y7z8a9b0c1d2 disposition"] --> R45["z9b0c1d2e3f4 disposition_reason HEAD"]
```

Full chronological list, in dependency order:

| # | Revision | Down revision | What it does |
|---|---|---|---|
| 1 | `fd743ae4b9ee` | — | Initial: `partners`, `tenants`, `users`, `refresh_tokens`, `agents`, `workflows`, `executions`, `ai_models`, `system_configs` |
| 2 | `093ffa970086` | `fd743ae4b9ee` | `CREATE EXTENSION vector` |
| 3 | `e3bbbefdc5b9` | `093ffa970086` | `documents` + `document_chunks` for RAG |
| 4 | `6fdc110c5698` | `e3bbbefdc5b9` | Adds `model_name` to `ai_models`; creates the first billing tables |
| 5 | `c830b1839465` | `6fdc110c5698` | Creates `companies`; hierarchical RBAC |
| 6 | `c3e80da7ca0a` | `c830b1839465` | Drops `partners` and `tenants` |
| 7 | `a804c0db1551` | `c3e80da7ca0a` | Costing refactor: creates `integration_registry` + `usage_logs`, drops seven legacy billing tables |
| 8 | `f4bdb8730f25` | `a804c0db1551` | Renames `usage_logs.metadata` → `log_metadata` |
| 9 | `9bf859b51116` | `f4bdb8730f25` | Adds execution id to `usage_logs` |
| 10 | `54b608877f40` | `9bf859b51116` | Unique constraint on `integration_registry` |
| 11 | `09e4d21677b1` | `54b608877f40` | Creates `hierarchical_entities`, `execution_runs`, `llm_interaction_logs`; drops `agents`/`workflows`/`executions` |
| 12 | `9bc12d4c6cc6` | `09e4d21677b1` | `human_approvals` + `tool_interaction_logs` |
| 13 | `a1b2c3d4e5f6` | `9bc12d4c6cc6` | `voice_sessions`, `whatsapp_sessions`, `conversation_history`, `customer_phone_numbers` |
| 14 | `b2c3d4e5f6a7` | `a1b2c3d4e5f6` | `campaigns` + `campaign_calls` |
| 15 | `e1a2b3c4d5e6` | `9bf859b51116` | `email_connections` (branch) |
| 16 | `g1h2i3j4k5l6` | (`e1a2b3c4d5e6`, `b2c3d4e5f6a7`) | **Merge**; creates `assets`, `call_logs`, `call_content`, `billing_config`, `credit_wallets`, `subscriptions`, `payment_transactions`, `billing_events` |
| 17 | `39b85529e254` | `g1h2i3j4k5l6` | Merge marker for the campaign/assets branches |
| 18 | `h1i2j3k4l5m6` | `g1h2i3j4k5l6` | Creates `artifacts`, migrates rows from `assets`, repoints `call_content` |
| 19 | `i1j2k3l4m5n6` | (`39b85529e254`, `h1i2j3k4l5m6`) | **Merge** |
| 20 | `j1k2l3m4n5o6` | `i1j2k3l4m5n6` | `model_task_defaults`; deletes legacy entities carrying `llm_config` |
| 21 | `k1l2m3n4o5p6` | `j1k2l3m4n5o6` | CORTEX v1: `cortex_trees`, `cortex_nodes`, three enum types, `episodic_memories.tree_id` |
| 22 | `l1m2n3o4p5q6` | `k1l2m3n4o5p6` | `social_connections` |
| 23 | `m1n2o3p4q5r6` | `l1m2n3o4p5q6` | Adds `goal`, `is_template`, `template_source_id` to entities |
| 24 | `n1o2p3q4r5s6` | `m1n2o3p4q5r6` | `tool_registry_entries` |
| 25 | `o1p2q3r4s5t6` | `n1o2p3q4r5s6` | `service_category` + `service_metadata` on `integration_registry` |
| 26 | `p1q2r3s4t5u6` | `o1p2q3r4s5t6` | `execution_runs.user_id` |
| 27 | `q1r2s3t4u5v6` | `p1q2r3s4t5u6` | `episodic_memories` |
| 28 | `2999001a9221` | `q1r2s3t4u5v6` | Fixes `billing_config` columns (branch) |
| 29 | `r1s2t3u4v5w6` | `q1r2s3t4u5v6` | CORTEX scheduling columns (branch) |
| 30 | `s1t2u3v4w5x6` | `r1s2t3u4v5w6` | Removes legacy entity fields `is_active`, `static_plan`, `llm_config`, `toolkit` |
| 31 | `t1u2v3w4x5y6` | (`2999001a9221`, `s1t2u3v4w5x6`) | **Merge** |
| 32 | `u1v2w3x4y5z6` | `t1u2v3w4x5y6` | `lead_queue` |
| 33 | `v1w2x3y4z5a6` | `u1v2w3x4y5z6` | No-op: templates stay `company_id NOT NULL` |
| 34 | `w1x2y3z4a5b6` | `t1u2v3w4x5y6` | `hierarchical_entities.deleted_at` + `idx_entities_not_deleted` (branch) |
| 35 | `p3_idempotency_001` | `w1x2y3z4a5b6` | `idempotency_key` on runs and tool logs, with partial indexes |
| 36 | `x1y2z3a4b5c6` | (`p3_idempotency_001`, `v1w2x3y4z5a6`) | **Merge**; CORTEX v2: `memory_domain`/`scope_level` enums, 12 new node types, node embeddings, `cortex_edges`, HNSW index |
| 37 | `p11t08_usage_attr` | `x1y2z3a4b5c6` | `usage_logs.attribution` |
| 38 | `p11t09_kpi_rollup` | `p11t08_usage_attr` | `kpi_daily_rollup` materialised view |
| 39 | `p11t02_feature_flags` | `p11t09_kpi_rollup` | `feature_flags` table + partial unique indexes |
| 40 | `p11t05_preserve_meta_cog` | `p11t02_feature_flags` | Preserves meta-cognition tiers across a default flip |
| 41 | `p11t06_intel_status` | `p11t05_preserve_meta_cog` | Backfills intelligence-rule status |
| 42 | `p11t09_drop_flags` | `p11t06_intel_status` | Deletes unused `feature_flags` rows |
| 43 | `y2z3a4b5c6d7` | `x1y2z3a4b5c6` | Onboarding columns on `companies`, `phone_number_pool`, self-heals `lead_queue` (branch; note the **filename says `a1b2c3d4e5f6`** but the revision id is `y2z3a4b5c6d7`) |
| 44 | `p11_merge_2026_05_28` | (`p11t09_drop_flags`, `y2z3a4b5c6d7`) | **Merge** |
| 45 | `p11t_cortex_loop_node_types` | `p11_merge_2026_05_28` | Adds `snapshot`, `health_record`, `health_root` node types |
| 46 | `p11t10_cortex_entity_nullable` | `p11t_cortex_loop_node_types` | Makes `cortex_trees.entity_id` nullable |
| 47 | `p11_execution_trace_events` | `p11t10_cortex_entity_nullable` | `execution_trace_events` + 4 indexes |
| 48 | `p12_retire_reasoning_modes` | `p11_execution_trace_events` | Data migration off `REFLECTION` / `TREE_OF_THOUGHTS` |
| 49 | `p12_source_trust_scores` | `p12_retire_reasoning_modes` | `source_trust_scores` |
| 50 | `p12_run_csat` | `p12_source_trust_scores` | `execution_runs.csat_score` + `csat_comment` |
| 51 | `y7z8a9b0c1d2` | `p12_run_csat` | `campaign_calls.disposition` + index + backfill |
| 52 | `z9b0c1d2e3f4` | `y7z8a9b0c1d2` | `campaign_calls.disposition_reason` — **current head** |

Two filenames collide on the prefix `a1b2c3d4e5f6_`: the voice-tables migration
(revision `a1b2c3d4e5f6`) and the onboarding/phone-pool migration (revision
`y2z3a4b5c6d7`). Alembic keys off the `revision` variable, not the filename, so this
works — but it is confusing when grepping.

Several migrations are defensively idempotent: they call `sa.inspect(bind)` and skip
work if a table or column already exists (see `p11t02_feature_flags` and
`y2z3a4b5c6d7`). That pattern exists because some environments were stamped past
migrations that never actually ran.

---

## 15. Seed and utility scripts

### `backend/db-scripts/`

| Script | What it does | When to run it |
|---|---|---|
| [`seed_admin_user.py`](../../backend/db-scripts/seed_admin_user.py) | Creates the `APP` company "HireBuddha" and the `app_admin` user `admin@hirebuddha.com` / `adminpass`. Idempotent | Immediately after the first `alembic upgrade head` on a fresh database |
| [`clean_db.sql`](../../backend/db-scripts/clean_db.sql) | `TRUNCATE`s all transactional tables in dependency order, preserving `subscription_tiers` and `tool_registry_entries WHERE tool_type='BUILT_IN'`. Skips tables that do not exist | Resetting a dev/staging environment. Irreversible |
| [`backfill_cortex_trees.py`](../../backend/db-scripts/backfill_cortex_trees.py) | Creates a CORTEX tree for each completed execution run that lacks one, so the Memory Trees UI shows history | One-off after enabling CORTEX on an existing database |

```bash
cd backend
python db-scripts/seed_admin_user.py
PGPASSWORD=postgres psql -U postgres -h localhost -p 5433 -d hirebuddha -f db-scripts/clean_db.sql
DATABASE_URL=postgresql+asyncpg://... python -m db-scripts.backfill_cortex_trees
```

### `backend/scripts/migrations/` — post-deploy data migrations

Not Alembic. Each is idempotent and run manually
([README](../../backend/scripts/migrations/README.md)).

| Script | What it does |
|---|---|
| [`documents_to_knowledge_trees.py`](../../backend/scripts/migrations/documents_to_knowledge_trees.py) | Backfills v2 Knowledge Trees (`DOCUMENT` → `SECTION` → `CHUNK` nodes) from legacy `document_chunks` rows. Skips entities that already have one |
| [`episodic_to_trees.py`](../../backend/scripts/migrations/episodic_to_trees.py) | Backfills v2 Episodic Trees from legacy `episodic_memories` rows |
| [`reseed_meta_agent.py`](../../backend/scripts/migrations/reseed_meta_agent.py) | Replaces the Meta-Agent's prompts/capabilities/planning/governance with the latest template while **preserving its `entity_id`**. Supports `--company` and `--dry-run` |

### `backend/scripts/seeds/` and other scripts

| Path | What it does |
|---|---|
| [`seeds/default_entities/SeedAutonomousBI/`](../../backend/scripts/seeds/default_entities/SeedAutonomousBI/) | Creates the Autonomous BI process, agents, skills and actions |
| [`seeds/default_entities/SeedDocumentFactory/`](../../backend/scripts/seeds/default_entities/SeedDocumentFactory/) | Document Factory entities for docx / pdf / pptx / xlsx / QA |
| [`seeds/default_entities/SeedDocFactoryLite/`](../../backend/scripts/seeds/default_entities/SeedDocFactoryLite/) | Trimmed Document Factory variant |
| [`seeds/deep_research/DeepResearchSetup/`](../../backend/scripts/seeds/deep_research/DeepResearchSetup/) | Deep Research v2 entities plus a `trigger_execution.py` smoke test. Created entity ids are cached in `entity_ids.json` |
| [`scripts/seed_sandbox_sku.py`](../../backend/scripts/seed_sandbox_sku.py) | Idempotently inserts the `sandbox-runtime` SKU into `integration_registry`, owned by the APP company, `cost_unit=second`. Without it, sandbox metering logs a warning and records nothing |
| [`migrations/merge_phone_tables.py`](../../backend/migrations/merge_phone_tables.py) | Creates `phone_numbers` and merges `phone_number_pool` + `customer_phone_numbers` into it, then drops the old tables |

```mermaid
flowchart LR
  A["createdb hirebuddha"] --> B["alembic upgrade head"]
  B --> C["python -m migrations.merge_phone_tables"]
  C --> D["python db-scripts/seed_admin_user.py"]
  D --> E["python -m scripts.seed_sandbox_sku"]
  E --> F["seed integration_registry SKUs via admin UI or API"]
  F --> G["optional: scripts/seeds/... default entities"]
```

---

## 16. Where is X stored? Quick lookup

| Question | Table.column | Notes |
|---|---|---|
| An agent's system prompt | `hierarchical_entities.identity` → `system_prompt` | JSON; `AgentPersona` schema |
| An agent's voice / language / speaking rate | `hierarchical_entities.identity` → `voice{...}` | `VoiceConfig` |
| An agent's goal | `hierarchical_entities.goal` | Real column, not JSON |
| Which tools an agent may use | `hierarchical_entities.capabilities` → `tools[].tool_id` | |
| A tool's function schema | `tool_registry_entries.function_schema` | Built-ins are seeded at startup |
| A tool's price | `integration_registry.internal_cost` where `service_sku` = tool id (or an alias in `_TOOL_SKU_MAP`) | Lookup at [step_executor.py:469](../../backend/src/ai/step_executor.py:469); some tools have hard-coded fallbacks |
| An LLM's API key | `integration_registry.encrypted_api_key` | AES-256-GCM; Vertex models use ADC and may have no key |
| Which model serves a task type | `model_task_defaults.integration_id` for that `(company_id, task_type)` | |
| Razorpay credentials | `integration_registry` where `service_sku='razorpay_keys'` | [credits_router.py:34](../../backend/src/billing/credits_router.py:34) |
| Platform SMTP credentials | `integration_registry` where `service_sku='smtp-system'` | [common/email.py:63](../../backend/src/common/email.py:63) |
| A tenant's mailbox password | `email_connections.encrypted_app_password` | |
| A social OAuth token | `social_connections.encrypted_access_token` / `encrypted_refresh_token` | |
| A user's credit balance | `credit_wallets` — sum of `daily_credits`, `wallet_balance`, `subscription_credits`, `subscription_bonus_credits` | One wallet per company |
| A single charge | `usage_logs` row (`raw_quantity`, `calculated_cost`, `attribution`) | |
| A run's internal cost vs what the user is charged | `execution_runs.total_cost_usd` vs `execution_runs.billed_amount` | |
| Monthly invoice figures | `billing_events` for `(company_id, period_month)` | |
| The billing formula parameters | `billing_config` (company row, else the `company_id IS NULL` global row) | |
| The exact prompt sent to an LLM | `llm_interaction_logs.input_prompt` and `execution_trace_events.payload` for `kind='llm'` | Trace payload fields are byte-capped |
| A tool call's arguments and result | `tool_interaction_logs.input_parameters` / `output_result` | |
| The per-iteration execution tree | `execution_trace_events` ordered by `seq` | |
| The plan a run executed | `execution_runs.dynamic_plan`, falling back to `hierarchical_entities.planning.static_plan` | |
| A resumable run's saved state | `execution_runs.context_state["__agent_state_snapshot__"]` | Written when a run goes `WAITING_ON_CHILDREN` |
| A pending human approval | `human_approvals` where `status='PENDING'` | |
| A thumbs up/down on a run | `execution_runs.csat_score` (+1 / −1) and `csat_comment` | |
| An uploaded document's text | `document_chunks.content`; its vector in `document_chunks.embedding` | |
| An agent's long-term memory | `cortex_nodes` under a `cortex_trees` row with the right `memory_domain` | |
| A learned rule the system distilled | `cortex_nodes` with `node_type='instruction'` in an `intelligence` tree | |
| Past run summaries | Episodic CORTEX trees; legacy rows in `episodic_memories` | |
| How much a source is trusted | `source_trust_scores.learned_trust` for `(company_id, source_key)` | |
| A call recording | `artifacts` row with `file_category='recordings'`, path in `file_path`; linked from `call_content.audio_artifact_id` | Bytes are on disk, not in the DB |
| A call transcript | `call_content.transcript_text`, `voice_sessions.conversation_log`, and turn-by-turn in `conversation_history` | |
| A call's cost | `voice_sessions.total_cost_usd` and `call_logs.call_cost_usd` | |
| Which agent answers a phone number | `phone_numbers.agent_id` where `status='assigned'` | |
| A campaign's contact list | `campaigns.contact_list` (JSONB) and per-contact rows in `campaign_calls.contact_data` | |
| Why a lead said no | `campaign_calls.disposition_reason` | LLM-classified |
| A CRM lead awaiting a call | `lead_queue` where `status='pending'` | Dedup key `(company_id, lead_id)` |
| Any generated file | `artifacts` (`origin='system-generated'`) | Path convention `artificate/{origin}/{company_id}/{date}/{name}` |
| A feature flag's value | `feature_flags`, then env `AI_FLAG_*`, then `DEFAULTS` in `core/feature_flags.py` | Entity-level override wins over all of them |
| Dashboard run counts | `kpi_daily_rollup` materialised view | Refreshed hourly |
| The current schema version | `alembic_version.version_num` | |

---

## Key files reference

| File | Lines | What it does |
|---|---|---|
| [backend/src/common/database.py](../../backend/src/common/database.py) | 36 | Async engine, session factory, `Base`, `get_db` dependency |
| [backend/src/auth/models.py](../../backend/src/auth/models.py) | 55 | `companies`, `users`, `refresh_tokens` |
| [backend/src/ai/orm/entity.py](../../backend/src/ai/orm/entity.py) | 69 | `hierarchical_entities` |
| [backend/src/ai/orm/execution.py](../../backend/src/ai/orm/execution.py) | 138 | `execution_runs`, `llm_interaction_logs`, `tool_interaction_logs`, `human_approvals` |
| [backend/src/ai/orm/trace.py](../../backend/src/ai/orm/trace.py) | 102 | `execution_trace_events` + span kind constants |
| [backend/src/ai/orm/document.py](../../backend/src/ai/orm/document.py) | 50 | `documents`, `document_chunks` |
| [backend/src/ai/orm/memory.py](../../backend/src/ai/orm/memory.py) | 41 | `episodic_memories` (legacy) |
| [backend/src/ai/orm/tools.py](../../backend/src/ai/orm/tools.py) | 43 | `tool_registry_entries` |
| [backend/src/ai/orm/trust.py](../../backend/src/ai/orm/trust.py) | 52 | `source_trust_scores` |
| [backend/src/ai/orm/usage.py](../../backend/src/ai/orm/usage.py) | 43 | `usage_logs` |
| [backend/src/ai/orm/__init__.py](../../backend/src/ai/orm/__init__.py) | 47 | Registers every ORM class; re-exports `EntityType` / `RunStatus` |
| [backend/src/ai/models.py](../../backend/src/ai/models.py) | 41 | Deprecated back-compat shim re-exporting `src.ai.orm.*` |
| [backend/src/billing/billing_models.py](../../backend/src/billing/billing_models.py) | 193 | Six billing tables |
| [backend/src/config/models.py](../../backend/src/config/models.py) | 82 | `integration_registry`, `model_task_defaults`, `TASK_TYPES` |
| [backend/src/voice/models.py](../../backend/src/voice/models.py) | 119 | `voice_sessions`, `whatsapp_sessions`, `conversation_history` |
| [backend/src/voice/phone_pool_models.py](../../backend/src/voice/phone_pool_models.py) | 75 | `phone_numbers` |
| [backend/src/ai/campaign_models.py](../../backend/src/ai/campaign_models.py) | 146 | `campaigns`, `campaign_calls`, disposition ordering |
| [backend/src/ai/artifact_models.py](../../backend/src/ai/artifact_models.py) | 117 | `artifacts`, `call_logs`, `call_content` |
| [backend/src/ai/lead_queue_model.py](../../backend/src/ai/lead_queue_model.py) | 81 | `lead_queue` |
| [backend/src/ai/email_models.py](../../backend/src/ai/email_models.py) | 39 | `email_connections` |
| [backend/src/ai/social_models.py](../../backend/src/ai/social_models.py) | 58 | `social_connections` |
| [backend/src/ai/memory/cortex_models.py](../../backend/src/ai/memory/cortex_models.py) | 34 | Re-export shim for the `cortex_memory` package ORM |
| [backend/src/ai/schemas/enums.py](../../backend/src/ai/schemas/enums.py) | 179 | Every kernel enum + `VALID_TRANSITIONS` |
| [backend/src/ai/memory/embedding_service.py](../../backend/src/ai/memory/embedding_service.py) | 450 | Embedding model resolution, batching, attributed metering |
| [backend/src/billing/credit_service.py](../../backend/src/billing/credit_service.py) | — | Wallet creation, daily injection, bucket-priority deduction |
| [backend/migrations/env.py](../../backend/migrations/env.py) | 104 | Alembic async env, dual `target_metadata` |
| [backend/alembic.ini](../../backend/alembic.ini) | — | Alembic configuration |

---

## Gotchas and things that surprise newcomers

- **`phone_numbers` has no Alembic migration.** It is created by
  [migrations/merge_phone_tables.py](../../backend/migrations/merge_phone_tables.py), a
  standalone script that lives *next to* the Alembic `versions/` folder but is not part
  of the chain. A database built only from `alembic upgrade head` will be missing it.
- **`target_metadata` is a list.** `[Base.metadata, cortex_memory.metadata]`. Reduce it
  to one entry and autogenerate will propose dropping the CORTEX tables.
- **The CORTEX ORM lives in `site-packages`, not the repo.** `cortex_memory` is an
  installed package (`hb-cortex-memory 0.1.0`). Its tables have **no foreign keys** to
  host tables — external references are opaque nullable UUIDs by design.
- **Three columns are literally named `metadata`** (`campaigns`, `campaign_calls`,
  `cortex_edges`) and are mapped to differently-named Python attributes. Writing
  `campaign.metadata` gets you SQLAlchemy's table metadata object, not your JSON.
- **`document_chunks.embedding` has no ANN index** while `cortex_nodes.embedding` gets
  HNSW. Legacy document search is a full scan.
- **`execution_runs` has no index on `company_id` or `entity_id`** — only the partial
  idempotency index.
- **Several numeric-looking values are stored as text**: `episodic_memories.total_cost_usd`
  (`String(20)`), `documents.file_size` (`String`), `document_chunks.chunk_index`
  (`String`), `companies.default_daily_credits` (`String`).
- **All `DateTime` columns are naive.** There is no `timezone=True` anywhere. UTC is a
  convention enforced only by `datetime.utcnow` defaults.
- **Only `hierarchical_entities` is soft-deleted.** Deletion sets `status='DELETED'` and
  `deleted_at`, recursively across descendants, and nulls out `documents.entity_id` and
  `template_source_id` on referencing rows ([service.py:203](../../backend/src/ai/service.py:203)).
  Queries must add `.where(status != "DELETED")` themselves — there is no default filter.
- **Run status transitions are advisory.** `validate_transition` warns but never blocks.
  And `REPAIRING` is unreachable: no other status lists it as an allowed target.
- **`tool_registry_entries.name` is globally unique** even though `company_id` is
  nullable, so two tenants cannot register the same custom tool name.
- **`artifacts.campaign_id` points at `hierarchical_entities`, not `campaigns`.**
- **`call_logs.voice_session_id` deliberately has no FK** because the two tables belong
  to different modules; the same is true of `conversation_history.session_id`, which is
  polymorphic across `voice_sessions` and `whatsapp_sessions`.
- **The legacy `assets` table was never dropped.** The artifacts migration says it will
  be "dropped last after verification"; that follow-up migration does not exist.
- **`feature_flags` has no ORM model** and is queried with raw SQL. It is also optional —
  the flag service falls through to env vars and defaults if the table is absent.
- **Two migration files share the `a1b2c3d4e5f6_` filename prefix** with different
  revision ids. Alembic reads the `revision` variable, not the filename.
- **`clean_db.sql` truncates by an explicit table list.** New tables are not covered
  until someone adds them to the array — the list currently omits `cortex_edges`,
  `execution_trace_events`, `source_trust_scores`, `feature_flags`, `lead_queue`,
  `phone_numbers` and `tool_registry_entries` (the last is intentional).

---

## Where to go next

- [04 — Auth, RBAC & multi-tenancy](04-auth-rbac-tenancy.md) — how `company_id` and
  `role` are actually enforced at the API layer.
- [06 — Entities & the execution pipeline](06-execution-pipeline.md) — what writes
  `execution_runs` and its log tables.
- [08 — Memory, CORTEX & RAG](08-memory-and-cortex.md) — how the CORTEX tables are read
  and written at runtime.
- [14 — Billing, costing & credits](14-billing-and-credits.md) — the TB formula,
  `usage_logs` and wallet settlement in depth.
- [12 — Voice, telephony & messaging](12-voice-and-telephony.md) — the call lifecycle
  behind `voice_sessions` and `campaign_calls`.
