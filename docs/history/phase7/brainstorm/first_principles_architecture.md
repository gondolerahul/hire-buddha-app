# Meta-Agent Architecture — First Principles Analysis

**Status:** Architectural proposal  
**Author:** Antigravity  
**Date:** 2026-05-11  
**Scope:** Strip all V1/V2/V3 assumptions. Reason from what the codebase *actually is*.

---

## 1. Ground Truth — What HireBuddha Actually Is

Before any architecture, five axioms derived from reading every line of the platform:

### Axiom 1: The unit of agency is a typed JSON document

`HierarchicalEntity` (`models.py:44`) is one DB row with 8 JSON columns. The Meta-Agent's *entire job* is to produce a valid instance of this document — or find an existing one. This is **not** open-ended code generation. It is **constrained structured output** against a known schema.

### Axiom 2: The platform surface is finite and small

- 4 entity types: `ACTION → SKILL → AGENT → PROCESS`
- 9 step types: `THOUGHT`, `ACTION`, `TOOL_CALL`, `CHILD_ENTITY_INVOCATION`, + 5 CORTEX ops
- ~14 built-in tools + tenant-scoped custom tools
- 2 execution modes: `STANDARD`, `AUTONOMOUS`
- 2 memory modes: `EPISODIC`, `SEMANTIC`

The entire capability surface fits in ~10KB of summarized text. You do **not** need RAG, knowledge graphs, or incremental introspection. You need one prompt with the manifest injected.

### Axiom 3: The decision tree is finite and deterministic at the branch level

The Meta-Agent's workflow is always:

```
1. Understand intent    → structured spec       (LLM)
2. Search registry      → scored candidates     (deterministic + 1 LLM call for semantic)
3. Decide strategy      → REUSE/ADAPT/CREATE    (deterministic threshold)
4. If not REUSE: generate entity JSON           (LLM)
5. Validate                                     (deterministic)
6. Persist                                      (deterministic)
```

Steps 2, 3, 5, 6 are **programmatic operations** — DB queries, schema validation, DB writes. Only steps 1 and 4 require LLM reasoning. Step 3 uses the LLM only for semantic scoring inside `RegistrySearchService`.

### Axiom 4: The execution engine is the wrong host for the Meta-Agent

`worker.py` (~1.7K LOC) + `step_executor.py` (~1.3K LOC) are designed for executing **user-defined entities** with arbitrary plans, CORTEX trees, DAG fan-out, context summarization, and memory retrieval. When the Meta-Agent runs through this engine:

- It inherits complexity it doesn't use (CORTEX viewport, episodic memory, context pruning)
- Its errors get entangled with the engine's errors (the MissingGreenlet bugs from conversation `332e38de`)
- Its cost is inflated by engine overhead (memory retrieval, sandwich prompt construction, REACT self-narration)
- Each REACT turn wastes ~2K tokens on "I should now search the registry..." narration × 8 turns = **~16K tokens of overhead**

### Axiom 5: REACT is for open-ended problems; this problem is closed

REACT's strength is **dynamic tool selection** — the LLM decides what to do next based on observations. But the Meta-Agent's tool sequence is known in advance:

```
introspect → search → decide → [generate] → validate → create → [test-execute]
```

The only real branch is at step 3 (REUSE vs ADAPT vs CREATE). REACT spends 8-12 turns discovering a workflow that could be hardcoded in 50 lines of Python.

---

## 2. The Core Insight: The Meta-Agent Is a Compiler

The Meta-Agent compiles **natural language intent** into **a typed intermediate representation** (the HierarchicalEntity JSON). This is the same problem structure as a programming language compiler:

```
Source code  →  [Frontend]  →  IR  →  [Optimizer]  →  IR  →  [Backend]  →  Machine code
     ↕               ↕           ↕          ↕            ↕         ↕             ↕
NL intent   →  [Parser]    → IntentSpec → [Search]  → Decision → [CodeGen] → Entity JSON
```

| Compiler Stage | Meta-Agent Equivalent | Implementation |
|---|---|---|
| **Lexer/Parser** | Intent analysis | 1 LLM call → structured `IntentSpec` |
| **Semantic Analysis** | Registry search + scoring | `RegistrySearchService` (existing, deterministic + 1 LLM) |
| **Optimizer** | Reuse decision | Deterministic thresholds on scores |
| **Code Generator** | Entity synthesis | 1 LLM call → structured `HierarchicalEntity` JSON |
| **Linker** | Validation | `MetaSchemaValidatorTool` (existing, deterministic) |
| **Loader** | Persistence | `AIService.create_entity()` (existing) |

**Total LLM calls: 2-3** (vs V2's 5-12 REACT turns)  
**Total cost: ~$0.03-0.08** (vs V2's ~$0.50-2.00)  
**Total latency: ~3-8s** (vs V2's ~15-45s)

---

## 3. Three Architectural Options

### Option A — Deterministic Pipeline Service (The Compiler)

A dedicated `MetaAgentService` class with a hardcoded pipeline. No REACT. No worker. No entity-as-agent.

```python
class MetaAgentService:
    """Compiles NL intent → HierarchicalEntity."""

    async def synthesize(self, intent: str, user_id, company_id) -> SynthesisResult:
        # Stage 1: Parse intent (1 LLM call)
        spec = await self._parse_intent(intent)

        # Stage 2: Search registry (deterministic + 1 semantic LLM call)
        candidates = await self.registry_search.search(spec)

        # Stage 3: Decide strategy (deterministic)
        decision = self._decide(candidates, spec)

        # HITL checkpoint
        if decision.needs_confirmation:
            await self._request_approval(decision)

        # Stage 4: Execute decision
        if decision.strategy == "REUSE":
            return SynthesisResult(entity_id=decision.candidate.id)

        if decision.strategy == "ADAPT":
            entity_json = await self._generate_adaptation(decision, spec)
        else:  # CREATE
            entity_json = await self._generate_entity(spec)

        # Stage 5: Validate (deterministic)
        errors = await self.validator.validate(entity_json)
        if errors:
            entity_json = await self._fix_errors(entity_json, errors)

        # Stage 6: Anti-sprawl + persist (deterministic)
        self.anti_sprawl.check_creation_allowed(company_id)
        self.anti_sprawl.check_semantic_duplicate(entity_json, company_id)
        entity = await self.ai_service.create_entity(entity_json)

        return SynthesisResult(entity_id=entity.id, decision=decision)
```

**Pros:**
- Predictable cost (2-3 LLM calls, always)
- Predictable latency (3-8s, always)
- Fully testable (each stage is a unit-testable method)
- No worker overhead, no REACT narration waste
- Errors are in service code, not in LLM reasoning traces
- Governance applied programmatically (credit check, HITL, audit)

**Cons:**
- Loses self-referentiality (Meta-Agent is no longer "just another agent")
- No CORTEX memory for cross-session learning
- Rigid workflow — adding a new step requires code change, not config change
- Can't handle truly novel situations that need open-ended reasoning

### Option B — Enhanced REACT Agent (V2 Improved)

Keep the current architecture but fix the waste:
- Inject manifest into system prompt once (not via tool call)
- Pre-run registry search before REACT starts (don't waste turns on it)
- Limit REACT to 4 turns max (decision + action + validate + report)
- Add structured output mode for entity generation

**Pros:**
- Minimal code change from V2
- Retains self-referentiality
- Retains CORTEX memory and governance inheritance
- Handles ambiguous cases via natural REACT reasoning

**Cons:**
- Still 4+ LLM calls minimum (REACT overhead)
- Still inherits worker complexity
- Still unpredictable cost/latency (LLM decides turn count)
- Still entangles Meta-Agent errors with engine errors

### Option C — Hybrid: Deterministic Pipeline + REACT Escape Hatch (Recommended)

**The pipeline is deterministic by default. The LLM can signal "I need to reason" at exactly one decision point, triggering a bounded REACT sub-loop.**

```
┌─────────────────────────────────────────────────────────┐
│                  MetaAgentService                       │
│                                                         │
│  ┌──────────┐    ┌──────────┐    ┌──────────────────┐  │
│  │ Stage 1  │───▶│ Stage 2  │───▶│    Stage 3       │  │
│  │ Parse    │    │ Search   │    │    Decide        │  │
│  │ (1 LLM)  │    │ (determ.)│    │                  │  │
│  └──────────┘    └──────────┘    │  score ≥ 0.85 ──▶│──▶ REUSE (fast path)
│                                  │  score ≥ 0.60 ──▶│──▶ ADAPT (1 LLM call)
│                                  │  score < 0.40 ──▶│──▶ CREATE (1 LLM call)
│                                  │                  │  │
│                                  │  AMBIGUOUS ──────▶│──▶ REACT sub-loop
│                                  │  (0.40-0.60, or  │    (max 4 turns)
│                                  │   top 2 within   │    (clarify + decide)
│                                  │   0.05 of each   │  │
│                                  │   other)         │  │
│                                  └──────────────────┘  │
│                                                         │
│  ┌──────────┐    ┌──────────┐    ┌──────────────────┐  │
│  │ Stage 4  │───▶│ Stage 5  │───▶│    Stage 6       │  │
│  │ Generate │    │ Validate │    │    Persist       │  │
│  │ (1 LLM)  │    │ (determ.)│    │    (determ.)     │  │
│  └──────────┘    └──────────┘    └──────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

The REACT escape hatch triggers **only** when:
1. Top two candidates are within 0.05 of each other (disambiguation needed)
2. Score is in the 0.40-0.60 dead zone (ADAPT vs CREATE is unclear)
3. The IntentSpec parser signals low confidence (ambiguous user intent)

In practice, **~80% of requests hit the fast path** (clear REUSE or clear CREATE). Only the ambiguous 20% enter REACT, and even then it's bounded to 4 turns.

**Pros:**
- Fast path: 2-3 LLM calls, $0.03-0.08, 3-8s (covers 80% of cases)
- Slow path: 4-7 LLM calls, $0.15-0.30, 10-20s (covers the remaining 20%)
- Fully testable pipeline with predictable cost for common cases
- Graceful degradation for ambiguous cases
- No worker overhead — dedicated service
- Governance applied programmatically (same guarantees, less machinery)

**Cons:**
- More code than Option A (REACT sub-loop adds ~200 LOC)
- Loses CORTEX memory (addressed below in §5)
- Two code paths to maintain (pipeline + REACT fallback)

---

## 4. Recommendation: Option C (Hybrid)

### 4.1 Why Not Pure REACT (Option B / V2)

V2 treats the Meta-Agent as an open-ended reasoning agent. But the problem isn't open-ended — it's a **search + generation** pipeline with exactly one decision point. Using REACT for this is like using a neural network to sort a list: technically works, dramatically over-engineered, unpredictably expensive.

The empirical evidence supports this. From the execution logs:
- Most Meta-Agent runs follow the same tool sequence: `introspect → search → create/reuse → validate → report`
- REACT "discovers" this sequence every time, wasting 3-5 turns on narration
- The 10-turn cap often gets hit on COMPOSE paths, causing incomplete results
- MissingGreenlet errors (conversation `332e38de`) were caused by running meta-tools through the worker's session lifecycle — a problem that doesn't exist in a dedicated service

### 4.2 Why Not Pure Pipeline (Option A)

Pure pipeline can't handle the 20% of cases where the decision is genuinely ambiguous. When a user says "build me something that handles leads" and there are 3 agents at scores 0.55, 0.52, 0.48 — the system needs to **ask a clarifying question**, not silently pick one. REACT's natural language reasoning is the right tool for that specific sub-problem.

### 4.3 Why Hybrid (Option C)

The hybrid gives you **predictable performance for predictable cases** and **flexible reasoning for ambiguous cases**. The key design decision is that the REACT sub-loop is:
- **Bounded** (4 turns max)
- **Scoped** (only decides between candidates; doesn't re-search or re-introspect)
- **Isolated** (runs via `LLMRouter.call_llm_react()`, not through the worker)

---

## 5. Detailed Design — The Compiler Architecture

### 5.1 IntentSpec — The Intermediate Representation

The output of Stage 1 (intent parsing). This is the **contract** between the parser and all downstream stages:

```python
@dataclass
class IntentSpec:
    """Structured representation of user's agent-building intent."""
    intent_normalized: str           # Canonical description
    required_tools: list[str]        # Tools the agent must have
    preferred_type: EntityType       # ACTION/SKILL/AGENT/PROCESS
    complexity: str                  # LOW/MEDIUM/HIGH
    io_schema: dict                  # {input: {...}, output: {...}}
    constraints: list[str]           # "must use Apollo API", "max $0.50/run"
    confidence: float                # Parser's self-assessed confidence (0-1)
```

Generated via a **single LLM call with structured output** (JSON mode). The platform manifest is injected into the system prompt so the LLM knows what tools exist.

### 5.2 SearchResult — The Decision Input

Output of Stage 2. Wraps the existing `RegistrySearchService` output:

```python
@dataclass
class SearchResult:
    candidates: list[ScoredCandidate]   # Ranked by combined score
    decision: str                        # REUSE/ADAPT/COMPOSE/CREATE/AMBIGUOUS
    ambiguity_reason: str | None         # Why AMBIGUOUS, if applicable
    top_score: float
    runner_up_score: float | None
```

**Key change from V2:** Add `AMBIGUOUS` as a fifth decision outcome. Triggers when:
- Top two candidates within 0.05 of each other
- Top score in 0.40-0.60 range
- `IntentSpec.confidence < 0.7`

### 5.3 Decision Logic — Hardened Thresholds + Hard Filters

```python
def _decide(self, search: SearchResult, spec: IntentSpec) -> Decision:
    top = search.candidates[0] if search.candidates else None

    # Hard filter: tool coverage veto (V3 brainstorm §B.2 Option α)
    if top and top.tool_coverage < 0.7:
        return Decision("CREATE", reason="Insufficient tool coverage")

    # Ambiguity detection
    if self._is_ambiguous(search, spec):
        return Decision("AMBIGUOUS", candidates=search.candidates[:3])

    # Standard thresholds
    if top and top.combined_score >= 0.85:
        return Decision("REUSE", candidate=top)
    elif top and top.combined_score >= 0.60:
        return Decision("ADAPT", candidate=top)
    elif len(search.candidates) >= 2 and search.candidates[1].combined_score >= 0.40:
        return Decision("COMPOSE", candidates=search.candidates[:3])
    else:
        return Decision("CREATE")
```

### 5.4 Entity Generation — Structured Output

Stage 4 uses a **single LLM call with JSON mode** to generate the full entity payload:

```python
async def _generate_entity(self, spec: IntentSpec) -> dict:
    system = f"""You are an agent architect for the HireBuddha platform.
Generate a complete HierarchicalEntity JSON payload.

## Platform Manifest
{self.manifest_summary}

## Schema Requirements
{self.schema_requirements}

## Rules
- Only use tools from the manifest
- Set governance.max_cost_usd based on complexity
- Include HITL checkpoints for any egress tools (email, slack)
- Step step_ids must be unique UUIDs
"""
    user = f"""## User Intent
{spec.intent_normalized}

## Required Tools: {spec.required_tools}
## Entity Type: {spec.preferred_type}
## IO Schema: {json.dumps(spec.io_schema)}
## Constraints: {spec.constraints}

Generate the complete entity JSON:"""

    response = await self.llm.call_llm(
        task_type="text_generation",
        system_prompt=system,
        user_prompt=user,
        temperature=0.3,
        response_format={"type": "json_object"},
    )
    return json.loads(response.output)
```

### 5.5 REACT Escape Hatch — Bounded Disambiguation

When the decision is `AMBIGUOUS`, enter a mini-REACT loop:

```python
async def _disambiguate(self, candidates: list, spec: IntentSpec) -> Decision:
    """Bounded REACT loop for ambiguous cases. Max 4 turns."""
    system = f"""You are deciding between agent candidates for a user.
Candidates: {json.dumps([c.summary() for c in candidates])}
User intent: {spec.intent_normalized}

You have these tools:
- ask_user(question: str) → Ask the user a clarifying question
- select_candidate(id: str, strategy: str) → Pick a candidate
- reject_all() → None of these work; signal CREATE

You MUST call exactly one tool per turn. Max 4 turns."""

    # Run bounded REACT via LLMRouter
    result = await self.llm.call_llm_react(
        system_prompt=system,
        user_prompt=f"Which candidate best fits: {spec.intent_normalized}?",
        tools=[ask_user_schema, select_candidate_schema, reject_all_schema],
        execute_tools=self._execute_disambiguation_tools,
        max_turns=4,
    )
    return self._parse_disambiguation_result(result)
```

### 5.6 Governance — Programmatic, Not Inherited

The `MetaAgentService` applies governance directly:

```python
async def synthesize(self, intent, user_id, company_id):
    # Credit gate
    await self.governance.check_credit_gate(company_id, "META_AGENT")

    # ... pipeline stages ...

    # Anti-sprawl
    self.anti_sprawl.check_creation_allowed(company_id)
    self.anti_sprawl.check_semantic_duplicate(entity_json, company_id)

    # HITL checkpoint (via API, not Redis pub/sub)
    if decision.needs_confirmation:
        approval = await self._create_approval_request(decision)
        # Return to frontend; resume on approval callback

    # Audit log
    self._log_audit(intent, spec, decision, entity_id)

    # Cost tracking
    await self.usage_service.log_usage(company_id, "meta-agent", ...)
```

### 5.7 Memory — Lightweight Provenance, Not CORTEX

The Meta-Agent doesn't need CORTEX trees. It needs **decision provenance**:

```python
# Stored as metadata_extensions.meta_agent_provenance on created entities
provenance = {
    "intent": spec.intent_normalized,
    "decision": decision.strategy,
    "candidates_considered": [c.summary() for c in candidates[:5]],
    "top_score": decision.top_score,
    "rationale": decision.reason,
    "manifest_hash": self.manifest_hash,
    "created_at": datetime.utcnow().isoformat(),
}
```

For cross-session memory (V3 brainstorm §C.4), query provenance at decision time:

```python
# "Have I made similar decisions for this user before?"
prior = await self.db.execute(
    select(HierarchicalEntity.metadata_extensions)
    .where(
        HierarchicalEntity.company_id == company_id,
        HierarchicalEntity.metadata_extensions["meta_agent_provenance"].isnot(None),
    )
    .order_by(HierarchicalEntity.created_at.desc())
    .limit(10)
)
```

No new tables. No CORTEX overhead. Just querying existing entity metadata.

---

## 6. What This Architecture Preserves From V2

| V2 Component | Status in Compiler Model |
|---|---|
| `PlatformSchemaCompiler` | ✅ **Kept.** Compiles manifest injected into Stage 1 system prompt |
| `RegistrySearchService` (4-phase) | ✅ **Kept.** Called directly in Stage 2 |
| `AntiSprawlGuard` | ✅ **Kept.** Called in Stage 6 as hard gate |
| `MetaSchemaValidatorTool` logic | ✅ **Kept.** Validation logic extracted into Stage 5 |
| `MetaEntityCreatorTool` logic | ✅ **Kept.** Creation logic extracted into Stage 6 |
| `MetaEntityExecutorTool` | ✅ **Kept as optional.** Post-creation test execution |
| `meta_agent_template.py` | ❌ **Removed.** No entity template needed |
| `seed_meta_agent.py` | ❌ **Removed.** No entity to seed |
| REACT loop via worker | ❌ **Removed.** Replaced by deterministic pipeline |
| 5 meta-tools as Tool subclasses | ❌ **Removed.** Logic moved into service methods |

**~70% of the existing meta code is preserved.** The tool classes become service methods. The template and seeder are eliminated. The worker is bypassed entirely.

---

## 7. Failure Mode Analysis

| # | Failure | V2 (REACT) | Compiler Model |
|---|---|---|---|
| F1 | LLM hallucinates tool name | Caught at execution time (late) | Caught at Stage 5 validation (early) |
| F2 | REACT runs out of turns | Incomplete result, no recovery | N/A — no REACT in common path |
| F3 | Worker session errors (MissingGreenlet) | Frequent (conv `332e38de`) | N/A — no worker involvement |
| F4 | Unpredictable cost | $0.50-2.00 range | $0.03-0.30 range (bounded) |
| F5 | Ambiguous intent → wrong decision | LLM picks silently | `AMBIGUOUS` triggers clarification |
| F6 | Entity passes validation but fails execution | Caught only by optional test-run | Same (inherent LLM limitation) |
| F7 | Context window overflow | Possible with large manifest | N/A — manifest is summarized, no accumulation |
| F8 | Meta-Agent invoked recursively | Blocked by tool allowlist | N/A — no meta-tools to invoke |

---

## 8. Implementation Roadmap

### Phase 1: Core Service (3-4 days)

1. Create `backend/src/ai/meta/meta_agent_service.py`
   - `MetaAgentService` class with `synthesize()` method
   - `IntentSpec` dataclass
   - Stage 1: `_parse_intent()` — 1 LLM call with JSON mode
   - Stage 3: `_decide()` — deterministic thresholds + hard filters

2. Wire existing services:
   - Stage 2: Call `RegistrySearchService.search()` directly
   - Stage 5: Extract validation logic from `MetaSchemaValidatorTool`
   - Stage 6: Call `AIService.create_entity()` + `AntiSprawlGuard`

3. Stage 4: `_generate_entity()` — 1 LLM call with JSON mode

### Phase 2: API + HITL (2 days)

4. Add API endpoint: `POST /ai/meta/synthesize`
   - Request: `{intent: str, options?: {...}}`
   - Response: `{decision, entity_id?, approval_id?}`

5. HITL integration:
   - `POST /ai/meta/synthesize` returns `202 Accepted` with `approval_id` when HITL needed
   - `POST /ai/meta/approve/{approval_id}` resumes pipeline
   - Uses existing `HumanApproval` model

### Phase 3: REACT Escape Hatch (2 days)

6. Implement `_disambiguate()` bounded REACT loop
7. Add `AMBIGUOUS` detection logic in `_decide()`
8. Wire `ask_user` tool to HITL approval flow

### Phase 4: Hardening (2-3 days)

9. Add tool coverage hard filter to `RegistrySearchService` (V3 brainstorm §B.2)
10. Add exponential recency decay (replace step-function)
11. Cross-session provenance reader
12. Audit logging
13. Integration tests

**Total: ~10 days** to replace V2 with a system that is cheaper, faster, more predictable, and more testable.

---

## 9. The Self-Referentiality Question

> *"But if the Meta-Agent isn't a HierarchicalEntity, it breaks the platform's self-consistency — the agent builder isn't built with agents."*

This is the strongest argument for V2. Here's why it's wrong:

**Compilers are not written in their own output language.** GCC is written in C, not in x86 assembly. The Rust compiler is written in Rust (bootstrapped), but it doesn't *execute as* a Rust program — it's a build tool. Similarly, the Meta-Agent should be a **build tool** for the platform, not a product of it.

The platform's value proposition is: *"users create and execute AI agents."* The Meta-Agent is infrastructure that helps users do this faster. Making it "just another agent" is elegant in theory but creates practical problems:
- Debugging meta-agent failures requires understanding both the agent's reasoning AND the worker's execution — two interleaved failure domains
- Performance tuning requires modifying entity JSON configs instead of code — slower iteration
- The Meta-Agent inherits every worker bug and every context engineering edge case

The right boundary: **the Meta-Agent uses the platform's services** (schema compiler, registry search, entity creation, validation) **but not its execution engine** (worker, step executor, CORTEX bridge).

---

## 10. Open Decisions for You

> [!IMPORTANT]
> Three decisions that affect implementation order:

### Q1: COMPOSE path — adapter SKILLs or monolithic AGENT?
When the user needs capabilities from multiple existing agents, should we generate adapter SKILLs + a PROCESS wrapper (compositional but complex) or a single self-contained AGENT (simpler but duplicates logic)?

**My recommendation:** Single AGENT for V1 of the compiler. Add COMPOSE-via-adapters as a V2 enhancement once the pipeline is stable.

### Q2: Frontend integration — dedicated page or inline in existing agent builder?
The pipeline returns a `SynthesisResult`. Should this power a new "Meta-Agent Console" page, or integrate into the existing entity creation flow as an "AI Assist" button?

**My recommendation:** New dedicated page. The three-round HITL flow (V3 brainstorm §E.2) needs its own UI surface.

### Q3: V2 migration — parallel run or hard cutover?
Keep V2 entity + meta-tools operational during migration, or remove them?

**My recommendation:** Parallel for 2 weeks. V2 entity stays seeded but the default API route points to the new `MetaAgentService`. Feature flag `META_AGENT_VERSION=v3` to switch.
