# 07 — Proposed Folder / File Restructure

The codebase is now part-way through the Phase 10A move. This document
finishes the job: a single, mechanically-applied layout that any new
contributor can reason about in 10 minutes.

> The intent is **not** to invent a new architecture. It is to make the
> architecture that already exists in the code **visible from the
> directory tree**.

---

## 1. Current state (the half-refactor)

```
backend/src/ai/
├── __init__.py
├── artifact_*.py                  (3 files: models, router, service)
├── campaign_*.py                  (5 files: executor, models, router, service, worker)
├── constants.py
├── core/                          ✅ established
│   ├── __init__.py
│   ├── arq_jobs.py
│   ├── context_utils.py
│   ├── exceptions.py
│   ├── execution_engine.py
│   ├── meta_review.py
│   ├── prompt_utils.py
│   └── recursive_engine.py
├── email_*.py                     (models, router)
├── entity_clone_helpers.py        ⚠ unclear home
├── failure_pattern_service.py     ⚠ barely used
├── governance/                    ✅ established
│   ├── governance_service.py
│   └── rate_limiter.py
├── lead_queue_*.py                (3 files: model, service, worker)
├── llm/                           ✅ established
│   ├── anthropic_adapter.py
│   ├── azure_adapter.py
│   ├── base.py
│   ├── gemini_adapter.py
│   ├── router.py
│   └── types.py
├── memory/                        ✅ established
│   ├── assembler.py
│   ├── cortex_bridge.py
│   ├── cortex_ingestion.py
│   ├── cortex_models.py
│   ├── cortex_router.py           ⚠ HTTP router
│   ├── cortex_service.py          ⚠ class name 'CortexRouter' confusing
│   ├── dreaming_engine.py
│   ├── dreaming_prompts.py
│   ├── embedding_service.py
│   ├── episodic_tree_service.py
│   ├── experience_tree_service.py
│   ├── graph_service.py
│   ├── intelligence_tree_service.py
│   ├── knowledge_tree_service.py
│   ├── memory_assembly_service.py
│   └── memory_service.py
├── meta/                          ✅ established
│   ├── anti_sprawl.py
│   ├── meta_agent_template.py
│   ├── platform_schema_compiler.py
│   ├── registry_search_service.py
│   └── seed_meta_agent.py
├── migrate_documents_to_knowledge_trees.py   ⚠ migration in runtime pkg
├── migrate_episodic_to_trees.py              ⚠ migration in runtime pkg
├── models.py                      (SQLAlchemy ORM, single big file)
├── persona_service.py
├── planning/                      ✅ established
│   ├── goal_alignment.py
│   ├── goal_guard.py
│   └── planner_service.py
├── reports_*.py                   (router, service)
├── router.py                      (FastAPI HTTP router — entities, executions, docs)
├── schemas.py                     ⚠ 970 lines, all domains
├── service.py                     (HTTP service layer)
├── shared/
│   ├── json_utils.py
│   └── text_utils.py
├── social_*.py                    (connection_service, models, router)
├── step_executor.py               ⚠ 1497 lines
├── text_extractor.py              ⚠ generic util in pkg root
├── tool_executor.py
├── tool_fallback.py
├── tool_management_*.py           (router, service)
├── tools/                         ✅ established
│   ├── ...23 tools...
│   ├── meta/
│   └── social/                    (15 platform integrations)
├── usage_service.py
└── worker.py                      (now ~80 lines, just Arq settings)
```

(plus ghosted top-level duplicates in the git index — see §02)

---

## 2. Proposed layout (after Phase 11 restructure)

```
backend/src/ai/
├── README.md                      ← module-level architecture
├── __init__.py                    ← keep re-exports minimal
│
├── api/                           ← HTTP layer (was: router.py / *_router.py)
│   ├── __init__.py
│   ├── entities.py                ← /entities CRUD
│   ├── executions.py              ← /execute + /executions
│   ├── documents.py               ← /documents
│   ├── templates.py               ← /templates
│   ├── approvals.py               ← /approvals
│   ├── tools.py                   ← /tools
│   ├── reports.py                 ← /reports
│   ├── tool_management.py
│   ├── artifacts.py
│   ├── campaigns.py
│   ├── email.py
│   ├── social.py
│   ├── cortex.py                  ← /api/v1/cortex
│   └── deps.py                    ← FastAPI deps
│
├── schemas/                       ← was: schemas.py (split per domain)
│   ├── __init__.py                ← convenience re-exports
│   ├── enums.py                   ← EntityType, RunStatus, ReasoningMode, StepType, …
│   ├── entity.py                  ← HierarchicalEntity{Base,Create,Update,Response}, Persona, Hierarchy
│   ├── planning.py                ← PlanStep, StaticPlan, DynamicPlanning, AllowedDeviations, ExitCondition
│   ├── reasoning.py               ← LogicGate, ReasoningConfig, RetryPolicy, ReviewMechanism, ContextPolicy
│   ├── capabilities.py            ← Capabilities, MetaCognitionConfig, MemoryConfig, ContextEngineering, ToolReference
│   ├── governance.py              ← Governance, HITLCheckpoint, ExecutionLimits
│   ├── io_contract.py             ← IOContract, ContextSource
│   ├── execution.py               ← ExecutionRun{Create,Refine,Response,Summary}, LLM/Tool/HumanApproval responses
│   ├── cortex.py                  ← CORTEX HTTP schemas + GoalNode
│   ├── tools.py                   ← ToolRegistryEntry{Create,Update,Response}
│   └── prompts.py                 ← DEFAULT_PLANNING_SYSTEM_PROMPT, DEFAULT_REVIEW_SYSTEM_PROMPT
│
├── orm/                           ← was: models.py (split per domain)
│   ├── __init__.py
│   ├── base.py                    ← Base, DeclarativeBase
│   ├── entity.py                  ← HierarchicalEntity
│   ├── execution.py               ← ExecutionRun, LLMInteractionLog, ToolInteractionLog, HumanApproval
│   ├── document.py                ← Document, DocumentChunk
│   ├── memory.py                  ← EpisodicMemory (legacy table)
│   ├── cortex.py                  ← CortexTree, CortexNode, CortexEdge
│   ├── campaign.py
│   ├── artifact.py
│   ├── lead_queue.py
│   ├── usage.py                   ← UsageLog
│   └── email.py
│
├── core/                          ← orchestration kernel
│   ├── __init__.py
│   ├── agent_loop.py              ← NEW: top-level loop (§03)
│   ├── agent_state.py             ← NEW: typed AgentState envelope
│   ├── budget.py                  ← NEW: Budget tracker
│   ├── perceiver.py               ← NEW
│   ├── strategist.py              ← NEW
│   ├── observer.py                ← NEW
│   ├── reflector.py               ← NEW
│   ├── executors/                 ← swappable executors
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── single_step.py         ← was: step_executor._execute_step routing
│   │   ├── dag.py                 ← was: execution_engine._execute_steps_dag
│   │   ├── recursive.py           ← was: core/recursive_engine.py
│   │   ├── child_entity.py        ← was: step_executor._execute_child_invocation
│   │   ├── dialog.py              ← NEW
│   │   ├── tool_burst.py          ← NEW
│   │   └── skill.py               ← NEW
│   ├── reasoning/                 ← reasoning modes as strategies
│   │   ├── __init__.py
│   │   ├── react.py               ← REACT loop (was inside step_executor)
│   │   ├── chain_of_thought.py
│   │   ├── reflection.py
│   │   └── tree_of_thoughts.py
│   ├── arq_jobs.py                ← unchanged
│   ├── exceptions.py
│   ├── prompt_builder.py          ← was: prompt_utils.build_sandwich_prompt
│   ├── prompt_variables.py        ← was: prompt_utils.parse_variables
│   ├── context_utils.py
│   └── constants.py               ← was: ai/constants.py
│
├── planning/
│   ├── __init__.py
│   ├── planner.py                 ← was: planner_service.py (PlanGenerator + adapter)
│   ├── plan_invariants.py         ← NEW (§05)
│   ├── child_resolver.py          ← NEW (consolidates child_id resolution)
│   ├── critic_pipeline.py         ← NEW (pre/post/align/super critics)
│   ├── goal_guard.py
│   ├── goal_alignment.py
│   └── failure_tags.py            ← NEW (closed enum for critic verdicts)
│
├── memory/
│   ├── __init__.py
│   ├── cortex_service.py          ← class renamed to CortexService
│   ├── cortex_bridge.py
│   ├── cortex_ingestion.py
│   ├── cortex_models.py           ← Pydantic DTOs (move ORM models to orm/cortex.py)
│   ├── domains/
│   │   ├── __init__.py
│   │   ├── base.py                ← DomainTreeBase (§06)
│   │   ├── knowledge.py
│   │   ├── episodic.py
│   │   ├── experience.py
│   │   └── intelligence.py
│   ├── assembler.py               ← only v2 path; legacy_reader for v1
│   ├── legacy_episodic_reader.py  ← read-only adapter for old EpisodicMemory rows
│   ├── graph_service.py
│   ├── dreaming/
│   │   ├── __init__.py
│   │   ├── engine.py
│   │   ├── prompts.py
│   │   └── scheduler.py           ← NEW: outcome-triggered consolidation
│   └── embedding_service.py
│
├── meta/                          ← Meta-Agent (the architect)
│   ├── __init__.py
│   ├── board/                     ← NEW: multi-role architecture board (§04)
│   │   ├── __init__.py
│   │   ├── requirement_chat.py
│   │   ├── architect.py
│   │   ├── critic.py
│   │   ├── validator.py
│   │   ├── test_driver.py
│   │   ├── promoter.py
│   │   └── curator.py
│   ├── meta_agent_template.py     ← becomes thin orchestrator
│   ├── seed_meta_agent.py
│   ├── platform_schema_compiler.py
│   ├── registry_search_service.py
│   ├── anti_sprawl.py
│   ├── meta_intelligence_tree.py  ← NEW (§04)
│   ├── skill_library.py           ← NEW (§04)
│   └── tool_synthesis.py          ← NEW (P3)
│
├── governance/
│   ├── __init__.py
│   ├── governance_service.py
│   ├── rate_limiter.py
│   └── tool_cost_resolver.py      ← NEW (consolidates duplicate tool cost lookup)
│
├── llm/                           ← keep
│   ├── router.py
│   ├── base.py
│   ├── types.py
│   ├── anthropic_adapter.py
│   ├── azure_adapter.py
│   └── gemini_adapter.py
│
├── tools/                         ← tool registry + impls
│   ├── __init__.py                ← registrations
│   ├── base.py
│   ├── resilience.py              ← NEW (reformat-retry + fallback)
│   ├── core/                      ← built-in tools
│   │   ├── calculator.py
│   │   ├── search.py
│   │   ├── batch_search.py
│   │   ├── scraper.py
│   │   ├── browser_tool.py
│   │   ├── text_extractor.py      ← was: ai/text_extractor.py
│   │   └── file_writer.py
│   ├── documents/
│   │   ├── pdf_generator.py
│   │   ├── docx_tool.py
│   │   ├── pptx_tool.py
│   │   ├── excel.py
│   │   ├── xlsx_engine.py
│   │   └── document_save.py
│   ├── media/
│   │   ├── image_generation.py
│   │   └── video_generation.py
│   ├── sandbox/
│   │   ├── sandbox_executor.py
│   │   ├── sandbox_provision.py
│   │   └── terminal_tool.py
│   ├── email/
│   │   └── email_tool.py
│   ├── crm/
│   │   └── crm_tools.py
│   ├── integrations/
│   │   ├── social/
│   │   │   └── ... (15 platforms)
│   │   └── ads/
│   │       └── ...
│   ├── meta/                      ← unchanged
│   │   ├── platform_introspect.py
│   │   ├── registry_search.py
│   │   ├── schema_validator.py
│   │   ├── entity_creator.py
│   │   ├── entity_executor.py
│   │   └── spec_critic.py         ← NEW
│   └── management/                ← was: tool_management_*.py
│       ├── router.py              ← /tools admin endpoints
│       └── service.py
│
├── billing/                       ← was: src/billing (already there, leave)
│
├── services/                      ← long-running services not part of core loop
│   ├── __init__.py
│   ├── ai_service.py              ← was: service.py
│   ├── usage_service.py
│   ├── persona_service.py
│   ├── failure_pattern_service.py
│   ├── entity_lifecycle.py        ← was: entity_clone_helpers.py
│   ├── reports_service.py
│   ├── artifact_service.py
│   ├── lead_queue_service.py
│   ├── campaign_service.py
│   ├── campaign_executor.py
│   ├── campaign_worker.py
│   ├── lead_queue_worker.py
│   ├── social_connection_service.py
│   └── email_service.py            ← consolidate email_models / email_router HTTP layer split into api/email.py
│
├── shared/
│   ├── json_utils.py
│   └── text_utils.py
│
└── worker.py                      ← Arq WorkerSettings (NO re-exports)
```

Then at the repo root:

```
backend/scripts/
├── migrations/
│   ├── documents_to_knowledge_trees.py     (was: ai/migrate_documents_…)
│   └── episodic_to_trees.py                (was: ai/migrate_episodic_…)
└── seeds/
    ├── deep_research/                       (was: /DeepResearchSetup)
    └── default_entities/                    (was: /SeedEntities)
```

---

## 3. What this layout makes obvious

* `core/` answers "how does the agent think?"
* `planning/` answers "how does the agent decide what to do next?"
* `memory/` answers "what does the agent remember?"
* `meta/` answers "how does the platform build and improve its agents?"
* `governance/` answers "what is the agent allowed to do?"
* `tools/` answers "what can the agent reach for?"
* `api/` answers "how does the outside world talk to all of this?"
* `services/` is the "everything not in the agent loop" bucket — voice
  campaigns, social ops, reports, lead queues. Keep it explicitly outside
  the loop so it cannot accidentally couple.

A new contributor can navigate the agent stack by reading those six
package READMEs.

---

## 4. Mechanical migration plan

### 4.1 Pre-flight (one PR)

* Remove the ghost duplicates listed in §02 (one `git rm` commit).
* Remove the backward-compat re-exports in `worker.py:48-67`.
* Run worker; fix any lingering imports.

### 4.2 Cut 1 — schema split (one PR)

* Split `schemas.py` into `schemas/*.py`.
* Generate a single `schemas/__init__.py` that re-exports everything that
  the codebase currently imports from `src.ai.schemas`. This keeps the
  rest of the move boring.
* Add `_DEPRECATED_WARN` for direct deep imports if you want to nudge.

### 4.3 Cut 2 — ORM split (one PR)

* Same approach for `models.py` → `orm/*.py`.
* `orm/__init__.py` re-exports for backward compat.

### 4.4 Cut 3 — api/ extraction (one PR)

* Move `router.py` into `api/entities.py`, `api/executions.py`, etc.
* `main.py` imports change.

### 4.5 Cut 4 — services/ extraction (one PR)

* Move `service.py`, `*_service.py`, `*_executor.py`, `*_worker.py` into
  `services/`.

### 4.6 Cut 5 — tools/ subgrouping (one PR)

* Just `mv`. Update `tools/__init__.py` imports.

### 4.7 Cut 6 — memory/ domains/ subgrouping (one PR)

* Introduce `memory/domains/base.py`.
* Refactor each tree service to subclass it.
* Move dreaming files into `memory/dreaming/`.

### 4.8 Cut 7 — core/ reasoning + executors (one PR per executor)

* Extract `core/reasoning/{react,cot,reflection,tot}.py` from
  `step_executor.py`.
* Extract `core/executors/*.py` from `execution_engine.py`.
* `step_executor.py` shrinks to the bag of helpers it still owns.

### 4.9 Cut 8 — AgentLoop introduction (multiple PRs over weeks 3-4 in roadmap)

* New file, new tests, new code path. Engines become executors.

### 4.10 Cut 9 — Meta-Agent board (multiple PRs over weeks 7-8)

* Introduce `meta/board/*` one role at a time.
* The Meta-Agent's `static_plan` step orchestrates them via `meta_*`
  tools; existing tools are reused.

Each PR is mergeable independently and reverts cleanly.

---

## 5. Hard rules to lock in via CI

1. **No top-level files in `src/ai/`** other than `__init__.py`,
   `worker.py`, and `README.md`. Anything else fails CI.
2. **No file > 600 lines** in `core/`, `planning/`, `memory/`, `meta/`,
   `governance/`. (Tools are allowed to be longer because some are
   provider-driven; cap at 800 there.)
3. **No new `as XYZ` aliases** for imports across package boundaries
   (catches the `CortexRouter as CortexService` pattern).
4. **No `from src.ai.worker import …`** anywhere (the re-export shim is
   gone).
5. **No "Phase N" or "Fix N" inline comments** added in new code (codify
   intent in commit messages, not source).
6. **`schemas/__init__.py` and `orm/__init__.py`** are the only files
   that may have wildcard re-exports.

A simple `tools/check_layout.py` (or pre-commit hook) enforces these.

---

## 6. What this is *not* trying to do

* It is not a rewrite. Almost every file already exists; this is a
  `git mv` exercise with `__init__.py` glue.
* It is not introducing new external dependencies.
* It is not changing public API surface (entity JSON schema, HTTP
  endpoints) — that is governed by §05/§04 functional changes, not by
  the move.
* It is not adding microservices. Everything still runs inside the same
  Arq worker / FastAPI app.

The whole reorg should be achievable in ~3 working days of focused work,
plus one full QA cycle to catch import drift.
