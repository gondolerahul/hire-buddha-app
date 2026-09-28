# `memory/` — Cortex substrate, four typed domains, Dreaming engine

The agent never gets raw context — it gets a *viewport*. Every
durable thing the system remembers (knowledge, experience,
intelligence, episodic) is a typed view over the CORTEX tree.

## What's in here

| File | Purpose |
|------|---------|
| `cortex_service.py` | The 7-operation CORTEX engine (NAVIGATE / READ / WRITE / RECURSE / AWAIT_CHILDREN / CHECKPOINT). Track 6 added `ScopePolicy` enforcement and a Provenance-aware `write(...)`. |
| `cortex_models.py` | `CortexTree` / `CortexNode` ORM + enums (`CortexNodeType`, `MemoryDomain`, `ScopeLevel`). |
| `cortex_bridge.py`, `cortex_ingestion.py`, `cortex_router.py` | HTTP / ingestion glue. |
| `scope_policy.py` | Declarative `ScopePolicy` + `ScopeViolation`. Strict by default. |
| `run_memory.py` | The AgentLoop's per-run wiring: `open_run_tree` (the run's CORTEX tree), `assemble_run_memory` (the memory read path — assembles once per run and returns the `RunMemory` reader the Perceiver and critic use) and `record_episode` (writes the finished run into its entity's Episodic Tree). |
| `assembler.py` | `assemble_memory(...)` — maps `memory_scope` to domains and renders the `__memory__` block. |
| `memory_assembly_service.py` | Four-domain assembly. |
| `domains/` | Track 6 `DomainTreeBase` + per-domain retrieval weights (semantic / recency / user_match / success). |
| `knowledge_tree_service.py`, `episodic_tree_service.py`, `experience_tree_service.py`, `intelligence_tree_service.py` | One per memory domain. Each is a typed view over CORTEX. Uploaded documents live only in Knowledge Trees — the entity's, or the company-wide (tenant-scoped) tree for documents without an entity. |
| `task_classifier.py` | v1 rule-based + v2 embedding NN; emits a stable `task_class` string consumed by bandit + calibration + supervisor. |
| `dreaming_engine.py`, `dreaming_prompts.py` | Cron + outcome-triggered consolidator (writes confirmed Intelligence rules). |
| `embedding_service.py` | Per-company embedding resolver with `EMBEDDING_MODEL_FALLBACK` fallback. `resolve_embedding_model(db, company_id)` is the standalone helper. |
| `graph_service.py` | Cortex edge / semantic-graph layer. |

## Key types

- `Viewport` — `to_prompt_text(include_ops_help=False, max_chars=4000)`.
- `NodeSummaryDTO`, `NodeContent`, `CheckpointData`.
- `ScopePolicy`, `ScopeViolation`.
- `Provenance`, `SourceType`, `DEFAULT_TRUST_BY_SOURCE` (in `schemas/cortex.py`).
- `DomainItem`, `DomainTreeBase`, `KnowledgeWeights / EpisodicWeights / ExperienceWeights / IntelligenceWeights`.

## Entry points

- `assemble_run_memory(...)` is the AgentLoop's entry point: once per run it puts `__memory__` into the step prompt (sandwich layer 9), `__intelligence_rules__` into the planner, and a `RunMemory` reader into the Perceiver / supervisor critic. It is gated per entity by `capabilities.memory` (`enabled`, `memory_scope`).
- `CortexService(scoped_subtree_root_id=..., scope_policy=...)` is the only legal write path.
- The Dreaming engine is triggered by `core/arq_jobs.dreaming_outcome_trigger` (from `AgentLoop._finalize`) and by the existing cron.

## See also

- `docs/phase11/plan/08_track_6_memory_v2.md`
- `core/INTERNAL_KEYS.md` — keys inside the legacy `context_state` bridge.
