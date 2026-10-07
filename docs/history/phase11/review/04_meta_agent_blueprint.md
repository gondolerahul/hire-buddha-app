# 04 — Meta-Agent: Deep Dive and World-Class Blueprint

The Meta-Agent is the single most leveraged piece of the platform: it builds
the other agents. A 10% improvement here is a 10% improvement to *every*
generated agent.

This document audits the current Meta-Agent in detail and proposes a
**Meta-Agent v4** — a multi-role architecture board, not a single prompt
with five tools.

---

## 1. Current Meta-Agent (v3) anatomy

### 1.1 What exists today

| Component | File | What it does |
|-----------|------|--------------|
| Template | `meta/meta_agent_template.py` | Single AGENT entity, prompt-engineered with the 6-phase cognitive framework |
| Seed | `meta/seed_meta_agent.py` | Inserts the template per company on startup |
| Platform manifest | `meta/platform_schema_compiler.py` | Compiles tools, step types, behavioral rules into a markdown manifest injected into prompts |
| Registry search | `meta/registry_search_service.py` | 4-phase scoring: structural + IO + semantic + execution history |
| Anti-sprawl | `meta/anti_sprawl.py` | Daily limit, adaptation chain, semantic duplicate threshold |
| Tools | `tools/meta/*` | platform_introspect, registry_search, schema_validator, entity_creator, entity_executor |

### 1.2 The current cognitive framework (the prompt)

The Meta-Agent system prompt (`meta_agent_template.py:28-244`) walks the
LLM through 6 phases:

```
1. UNDERSTAND  → decompose requirement into structured primitives
2. SEARCH      → meta_registry_search
3. DECIDE      → REUSE / ADAPT / COMPOSE / CREATE
4. BUILD       → design + validate + create
5. TEST        → meta_entity_executor sandboxed at $1.00
6. DELIVER     → final report
```

It is reasonable. The system prompt has explicit invariants ("NEVER include
meta_ tools," "ALWAYS validate before creating"). The schema dump is
included.

### 1.3 The pipeline today

```
User input ───▶ MetaAgent (one AGENT, REACT mode, 12 turns)
                  │
                  │ tool calls (REACT loop):
                  ├─▶ meta_registry_search   (semantic + structural search)
                  ├─▶ meta_schema_validator  (Pydantic validation)
                  ├─▶ meta_entity_creator    (CREATE or VERSION mode)
                  ├─▶ meta_entity_executor   (test run, $1 cap)
                  └─▶ meta_platform_introspect (full schema, if asked)
                  │
                  ▼
           Final report (decision + entity_id)
```

### 1.4 Strengths

* Templated prompt is *thoughtful* (entity-type selection guide,
  prompt-engineering rules, invariant list).
* The registry search has four legitimate scoring axes.
* Anti-sprawl exists with three hard gates.
* All meta-tools use isolated AsyncSessions (good).
* Tier 1 meta-cognition (platform_awareness) is automatically injected.

### 1.5 Weaknesses (the gap between v3 and "world-class")

| # | Weakness | Why it matters |
|---|---------|----------------|
| W1 | **No learning loop.** Generated entities' real-world outcomes never flow back into Meta-Agent guidance. | Same mistakes repeat (e.g. "always uses CHILD_ENTITY_INVOCATION without enough context"). |
| W2 | **No peer-review / critic on generated specs.** `meta_schema_validator` is *syntactic* only. There is no "would this work?" critic before persistence. | Bad agents persist, then waste credits on `meta_entity_executor`. |
| W3 | **Test execution is a single $1 sandbox run.** No A/B vs the existing top candidate. No regression suite. | "Tested" generated agents still routinely flop on real data. |
| W4 | **Adaptation is clone+modify**, not "what made the original succeed/fail." | Adaptations inherit baggage. |
| W5 | **Anti-sprawl is hard-coded numeric** (10/day, 3 adaptations, 0.85 similarity). It cannot say "merge these two near-duplicates." | Bloat over months. |
| W6 | **Meta-Agent prompt is static.** It cannot self-edit its own prompt as the platform's tools evolve. | Drift between platform reality and Meta-Agent's mental model. |
| W7 | **No multi-model strategy.** Same model role for understand, build, validate, critique. | All-or-nothing model upgrades. |
| W8 | **No "tool synthesis."** Cannot create a *new* tool, only compose existing ones. | Voyager / Devin can; we can't. |
| W9 | **No "skill promotion."** Cannot detect that an ad-hoc 3-step chain has been run 8 times successfully and promote it to a reusable SKILL. | Wastes the platform's own emergent intelligence. |
| W10 | **Single-agent failure mode.** The Meta-Agent's REACT loop is the *only* safeguard. If the LLM hallucinates a spec that passes schema validation, the bad entity is created. | One bad model day = bad agents enter the catalogue. |
| W11 | **No diff visualization** for ADAPT mode. The LLM must mentally compute the diff vs source. | Bigger ADAPT operations get murky. |
| W12 | **No "ask the user" pattern**. Even with `UncertaintySignal` available, the Meta-Agent rarely uses it (single static-plan step, hard to mid-stream-pause). | UX feels brittle. |
| W13 | **`is_meta_agent` flag bypasses runtime creation HITL.** Auditing is harder. | Trust gap. |
| W14 | **`resolve_meta_cognition` auto-enables `self_modification` for every AGENT/PROCESS by default** (`meta/platform_schema_compiler.py:783-838`). This means **any agent can create more agents.** | Strong sprawl risk; the Meta-Agent is no longer the sole architect. |

---

## 2. The blueprint: Meta-Agent v4 — the Architecture Board

The leap from v3 to v4 is from "one prompt with five tools" to **"a council
of specialists with their own memories, calibrated against outcomes."**

### 2.1 Roles

```
                              ┌───────────────────┐
                              │  Front Office     │
                              │  (RequirementChat)│
                              └────────┬──────────┘
                                       │ structured spec
                                       ▼
        ┌──────────────────────────────────────────────┐
        │              ARCHITECTURE BOARD              │
        │                                              │
        │  ┌─────────────┐    ┌─────────────┐         │
        │  │ Architect   │    │ Curator     │         │
        │  │ (build/adapt│◀──▶│ (registry + │         │
        │  │  spec)      │    │  sprawl mgmt│         │
        │  └──────┬──────┘    └──────┬──────┘         │
        │         │                  │                 │
        │         ▼                  ▼                 │
        │  ┌─────────────┐    ┌─────────────┐         │
        │  │ Critic      │    │ Validator   │         │
        │  │ (red-team)  │    │ (schema +   │         │
        │  │             │    │  static an.)│         │
        │  └──────┬──────┘    └──────┬──────┘         │
        │         │                  │                 │
        │         └────────┬─────────┘                 │
        │                  ▼                           │
        │         ┌─────────────────┐                  │
        │         │ Test Driver     │                  │
        │         │ (suite runner)  │                  │
        │         └────────┬────────┘                  │
        │                  │                           │
        │                  ▼                           │
        │         ┌─────────────────┐                  │
        │         │ Promoter        │                  │
        │         │ (PROD vs DRAFT) │                  │
        │         └────────┬────────┘                  │
        └──────────────────┼───────────────────────────┘
                           ▼
                  Entity Catalogue
                  + Meta-Intelligence Tree
```

* **RequirementChat** — Front office. Owns clarifying questions. Output is
  a structured `Spec` (intent / constraints / IO contract / known examples).
  This is the only role talking to the user.
* **Curator** — Searches the registry (current `RegistrySearchService`) and
  manages sprawl. Owns REUSE / ADAPT / COMPOSE / CREATE decision *and*
  proposes merges of near-duplicates.
* **Architect** — Synthesises a HierarchicalEntity payload (today's
  Meta-Agent's "BUILD" phase).
* **Critic** — Red-teams the spec against known failure patterns (drawn
  from the Meta-Intelligence Tree). Uses a *different* model than the
  Architect.
* **Validator** — Schema + static analysis: cycle detection in CHILD
  invocations, dangling entity_ids, prompt_template variables resolve,
  cost estimation, budget feasibility.
* **Test Driver** — Runs a *suite* of tests (not one), each capped, with
  golden-output comparison if available; can fall back to LLM judge.
* **Promoter** — Promotes from DRAFT → ACTIVE only if all gates pass.
  Owns `is_meta_agent` clearance.

Each role can be one LLM call (or zero, in the validator's case). They are
*not* separate `HierarchicalEntity`s — that adds overhead. They are
*services* inside the Meta-Agent's runtime.

### 2.2 The interaction is a graph, not a chain

```
Architect ⇄ Critic (until critic is satisfied or max_iters)
Architect ⇄ Validator (until validator passes)
Architect ⇄ Curator (if Curator wants merge / version)
Test Driver → Architect (if tests fail, with structured failure tags)
Promoter → user (if HITL needed)
```

The Meta-Agent's own *AgentLoop* (see §03) is the natural fit:

* Open subgoals = each role's remaining work.
* Reflections = what the Critic / Validator caught.
* Skill library = patterns that pass critic+validator first time become
  reusable "architecture moves."

So the Meta-Agent **uses** the AgentLoop it builds for everybody else.
That's the right symmetry.

---

## 3. Concrete additions vs deletions

### 3.1 New components to introduce

| Component | Description | Where it lives |
|-----------|-------------|----------------|
| `meta/board/requirement_chat.py` | Clarification dialog, emits `Spec` | new |
| `meta/board/architect.py` | Spec → entity payload | extracted from today's prompt |
| `meta/board/critic.py` | Red-team + failure-pattern-aware | new (uses Intelligence Tree) |
| `meta/board/validator.py` | Static checks beyond pydantic | new |
| `meta/board/test_driver.py` | Suite runner | replaces today's `meta_entity_executor` 1-shot test |
| `meta/board/promoter.py` | Gate + audit | new |
| `meta/meta_intelligence_tree.py` | Cross-entity learnings written by all roles | new (subtype of IntelligenceTree, scope=`platform`) |
| `meta/skill_library.py` | Detects + persists reusable plans → SKILL entities | new |
| `meta/tool_synthesis.py` | Optional: synthesise new tools from NL description | new (advanced) |

### 3.2 Today's components that become *plumbing* for the board

| Today | Role under v4 |
|-------|---------------|
| `meta/meta_agent_template.py` | Becomes a thin orchestrator: it dispatches to the board roles, no longer the full brain |
| `meta/platform_schema_compiler.py` | Used by Architect and Critic |
| `meta/registry_search_service.py` | Used by Curator |
| `meta/anti_sprawl.py` | Used by Curator |
| `tools/meta/schema_validator.py` | Used by Validator |
| `tools/meta/entity_creator.py` | Used by Promoter |
| `tools/meta/entity_executor.py` | Used by Test Driver |
| `tools/meta/registry_search.py` | Used by Curator |
| `tools/meta/platform_introspect.py` | Used by Architect |

No tool is deleted; they all keep functioning. The change is in *who* uses
them and *when*.

---

## 4. The Critic — the most important new role

### 4.1 Why a separate Critic matters

A single-model Meta-Agent that writes *and* checks its own spec is the
agentic equivalent of a developer reviewing their own PR. Models are
biased toward their own outputs.

### 4.2 Critic's inputs

* Spec (from RequirementChat)
* Draft entity payload (from Architect)
* Top-K nearest entities (from Curator)
* Failure rules from **Meta-Intelligence Tree** (filtered by spec tags)
* Platform manifest (Tier 1 awareness)

### 4.3 Critic's prompt anchors

The Critic prompt is **adversarial by construction**:

> "You are a senior staff engineer reviewing this agent specification.
> Assume the Architect is overconfident. Your job is to enumerate
> every plausible failure mode. For each failure mode, cite a concrete
> input that triggers it, an expected pathology, and the cheapest fix.
> If you cannot find ≥3 issues, you are not looking hard enough."

It is allowed to escalate to:

* **BLOCK** — spec fundamentally broken (cycle, missing tool capability,
  cost > governance ceiling).
* **REVISE** — fix specific issues; Architect re-runs.
* **PASS** — go to Validator.

### 4.4 Different model for the Critic

Critic should use a **second model** by default (e.g. Architect on Sonnet,
Critic on Opus, or vice-versa). Even using the *same* model with a
non-overlapping seed and a contradicting persona gives a non-trivial lift
in research.

This is a one-line setting in `meta/board/critic.py`:

```python
model_override = "claude-opus-4-7"  # default; configurable per company
```

### 4.5 Critic's persistent record

Every Critic ruling becomes a **node in the Meta-Intelligence Tree**:

```
Meta-Intelligence Tree
└── Architecture Anti-Patterns
    ├── Rule: "PROCESS entities with >5 children rarely complete within budget"
    │  evidence: 14 failures, 2 successes
    ├── Rule: "REACT with goal_validation_interval=0 drifts off-topic"
    │  evidence: …
    └── Rule: "Tool 'image_generation' as step 1 without prior search produces unrelated images"
       evidence: …
```

The Critic queries this on every spec review. Over time the rules tighten.

---

## 5. The Test Driver — beyond a single $1 run

Today: `meta_entity_executor` runs *one* test, $1 cap, no comparison
baseline.

Proposal: the Test Driver runs a **suite**.

| Test | What it does | When |
|------|--------------|------|
| Smoke | One representative input; check no exceptions | always |
| Comparative | Same input through TOP-2 search results (REUSE candidate) and the new entity; LLM-judge which is better | when ADAPT/CREATE on a contested space |
| Boundary | Edge inputs from the spec's `io_contract` (empty string, max-length, multilingual) | always |
| Regression | If ADAPT: run source entity's last 3 episodic inputs through new entity; flag regressions | ADAPT only |
| Hostile | Adversarial inputs the Critic suggested; check graceful failure (UncertaintySignal, not silent wrong output) | always |

All tests share a **suite budget** (e.g. $3 total). Test Driver writes the
results into a sub-node of the entity's CORTEX tree before Promoter sees
them.

---

## 6. The Promoter — gating and lifecycle

| Gate | Rule |
|------|------|
| G1 | All critic concerns resolved or explicitly accepted |
| G2 | Validator green |
| G3 | Test suite ≥ pass threshold |
| G4 | Test cost ≤ test budget |
| G5 | Anti-sprawl (daily limit, semantic dedup) |
| G6 | Cost projection for *real* use ≤ entity's `max_cost_usd` |

On promotion: `status = ACTIVE`, audit row, optional HITL "deploy?" gate.
DRAFT-stage entities can be tested in the UI but are invisible to other
PROCESS entities until promoted.

---

## 7. Meta-Intelligence Tree — the Meta-Agent's own memory

Today's Intelligence Tree is scoped to an *entity*. The Meta-Agent needs a
*platform*-scoped one:

```
MetaIntelligenceTree (scope=PLATFORM, owner=meta_agent)
├── Spec Patterns       — common request shapes, suggested templates
├── Architecture Rules  — populated by Critic
├── Test Failure Tags   — populated by Test Driver
├── Curator Decisions   — REUSE/ADAPT/COMPOSE outcomes with eventual quality scores
└── Tool Reliability    — per-tool real-world success rates per task class
```

It is read by every board role.

It is written by:
* Critic (during review)
* Test Driver (after suite)
* `core/meta_review.MetaReviewer` (after a *promoted* entity's real
  executions, periodically — connecting the loop to long-term outcomes)

This is the engine of compounding improvement. Without it, v4 is just v3
with extra prompts.

---

## 8. Self-modification of the Meta-Agent itself

Once the board is in place, two new abilities become possible:

### 8.1 Prompt evolution

Daily / weekly job:
1. Sample 20 recent Meta-Agent runs.
2. For each: ask a *Critic-of-Critics* (separate prompt) what the
   Meta-Agent itself did wrong.
3. Aggregate into a `prompt_update_candidate` saved in the
   MetaIntelligenceTree.
4. HITL approves → Meta-Agent's prompt is bumped to v3.x.y.

### 8.2 Tool set evolution

The Meta-Agent can propose adding a new meta-tool when a recurring need is
detected (e.g. "spec→test-suite generator"). HITL gates new meta-tools.

These both fold into the same MetaIntelligenceTree pipeline.

---

## 9. Sprawl management: from hard limits to *consolidation*

Today: `daily_limit=10`, `adaptation_threshold=3`, `similarity=0.85`.
These are blocks, not solutions.

Proposed: **active consolidation**.

When the registry has ≥5 entities with combined similarity > 0.9, the
**Curator** can propose a **merge plan**:

```
merge_plan:
  winners: [entity_A]
  losers:  [entity_B, entity_C]
  steps:
    - re-point all references from B,C to A
    - archive B, C
    - update Intelligence Tree of A with rules learned from B,C
```

This *requires* a UI confirmation and audit row. But the *option* must
exist — otherwise sprawl can only be blocked, never fixed.

---

## 10. The single sharpest fix you can make today (one-week version)

If you can only do *one* thing to lift the Meta-Agent before the full v4:

> **Add a Critic role that runs after `meta_schema_validator` and before
> `meta_entity_creator`, uses a different LLM, and writes its rulings
> into a new `MetaIntelligenceTree` so future critics learn from it.**

That single change:
* Catches the most common Meta-Agent failure mode (overconfident,
  syntactically-valid, semantically-broken spec).
* Establishes the MetaIntelligenceTree (the substrate everything else
  builds on).
* Costs one extra LLM call per Meta-Agent run (≤$0.10 typically).
* Slots in as a new tool `meta_spec_critic` that the v3 system prompt
  can call between phases 4 (BUILD) and 5 (TEST).

Once that is shipped and producing data, the rest of v4 follows naturally.

---

## 11. Concrete day-1 to day-30 checklist

| Day | Deliverable |
|-----|-------------|
| 1-3 | New tool `tools/meta/spec_critic.py` + `MetaIntelligenceTree` model |
| 4-5 | Update Meta-Agent system prompt: "After BUILD, call meta_spec_critic. Address every BLOCK before TEST." |
| 6-10 | Multi-test suite Test Driver (replace `meta_entity_executor` 1-shot) |
| 11-15 | Curator role (consolidation proposals; UI hooks) |
| 16-20 | Architect / Critic split into separate prompts with separate models |
| 21-25 | Skill promotion: detect repeated chains in episodic memory, surface as candidate SKILL entities |
| 26-30 | Self-modification gate: prompt-update candidates flow through HITL |

By day 30 the Meta-Agent is no longer a single prompt; it is a board with
memory.
