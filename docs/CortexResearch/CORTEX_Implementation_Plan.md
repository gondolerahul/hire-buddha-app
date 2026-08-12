# CORTEX — Techno-Functional Implementation Plan
## Converting CORTEX into a pip-installable package and re-integrating it into the host project

> **Audience.** Engineering lead, the implementing engineer(s), and the product owner who needs to sign off on scope/timeline.
> **Status.** Plan. Not yet executed.
> **Companion documents.**
> - `CORTEX_Memory_Architecture.md` — the source of truth for current behavior
> - `CORTEX_Research_Paper.md/.tex` — the design narrative
> - `CORTEX_Evaluation_Plan.md` — the benchmark program (parallel track)

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Goals and Non-Goals](#2-goals-and-non-goals)
3. [Current State Snapshot](#3-current-state-snapshot)
4. [Target Architecture](#4-target-architecture)
5. [Package Design](#5-package-design)
6. [The Seven Decoupling Tasks (D1–D7)](#6-the-seven-decoupling-tasks-d1d7)
7. [Repository and Workflow Strategy](#7-repository-and-workflow-strategy)
8. [Database and Migration Strategy](#8-database-and-migration-strategy)
9. [Testing Strategy](#9-testing-strategy)
10. [Documentation Strategy](#10-documentation-strategy)
11. [CI / CD Pipeline](#11-ci--cd-pipeline)
12. [Versioning and Release Plan](#12-versioning-and-release-plan)
13. [Phased Implementation (Three Stages)](#13-phased-implementation-three-stages)
14. [Host-App Integration Plan](#14-host-app-integration-plan)
15. [Backward Compatibility](#15-backward-compatibility)
16. [Risk Register](#16-risk-register)
17. [Resource and Cost Plan](#17-resource-and-cost-plan)
18. [Acceptance Criteria / Definition of Done](#18-acceptance-criteria--definition-of-done)
19. [Open Decisions Required Before Kickoff](#19-open-decisions-required-before-kickoff)
20. [Appendices](#20-appendices)

---

## 1. Executive Summary

This plan converts CORTEX from a deeply embedded subsystem inside `backend/src/ai/memory/` into a standalone, pip-installable, open-source-ready Python package. The host project then re-consumes the package as a normal dependency.

**Why now.** The CORTEX subsystem is architecturally complete, in production use, and conceptually distinct from the rest of the application. Extracting it (a) reduces blast radius of changes, (b) creates a credible OSS asset for recruiting and credibility, (c) forces clean Protocol-based abstractions that benefit the host app regardless of open-sourcing, and (d) lets external developers adopt the substrate without taking on the host application's planner, governance, or billing code.

**Headline numbers.**

| Dimension | Estimate |
|---|---|
| Engineering effort | ~30 person-days (one senior engineer, ~6 elapsed weeks) |
| Calendar timeline | 10 weeks across three stages (parallelizable with the benchmark plan) |
| API surface stabilization | v0.1.0 published to PyPI at end of Stage C |
| Direct cost | ~$200 PyPI/CI/infra; ~$1,000 in LLM testing budget |
| Host-app disruption window | One controlled cutover (~1 day) at end of Stage B |
| Risk to production | Low if Stage A is executed before Stage B; high if rushed |

**Decision required from leadership.** Approve the three-stage plan, the package name, the license, and the engineer assignment. Once approved, execution is mechanical.

---

## 2. Goals and Non-Goals

### Functional Goals

| ID | Goal | Success indicator |
|---|---|---|
| F1 | A third-party developer can `pip install cortex-memory`, run migrations, and have a working tree memory in under 10 minutes | Documented quickstart works on a clean machine |
| F2 | The host project consumes the package as an external dependency; nothing in the host's `src/ai/memory/` shadows package code | No code in `backend/src/ai/memory/` other than thin host adapters |
| F3 | All current CORTEX behavior is preserved across the cutover | Existing runs replay with identical results; smoke-test pass rate = 100% |
| F4 | The package supports at least three LLM providers and three embedding providers via adapters | Adapter modules ship with the package |
| F5 | The package's API is stable enough to commit to a v1.0 within 6 months of v0.1.0 release | Public API documented and frozen with semver discipline |

### Technical Goals

| ID | Goal |
|---|---|
| T1 | Zero dependency on the host's `src/ai/llm_router`, `usage_service`, `config.models`, `auth`, or `common.database` from inside the package |
| T2 | All external FKs in `cortex_models.py` either become nullable opaque UUIDs or are made configurable via a hook |
| T3 | One ORM `Base` is owned by the package; host can choose to share it or keep separate metadata |
| T4 | Type hints throughout; `mypy --strict` passes on the package |
| T5 | ≥ 85% line coverage on package code |
| T6 | All public methods documented with NumPy/Google-style docstrings |
| T7 | Postgres + Redis are the only required runtime services |

### Non-Goals (explicit)

| ID | Non-goal | Why |
|---|---|---|
| N1 | Do **not** ship the execution engine, planner, governance, billing, or step executor | These are host-app logic, not memory primitives. Shipping them would force opinionated adoption. |
| N2 | Do **not** support SQLite or non-pgvector backends | Recursive CTE + pgvector is the architectural moat |
| N3 | Do **not** provide a sync API in v1 | Modern Python agents are async; sync wrapper can be added in v2 if demand emerges |
| N4 | Do **not** rewrite the Dreaming Engine prompts | They work; ship as-is, evolve via versioned prompt files |
| N5 | Do **not** retrofit older CortexTree versions during cutover | Existing rows continue to work without migration; new behavior applies to new rows |
| N6 | Do **not** commercialize via dual-licensing in v1 | Decision deferred to post-1.0; Apache-2.0 keeps options open |
| N7 | Do **not** bundle a hosted control plane | Out of scope; if commercial, that's a separate product |

---

## 3. Current State Snapshot

A complete description of the existing system is in `CORTEX_Memory_Architecture.md`. The relevant facts for *this* plan:

### 3.1 What's Already Clean

| Component | File | Why it's clean |
|---|---|---|
| Data model | `memory/cortex_models.py` | Self-contained except for FK targets and shared `Base` |
| Tree engine | `memory/cortex_service.py` | No external imports beyond models |
| Semantic graph | `memory/graph_service.py` | Self-contained |
| Domain services | `memory/{knowledge,episodic,experience,intelligence}_tree_service.py` | Each is single-file, single-purpose |
| Dreaming engine | `memory/dreaming_engine.py` | Self-contained except for LLM and embedding deps |
| Dreaming prompts | `memory/dreaming_prompts.py` | Pure string constants |

### 3.2 The Seven Coupling Seams

These are the **only** seams that block extraction. Each gets a dedicated decoupling task in §6.

| Seam | Symptom in current code | Detected in audit |
|---|---|---|
| S1 — LLM provider | `from src.ai.llm_router import LLMRouter` | `cortex_bridge.py`, `cortex_service.py`, `cortex_ingestion.py`, `dreaming_engine.py` |
| S2 — Embedding provider | `from src.common.genai_factory import build_vertex_genai_client` | `memory/embedding_service.py` |
| S3 — Usage / cost tracking | `from src.ai.usage_service import UsageService` | `cortex_bridge.py` |
| S4 — Admin config registry | `from src.config.models import IntegrationRegistry, ModelTaskDefault` | `embedding_service.py` |
| S5 — Shared SQLAlchemy `Base` | `from src.common.database import Base` | `cortex_models.py` |
| S6 — External FK targets | FKs to `companies`, `users`, `hierarchical_entities`, `execution_runs` | `cortex_models.py` |
| S7 — Auth coupling on REST | `from src.auth.dependencies import get_current_user` | `cortex_router.py` |

### 3.3 The 14 Backward-Compat Shim Files

A previous restructuring left re-export stubs in `backend/src/ai/*.py` for `cortex_service`, `cortex_models`, `cortex_router`, `cortex_bridge`, `cortex_ingestion`, `memory_service`, `memory_assembly_service`, `dreaming_engine`, `dreaming_prompts`, `embedding_service`, `episodic_tree_service`, `experience_tree_service`, `intelligence_tree_service`, `knowledge_tree_service`, `graph_service`. Each is 12 lines of `from src.ai.memory.X import *`. These either delete or get rewritten to re-export from the new package.

### 3.4 What's Tangled

- `MemoryRouter` (v1) and `MemoryAssemblyService` (v2) both exist. v1 is the default. v2 is the documented future.
- `EpisodicTreeService.write_episode()` accepts an opaque `run` argument expected to be an `ExecutionRun` ORM row.
- `CortexRouter.recurse()` directly instantiates `ExecutionRun`, which couples it to host scheduling.
- The HTTP API in `cortex_router.py` calls `Depends(get_current_user)` and reads `company_id` from the auth principal.
- Several services do lazy imports of `LLMRouter` to avoid circular imports at module load.

---

## 4. Target Architecture

### 4.1 Boundary

```
┌─────────────────────────────────────────────────────────────┐
│  HOST APPLICATION (backend/)                                │
│                                                             │
│   ExecutionEngine, StepExecutor, Planner, Governance        │
│   │                                                         │
│   ├── Adapters (host-specific):                             │
│   │     • HostLLMProvider (wraps existing LLMRouter)        │
│   │     • HostEmbeddingProvider (wraps Vertex factory)      │
│   │     • HostUsageReporter (wraps UsageService)            │
│   │     • HostRunRegistry (creates ExecutionRun rows)       │
│   │                                                         │
│   └── CortexBridge (lives in host; thin wrapper)            │
│       │                                                     │
│       ▼                                                     │
│   ┌─────────────────────────────────────────────────────┐   │
│   │   cortex-memory  (pip package)                      │   │
│   │                                                     │   │
│   │   CortexRouter  ────  MemoryAssembler              │   │
│   │   DreamingEngine ──── SemanticGraphService         │   │
│   │   KnowledgeTreeService, EpisodicTreeService,       │   │
│   │   ExperienceTreeService, IntelligenceTreeService   │   │
│   │                                                     │   │
│   │   Protocols: LLMProvider, EmbeddingProvider,        │   │
│   │             UsageReporter, RunRegistry              │   │
│   │                                                     │   │
│   │   Providers: openai_*, anthropic_*, vertex_*,       │   │
│   │             sentence_transformers_*, litellm_*      │   │
│   │                                                     │   │
│   │   Models: CortexTree, CortexNode, CortexEdge        │   │
│   │   Migrations: Alembic, shipped with package        │   │
│   └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
                  ▲                          ▲
                  │                          │
                  │ pip install              │ adapter pattern
                  │                          │
            PyPI / GitHub               Provider plugins
```

The contract is one-directional: the host depends on the package; the package never imports from the host.

### 4.2 Plugin Model

Three Protocol interfaces let users plug in their own providers:

```python
# cortex_memory/providers/base.py

class LLMProvider(Protocol):
    async def complete(
        self,
        system: str,
        user: str,
        *,
        temperature: float = 0.3,
        max_tokens: int = 1000,
        task_type: str = "text_generation",
    ) -> LLMResponse: ...

class EmbeddingProvider(Protocol):
    async def embed(
        self, texts: list[str], *, task_type: str = "RETRIEVAL_DOCUMENT"
    ) -> list[list[float] | None]: ...
    @property
    def model_name(self) -> str: ...
    @property
    def vector_dim(self) -> int: ...

class UsageReporter(Protocol):
    async def report(
        self, *, kind: str, model: str, prompt_tokens: int,
        completion_tokens: int, cost_usd: Decimal | None = None,
        run_id: UUID | None = None,
    ) -> None: ...
```

The package ships **reference providers** for OpenAI, Anthropic, Vertex AI (Google), and a `LiteLLMProvider` that wraps the LiteLLM library for "all of the above" via one switch. Embedding ships providers for OpenAI, Vertex, and `sentence-transformers` (CPU-friendly default for tests).

### 4.3 What Stays in the Host

| Component | Reason |
|---|---|
| `ExecutionEngine` | Application's orchestration; not a memory primitive |
| `StepExecutor` | Application's step semantics |
| `Planner`, `RecursiveReasoningEngine`, `MetaReviewer`, `GoalGuard` | Application logic |
| `Governance`, billing, credits | Application logic |
| `CortexBridge` | Becomes a thin host adapter that holds the host's `LLMRouter`, `UsageService`, and Redis; calls into the package |
| HTTP API (`/api/v1/cortex/*`) | Stays in host because it depends on host auth |
| `FailurePatternService` | Reads host's `ExecutionRun` table; not a memory primitive |

### 4.4 What Moves to the Package

| Component | Refactor required |
|---|---|
| `CortexTree`, `CortexNode`, `CortexEdge` ORM models | Switch to own `Base` (S5); drop or parameterize FKs (S6) |
| `CortexRouter` (the 7 ops) | Move as-is; `recurse()` returns data instead of creating `ExecutionRun` (D6) |
| All four domain services | Move as-is |
| `SemanticGraphService` | Move as-is |
| `EmbeddingService` | Replace provider resolution with `EmbeddingProvider` injection (D2, D4) |
| `DreamingEngine` | Accept `LLMProvider` via constructor (D1) |
| `MemoryRouter` (v1) and `MemoryAssemblyService` (v2) | Move; default to v2 in package (host can still pick v1) |
| `CortexIngestionPipeline` | Move; `LLMProvider` injection |
| Dreaming prompts | Move as-is (they're constants) |
| Alembic migrations for the three tables | New, shipped with package |

---

## 5. Package Design

### 5.1 Naming and Licensing

**Required decision before kickoff.** Recommended defaults:

| Option | Status on PyPI | Notes |
|---|---|---|
| `cortex-memory` | Check `pip index versions cortex-memory` | First choice; descriptive |
| `cortexmem` | Check | Shorter, available historically |
| `treemem` | Check | Generic, descriptive of mechanism |
| `kortex` | Check | Distinct spelling, brandable |
| `cortex-agent` | Check | Confuses with broader scope |

**License recommendation.** Apache-2.0. Reasons:
- Permissive enough for commercial adoption (drives uptake).
- Patent grant clause protects contributors.
- Compatible with the broader Python AI ecosystem.
- Leaves dual-licensing for an enterprise edition open.

Reject MIT (no patent grant), AGPL (kills enterprise adoption), GPL-3 (same), BSL (unfamiliar to most adopters).

### 5.2 Module Layout

```
cortex-memory/                            # GitHub repo
├── pyproject.toml
├── README.md
├── LICENSE
├── CHANGELOG.md
├── CONTRIBUTING.md
├── docs/
│   ├── index.md
│   ├── quickstart.md
│   ├── concepts.md
│   ├── api-reference.md
│   ├── providers.md
│   ├── migration-v0-to-v1.md
│   └── adr/                              # Architecture Decision Records
├── examples/
│   ├── minimal_agent.py
│   ├── document_ingestion.py
│   ├── with_litellm.py
│   └── fastapi_service/
├── src/
│   └── cortex_memory/
│       ├── __init__.py                   # Public API re-exports
│       ├── py.typed                      # PEP 561 type marker
│       ├── models/
│       │   ├── __init__.py
│       │   ├── base.py                   # Declarative Base (owned)
│       │   ├── tree.py
│       │   ├── node.py
│       │   ├── edge.py
│       │   └── enums.py
│       ├── tree/
│       │   ├── __init__.py
│       │   ├── router.py                 # CortexRouter — 7 ops
│       │   ├── viewport.py               # NodeSummaryDTO, Viewport, NodeContent
│       │   └── checkpoint.py
│       ├── domains/
│       │   ├── knowledge.py
│       │   ├── episodic.py
│       │   ├── experience.py
│       │   └── intelligence.py
│       ├── graph/
│       │   ├── service.py                # SemanticGraphService
│       │   └── edges.py
│       ├── retrieval/
│       │   ├── assembler.py
│       │   ├── v1_router.py
│       │   └── v2_service.py
│       ├── consolidation/
│       │   ├── engine.py                 # DreamingEngine
│       │   └── prompts.py
│       ├── ingestion/
│       │   ├── document.py               # CortexIngestionPipeline
│       │   └── section_parser.py
│       ├── providers/
│       │   ├── base.py                   # Protocols
│       │   ├── openai.py
│       │   ├── anthropic.py
│       │   ├── vertex.py
│       │   ├── litellm.py
│       │   └── sentence_transformers.py
│       ├── config.py                     # CortexConfig dataclass
│       ├── exceptions.py
│       ├── migrations/                   # Alembic env + versions
│       │   ├── env.py
│       │   ├── script.py.mako
│       │   └── versions/
│       └── cli.py                        # cortex-memory migrate ...
└── tests/
    ├── conftest.py
    ├── unit/
    ├── integration/                       # Postgres via testcontainers
    └── property/                          # Hypothesis-based invariant tests
```

### 5.3 Public API Surface

The package's public surface (importable as `from cortex_memory import X`):

```python
# Core
CortexRouter
CortexConfig

# Models
CortexTree, CortexNode, CortexEdge
CortexNodeType, CortexTreeStatus, CortexNodeStatus
MemoryDomain, ScopeLevel
Base  # SQLAlchemy declarative Base

# DTOs
Viewport, NodeSummaryDTO, NodeContent, CheckpointData

# Domain services
KnowledgeTreeService
EpisodicTreeService
ExperienceTreeService
IntelligenceTreeService

# Graph
SemanticGraphService

# Retrieval
MemoryAssembler          # façade (selects v1 or v2)
MemoryAssemblyService    # v2
MemoryAssemblyResult

# Consolidation
DreamingEngine

# Ingestion
CortexIngestionPipeline

# Providers (Protocols + concrete reference implementations)
LLMProvider, EmbeddingProvider, UsageReporter
OpenAILLM, AnthropicLLM, VertexLLM, LiteLLMProvider
OpenAIEmbeddings, VertexEmbeddings, SentenceTransformersEmbeddings

# Exceptions
CortexError, InvariantViolation, OutOfScopeError, NodeNotFound, TreeNotFound
```

Everything else is implementation detail (`_private`).

### 5.4 The `CortexConfig` Object

A single dataclass replaces the scattered constants currently in `ai/constants.py`:

```python
@dataclass(frozen=True)
class CortexConfig:
    # Tree invariants
    max_children: int = 12
    page_size_tokens: int = 8000
    context_budget_pct: int = 40
    chars_per_token: int = 4

    # Embedding
    embedding_vector_dim: int = 768          # Must match provider's output
    embedding_batch_size: int = 100
    embedding_truncate_chars: int = 8000

    # Graph
    graph_similarity_threshold: float = 0.85
    graph_max_auto_edges_per_node: int = 5
    graph_weight_decay_rate: float = 0.95
    graph_min_edge_weight: float = 0.01
    graph_max_expansion_depth: int = 2
    graph_boost_on_traversal: float = 0.05

    # Dreaming
    dreaming_consolidation_interval_hours: int = 24
    dreaming_min_episodes: int = 5
    dreaming_batch_size: int = 20
    dreaming_observation_confidence_threshold: float = 0.5
    dreaming_pattern_strength_threshold: float = 0.7
    dreaming_observation_cluster_threshold: float = 0.75

    # Memory assembly
    default_memory_pipeline: Literal["v1", "v2"] = "v2"
    default_memory_scope: str = "FULL"

    # Operational
    viewport_cache_ttl_seconds: int = 30
```

Construction example:

```python
config = CortexConfig(max_children=16, graph_max_expansion_depth=3)
router = CortexRouter(db=session, tenant_id=..., config=config, llm=..., embeddings=...)
```

---

## 6. The Seven Decoupling Tasks (D1–D7)

These are the seven concrete refactors that produce a clean package. Each is sized in *engineering days* and lists the files it touches.

### D1 — LLM Provider Abstraction

**Current.** `LLMRouter` is imported in four files via lazy `from src.ai.llm_router import LLMRouter`. Each call uses `task_type`, `system_prompt`, `user_prompt`, `temperature`, `max_tokens` and reads `output`, `prompt_tokens`, `completion_tokens`, `model_name` from the response.

**Target.**

```python
# cortex_memory/providers/base.py

@dataclass
class LLMResponse:
    output: str
    model_name: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: Decimal | None = None

class LLMProvider(Protocol):
    async def complete(
        self, system: str, user: str, *,
        temperature: float = 0.3, max_tokens: int = 1000,
        task_type: str = "text_generation",
    ) -> LLMResponse: ...
```

**Reference adapters.** `OpenAILLM`, `AnthropicLLM`, `VertexLLM`, `LiteLLMProvider`.

**Files affected (package side).** `dreaming_engine.py`, `cortex_ingestion.py`, `cortex_service.py` (coherence pass), and the host-side adapter that wraps `LLMRouter`.

**Effort.** 3 days.

**Acceptance.** Package tests pass with both `OpenAILLM` and a `MockLLM` injected; no `from src.ai.llm_router` remains in the package.

---

### D2 — Embedding Provider Abstraction

**Current.** `EmbeddingService._resolve_embedding_model()` does a four-priority lookup against `IntegrationRegistry` and `ModelTaskDefault` to find a Vertex AI client.

**Target.**

```python
class EmbeddingProvider(Protocol):
    async def embed(
        self, texts: list[str], *, task_type: str = "RETRIEVAL_DOCUMENT"
    ) -> list[list[float] | None]: ...
    @property
    def model_name(self) -> str: ...
    @property
    def vector_dim(self) -> int: ...
```

The `vector_dim` property is critical: it must match the `Vector(N)` declaration on `CortexNode.embedding`. The package validates this at startup and raises `CortexConfigError` on mismatch.

**Reference adapters.** `OpenAIEmbeddings` (1536-dim small, 3072-dim large), `VertexEmbeddings` (768-dim), `SentenceTransformersEmbeddings` (configurable, MiniLM by default = 384-dim for tests).

**Schema impact.** `CortexNode.embedding` becomes `pgvector.Vector(config.embedding_vector_dim)` — i.e., the vector dimension is now a deployment-time choice, not hard-coded to 768. This requires a small migration generator.

**Files affected.** `embedding_service.py`, `cortex_models.py`, all callers of `embed_node`.

**Effort.** 3 days.

**Acceptance.** `pytest` runs offline using `SentenceTransformersEmbeddings`; mismatched-vector-dim raises a clear error.

---

### D3 — Usage Reporter Hook

**Current.** `CortexBridge._generate_summary` calls `UsageService.log_usage(company_id, service_sku, raw_quantity, execution_id)` after every LLM call. `CortexRouter._generate_bridge_paragraphs` logs token counts but does not yet bill.

**Target.**

```python
class UsageReporter(Protocol):
    async def report(
        self, *, kind: str, model: str,
        prompt_tokens: int, completion_tokens: int,
        cost_usd: Decimal | None = None,
        run_id: UUID | None = None,
    ) -> None: ...

class NullUsageReporter:  # default
    async def report(self, **kw) -> None: pass
```

`UsageReporter` is **optional** in the package (defaults to no-op). The host's adapter wraps `UsageService.log_usage`.

**Files affected.** Only `CortexBridge` (host) and `CortexIngestionPipeline` (package). Inside the package, every place that previously called `UsageService.log_usage` calls `self.usage.report(...)`.

**Effort.** 1 day.

**Acceptance.** Package has no `usage_service` imports; the optional `usage_reporter` parameter on every relevant class defaults to a no-op.

---

### D4 — SQLAlchemy Base Ownership

**Current.** `cortex_models.py` imports `from src.common.database import Base`. The host's `Base` carries metadata for *all* host tables.

**Target.** The package owns its own `Base`:

```python
# cortex_memory/models/base.py
from sqlalchemy.orm import DeclarativeBase

class Base(DeclarativeBase):
    pass
```

**Host integration option A (recommended).** Host shares the package's `Base` for the three CORTEX tables and keeps its own `Base` for everything else:

```python
# Host code
from cortex_memory import Base as CortexBase
from src.common.database import Base as HostBase
# Two registries; Alembic configured to scan both.
```

**Host integration option B.** Host keeps a shim that re-exports the package's `Base` as the host's `Base`. Simpler but couples release cycles.

**Decision.** Option A. Host's Alembic config gets a second `target_metadata`.

**Files affected.** `cortex_models.py`, every place that imported `Base` from the host, and host Alembic config.

**Effort.** 2 days.

**Acceptance.** Package's three tables resolve and migrate cleanly; host's other tables are unaffected.

---

### D5 — External FK Targets → Opaque IDs

**Current.** `CortexTree` has FKs to `hierarchical_entities`, `users`, `companies`, `execution_runs`. Outside the host's schema, these tables don't exist.

**Target.** Make these columns **opaque `UUID(as_uuid=True)`** with `nullable=True` (where they aren't already) and **without** an SQL-level FK constraint:

```python
class CortexTree(Base):
    # Was: entity_id = Column(UUID, ForeignKey("hierarchical_entities.id"), nullable=False)
    # Now:
    owner_id   = Column(UUID(as_uuid=True), nullable=False)  # was entity_id
    user_id    = Column(UUID(as_uuid=True), nullable=True)
    tenant_id  = Column(UUID(as_uuid=True), nullable=False)  # was company_id
    run_id     = Column(UUID(as_uuid=True), nullable=True)   # was execution_run_id-related
```

**Naming.** Domain-neutral terms (`owner_id`, `tenant_id`) replace host-specific terms (`entity_id`, `company_id`). The host adapter passes the host's UUIDs in.

**Index/uniqueness.** Indexes on `owner_id`, `tenant_id`, `(tenant_id, owner_id)`, etc. are kept and renamed.

**Files affected.** `cortex_models.py`, every `select(...).where(CortexTree.entity_id == ...)` and `.where(CortexTree.company_id == ...)` across the package.

**Effort.** 4 days (this is the biggest mechanical refactor — touches the most lines).

**Acceptance.** Package compiles and tests pass with no FK to any host table; existing host data is preserved via a forward-only migration that renames columns and drops the FK constraints.

---

### D6 — `ExecutionRun` Decoupling

**Current.** Two coupling points:

1. `CortexRouter.recurse()` directly creates an `ExecutionRun` row: `from src.ai.models import ExecutionRun; child_run = ExecutionRun(...)`.
2. `EpisodicTreeService.write_episode(entity_id, run, runtime_tree_id)` reads `run.id`, `run.status`, `run.total_cost_usd`, `run.total_tokens`, etc., from a typed ORM row.

**Target.**

1. `CortexRouter.recurse()` **stops creating runs**. It returns a `RecurseRequest` dataclass and lets the host create the run:

```python
@dataclass
class RecurseRequest:
    task_node_id: UUID
    task: str
    result_slot: str
    scoped_subtree_root_id: UUID
    tree_id: UUID
    parent_metadata: dict  # owner_id, tenant_id, etc.

async def recurse(self, node_id, task, result_slot, ...) -> RecurseRequest:
    task_node_id = await self.write(...)
    return RecurseRequest(...)
```

The host's `CortexBridge.execute_cortex_step` is responsible for `ExecutionRun(...)` creation and arq enqueue.

2. `EpisodicTreeService.write_episode` accepts a domain-neutral `EpisodeRecord` dataclass:

```python
@dataclass
class EpisodeRecord:
    run_id: UUID
    created_at: datetime
    status: str
    input_data: dict
    result_data: dict | None
    context_state: dict | None
    total_cost_usd: Decimal | None
    total_tokens: int | None
    execution_time_ms: int | None
    runtime_tree_id: UUID | None = None
```

The host constructs `EpisodeRecord` from `ExecutionRun`.

**Files affected.** `cortex_service.py:recurse`, `episodic_tree_service.py:write_episode`, host's `CortexBridge`.

**Effort.** 3 days.

**Acceptance.** Package has no `from src.ai.models import ExecutionRun`; host adapter is < 50 lines.

---

### D7 — Auth-Free API Layer

**Current.** `cortex_router.py` mounts `/api/v1/cortex/*` routes that depend on `get_current_user`.

**Target.** The package ships a `cortex_memory.api` submodule with **auth-agnostic** routes:

```python
from cortex_memory.api import build_router

router = build_router(
    auth=Depends(my_auth_dependency),       # host provides
    resolve_tenant=lambda principal: principal.company_id,
    resolve_user=lambda principal: principal.id,
)
app.include_router(router)
```

`build_router` returns a `fastapi.APIRouter` parameterized by callables the host supplies. The package never imports any auth code.

**Files affected.** `cortex_router.py` becomes `cortex_memory/api/__init__.py`.

**Effort.** 2 days.

**Acceptance.** Package's `examples/fastapi_service/` runs end-to-end with a stub `auth` dependency.

---

### Summary of Decoupling Effort

| Task | Days |
|---|---|
| D1 — LLM provider | 3 |
| D2 — Embedding provider | 3 |
| D3 — Usage reporter | 1 |
| D4 — SQLAlchemy Base | 2 |
| D5 — External FK targets | 4 |
| D6 — ExecutionRun decoupling | 3 |
| D7 — Auth-free API | 2 |
| **Subtotal** | **18 days** |

Plus: packaging (3), testing infra (4), docs (3), examples (2) → ~30 days total.

---

## 7. Repository and Workflow Strategy

### 7.1 Decision: Where Does the Code Live?

Two viable paths:

**Path A — Subdirectory monorepo (recommended).**

```
hb-proto-3/                                    # existing repo
├── backend/
│   └── src/ai/memory/   ←  remains as host adapter layer only
├── packages/
│   └── cortex-memory/   ←  the package, with its own pyproject.toml
└── pyproject.toml        # host root
```

Host installs the package with `pip install -e packages/cortex-memory` during development.

Pros: single PR for cross-cutting changes; clean preserved git history; ergonomic refactor flow.
Cons: must split out before public PyPI release (Stage C).

**Path B — Separate repo from day one.**

Pros: cleaner mental model; forces real decoupling early.
Cons: every cross-cutting change is two PRs; bisecting is harder; refactor velocity drops.

**Recommendation.** Path A through Stages A–B; split to a separate repo at the start of Stage C (after the API stabilizes). Use `git subtree split` to preserve history.

### 7.2 Branching

- `main` of the package tracks releases; protected.
- `dev/cortex-extraction` branch in the monorepo holds Stage A–B work; merged to `main` once stable.
- Stage C uses its own repo with standard GitHub flow.

### 7.3 PR Discipline

Every PR during extraction has:

- A linked task in this plan (e.g., "D5 — rename `entity_id` → `owner_id`").
- A "what could regress" section in the description.
- Either zero changes outside the package or a clear scope note.
- Green CI before review.

---

## 8. Database and Migration Strategy

### 8.1 Package-Owned Migrations

The package ships its own Alembic environment. Three migration scripts at v0.1.0:

1. `001_create_cortex_trees.py`
2. `002_create_cortex_nodes.py`
3. `003_create_cortex_edges.py`

A CLI entry point makes them easy to run:

```bash
cortex-memory migrate --database-url=postgresql+asyncpg://...
cortex-memory migrate downgrade --target=base
```

### 8.2 Host's Existing Data

The host already has populated `cortex_trees`, `cortex_nodes`, `cortex_edges` tables. The cutover must preserve them.

**Cutover migration (one-time, host-side).**

```sql
-- 1. Drop FK constraints (D5).
ALTER TABLE cortex_trees DROP CONSTRAINT cortex_trees_entity_id_fkey;
ALTER TABLE cortex_trees DROP CONSTRAINT cortex_trees_company_id_fkey;
-- ... etc.

-- 2. Rename columns to domain-neutral names (D5).
ALTER TABLE cortex_trees RENAME COLUMN entity_id TO owner_id;
ALTER TABLE cortex_trees RENAME COLUMN company_id TO tenant_id;

-- 3. Confirm vector dimension matches the chosen provider (D2).
--    If host stays on Vertex 768-dim, no change. If they switch to OpenAI
--    1536-dim, a re-embedding pass is required and falls outside this plan.
```

This migration is **not** auto-generated by Alembic — it's a one-shot, host-side script reviewed manually.

### 8.3 Schema Versioning

The package's Alembic `versions/` directory uses a `cortex_` prefix on revision IDs to avoid collision with host migrations. Host Alembic config gets a second `version_table = "alembic_version_cortex"` so both lineages run independently.

### 8.4 Vector Dimension Migration (Future)

If a user switches embedding providers and needs a different `vector_dim`, the package provides a helper:

```bash
cortex-memory reembed --provider=openai --batch-size=100
```

This drops the `embedding` column, recreates it with the new dimension, and re-embeds all nodes that previously had embeddings. Slow but mechanical.

---

## 9. Testing Strategy

### 9.1 Layers

| Layer | What it tests | Tooling |
|---|---|---|
| Unit | Single class/function, no I/O | `pytest`, in-memory mocks |
| Integration | Real Postgres + pgvector via `testcontainers` | `pytest`, `testcontainers-postgres` |
| Property | Invariants 1–4 and Properties 1–2 via fuzz | `hypothesis` |
| Benchmark | Scaling curves and head-to-head accuracy | `pytest-benchmark`, custom harness (see Evaluation Plan) |
| Smoke | End-to-end with `SentenceTransformersEmbeddings` and a real LLM | manual & nightly CI |

### 9.2 Coverage Targets

- Line coverage ≥ 85%.
- Branch coverage ≥ 75%.
- Every public method has at least one unit test and one integration test.
- Every Protocol has a `tests/unit/conftest.py` fixture providing a `MockLLM` / `MockEmbeddings`.

### 9.3 Property-Based Tests

These directly verify the system's design claims:

| Property | Test |
|---|---|
| Invariant 1 (Summary Always Exists) | `test_write_rejects_no_summary_parent` |
| Invariant 2 (No Unbounded Viewports) | `test_reclustering_triggers_at_max_children` |
| Invariant 3 (Content Always Paged) | `test_read_returns_one_page_at_a_time` |
| Invariant 4 (Write-Once) | `test_no_setter_on_content` |
| Property 1 (Bounded Viewport) | `test_viewport_token_count_independent_of_tree_size` |
| Property 2 (Subtree Isolation) | 10,000 random-op fuzz (mirrors Evaluation Plan E7) |

### 9.4 Test Database

`testcontainers` spins up a fresh Postgres 15 + pgvector container per test session. Migrations run once. Each test rolls back its transaction.

### 9.5 CI Test Matrix

| Python | Postgres | pgvector | SQLAlchemy |
|---|---|---|---|
| 3.11 | 15 | 0.5 | 2.0 |
| 3.12 | 15 | 0.5 | 2.0 |
| 3.13 | 16 | 0.6 | 2.0 |

---

## 10. Documentation Strategy

### 10.1 README (front door)

One-pager. Three sections only:

1. **What it is.** (One paragraph: "Persistent, navigable tree memory for LLM agents.")
2. **30-second usage.** (Code block: install, configure, write a node, navigate.)
3. **Links to deep dives.**

### 10.2 Quickstart (≤ 5 minutes)

Step-by-step: prereqs → install → migrate → minimal example → next steps. Targets a developer who has never seen the system.

### 10.3 Concept Guide

The architecture from `CORTEX_Memory_Architecture.md`, trimmed to user-facing material. Includes the seven-operations table and the four-domain table.

### 10.4 API Reference

Generated from docstrings with `mkdocstrings` (mkdocs-material) or `pdoc`. Auto-built on every release.

### 10.5 Providers Guide

How to write a custom `LLMProvider` / `EmbeddingProvider`. Reference implementations are the working examples.

### 10.6 Migration Guides

- `v0-to-v1.md` for adopters of pre-1.0 versions (none exist yet, but the file exists).
- `from-host-monolith.md` for the host project's own cutover.

### 10.7 ADRs

Architecture Decision Records under `docs/adr/`. One per major decision:

- `0001-postgres-only-backend.md`
- `0002-async-only-api.md`
- `0003-package-vs-monorepo.md`
- `0004-license-apache-2.md`
- `0005-six-level-scope.md`
- `0006-vector-dim-configurable.md`

These are short (1–2 pages) and link to the trade-off discussions.

---

## 11. CI / CD Pipeline

GitHub Actions, four workflows:

### 11.1 `ci.yml` (every PR)

- Lint: `ruff check` and `ruff format --check`.
- Type-check: `mypy --strict src/cortex_memory`.
- Unit + integration tests on the matrix above.
- Coverage report uploaded to Codecov.
- Build wheel and source dist; verify they install on a clean venv.

### 11.2 `nightly.yml`

- Run the smoke suite with real OpenAI / Anthropic / Vertex credentials (loaded from GitHub Secrets).
- Run the benchmark suite (subset; full suite is manual).

### 11.3 `release.yml` (on git tag `v*`)

- Re-run CI.
- Build wheel.
- Publish to TestPyPI, install from TestPyPI, run smoke.
- Publish to PyPI.
- Create GitHub Release with changelog.
- Build and deploy docs to GitHub Pages.

### 11.4 `security.yml` (weekly)

- `pip-audit` for dependency CVEs.
- `bandit` for security smells.

### 11.5 Pre-commit Hooks

`.pre-commit-config.yaml` ships with the repo:

- `ruff` (lint + format)
- `mypy` (typing)
- `commitizen` (commit-message convention)

---

## 12. Versioning and Release Plan

### 12.1 Semantic Versioning

- `v0.x.y` — unstable; breaking changes possible between minors.
- `v1.0.0` — public API frozen; breaking changes require a major bump.
- `v1.x.y` — additive only.
- `v2.0.0` — next breaking change cycle.

### 12.2 Release Cadence (proposed)

- `v0.1.0` at end of Stage C (extraction complete, smoke passes).
- Bug-fix releases every 2 weeks for the first 3 months.
- Minor (feature) releases monthly thereafter.
- `v1.0.0` cut when:
  - At least three external users have adopted.
  - Coverage ≥ 90%.
  - All documented APIs have been stable for two minor releases.
  - At least one benchmark from the Evaluation Plan is published.

### 12.3 Deprecation Policy

Public APIs marked `@deprecated` survive at least one minor release. Removal happens on the next major.

---

## 13. Phased Implementation (Three Stages)

### Stage A — Internal Restructure (Weeks 1–3)

**Goal.** All seven coupling seams broken via Protocols, while the code still lives at `backend/src/ai/memory/`. No external visibility yet.

**Tasks.**

| # | Task | Owner | Days |
|---|---|---|---|
| A1 | Define Protocols (`LLMProvider`, `EmbeddingProvider`, `UsageReporter`) in `memory/providers/base.py` | Eng | 1 |
| A2 | Implement host adapters that wrap `LLMRouter`, Vertex factory, `UsageService` | Eng | 2 |
| A3 | Refactor `dreaming_engine.py` to accept `LLMProvider` via constructor (D1) | Eng | 2 |
| A4 | Refactor `cortex_ingestion.py` and `cortex_service.py` similarly (D1) | Eng | 1 |
| A5 | Refactor `embedding_service.py` to accept `EmbeddingProvider` (D2) | Eng | 2 |
| A6 | Make `vector_dim` configurable; validate against schema (D2) | Eng | 1 |
| A7 | Refactor `cortex_bridge.py` to accept `UsageReporter` (D3) | Eng | 1 |
| A8 | Refactor `cortex_service.py:recurse` to return `RecurseRequest` (D6) | Eng | 2 |
| A9 | Refactor `episodic_tree_service.py:write_episode` to accept `EpisodeRecord` (D6) | Eng | 1 |
| A10 | Wire host's `CortexBridge` to construct `RecurseRequest`-based recursion and `EpisodeRecord`-based writes | Eng | 2 |
| A11 | Run full smoke suite; bisect any regressions | Eng | 2 |
| A12 | Add property tests for invariants 1–4 and Properties 1–2 | Eng | 1 |

**Acceptance gate at end of Stage A.**

- [ ] No `from src.ai.llm_router`, `from src.ai.usage_service`, `from src.config.models`, or `from src.ai.models import ExecutionRun` inside `backend/src/ai/memory/`.
- [ ] All existing tests pass.
- [ ] Smoke run of three representative production agents passes with identical outputs (compared via diff).
- [ ] One PR reviewer signs off.

**Go/no-go.** If smoke regresses, halt and fix before proceeding to Stage B.

---

### Stage B — Carve-Out (Weeks 4–6)

**Goal.** Code physically moves to `packages/cortex-memory/` in the monorepo with its own `pyproject.toml`. Host installs it as `-e packages/cortex-memory`.

**Tasks.**

| # | Task | Owner | Days |
|---|---|---|---|
| B1 | Create `packages/cortex-memory/` skeleton (`pyproject.toml`, `src/`, `tests/`, `docs/`, `examples/`) | Eng | 1 |
| B2 | Move `memory/cortex_models.py` → `cortex_memory.models.*`; switch to own `Base` (D4) | Eng | 1 |
| B3 | Rename columns and drop FKs in models (D5) | Eng | 1 |
| B4 | Move `cortex_service.py` → `cortex_memory.tree.router` | Eng | 0.5 |
| B5 | Move domain services → `cortex_memory.domains.*` | Eng | 1 |
| B6 | Move `graph_service.py` → `cortex_memory.graph.service` | Eng | 0.5 |
| B7 | Move `memory_service.py` + `memory_assembly_service.py` → `cortex_memory.retrieval.*` | Eng | 1 |
| B8 | Move `dreaming_engine.py` + prompts → `cortex_memory.consolidation.*` | Eng | 0.5 |
| B9 | Move `cortex_ingestion.py` → `cortex_memory.ingestion.document` | Eng | 0.5 |
| B10 | Refactor REST router with `build_router(auth=..., resolve_tenant=...)` (D7) | Eng | 2 |
| B11 | Write Alembic migrations for the three tables (D4) | Eng | 1 |
| B12 | Write one-shot cutover SQL for the host's existing data | Eng | 1 |
| B13 | Replace host's `backend/src/ai/memory/*.py` files with deletions; replace the 14 shims in `backend/src/ai/*.py` with `from cortex_memory import X` re-exports (or delete them and update all callers) | Eng | 3 |
| B14 | Wire host's `CortexBridge` to import from `cortex_memory` | Eng | 1 |
| B15 | Update host's `pyproject.toml` / `requirements.txt` to include `cortex-memory` as a path dependency | Eng | 0.5 |
| B16 | Run cutover on a staging database; verify data preservation; run full smoke | Eng | 2 |
| B17 | Production cutover (one controlled deploy) | Eng + ops | 0.5 |

**Acceptance gate at end of Stage B.**

- [ ] `backend/src/ai/memory/` directory is empty or contains only host-side adapters (`CortexBridge` and friends).
- [ ] Host's `import cortex_memory` works.
- [ ] All host tests pass.
- [ ] Production has been cut over for at least 24 hours with no regression in any monitored CORTEX metric.
- [ ] One PR reviewer + one operations sign-off.

**Go/no-go.** If post-cutover monitoring shows any regression for ≥ 1 hour, roll back via feature flag (the previous host-side code is preserved on a `pre-extraction` branch). Diagnose, fix, retry.

---

### Stage C — Public Release (Weeks 7–10)

**Goal.** Package is independently installable from PyPI; first external developer can use it without reading source.

**Tasks.**

| # | Task | Owner | Days |
|---|---|---|---|
| C1 | `git subtree split` to a new public repo `github.com/<org>/cortex-memory` | Eng | 0.5 |
| C2 | Write README, quickstart, concept guide | Eng + writer | 3 |
| C3 | Auto-generate API reference (mkdocs-material + mkdocstrings) | Eng | 1 |
| C4 | Write `examples/minimal_agent.py`, `examples/document_ingestion.py`, `examples/with_litellm.py`, `examples/fastapi_service/` | Eng | 2 |
| C5 | Write ADRs (six of them, listed in §10.7) | Eng | 1 |
| C6 | Set up GitHub Actions (CI, nightly, release, security) | Eng | 2 |
| C7 | Reach ≥ 85% line coverage; add integration tests where needed | Eng | 3 |
| C8 | Verify `mypy --strict` passes | Eng | 1 |
| C9 | Publish to TestPyPI; install from TestPyPI in a clean venv; run smoke | Eng | 0.5 |
| C10 | Publish v0.1.0 to PyPI | Eng | 0.5 |
| C11 | Submit to PyPI badges, awesome-lists, Python Weekly | Eng | 0.5 |
| C12 | Write announcement post (blog / HN / r/LocalLLaMA) | Eng + writer | 1 |
| C13 | Onboard at least one external pilot user; collect feedback | Product + Eng | 3 |

**Acceptance gate at end of Stage C.**

- [ ] `pip install cortex-memory` works on Python 3.11/3.12/3.13.
- [ ] A new engineer can complete the quickstart in under 10 minutes.
- [ ] CI is green on `main`.
- [ ] Docs deploy to GitHub Pages.
- [ ] At least one external user has run the quickstart end-to-end and provided feedback.

---

## 14. Host-App Integration Plan

This section describes what changes in the host (`hb-proto-3/backend/`) at the end of Stage B.

### 14.1 Net Code Reduction

```
Removed from host:
  backend/src/ai/memory/cortex_models.py             (~350 lines)
  backend/src/ai/memory/cortex_service.py            (~1100 lines)
  backend/src/ai/memory/cortex_router.py             (~315 lines)
  backend/src/ai/memory/cortex_ingestion.py          (~215 lines)
  backend/src/ai/memory/memory_service.py            (~455 lines)
  backend/src/ai/memory/memory_assembly_service.py   (~325 lines)
  backend/src/ai/memory/graph_service.py             (~400 lines)
  backend/src/ai/memory/dreaming_engine.py           (~560 lines)
  backend/src/ai/memory/dreaming_prompts.py          (~55 lines)
  backend/src/ai/memory/embedding_service.py         (~295 lines)
  backend/src/ai/memory/knowledge_tree_service.py    (~490 lines)
  backend/src/ai/memory/episodic_tree_service.py     (~470 lines)
  backend/src/ai/memory/experience_tree_service.py   (~230 lines)
  backend/src/ai/memory/intelligence_tree_service.py (~275 lines)
  backend/src/ai/memory/assembler.py                 (~150 lines)
  backend/src/ai/memory/__init__.py                  (~25 lines)
  14 shim files in backend/src/ai/                    (~170 lines total)
  -----
  Total removed:   ~5,880 lines

Added to host:
  backend/src/ai/memory/cortex_bridge.py             (kept — ~650 lines)
  backend/src/ai/memory/adapters.py                  (NEW — ~250 lines)
                                                     adapters for LLM, embeddings,
                                                     usage, run-registry, auth.
  -----
  Total added:    ~250 net (cortex_bridge stays; some lines move into adapters)
```

**Net host code reduction: roughly 5,600 lines** moving to an isolated, tested, versioned package.

### 14.2 The Host Adapter File (`adapters.py`)

```python
# backend/src/ai/memory/adapters.py
from cortex_memory.providers import LLMProvider, EmbeddingProvider, UsageReporter, LLMResponse
from src.ai.llm_router import LLMRouter
from src.ai.usage_service import UsageService
from src.common.genai_factory import build_vertex_genai_client

class HostLLMProvider:
    def __init__(self, db, company_id):
        self._router = LLMRouter(db=db, company_id=company_id)

    async def complete(self, system, user, *, temperature=0.3, max_tokens=1000, task_type="text_generation"):
        resp = await self._router.call_llm(
            task_type=task_type, system_prompt=system, user_prompt=user,
            temperature=temperature, max_tokens=max_tokens,
        )
        return LLMResponse(
            output=resp.output, model_name=resp.model_name,
            prompt_tokens=resp.prompt_tokens or 0,
            completion_tokens=resp.completion_tokens or 0,
        )

class HostEmbeddingProvider: ...   # similar, wraps Vertex factory
class HostUsageReporter: ...       # similar, wraps UsageService.log_usage
class HostRunRegistry: ...         # creates ExecutionRun rows for recurse()
```

### 14.3 Updated `CortexBridge`

The host's `CortexBridge` becomes a thin adapter that holds providers and forwards to the package:

```python
# backend/src/ai/memory/cortex_bridge.py (post-extraction)
from cortex_memory import CortexRouter, CortexConfig
from src.ai.memory.adapters import HostLLMProvider, HostEmbeddingProvider, HostUsageReporter, HostRunRegistry

class CortexBridge:
    def __init__(self, db, company_id, usage_service=None, redis=None):
        llm = HostLLMProvider(db, company_id)
        emb = HostEmbeddingProvider(db, company_id)
        usage = HostUsageReporter(usage_service or UsageService(db))
        runs = HostRunRegistry(db, company_id)
        config = CortexConfig()
        self.cortex = CortexRouter(
            db=db, tenant_id=company_id, config=config,
            llm=llm, embeddings=emb, usage=usage, runs=runs,
        )
        self.redis = redis
        # ... rest of bridge logic stays unchanged
```

### 14.4 Host Config Changes

- `backend/pyproject.toml` adds `cortex-memory = { path = "../packages/cortex-memory", develop = true }` during Stage B, then `cortex-memory = "^0.1.0"` from PyPI after Stage C.
- `backend/alembic.ini` adds a second migration directory for the package's migrations OR the host adds `cortex-memory migrate` as a post-deploy step.

### 14.5 Execution-Engine Changes

`backend/src/ai/core/execution_engine.py` line 475 currently does:

```python
cortex = CortexService(db=self.db, company_id=entity.company_id)
```

Becomes:

```python
cortex = self._cortex_bridge.cortex   # already configured with providers
```

No other engine logic changes. The five lifecycle phases C1–C5 stay identical.

---

## 15. Backward Compatibility

### 15.1 Host Code

The 14 shim files in `backend/src/ai/*.py` either:

- **Option 1.** Get rewritten as `from cortex_memory import *` re-exports, preserving the old import paths for one quarter, then deleted.
- **Option 2.** Get deleted at Stage B with a sweep that updates all callers.

Recommendation: Option 2 if the shim files have ≤ 50 callers (they do, based on grep). Single-PR sweep.

### 15.2 Database

- No data loss. Existing rows preserved through the column rename in §8.2.
- The dropped FK constraints become opaque UUIDs that still point to the right rows.
- Indexes are kept and renamed where columns are renamed.

### 15.3 HTTP API

- Endpoint paths under `/api/v1/cortex/*` are preserved.
- Request/response schemas unchanged.
- Auth wrapping moves from inline to the `build_router(auth=...)` parameter.

### 15.4 Behavior

- All current production behavior is preserved bit-for-bit through Stage B.
- New behavior (configurable `vector_dim`, optional providers) is opt-in.

### 15.5 What Does Change

- Some import paths inside the host (`from src.ai.memory.X` → `from cortex_memory.Y`). This is mechanical; an IDE-driven find-and-replace handles it.
- Two new dependencies in the host's `pyproject.toml`: `cortex-memory`, and the chosen `cortex-memory[provider]` extras.

---

## 16. Risk Register

| ID | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| R1 | Cutover causes production regression | Medium | High | Stage A's smoke gate; staging cutover before prod; feature flag with instant rollback |
| R2 | The 7th decoupling task (auth-free API) breaks the frontend | Low | Medium | The frontend talks to host routes; the package only ships a router *builder*; host keeps its route registration |
| R3 | Vector-dim mismatch causes silent data corruption | Low | High | Runtime validation on package init; CI test |
| R4 | Performance regresses due to extra abstraction layer | Low | Medium | Benchmarks (Evaluation Plan E3) before and after; rollback if > 5% |
| R5 | PyPI name collision | Low | Low | Reserve name in week 1; have two fallbacks |
| R6 | License decision blocks publication | Low | Low | Decide before kickoff (§19) |
| R7 | Engineer pulled to other work mid-extraction | Medium | High | Stages are independent; an unfinished Stage A is recoverable; an unfinished Stage B is not |
| R8 | Maintenance burden post-release exceeds capacity | Medium | Medium | Honest scoping: budget 4 hours/week per maintainer; if uptake is low, archive cleanly |
| R9 | External users find security issues post-release | Low | High | Security workflow + responsible-disclosure file in repo |
| R10 | The benchmark plan (parallel track) produces unfavorable numbers | Medium | High | Run benchmarks before publishing; if results are flat, delay v0.1.0 or reframe scope |
| R11 | Alembic migration collision with host | Low | Medium | Separate `alembic_version_cortex` table + revision-ID prefix |
| R12 | `ExecutionRun`-decoupling regression: child runs don't get enqueued | Medium | High | Smoke test that explicitly exercises RECURSE; canary deploy |

---

## 17. Resource and Cost Plan

### 17.1 People

- **1 senior engineer**, full-time, for 6–10 weeks (depending on stage scope).
- **0.25 senior engineer** for code review across the project.
- **0.1 technical writer** for Stage C docs polish (~3 days).
- **0.1 operations engineer** for the Stage B cutover and Stage C release infra.

### 17.2 Direct Costs

- ~$100 PyPI / domain / CI minutes (most free for OSS).
- ~$1,000 LLM testing budget (covers Stage A smoke runs and Stage C smoke).
- ~$500 contingency.

### 17.3 Time-to-Value

- End of Stage A (week 3): No external value yet; internal code health improvement.
- End of Stage B (week 6): Host runs on packaged code. Internal value: ~5,600 lines isolated; faster CI; clearer ownership.
- End of Stage C (week 10): External value begins. PyPI release + announcement.

---

## 18. Acceptance Criteria / Definition of Done

### 18.1 Project DONE when ALL of:

- [ ] `pip install cortex-memory` from PyPI installs cleanly on Python 3.11+.
- [ ] A new developer completes the quickstart in ≤ 10 minutes from a clean machine.
- [ ] The host project's `backend/src/ai/memory/` contains only the `CortexBridge` and `adapters.py` (host-specific).
- [ ] No imports in the package reference any `src.*` module.
- [ ] `mypy --strict` passes on the package.
- [ ] Line coverage ≥ 85%.
- [ ] All host smoke tests pass.
- [ ] Production has been running on the packaged version for ≥ 7 days with no regression.
- [ ] Docs are deployed and complete: README + quickstart + concept guide + API reference + 6 ADRs.
- [ ] At least one example in `examples/` runs end-to-end without modification.
- [ ] The first external user has successfully used the package and submitted at least one piece of feedback.
- [ ] A changelog entry exists for v0.1.0.
- [ ] The release process is automated via GitHub Actions.

### 18.2 Project NOT DONE if any of:

- Any decoupling task (D1–D7) is incomplete.
- The cutover from host code is not yet on production.
- The package has any `from src.` import.
- Coverage is < 85%.
- Quickstart fails on a clean machine.

---

## 19. Open Decisions Required Before Kickoff

These need owners and signed-off answers before Stage A starts.

| # | Decision | Owner | Default |
|---|---|---|---|
| Q1 | Final package name on PyPI | Product / Eng lead | `cortex-memory` |
| Q2 | License | Legal / Eng lead | Apache-2.0 |
| Q3 | GitHub org for the public repo | Eng lead | `<your-org>` |
| Q4 | Whether to ship a hosted control plane in scope | Product | No (out of scope per N7) |
| Q5 | Vector dimension default for v0.1.0 | Eng lead | 768 (matches existing Vertex deployments) |
| Q6 | Default LLM provider in docs/quickstart | Eng lead | OpenAI (broadest reach) + LiteLLM as the "all of the above" path |
| Q7 | Trademark / brand check on the chosen name | Legal | Required |
| Q8 | Whether to dual-license now or defer to post-1.0 | Product / Legal | Defer |
| Q9 | Owner for ongoing maintenance | Eng manager | 1 engineer at 4 h/week |
| Q10 | Initial release announcement venue | Product | HN + r/LocalLLaMA + Python Weekly |

---

## 20. Appendices

### Appendix A — Reference `pyproject.toml`

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "cortex-memory"
version = "0.1.0"
description = "Persistent, navigable, writable tree memory for LLM agents."
readme = "README.md"
license = "Apache-2.0"
requires-python = ">=3.11"
authors = [{ name = "<TBD>" }]
keywords = ["llm", "agent", "memory", "rag", "cognitive-architecture"]
classifiers = [
    "Development Status :: 3 - Alpha",
    "Programming Language :: Python :: 3.11",
    "Programming Language :: Python :: 3.12",
    "Programming Language :: Python :: 3.13",
    "License :: OSI Approved :: Apache Software License",
    "Topic :: Scientific/Engineering :: Artificial Intelligence",
]
dependencies = [
    "sqlalchemy[asyncio]>=2.0",
    "asyncpg>=0.29",
    "pgvector>=0.2",
    "alembic>=1.13",
    "pydantic>=2.6",
    "tenacity>=8",
    "redis>=5",
]

[project.optional-dependencies]
openai = ["openai>=1.30"]
anthropic = ["anthropic>=0.40"]
vertex = ["google-genai>=0.5"]
litellm = ["litellm>=1.40"]
local = ["sentence-transformers>=2.7"]
api = ["fastapi>=0.110"]
all = ["cortex-memory[openai,anthropic,vertex,litellm,local,api]"]
dev = [
    "pytest>=8", "pytest-asyncio>=0.23", "pytest-cov>=5",
    "testcontainers[postgres]>=4", "hypothesis>=6.100",
    "ruff>=0.5", "mypy>=1.10", "pre-commit>=3.7",
]

[project.scripts]
cortex-memory = "cortex_memory.cli:main"

[project.urls]
Documentation = "https://<org>.github.io/cortex-memory"
Repository = "https://github.com/<org>/cortex-memory"
Issues = "https://github.com/<org>/cortex-memory/issues"
Changelog = "https://github.com/<org>/cortex-memory/blob/main/CHANGELOG.md"

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.mypy]
strict = true
python_version = "3.11"
```

### Appendix B — Minimal Working Example (target)

```python
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from cortex_memory import CortexRouter, CortexConfig, Base
from cortex_memory.providers import OpenAILLM, OpenAIEmbeddings

async def main():
    engine = create_async_engine("postgresql+asyncpg://localhost/cortex_demo")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with Session() as db:
        config = CortexConfig(embedding_vector_dim=1536)  # OpenAI small
        llm  = OpenAILLM(model="gpt-4o-mini")
        emb  = OpenAIEmbeddings(model="text-embedding-3-small")

        router = CortexRouter(
            db=db, tenant_id="00000000-0000-0000-0000-000000000001",
            config=config, llm=llm, embeddings=emb,
        )

        tree = await router.create_tree(
            owner_id="00000000-0000-0000-0000-000000000002",
            task_description="Draft Q3 report",
        )
        node = await router.write(
            parent_id=tree.root_node_id, node_type="finding",
            title="Revenue", summary="Q3 revenue analysis",
            content="Q3 revenue was $4.2M, up 18% YoY...",
        )
        viewport = await router.navigate(tree.root_node_id)
        print(viewport.to_prompt_text())
        await db.commit()

asyncio.run(main())
```

### Appendix C — Pre-Kickoff Checklist

Before Stage A begins, confirm:

- [ ] Decisions Q1–Q10 in §19 are signed off.
- [ ] Engineer is assigned and calendared for 6 weeks.
- [ ] Staging database has been backed up.
- [ ] Production CORTEX metrics dashboard exists for regression detection (latency, error rate, write throughput, embedding success rate).
- [ ] Feature flag plumbing exists for the cutover (host can fall back to `pre-extraction` code path via env var).
- [ ] Stakeholders (product, ops, security) have read the Risk Register (§16).

### Appendix D — Glossary (Plan-Specific)

| Term | Meaning |
|---|---|
| **The host** | The `hb-proto-3` backend application |
| **The package** | The future `cortex-memory` Python package |
| **Cutover** | The single deploy that switches host imports from `src.ai.memory` to `cortex_memory` |
| **Coupling seam** | A specific import-or-FK that crosses the host/package boundary |
| **Stage gate** | A checklist that must pass before the next stage starts |
| **Smoke suite** | A fixed set of production-representative agent runs with deterministic outputs |
| **Decoupling task (D1–D7)** | One of seven concrete refactors enumerated in §6 |

---

## Closing Note

This plan is sized to be executed by **one** focused senior engineer in **6 elapsed weeks** for Stages A and B (the high-leverage internal work), with **another 4 weeks** for Stage C (the open-source polish). The host project sees no behavior change; the engineering organization gains a clean, tested, independently versioned subsystem; the broader ecosystem gains a new memory framework with a credible architectural pedigree.

If the open-source ambition is dropped post-Stage B (e.g., because maintenance bandwidth is unavailable), the work done in Stages A and B is still valuable: it leaves the host's CORTEX subsystem properly abstracted, testable in isolation, and recoverable should the OSS path be re-opened later.

The single most important commitment leadership makes by approving this plan is **not** "we will publish a package" — it is **"we will own the maintenance burden of a public package for at least 12 months."** If that commitment is not solid, run Stages A and B only.

---

*End of CORTEX Implementation Plan.*
