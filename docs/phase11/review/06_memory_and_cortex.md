# 06 — Memory & CORTEX Architecture Review

Memory is the strongest layer of the platform. This document is therefore
shorter than the rest — but it has a few important cuts that need to be
made to keep the layer crisp.

---

## 1. The memory stack today

```
                  ┌─────────────────────────────────────────┐
                  │                Agent Run                 │
                  └───────────────────┬─────────────────────┘
                                      │
                       memory_assemble (v1 or v2)
                                      │
            ┌─────────────────────────┴─────────────────────────┐
            ▼                                                     ▼
       v1 path:                                              v2 path:
       MemoryRouter.retrieve                                  MemoryAssemblyService
        ├─ EpisodicMemory rows                                ├─ Knowledge Tree (semantic graph)
        ├─ DocumentChunk vector search                        ├─ Experience Tree (patterns)
        └─ optional CORTEX viewport                           ├─ Intelligence Tree (rules)
                                                              └─ Episodic Tree (recent runs)
                                      │
                                      ▼
                          context_state["__memory__"] etc.
                                      │
                                      ▼
                  ┌─────────────────────────────────────────┐
                  │              CORTEX Tree                 │
                  │  Runtime cognitive workspace             │
                  │  └─ Root                                 │
                  │     ├─ Knowledge subtree (📚)           │
                  │     ├─ Working subtree (🛠)              │
                  │     └─ Output subtree (📤)               │
                  └───────────────────┬─────────────────────┘
                                      │ on completion
                                      ▼
                        DreamingEngine (background)
                          ├─ Observations  (from Episodic)
                          ├─ Patterns      (from Observations)
                          └─ Rules         (→ Intelligence Tree)
```

The architecture is **excellent**. The problems are:

1. Two assembly pipelines wired in parallel (§02 / F-07).
2. Viewport prompt rendering carries a fixed 250-token "operations help"
   block on every step (§01 / F-11).
3. `MemoryRouter.write_episodic` does a **dual write** (v1 row + v2 tree).
   That's correct during migration; needs an exit plan.
4. The four-domain tree services each have their own `CortexRouter` calls
   — no facade.
5. `failure_pattern_service.py` is referenced once in `assembler.py` with
   `try/except ImportError, Exception` (yes, both). It's load-bearing for
   nothing but pretends to be load-bearing.
6. `embedding_service.py` exists in `memory/` (active) and in `ai/` root
   (ghost). Same drift as §02.

---

## 2. What to keep, untouched

* `cortex_service.py::CortexRouter` (the service) — 1,109 lines, but
  every method is justified. Do **not** "simplify."
* `cortex_models.py` — schema is correct.
* `dreaming_engine.py` — three-phase pipeline is right. Promote the
  thresholds to per-entity config (today they are class constants).
* `intelligence_tree_service.py` / `experience_tree_service.py` /
  `knowledge_tree_service.py` / `episodic_tree_service.py` — keep the
  four-tree structure; it is the right ontology.
* `graph_service.py::SemanticGraphService` — cross-tree semantic links
  are a nice touch.
* `cortex_bridge.py` — good facade for runtime CORTEX use from the engine.

---

## 3. What to change

### 3.1 Pick v2 canonical, retire v1

`memory/assembler.py` should reduce to:

```python
async def assemble_memory(db, company_id, entity_id, user_id, tree_id,
                          task_description, memory_scope, runtime_tree,
                          long_running) -> Dict[str, Any]:
    return await MemoryAssemblyService(db, company_id).assemble_runtime_memory(
        entity_id=entity_id, user_id=user_id,
        task_description=task_description, runtime_tree=runtime_tree,
        include_domains=domain_map[memory_scope],
    )
```

`MemoryRouter` becomes `memory/legacy_episodic_reader.py` and is used
only for entities that have *zero* episodic-tree data yet. The Dreaming
Engine, during its first run for a new entity, migrates flat episodes →
episodic tree, then `MemoryRouter` stops being touched.

`write_episodic` becomes a single write to the EpisodicTree; the flat
`EpisodicMemory` table is *append-only legacy* read-only after migration
is complete.

**Exit signal**: when no production entity has `memory_pipeline = "v1"`
for ≥30 days, delete the v1 code.

### 3.2 Viewport prompt: separate the help block

`memory/cortex_service.py:46-53` defines `CORTEX_OPERATIONS_PROMPT` and
`Viewport.to_prompt_text()` appends it on every render. That's ~250
tokens per step in the LLM prompt, on every step — burning ≥10% of
typical context window cost.

Move the operations help into the **system prompt** as a one-time
injection (already injected by `platform_schema_compiler`'s step types
section). Have `to_prompt_text()` render *only* breadcrumb + current node
+ children, sized to a budget the caller specifies.

```python
def to_prompt_text(self, include_ops_help: bool = False, max_chars: int = 2000) -> str:
```

### 3.3 Unified CORTEX facade for the four tree services

`KnowledgeTreeService`, `EpisodicTreeService`, `ExperienceTreeService`,
`IntelligenceTreeService` all *call into* `CortexRouter` directly to write
nodes. They duplicate boilerplate (find/create section group, write a
typed child, update timestamps).

Add `memory/tree_domain_base.py`:

```python
class DomainTreeBase:
    DOMAIN: ClassVar[MemoryDomain]
    ROOT_TITLE: ClassVar[str]
    SECTIONS: ClassVar[dict[str, str]]  # type → emoji+title

    async def ensure_tree(self, scope_id: UUID) -> CortexTree: ...
    async def ensure_section(self, tree: CortexTree, section_type: str) -> CortexNode: ...
    async def write_item(self, tree, section_type, *, title, content, summary, tags): ...
    async def find(self, tree, query, top_k=5): ...
```

Each domain service becomes ~80 lines instead of 400-500. Behaviour
identical.

### 3.4 Domain-specific retrieval scoring

Today, every tree's retrieval looks similar: pgvector cosine + node-type
filter. But the **scoring weights** that matter differ per domain:

| Domain | Best signal |
|--------|-------------|
| Knowledge | semantic similarity + recency |
| Experience | task-class match + recency |
| Intelligence | task-class match + rule confidence + recency |
| Episodic | user_id match + run success status + recency |

Encode these in `tree_domain_base.py::retrieve(...)` with weight tables.
Today the assembly is generic and probably under-tuned.

### 3.5 Dreaming Engine triggers

`DreamingEngine.dream(entity_id, force)` runs on a cron. Better triggers:

* After every Nth successful run (e.g. 5).
* When entity's success rate dips below threshold (anomaly → quick
  consolidation).
* After a Promoter (§04) promotes an ADAPT of an existing entity (the
  source's intelligence rules should be inherited / forked).

A dispatcher pattern: `DreamingScheduler.maybe_dream(entity_id, reason)`.

### 3.6 Reflection-write integration

Per §03, the AgentLoop's `Reflector` writes structured reflections.
Today there is no entry point for "agent → Intelligence rule (candidate)."

Add `IntelligenceTreeService.add_candidate_rule(...)` and call it from
`Reflector.persist(...)`. Dreaming Engine's distillation phase then
validates/promotes candidates → confirmed rules.

### 3.7 Scoped subtree isolation: document the contract

`CortexRouter(scoped_subtree_root_id=...)` is used by recursive children
to isolate writes. The contract — *what scoped means* (cannot read above
the root? cannot write outside descendants?) — lives only in comments.
Promote to an explicit `ScopePolicy`:

```python
class ScopePolicy:
    can_read_outside: bool   # default False
    can_write_outside: bool  # default False
    can_navigate_to_siblings: bool  # default False
```

This protects against subtle bugs when a child mutates parent state.

### 3.8 Knowledge ingestion provenance

`CortexBridge.ingest_tool_result` writes scraper/browser output into the
Knowledge root. Today every node has `source_ref={"type": "context_source"}`
or similar. Strengthen to a typed `Provenance` block:

```python
{
  "provenance": {
    "source_type": "tool",
    "tool_id": "scraper_tool",
    "url": "https://...",
    "fetched_at": "...",
    "trust_score": 0.7,
    "run_id": "...",
    "step_id": "..."
  }
}
```

Downstream: the Critic in §04 can use `trust_score` to weight evidence.

### 3.9 Embedding service: one model, configurable

`memory/embedding_service.py` reads a single fallback model from
`constants.EMBEDDING_MODEL`. Per `constants.py:12-23`, there was a
historical bug where the constant differed between files. The fix is
done; lock it in with a unit test that asserts only one source of truth.

The bigger fix is to **resolve embedding model from IntegrationRegistry
per company** at runtime, not from a constant. (The comment in
`constants.py:11-17` says this is the goal.) Track this as a P2 item.

### 3.10 Context-size accounting

`CortexBridge` started tracking `_context_size_bytes` incrementally
(`memory/cortex_bridge.py`). Make sure it's the *single source of truth*
for context size and exposes a `pressure()` method consumed by the
budget (§03).

---

## 4. The four-domain memory: per-domain status

| Domain | File | What's good | What's missing |
|--------|------|-------------|----------------|
| Knowledge | `knowledge_tree_service.py` | Persistent ingested docs, semantic search, runtime references | Provenance is loose; no decay |
| Experience | `experience_tree_service.py` | Patterns from successful runs | Not yet read in many places; mostly written by Dreaming |
| Intelligence | `intelligence_tree_service.py` | 3-section (Instructions / Strategies / Preferences) — well-modelled | Status field (`candidate` / `confirmed` / `retired`) needs explicit lifecycle |
| Episodic | `episodic_tree_service.py` | Per-run record with structured outcome | Bridge from flat `EpisodicMemory` only partial; user_id filter weak |

The Intelligence section names (`📏 Instructions`, `🎯 Strategies`, `❤️
Preferences`, from `intelligence_tree_service.py`) are evocative and good.
Keep them.

---

## 5. CORTEX as cognitive scratchpad — push it further

Today CORTEX is mostly *used as memory*. It can do more:

### 5.1 Use CORTEX nodes as message-passing slots

Between two children in a PROCESS, today the parent passes outputs via
`context_state[step_name]` → child's `input`. This is string-based and
brittle.

Instead, each child's invocation can pass `result_slot_node_id`. The
child writes its structured result into that node; the parent reads it.
This is the `RECURSE` step type already in the schema — promote it from
opt-in to default for PROCESS→child invocations.

### 5.2 Use CORTEX edges for hypotheses

`CortexEdge` exists (`memory/cortex_models.py`). The Strategist (§03)
could write "supports" / "contradicts" edges between findings. Critic
can use those edges as the basis for "did the agent contradict itself?"

### 5.3 Use CORTEX as a *debate workspace*

Two LLM personas write counter-arguments as child nodes under a
`debate` subtree; a third LLM judges. This is far easier with CORTEX than
with raw context state. Pre-Critic / Critic from §05 are special cases of
this.

---

## 6. Concrete cleanup list

| # | Action | Effort |
|---|--------|--------|
| M1 | Pick v2 canonical, `MemoryRouter` → `LegacyEpisodicReader` | 3 days |
| M2 | Move `CORTEX_OPERATIONS_PROMPT` to system prompt; viewport rendering takes `max_chars` budget | 1 day |
| M3 | `DomainTreeBase` refactor; collapse 4 services into ~80 LoC each | 1 week |
| M4 | Typed `Provenance` on every knowledge node | 2 days |
| M5 | `ScopePolicy` on `CortexRouter` | 2 days |
| M6 | Dreaming triggers from outcomes (not just cron) | 3 days |
| M7 | Reflector → IntelligenceTree candidate-rule path | 2 days |
| M8 | Embedding model from IntegrationRegistry per company | 3 days |
| M9 | Delete root-level ghosts: `cortex_*.py`, `dreaming_*.py`, `embedding_service.py`, `episodic_tree_service.py`, `experience_tree_service.py`, `graph_service.py`, `intelligence_tree_service.py`, `knowledge_tree_service.py`, `memory_assembly_service.py`, `memory_service.py` (see §02) | 1 day |
| M10 | Unit test: `EMBEDDING_MODEL` resolved exactly once per process | 1 day |
| M11 | Document `CORTEX_OPERATIONS_PROMPT` move + new `ScopePolicy` in `docs/CortexResearch/` | 2 days |
