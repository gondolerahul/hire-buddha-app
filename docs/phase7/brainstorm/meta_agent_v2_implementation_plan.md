# Meta-Agent V2: Implementation Plan

Implement the 8 key architectural changes from the [brainstorm](file:///home/rahul/.gemini/antigravity/brain/a227368e-c723-42b0-b1fe-25122636cc77/meta_agent_architecture_brainstorm.md) to evolve the Meta-Agent from a fragile PROCESS hierarchy to a robust single REACT agent.

## Proposed Changes

### 1. Platform Schema Compiler — Behavioral Annotations

#### [MODIFY] [platform_schema_compiler.py](file:///home/rahul/workspace/hb-proto-3/backend/src/ai/meta/platform_schema_compiler.py)

Add `_compile_behavioral_annotations()` method that encodes the 15+ critical execution semantics the compiler can't extract from enums alone. Add it to the `compile()` output alongside existing sections.

Annotations cover: CORTEX tree propagation, context stripping rules, autonomous mode requirements, scraper auto-ingestion, step_id collision prevention, HITL checkpoint behavior, and more.

---

### 2. Reuse Decision Engine — IO Contract + Execution Traces

#### [MODIFY] [registry_search_service.py](file:///home/rahul/workspace/hb-proto-3/backend/src/ai/meta/registry_search_service.py)

**Phase 1.5 — IO Contract Compatibility:**
- Add `_score_io_compatibility()` that checks input/output schema property overlap between the candidate entity and the request's `io_schema`.

**Phase 2.5 — Execution Trace Weighting:**
- Add `_score_execution_history()` that calls the existing `get_execution_traces()` method (currently unused) to score candidates based on success rate, cost efficiency, and recency.

**Updated Weights:**
```python
STRUCTURAL_WEIGHT = 0.25
IO_CONTRACT_WEIGHT = 0.15
SEMANTIC_WEIGHT = 0.35
EXECUTION_WEIGHT = 0.25
```

Wire both new scoring phases into `search()` between Phase 1 and Phase 2, and after Phase 2 respectively.

---

### 3. Anti-Sprawl Hard Gate + Semantic Deduplication

#### [MODIFY] [anti_sprawl.py](file:///home/rahul/workspace/hb-proto-3/backend/src/ai/meta/anti_sprawl.py)

Add `check_semantic_duplicate()` method that searches for entities with >85% similarity before allowing creation. Uses `RegistrySearchService` internally.

#### [MODIFY] [entity_creator.py](file:///home/rahul/workspace/hb-proto-3/backend/src/ai/tools/meta/entity_creator.py)

Wire anti-sprawl as a **hard gate** in `_create_entity()`:
1. Check `check_creation_allowed()` — block if daily limit exceeded
2. Check `check_semantic_duplicate()` — block if near-duplicate exists (>85% match), suggest VERSION mode instead

---

### 4. Schema Validator — Semantic Coherence Check

#### [MODIFY] [schema_validator.py](file:///home/rahul/workspace/hb-proto-3/backend/src/ai/tools/meta/schema_validator.py)

Add `_validate_semantic_coherence()` method: a lightweight LLM call (~100 tokens) that checks whether the entity's system_prompt, tool selection, and step sequence are semantically aligned. Add as step 7 in `run_with_context()`, producing warnings (not errors) for misalignment.

---

### 5. Meta-Agent Template — Collapse to Single REACT Agent

#### [MODIFY] [meta_agent_template.py](file:///home/rahul/workspace/hb-proto-3/backend/src/ai/meta/meta_agent_template.py)

**This is the biggest change.** Replace the 5-entity hierarchy (PROCESS + 4 child AGENTs) with a single AGENT entity using REACT reasoning mode with all 5 meta-tools.

The new `generate_meta_agent_template()` returns a **single entity** (not a list of 5). The REACT loop handles the workflow naturally:
1. Introspect platform → 2. Decompose requirement → 3. Search registry → 4. Decide REUSE/ADAPT/CREATE → 5. Validate + Create → 6. Test execute → 7. Report

Includes HITL checkpoint after the decision point for user confirmation.

#### [MODIFY] [seed_meta_agent.py](file:///home/rahul/workspace/hb-proto-3/backend/src/ai/meta/seed_meta_agent.py)

Simplify from creating 5 entities to creating just 1. Remove the ID mapping and child entity creation logic.

---

### 6. Meta Module Init

#### [MODIFY] [__init__.py](file:///home/rahul/workspace/hb-proto-3/backend/src/ai/meta/__init__.py)

Update module docstring to reflect V2 architecture (single REACT agent instead of PROCESS hierarchy).

---

## User Review Required

> [!IMPORTANT]
> **Breaking change: The V1 Meta-Agent PROCESS hierarchy will be replaced.** Any existing seeded Meta-Agent entities in the database will need to be re-seeded. The old 4 child entities (RequirementAnalyst, RegistryCurator, AgentArchitect, ExecutionValidator) will no longer be created. Existing instances won't be deleted but will become orphaned.

> [!WARNING]
> **The semantic coherence check in `schema_validator.py` makes an LLM call.** This adds ~$0.01 and ~500ms to every entity validation. Since validation is only called during Meta-Agent creation flows (not user-facing execution), this is acceptable, but worth noting.

## Open Questions

1. **Should the old child entity templates be preserved for backward compatibility?** I plan to keep the old `generate_meta_agent_template()` renamed to `generate_meta_agent_template_v1()` as a reference but not use it in seeding.

2. **Anti-sprawl semantic deduplication uses `RegistrySearchService` which makes an LLM call.** Should we make this configurable (e.g., `ANTI_SPRAWL_SEMANTIC_CHECK=true`) so it can be disabled in dev environments?

## Verification Plan

### Automated Tests
- Validate the new `generate_meta_agent_template()` returns a single entity dict (not a list of 5)
- Run `seed_meta_agent.py` to confirm it creates exactly 1 entity
- Test `_compile_behavioral_annotations()` returns the expected annotation list
- Test `_score_io_compatibility()` and `_score_execution_history()` with mock data
- Test anti-sprawl hard gate blocks creation when daily limit is exceeded
- Test semantic deduplication blocks >85% similar entities

### Manual Verification
- Execute the Meta-Agent via the UI with a test requirement to verify the REACT loop works end-to-end
- Confirm HITL checkpoint fires after the decision gate
