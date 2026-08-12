# Track 6 — Memory v2 Canonicalisation (Week 9)

> **Owner:** Agent infra engineer.
> **Duration:** 5 working days.
> **Behaviour change:** v2 memory pipeline becomes canonical; v1 reduced
>   to a legacy-read adapter; CORTEX viewport stops carrying the ops-help
>   block; the four memory-domain services share a single base class.
> **Risk:** Medium. Memory drives every prompt; regressions here are
>   diffuse and easy to miss.
> **Goal mapping:** G5 (memory v2 canonical), G6 (kernel layout).

---

## 1. Objectives (functional)

After Track 6:

1. `memory/assembler.py` calls `MemoryAssemblyService` exclusively. The
   `v1` branch is gone for new runs; existing entities are
   auto-migrated on first run.
2. `MemoryRouter.retrieve` survives only via `memory/legacy_episodic_reader.py`
   as a fallback for entities with zero EpisodicTree data.
3. `CORTEX_OPERATIONS_PROMPT` (the 250-token ops-help) is moved into
   the **system prompt**, injected once. The viewport's
   `to_prompt_text(...)` no longer appends it.
4. Each viewport render takes a `max_chars` budget; default per
   entity = `governance.viewport_max_chars` or 4,000.
5. The four memory-domain services (`knowledge_tree_service`,
   `episodic_tree_service`, `experience_tree_service`,
   `intelligence_tree_service`) share a new `DomainTreeBase` for the
   80% of boilerplate they have in common.
6. Every knowledge-node write attaches a typed `Provenance` block.
7. `CortexService(scoped_subtree_root_id=...)` enforces a declarative
   `ScopePolicy`.
8. Dreaming Engine triggers from outcomes (run completes / fails) AND
   from the existing cron, not cron only.
9. `Reflector.persist(...)` writes `scope="entity"` and
   `scope="task_class"` reflections into `IntelligenceTree` as
   `status="candidate"`. The Dreaming Engine's distillation phase
   promotes confirmed candidates to `confirmed`.
10. Embedding model resolves from `IntegrationRegistry` per company at
    runtime, with a one-line fallback to the `EMBEDDING_MODEL_FALLBACK`
    constant.
11. `prompt_token_overhead_per_step` KPI drops ≥10% on the regression
    suite.

---

## 2. Scope

### In scope

* `memory/assembler.py` simplification.
* New: `memory/legacy_episodic_reader.py`.
* CORTEX viewport prompt rewrite (`memory/cortex_service.py`).
* New: `memory/domains/base.py` (`DomainTreeBase`).
* Refactor: each of the four tree services to subclass.
* New: typed `Provenance` block (Pydantic model + every write site).
* New: `memory/scope_policy.py` enforced by `CortexService`.
* Dreaming trigger from outcomes — change in `core/agent_loop._finalize`
  to enqueue a Dreaming job per entity.
* `Reflector.persist` integration with IntelligenceTree.
* Embedding-model resolver migration.
* Telemetry events for viewport bytes / memory assembly bytes.

### Out of scope

* Removing `EpisodicMemory` table (post-Phase 11).
* Cross-tenant knowledge sharing.
* Replacing pgvector with another vector store.
* Tree decay / forgetting policies (Phase 12).

---

## 3. Architecture (technical)

### 3.1 `DomainTreeBase`

```python
# memory/domains/base.py
class DomainTreeBase:
    DOMAIN: ClassVar[MemoryDomain]
    ROOT_TITLE: ClassVar[str]
    SECTIONS: ClassVar[dict[str, str]] = {}    # type → emoji+title
    RETRIEVAL_WEIGHTS: ClassVar[dict[str, float]] = {
        "semantic": 1.0,
        "recency":  0.5,
        "user_match": 0.0,
        "success":  0.0,
    }

    def __init__(self, db, company_id):
        self.db = db
        self.company_id = company_id
        self.cortex = CortexService(db, company_id)

    async def ensure_tree(self, *, scope_id, scope_level) -> CortexTree: ...
    async def ensure_section(self, tree, section_type: str) -> CortexNode: ...
    async def write_item(self, *, tree, section_type, title, content,
                          summary, tags=None, source_ref=None,
                          provenance: Provenance | None = None) -> CortexNode: ...
    async def find(self, *, tree, query: str, top_k=5,
                   filters: dict | None = None) -> list[DomainItem]: ...
    async def retrieve(self, *, scope_id, scope_level, query, top_k=5) -> list[DomainItem]: ...

    def _score(self, item, signals: dict[str, float]) -> float:
        return sum(self.RETRIEVAL_WEIGHTS[k] * signals[k]
                   for k in self.RETRIEVAL_WEIGHTS) / sum(self.RETRIEVAL_WEIGHTS.values())
```

Each domain subclass overrides `RETRIEVAL_WEIGHTS`:

| Domain | semantic | recency | user_match | success |
|--------|---------:|--------:|-----------:|--------:|
| Knowledge | 1.0 | 0.4 | 0.0 | 0.0 |
| Experience | 0.7 | 0.5 | 0.2 | 0.6 |
| Intelligence | 0.6 | 0.3 | 0.0 | 0.0 |
| Episodic | 0.5 | 0.7 | 0.6 | 0.5 |

### 3.2 `Provenance`

```python
# schemas/cortex.py (new dataclass)
class Provenance(BaseModel):
    source_type: Literal["tool","user_upload","reflection","dreaming",
                          "external_link","manual","context_source"]
    tool_id: Optional[str] = None
    url: Optional[str] = None
    upload_ref: Optional[str] = None
    fetched_at: Optional[datetime] = None
    trust_score: float = 0.5      # 0..1
    run_id: Optional[UUID] = None
    step_id: Optional[str] = None
    notes: Optional[str] = None
```

`CortexService.write(...)` accepts an optional `provenance: Provenance`
arg; when present, it's serialized into `source_ref["provenance"]`.

### 3.3 `ScopePolicy`

```python
# memory/scope_policy.py
@dataclass
class ScopePolicy:
    can_read_outside: bool = False
    can_write_outside: bool = False
    can_navigate_to_siblings: bool = False
    error_on_violation: bool = True


class CortexService:
    def __init__(self, db, company_id,
                 scoped_subtree_root_id: UUID | None = None,
                 scope_policy: ScopePolicy | None = None):
        self.scope_policy = scope_policy or ScopePolicy()
        ...

    async def write(self, parent_id, ...):
        if self.scoped_subtree_root_id and not self._is_descendant(parent_id):
            if not self.scope_policy.can_write_outside:
                if self.scope_policy.error_on_violation:
                    raise ScopeViolation(f"Cannot write outside subtree "
                                          f"{self.scoped_subtree_root_id}")
                logger.warning(...)
                return None
        return await self._write_inner(parent_id, ...)
```

Default policy: strict (cannot read or write outside subtree).

### 3.4 Viewport rewrite

```python
# memory/cortex_service.py
@dataclass
class Viewport:
    current_node: NodeSummaryDTO
    children: list[NodeSummaryDTO]
    parent: NodeSummaryDTO | None
    breadcrumb: list[dict[str, str]]

    def to_prompt_text(self,
                       *,
                       include_ops_help: bool = False,
                       max_chars: int = 4000) -> str:
        # Build sections in priority order: current_node → breadcrumb
        # → children → (ops_help if requested).
        # Stop when remaining budget < section size.
        ...
```

The system prompt builder in `core/prompt_builder.py` injects the
ops-help text once at the start of each LLM call (and only when the
entity is CORTEX-enabled).

```python
# core/prompt_builder.py
CORTEX_OPS_HELP = """## Available CORTEX Operations
NAVIGATE / READ / WRITE / RECURSE / AWAIT_CHILDREN / CHECKPOINT
(see system documentation for exact semantics)"""

def build_sandwich_prompt(..., cortex_enabled: bool):
    blocks = [...]
    if cortex_enabled:
        blocks.append(CORTEX_OPS_HELP)
    ...
```

This single move cuts ≥10% of prompt tokens on CORTEX-using entities.

### 3.5 Dreaming trigger from outcomes

```python
# core/agent_loop.py — at end of run
async def _finalize(self, state, db):
    ...
    if state.is_success() or state.is_failure():
        from arq.connections import ArqRedis
        arq = ArqRedis(self.redis.connection_pool)
        await arq.enqueue_job(
            "dreaming_outcome_trigger",
            str(state.entity_id),
            reason="success" if state.is_success() else "failure",
            run_id=str(state.run_id),
        )
```

```python
# core/arq_jobs.py
async def dreaming_outcome_trigger(ctx, entity_id_str, reason, run_id):
    """
    Lightweight trigger that enqueues a full DreamingEngine.dream(...)
    pass IF the entity has enough new episodes since last dream.
    """
    async with AsyncSessionLocal() as db:
        engine = DreamingEngine(db, company_id=...)
        if await engine.should_dream(UUID(entity_id_str)):
            await engine.dream(UUID(entity_id_str))
```

### 3.6 `Reflector.persist(...)` → IntelligenceTree candidate

```python
# core/reflector.py
async def persist(self, reflection, state):
    if reflection.scope == "run":
        return                    # in-memory only
    if reflection.scope in ("entity", "task_class"):
        await self.intelligence.write_candidate_rule(
            entity_id=state.entity_id,
            task_class=state.task_class,
            text=reflection.proposed_change,
            rationale=reflection.cause_hypothesis,
            evidence_run_ids=[state.run_id],
            confidence=reflection.confidence,
        )
```

`IntelligenceTreeService.write_candidate_rule(...)` writes a node with
`status="candidate"` under the entity's `📏 Instructions` (or
`🎯 Strategies`) section. The Dreaming Engine's distillation phase
later promotes the rule to `confirmed` when corroborating evidence
arrives.

### 3.7 Embedding model resolver

```python
# memory/embedding_service.py — updated
async def resolve_embedding_model(db, company_id) -> tuple[str, str|None]:
    """Returns (model_name, api_key). Falls back to constant if no row."""
    from src.config.models import IntegrationRegistry
    row = await db.execute(
        select(IntegrationRegistry).where(
            IntegrationRegistry.company_id == company_id,
            IntegrationRegistry.service_category == "embedding",
            IntegrationRegistry.is_enabled == True,
            IntegrationRegistry.is_default == True,
        )
    )
    integ = row.scalar_one_or_none()
    if integ:
        return integ.model_name, integ.api_key
    from src.ai.constants import EMBEDDING_MODEL_FALLBACK
    return EMBEDDING_MODEL_FALLBACK, None
```

Every embedding call routes through this resolver; tests assert it's
called exactly once per run (cached on the assembler / dreaming
engine).

---

## 4. Detailed deliverables

### 4.1 T6-1 — `memory/assembler.py` simplification (Day 1 AM)

```python
async def assemble_memory(db, company_id, entity_id, user_id=None,
                          tree_id=None, task_description="",
                          memory_pipeline="v2",         # default changed
                          memory_scope="FULL",
                          runtime_tree=None,
                          long_running=False) -> Dict[str, Any]:
    if memory_scope == "NONE":
        return {}

    # v2 is the only canonical path; v1 retained only for explicit
    # entity opt-in OR as a fallback when no Episodic Tree exists yet.
    if memory_pipeline == "v1":
        return await _assemble_v1_legacy(...)

    result = await MemoryAssemblyService(db, company_id) \
                    .assemble_runtime_memory(
        entity_id=entity_id, user_id=user_id,
        task_description=task_description,
        runtime_tree=runtime_tree,
        include_domains=_DOMAIN_MAP[memory_scope],
    )

    # First-run migration: if no Episodic Tree exists yet, top up with
    # legacy EpisodicMemory rows via legacy_episodic_reader.
    if not result.episodic_context:
        legacy_eps = await LegacyEpisodicReader(db).read(
            entity_id=entity_id, user_id=user_id, limit=5)
        if legacy_eps:
            result.episodic_context = legacy_eps

    return _to_context_dict(result)
```

### 4.2 T6-2 — `memory/legacy_episodic_reader.py` (Day 1 PM)

```python
class LegacyEpisodicReader:
    """
    Read-only adapter for the flat EpisodicMemory table.
    Used only when an entity has no Episodic Tree data yet.

    Will be removed in Phase 12 once all entities have migrated.
    """
    async def read(self, *, entity_id, user_id=None, limit=5) -> list[dict]:
        ...
```

### 4.3 T6-3 — Viewport rewrite (Day 2 AM)

* Move `CORTEX_OPERATIONS_PROMPT` to `core/prompt_builder.py`.
* Update `Viewport.to_prompt_text` signature per §3.4.
* Update every call site (`core/perceiver.py`,
  `memory/cortex_bridge.py`, `core/execution_engine.py` if any
  remain).
* Add a regression test: a viewport over a tree with 12 children fits
  in 2,000 chars.

### 4.4 T6-4 — `DomainTreeBase` + refactor (Day 2 PM + Day 3)

* Create `memory/domains/base.py`.
* Refactor `knowledge_tree_service.py` → `memory/domains/knowledge.py`
  (subclasses base).
* Same for episodic, experience, intelligence.
* Backwards-compat shims at the old paths re-exporting the new classes
  so external code doesn't break.
* Add `RETRIEVAL_WEIGHTS` per §3.1.
* Add `IntelligenceTreeService.write_candidate_rule(...)` per §3.6.

### 4.5 T6-5 — `Provenance` block (Day 4 AM)

* Add `Provenance` Pydantic model to `schemas/cortex.py`.
* Add `provenance: Provenance | None` param to `CortexService.write`.
* Update every knowledge-write site:
  * `cortex_bridge.ingest_tool_result` — `source_type="tool"`,
    `tool_id`, `url` if present, `fetched_at=now()`.
  * `execution_engine` context-source ingestion — `source_type="user_upload"`.
  * `Reflector.persist` — `source_type="reflection"`.
  * Dreaming Engine writes — `source_type="dreaming"`.

`trust_score` default rules:

| source_type | default trust |
|-------------|---------------|
| user_upload | 1.0 |
| tool (curated registry) | 0.7 |
| tool (third-party) | 0.5 |
| external_link (scraped) | 0.4 |
| reflection | 0.6 |
| dreaming | 0.8 |
| manual | 0.9 |

The Critic Pipeline (Track 3) consumes `trust_score` for weighting
evidence — wire is in place from Track 6 onward.

### 4.6 T6-6 — `ScopePolicy` (Day 4 PM)

* Add `memory/scope_policy.py`.
* Update `CortexService.__init__` to accept `scope_policy`.
* Update child-recursive code path
  (`step_executor._execute_child_invocation` creates the child with
  `scoped_subtree_root_id` already; now also pass `scope_policy =
  ScopePolicy(can_read_outside=True, can_write_outside=False)` so child
  can read shared knowledge but cannot pollute parent's tree).
* Add tests for both violation paths (write outside, read outside with
  `can_read_outside=False`).

### 4.7 T6-7 — Dreaming triggers + Reflector wiring (Day 5 AM)

Per §3.5 and §3.6.

### 4.8 T6-8 — Embedding-model resolver + caching (Day 5 PM)

* Implement `resolve_embedding_model` per §3.7.
* Cache result on `MemoryAssemblyService` constructor.
* Add test: two calls within one run hit the DB exactly once.

### 4.9 T6-9 — KPI: prompt overhead measurement (Day 5)

Add a telemetry counter on every LLM call:

```python
emit("agent.llm.call",
     prompt_tokens=resp.prompt_tokens,
     fixed_overhead_chars=len(CORTEX_OPS_HELP) if cortex_enabled else 0,
     dynamic_chars=len(user_prompt))
```

Track 9 dashboards consume these to validate the 10% reduction.

---

## 5. Database / schema changes

### 5.1 No new tables

Everything rides on CORTEX. New node types added (already in
`CortexNodeType`):

* `"candidate_rule"` — IntelligenceTree (status=candidate).
* `"confirmed_rule"` — IntelligenceTree (status=confirmed).
* `"skill_candidate"` (already in Track 5).
* `"snapshot"` (already in Track 2).
* `"health_record"` (already in Track 3).

If any are missing from the enum, add via `schemas/enums.py`.

### 5.2 Backfill candidate-rule status

A migration `p11t06_backfill_intelligence_status` adds a default
`status="confirmed"` to existing Intelligence rules (since pre-Track 6
rules all came from the Dreaming Engine's distillation):

```python
def upgrade():
    # For every CortexNode with node_type in (instruction, strategy,
    # preference) and source_ref doesn't have 'status', set
    # source_ref['status'] = 'confirmed'.
    ...
```

This preserves backward compatibility while making future rules
explicitly typed.

---

## 6. API changes

### 6.1 No path changes

Memory is server-internal. No HTTP API change.

### 6.2 SSE event additions

```jsonc
{"type":"memory_assembled","domains":["knowledge","intelligence","episodic"],
 "knowledge_refs":5,"intelligence_rules":3,"episodic_context":2,
 "prompt_chars":3140}
{"type":"dreaming_triggered","entity_id":"...","reason":"success"}
{"type":"intelligence_candidate_added","entity_id":"...","scope":"task_class"}
```

---

## 7. Telemetry events

| Event | Payload | When |
|-------|---------|------|
| `agent.memory.assembled` | `{run_id, domains, sizes, latency_ms}` | every assembly |
| `agent.memory.viewport_rendered` | `{run_id, chars, ops_help_chars, nodes}` | every viewport render |
| `agent.memory.provenance_attached` | `{node_id, source_type, trust_score}` | every knowledge write |
| `agent.memory.scope_violation` | `{run_id, subtree_root_id, attempted_parent_id}` | rare |
| `agent.dreaming.triggered` | `{entity_id, reason}` | outcome triggers |
| `agent.dreaming.completed` | `{entity_id, observations, patterns, rules}` | each dream |
| `agent.intelligence.candidate_added` | `{entity_id, scope, source}` | every candidate rule |
| `agent.intelligence.candidate_promoted` | `{entity_id, rule_id}` | dreaming distill |
| `agent.embedding.resolved` | `{company_id, model_name, cached}` | per assembly |

---

## 8. Feature flags

| Flag | Default | Notes |
|------|---------|-------|
| `memory.v2_canonical` | ON | Forces v2; v1 only via opt-in |
| `memory.viewport_compact` | ON | Excludes ops-help from viewport |
| `memory.scope_policy_enforced` | ON | Set to OFF only for safe-rollback |
| `memory.dreaming_outcome_trigger` | ON | Outcome-based Dreaming |
| `memory.embedding_resolver_v2` | ON | Per-company embedding from IntegrationRegistry |

---

## 9. Tests

### 9.1 Unit

* `test_assembler_v2_default` — `memory_pipeline` default is `"v2"`.
* `test_legacy_reader_used_only_when_no_tree` — fresh entity returns
  legacy episodes; an entity with EpisodicTree data does NOT trigger
  legacy reader.
* `test_viewport_max_chars_respected` — large tree → output ≤ budget.
* `test_viewport_no_ops_help` — `to_prompt_text(include_ops_help=False)`
  excludes the constant.
* `test_prompt_builder_injects_ops_help_once` — system prompt contains
  ops help; user prompt does not.
* `test_provenance_round_trip` — round-trip through CORTEX node.
* `test_scope_policy_write_outside_raises` — write into a non-descendant
  → `ScopeViolation`.
* `test_scope_policy_read_outside_blocked` — when
  `can_read_outside=False`, navigate above root → error.
* `test_dreaming_should_dream_thresholds` — `MIN_EPISODES_FOR_DREAMING`
  enforced.
* `test_embedding_resolver_uses_registry` — when integration row
  exists, model name matches.
* `test_embedding_resolver_falls_back_to_constant` — when no row,
  returns `EMBEDDING_MODEL_FALLBACK`.
* `test_domain_tree_base_score_weights` — per-domain weights produce
  expected ordering on synthetic items.

### 9.2 Integration

* `test_end_to_end_memory_pipeline_v2` — full run with v2 memory;
  episodic/experience/intelligence/knowledge keys present in context.
* `test_dreaming_triggered_on_run_complete` — Arq job
  `dreaming_outcome_trigger` enqueued on finalize.
* `test_reflector_writes_candidate_rule` — Reflector at scope="entity"
  produces an IntelligenceTree candidate.
* `test_dreaming_promotes_candidate_to_confirmed` — after seeding
  matching candidates, dream() promotes.

### 9.3 Performance / cost

* `test_prompt_token_overhead_drops_10pct` — on the fixture suite,
  prompt-token count drops ≥10% vs Track 2 baseline.

### 9.4 Smoke / regression

* Full fixture re-run with v2 default ON. Acceptance: cost ≤ Track 4
  baseline; quality similarity ≥ 0.85.

---

## 10. Acceptance criteria

1. `memory_pipeline` default in `MemoryConfig` is `"v2"`; existing
   entities continue to work via the auto-migration code path.
2. `to_prompt_text(include_ops_help=False)` is the only call shape
   used in production; no viewport string contains the ops-help
   block.
3. `CORTEX_OPS_HELP` is injected exactly once per LLM call from the
   system prompt builder.
4. The four memory domain services share `DomainTreeBase`; net file
   size of each drops ≥30%.
5. Every knowledge-node write attaches a Provenance.
6. ScopeViolation raised on every illegal write/read in the scoped
   subtree mode.
7. Dreaming enqueued on every successful run (asynchronously); cron
   still runs at its scheduled interval for catch-up.
8. Reflector writes candidate rules; Dreaming distillation promotes
   them.
9. Embedding resolver called once per assembly; per-company override
   respected.
10. `prompt_token_overhead_per_step` KPI shows ≥10% reduction (Track 9
    dashboard).
11. `mypy --strict` clean on new files.

---

## 11. Effort breakdown (5 working days)

| Day | Work |
|-----|------|
| 1 AM | T6-1: assembler simplification + tests |
| 1 PM | T6-2: legacy_episodic_reader |
| 2 AM | T6-3: viewport rewrite + ops-help move |
| 2 PM | T6-4 start: DomainTreeBase + Knowledge |
| 3 | T6-4 cont'd: Episodic / Experience / Intelligence subclasses |
| 4 AM | T6-5: Provenance everywhere |
| 4 PM | T6-6: ScopePolicy |
| 5 AM | T6-7: dreaming triggers + reflector wiring |
| 5 PM | T6-8: embedding resolver + KPI hook + PR |

---

## 12. Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Removing ops-help from viewport degrades CORTEX-tool understanding | M | Agent stops navigating | Ops-help injected into system prompt unchanged; A/B compare with `memory.viewport_compact` flag |
| `DomainTreeBase` retrieval weights wrong for one domain | M | Memory recall drops | Per-domain unit tests with synthetic items; KPI watch on `goal_hit_rate` after Track 6 |
| Provenance backfill drift (existing nodes lack it) | L | Critic can't weight evidence | New writes only; existing nodes get `provenance=None` and default trust 0.5 |
| ScopePolicy too strict; child run can't read parent context | M | Child runs fail | Default policy for child runs explicitly sets `can_read_outside=True` |
| Dreaming outcome trigger fires too often (every run) | M | Cost rises | `should_dream` checks min-episodes and time-since-last-dream guards; cron stays for full-pass coverage |
| Embedding resolver regression mid-run (model change) | L | Embedding drift | Cache per assembler instance; new model only on next run |
| v1 legacy reader returns stale results | M | Confusing context | Only invoked when EpisodicTree truly empty; logged with deprecation warning |

---

## 13. Dependencies

* **Upstream:**
  * Track 2 (Reflector exists, AgentLoop hooks into _finalize).
  * Track 5 (MetaIntelligenceTree uses DomainTreeBase-style patterns; share refactor).
* **Downstream:**
  * Track 7 (Planner uses promoted Intelligence rules).
  * Track 8 (Tool cost attribution per provenance source type).
  * Track 9 (KPIs).

---

## 14. Open questions

* Should `Provenance.trust_score` be **learned** (logistic regression
  on past outcomes) instead of constant per source_type? Phase 12+;
  Track 6 keeps it constant.
* Should the `EpisodicMemory` table be dropped at end of Phase 11?
  No — keep for at least 30 days of legacy data, drop in Phase 12.
* Should `DomainTreeBase` go further and absorb the section logic
  (`Instructions / Strategies / Preferences`) into a generic
  `sections` config? Phase 12+; Track 6 keeps section logic in
  IntelligenceTree.
