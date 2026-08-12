# Track 5 — Meta-Agent v4 Architecture Board (Weeks 7-8)

> **Owner:** AI / ML engineer.
> **Duration:** 10 working days (≈2 calendar weeks).
> **Behaviour change:** Meta-Agent gets a multi-role internal pipeline,
>   a `meta_spec_critic` tool, a real test suite runner, a sprawl curator,
>   a promotion gate, and starts populating a platform-scoped
>   `MetaIntelligenceTree`. Behind `meta_agent.board_routing` (default
>   ON for new Meta-Agent runs once Day-5 lands).
> **Risk:** Medium-high. The Meta-Agent builds all other agents — quality
>   regression here is amplified. Strong canary + rollback.
> **Goal mapping:** G2 (world-class Meta-Agent), G7 (per-level
>   meta-cognition), G8 (reflections compound into intelligence).

This is the most user-visible Track of the programme: every agent the
platform produces from Week 8 onward goes through the Board.

---

## 1. Objectives (functional)

After Track 5:

1. The Meta-Agent uses a **multi-role Architecture Board**:
   `RequirementChat → Curator → Architect → Critic → Validator →
   TestDriver → Promoter`.
2. A new tool **`meta_spec_critic`** runs between BUILD and TEST in the
   Meta-Agent's static plan, uses a different LLM model, writes its
   verdict to a new platform-scoped **`MetaIntelligenceTree`**, and
   blocks promotion on `BLOCK` verdicts.
3. **`meta_entity_executor`** is replaced by a **TestDriver** that runs
   a *suite* of tests (smoke, comparative, boundary, regression,
   hostile) under a shared `test_budget_usd` cap.
4. A **Curator** can detect near-duplicates (extends AntiSprawlGuard)
   and propose merges; UI receives a notification with a structured
   merge-plan.
5. **Promoter** enforces six gates before flipping a draft entity from
   `status=DRAFT` to `status=ACTIVE`.
6. **`resolve_meta_cognition`** defaults change: `registry_search` and
   `self_modification` become **opt-in** (was: auto-on for AGENT/PROCESS).
   The Meta-Agent itself is exempt (it sets both explicitly).
7. New **`SkillLibrary`** detects repeated successful tool chains and
   surfaces them as candidate SKILL entities (user can promote).
8. Meta-Agent's prompt evolution is scaffolded (cron job analyses past
   runs and writes `prompt_update_candidate` nodes); HITL gates the
   actual prompt bump.

---

## 2. Scope

### In scope

* New tool: `tools/meta/spec_critic.py` (`meta_spec_critic`).
* New service: `meta/meta_intelligence_tree.py`.
* New package: `meta/board/` with files for each role.
* New service: `meta/skill_library.py` + Arq job `skill_promotion_scan`.
* New cron: `meta_agent_prompt_evolution`.
* DB: `entities.status` already supports `DRAFT`; we add a soft
  migration to ensure existing DRAFTs are surfaced in the UI listing.
* Refactor: `meta/platform_schema_compiler.py::resolve_meta_cognition` —
  default changes (one-line fix listed in review §05).
* Refactor: `meta/meta_agent_template.py` — system prompt updated to
  reference the new tool, the test suite, and the Promoter gates.
* Telemetry events for each Board role + skill promotion + prompt-evo.

### Out of scope

* Tool synthesis from natural language (P3).
* Multi-tenant skill sharing.
* Replacing the Meta-Agent's *runtime template* entity with a Board of
  *separate AGENT entities* — Roles are services *inside* one entity
  for now (keeps the Meta-Agent self-contained).
* Cross-tenant MetaIntelligenceTree.

---

## 3. Architecture (technical)

### 3.1 File layout

```
backend/src/ai/meta/
├── meta_agent_template.py        ← updated system prompt (orchestrator)
├── seed_meta_agent.py            ← seeds template
├── platform_schema_compiler.py   ← resolve_meta_cognition defaults change
├── registry_search_service.py
├── anti_sprawl.py
├── meta_intelligence_tree.py     ← NEW
├── skill_library.py              ← NEW
└── board/
    ├── __init__.py
    ├── requirement_chat.py        ← role-1
    ├── curator.py                 ← role-2 (wraps RegistrySearch+AntiSprawl)
    ├── architect.py               ← role-3 (extracted from today's prompt)
    ├── critic.py                  ← role-4 (uses meta_spec_critic)
    ├── validator.py               ← role-5 (static analysis)
    ├── test_driver.py             ← role-6 (suite runner)
    └── promoter.py                ← role-7 (gating)

backend/src/ai/tools/meta/
├── spec_critic.py                ← NEW tool: meta_spec_critic
├── platform_introspect.py        ← unchanged
├── registry_search.py            ← unchanged
├── schema_validator.py           ← unchanged
├── entity_creator.py             ← Promoter uses it
└── entity_executor.py            ← retained, but TestDriver now also runs it
```

### 3.2 Board pipeline (logical view)

```
                  User natural-language request
                              │
                              ▼
                  ┌─────────────────────────┐
                  │   RequirementChat       │  emit Spec
                  │   (clarify if needed)   │
                  └────────────┬────────────┘
                              ▼
                  ┌─────────────────────────┐
                  │       Curator           │  → REUSE: return entity_id, done
                  │  (RegistrySearch +      │  → COMPOSE: propose multi-agent PROCESS
                  │   AntiSprawl + Merge)   │  → ADAPT  : fork existing, modify
                  │                         │  → CREATE : new
                  └────────────┬────────────┘
                              ▼
                  ┌─────────────────────────┐
                  │       Architect         │  emit draft_entity (JSON)
                  └────────────┬────────────┘
                              ▼ (loop until critic happy or k=2)
                  ┌─────────────────────────┐
                  │       Critic            │  meta_spec_critic tool
                  │  (DIFFERENT model)      │  emit verdict + concerns
                  └────────────┬────────────┘
                       │ BLOCK / REVISE / PASS
                       ▼
                  ┌─────────────────────────┐
                  │       Validator         │  static checks (cycle, refs, cost)
                  └────────────┬────────────┘
                              ▼ (loop until validator green)
                  ┌─────────────────────────┐
                  │      Test Driver        │  suite: smoke / compare /
                  │                         │         boundary / regression /
                  │                         │         hostile
                  └────────────┬────────────┘
                              ▼
                  ┌─────────────────────────┐
                  │       Promoter          │  6 gates → DRAFT → ACTIVE
                  └────────────┬────────────┘
                              ▼
                  Entity catalogue updated
                  MetaIntelligenceTree updated
```

### 3.3 MetaIntelligenceTree

A platform-scoped IntelligenceTree owned by the Meta-Agent (one per
company; could later be platform-global).

Structure:

```
MetaIntelligenceTree (scope=PLATFORM, owner=meta_agent)
├── 📏 Architecture Anti-Patterns      ← written by Critic
│   ├── "PROCESS with >5 children rarely completes within budget"
│   ├── "REACT without goal_validation_interval drifts off-topic"
│   └── …
├── 🎯 Spec Patterns                    ← written by Curator + Promoter
│   └── ("research_topic" → suggested skeleton)
├── 🚨 Test Failure Tags                ← written by TestDriver
│   └── ({tag: count, last_seen})
├── 🧠 Curator Decisions                ← written by Curator
│   └── (REUSE/ADAPT/COMPOSE/CREATE outcomes vs eventual quality)
├── 🔧 Tool Reliability                 ← written by post-Promoter monitor
│   └── (tool_id → success_rate per task_class)
└── 📝 Prompt-Update Candidates         ← written by prompt-evo cron
    └── (proposed Meta-Agent prompt diffs, awaiting HITL)
```

Read by every Board role.
Written by Critic, TestDriver, Curator, and the prompt-evo cron.

### 3.4 `meta_spec_critic` tool — input/output

```
Input (JSON):
{
  "mode": "review_spec",
  "spec": <full HierarchicalEntity payload>,
  "search_top_k": <output of meta_registry_search top 3>,
  "platform_manifest_hash": "<for cache key>"
}

Output (JSON):
{
  "verdict": "PASS|REVISE|BLOCK",
  "concerns": [
    {"severity": "low|med|high|critical",
     "category": "cost|cycles|prompt|tools|governance|io_contract|hallucination_risk",
     "issue": "...",
     "fix_suggestion": "...",
     "blocks_promotion": true|false}
  ],
  "rules_referenced": ["<intelligence_rule_node_id>", ...]
}
```

Implementation:

* Loads top-N anti-patterns from MetaIntelligenceTree filtered by spec
  tags / entity_type.
* Builds a hostile-by-construction system prompt (see review §04).
* Uses **a different LLM model** than the Architect's default
  (`spec_critic_model_override`).
* Writes a `🩺 Spec Critic Verdict` node into the run's CORTEX tree
  for audit.
* Writes confirmed anti-patterns into MetaIntelligenceTree's
  `📏 Architecture Anti-Patterns` when severity ≥ med and concern is
  novel.

### 3.5 TestDriver suite

```python
class TestDriver:
    SUITE_BUDGET_USD = Decimal("3.00")   # configurable per-company

    async def run(self, draft_entity, source_entity=None) -> SuiteResult:
        budget = Budget(usd_max=self.SUITE_BUDGET_USD, ...)
        results = {}
        results["smoke"] = await self._smoke(draft_entity, budget)
        if not results["smoke"].passed: return SuiteResult(results)

        if source_entity:                # ADAPT mode
            results["regression"] = await self._regression(
                draft_entity, source_entity, budget)
            if not results["regression"].passed: return SuiteResult(results)

        results["boundary"] = await self._boundary(draft_entity, budget)
        results["hostile"] = await self._hostile(draft_entity, budget)

        # Comparative test only when Curator's REUSE_THRESHOLD-1 candidate exists
        top = self._top_compare_candidate(draft_entity)
        if top:
            results["comparative"] = await self._comparative(
                draft_entity, top, budget)

        return SuiteResult(results)
```

Each `_*` returns a `TestCaseResult` with `{passed, output, cost,
notes}`. Tests share `budget`; if it exhausts, remaining tests are
skipped with `notes="budget exhausted"`.

### 3.6 Promoter gates

```python
class Promoter:
    async def promote(self, draft_entity, board_result) -> PromotionDecision:
        gates = [
            self._g1_critic_clean(board_result),
            self._g2_validator_clean(board_result),
            self._g3_test_pass_threshold(board_result),
            self._g4_test_budget_ok(board_result),
            self._g5_anti_sprawl_clean(board_result),
            self._g6_runtime_cost_within_cap(board_result, draft_entity),
        ]
        failures = [g for g in gates if not g.passed]
        if failures:
            return PromotionDecision(
                outcome="REJECT",
                failed_gates=[g.name for g in failures],
                reason="; ".join(g.reason for g in failures),
            )

        # Optional HITL gate before flip — gated by company setting
        if self._requires_hitl(draft_entity):
            await self._raise_hitl(draft_entity, board_result)
            return PromotionDecision(outcome="PENDING_HITL")

        await self._flip_to_active(draft_entity)
        return PromotionDecision(outcome="PROMOTED")
```

### 3.7 SkillLibrary

```python
class SkillLibrary:
    """
    Detects repeated successful tool chains and proposes SKILL entities.

    Pulls episodic data from the last N completed runs per entity.
    Groups consecutive tool_call sequences; for chains with ≥K
    successful repeats and consistent input/output shape, writes a
    `skill_candidate` node into the MetaIntelligenceTree.
    """
    MIN_REPEATS = 5
    LOOKBACK_RUNS = 50

    async def scan_entity(self, entity_id: UUID):
        ...
```

Run as Arq cron: `skill_promotion_scan` weekly.

UI consumes `skill_candidate` nodes and renders a "promote to SKILL"
panel.

---

## 4. Detailed deliverables

### 4.1 T5-1 — `meta/meta_intelligence_tree.py` + DB ensure (Day 1)

```python
class MetaIntelligenceTree:
    """
    Platform-scoped IntelligenceTree owned by the Meta-Agent.
    One tree per company.
    """
    SECTIONS = {
        "anti_patterns":  "📏 Architecture Anti-Patterns",
        "spec_patterns":  "🎯 Spec Patterns",
        "test_failures":  "🚨 Test Failure Tags",
        "curator_dec":    "🧠 Curator Decisions",
        "tool_reliab":    "🔧 Tool Reliability",
        "prompt_cand":    "📝 Prompt-Update Candidates",
    }

    async def ensure_tree(self) -> CortexTree: ...
    async def add_anti_pattern(self, *, title, evidence_count,
                               related_tags, suggestion): ...
    async def query_anti_patterns(self, *, entity_type, tags,
                                  top_k=5) -> list[Rule]: ...
    async def record_curator_decision(self, *, decision, candidates,
                                      outcome): ...
    async def add_test_failure(self, *, entity_id, tag, kind): ...
    async def add_tool_reliability_sample(self, *, tool_id,
                                          task_class, success): ...
    async def add_prompt_update_candidate(self, *, prompt_diff,
                                          rationale, evidence): ...
```

Persistence: re-uses `intelligence_tree_service.IntelligenceTreeService`
with `scope_level=PLATFORM`. No new SQL table.

### 4.2 T5-2 — `tools/meta/spec_critic.py` (Day 2)

```python
class MetaSpecCriticTool(Tool):
    name = "meta_spec_critic"
    description = "Reviews a draft HierarchicalEntity spec for failure modes."

    async def run_typed(self, params: SpecCriticParams,
                        context: dict) -> dict:
        meta_tree = MetaIntelligenceTree(db=..., company_id=...)
        anti = await meta_tree.query_anti_patterns(
            entity_type=params.spec["type"],
            tags=params.spec.get("tags", []),
            top_k=10,
        )
        # Build adversarial system prompt
        system = self._build_system_prompt(anti)
        user = self._build_user_prompt(params)
        llm = LLMRouter(db=..., company_id=...)
        model_override = self._resolve_critic_model(...)
        resp = await llm.call_llm(
            task_type="thinking",
            system_prompt=system,
            user_prompt=user,
            temperature=0.2,
            max_tokens=1200,
            model_override=model_override,
        )
        parsed = parse_json_object(resp.output)
        # Persist novel anti-patterns
        for c in parsed.get("concerns", []):
            if c.get("severity") in ("med","high","critical") and c.get("issue"):
                await meta_tree.add_anti_pattern(
                    title=c["issue"][:120],
                    evidence_count=1,
                    related_tags=params.spec.get("tags", []),
                    suggestion=c.get("fix_suggestion", ""),
                )
        return parsed

    def _build_system_prompt(self, anti):
        return (
            "You are a Staff Engineer reviewing an AI agent specification.\n"
            "Assume the Architect is overconfident.\n"
            "Enumerate every plausible failure mode. For each, cite a concrete "
            "input that triggers it, an expected pathology, and the cheapest fix.\n"
            "If you cannot find ≥3 issues, you are not looking hard enough.\n"
            "Known anti-patterns to check:\n"
            + "\n".join(f"  - {a.text}" for a in anti)
            + "\nReturn JSON only."
        )
```

Tool is registered in `tools/meta/__init__.py`.

### 4.3 T5-3 — `meta/board/*` role implementations (Days 3-6)

Each Role is a class with one main method. The current Meta-Agent
*template entity* (`meta_agent_template.py`) is updated so its
`static_plan` step calls the meta-tools that *power* the roles:

* `meta_platform_introspect` (used by Architect)
* `meta_registry_search` (used by Curator)
* `meta_schema_validator` (used by Validator)
* **`meta_spec_critic`** (NEW — used by Critic)
* `meta_entity_executor` (used by TestDriver smoke + boundary)
* `meta_entity_creator` (used by Promoter on flip-to-active)

The Roles themselves run **inside the agent runtime** as services (not
as separate entities). The Meta-Agent's prompt orchestrates them, but
the *deterministic* gates (Validator, Promoter) call straight into
their service classes from the static plan via tool wrappers.

#### Day 3 — Curator

```python
class Curator:
    def __init__(self, db, company_id):
        self.search = RegistrySearchService(db, company_id)
        self.sprawl = AntiSprawlGuard(db, company_id)
        self.meta = MetaIntelligenceTree(db, company_id)

    async def decide(self, spec) -> CuratorDecision:
        rec = await self.search.recommend(SearchRequest(
            intent=spec["description"],
            required_tools=spec.get("capabilities",{}).get("tools",[]),
            preferred_type=spec.get("type"),
        ))
        # Sprawl gate (only enforced on CREATE)
        if rec["decision"] == "CREATE":
            allow = await self.sprawl.check_creation_allowed(...)
            if not allow["allowed"]:
                # Convert to ADAPT against top candidate
                if rec["candidates"]:
                    rec["decision"] = "ADAPT"
            dup = await self.sprawl.check_semantic_duplicate(
                description=spec["description"], required_tools=...,
                preferred_type=spec.get("type"))
            if dup["is_duplicate"]:
                rec["decision"] = "ADAPT"

        await self.meta.record_curator_decision(
            decision=rec["decision"],
            candidates=rec["candidates"][:3],
            outcome=None,   # filled when Promoter completes
        )
        return CuratorDecision(**rec)
```

#### Day 4 — Architect, Critic

Architect is the LLM call that produces the entity payload. It uses
the existing Meta-Agent prompt, *minus* the deciding/searching/testing
parts (those are other Roles). Critic wraps the tool from §4.2 plus a
loop:

```python
class Critic:
    MAX_REVISE_ROUNDS = 2

    async def review_with_revision(self, draft, architect) -> tuple[draft, CriticReport]:
        for round_ in range(self.MAX_REVISE_ROUNDS + 1):
            report = await self._call_meta_spec_critic(draft)
            if report["verdict"] == "PASS":
                return draft, report
            if report["verdict"] == "BLOCK":
                return draft, report      # caller decides what to do
            # REVISE: ask architect to apply fixes
            if round_ < self.MAX_REVISE_ROUNDS:
                draft = await architect.revise(draft, report["concerns"])
            else:
                report["verdict"] = "BLOCK"
                report["reason"] = "max revise rounds reached"
        return draft, report
```

#### Day 5 — Validator, TestDriver

Validator runs deterministic checks (overlaps Track 7's PlanInvariants
but adds entity-spec-specific ones):

```python
class Validator:
    async def check(self, draft_entity) -> ValidatorReport:
        return ValidatorReport(checks=[
            self._json_schema_ok(draft_entity),
            self._no_cycle_in_children(draft_entity),
            self._all_tools_registered(draft_entity),
            self._all_child_ids_resolve(draft_entity),
            self._prompt_template_variables_resolve(draft_entity),
            self._cost_estimate_under_cap(draft_entity),
            self._review_mechanism_consistent(draft_entity),
            self._governance_caps_set(draft_entity),
        ])
```

TestDriver per §3.5; suite cases implemented one-by-one.

#### Day 6 — Promoter + DRAFT lifecycle

Promoter implements §3.6. New entities created via `meta_entity_creator`
are created with `status=DRAFT` by default; only Promoter flips to
`ACTIVE`. (`meta_entity_creator` already accepts `status` — we change
the Meta-Agent's prompt invariant to instruct DRAFT-creation.)

### 4.4 T5-4 — Meta-Agent template update (Day 7 AM)

Update `meta/meta_agent_template.py`:

1. System prompt gains an "Anti-Patterns Awareness" section that
   instructs the agent to call `meta_spec_critic` BEFORE
   `meta_entity_creator`.
2. Step prompt added between current step 4 (BUILD) and step 5 (TEST):
   "4.5 CRITIQUE — call meta_spec_critic with the draft spec. Address
   every BLOCK concern. If unable to address, return to user."
3. Invariant added: "ALWAYS create new entities with status=DRAFT;
   Promoter flips to ACTIVE only after the test suite passes."
4. Tool list adds `meta_spec_critic`.

A re-seed script `backend/scripts/seeds/reseed_meta_agent.py` bumps
existing Meta-Agent entities to `version=4.0.0` and updates their
identity / plan / capabilities. Existing meta_cognition explicit
settings preserved.

### 4.5 T5-5 — `resolve_meta_cognition` default flip (Day 7 PM)

`meta/platform_schema_compiler.py:783-838`:

```python
def resolve_meta_cognition(entity) -> Dict[str, Any]:
    caps = entity.capabilities or {}
    explicit = caps.get("meta_cognition", {})

    config = {
        "platform_awareness":  explicit.get("platform_awareness", True),
        "registry_search":     explicit.get("registry_search", False),   # was: auto-on
        "self_modification":   explicit.get("self_modification", False), # was: auto-on
        "max_runtime_creations": explicit.get("max_runtime_creations", 3),
        "max_registry_searches": explicit.get("max_registry_searches", 5),
    }
    entity_type = (getattr(entity, "type", None) or
                   entity.get("type", "")).upper()
    planning = (entity.planning if hasattr(entity, "planning")
                else entity.get("planning") or {})
    logic_gate = (entity.logic_gate if hasattr(entity, "logic_gate")
                  else entity.get("logic_gate") or {})
    dynamic_enabled = planning.get("dynamic_planning", {}).get("enabled", False)
    reasoning_mode = logic_gate.get("reasoning_config", {}).get("reasoning_mode", "REACT")
    if "platform_awareness" not in explicit:
        config["platform_awareness"] = dynamic_enabled or reasoning_mode == "REACT"

    # NEW: Meta-Agent itself opts in to self_modification + registry_search
    is_meta = (entity.metadata_extensions or {}).get("is_meta_agent", False)
    if is_meta:
        config["self_modification"] = True
        config["registry_search"] = True
    return config
```

This is one of the most impactful single-line changes of the programme.

A migration helper inspects every existing AGENT/PROCESS entity and
adds explicit `meta_cognition.registry_search = true` /
`self_modification = true` for those that were relying on the prior
default. Otherwise they'd silently lose capabilities at upgrade.

```python
# backend/scripts/migrations/p11t05_preserve_meta_cognition.py
async def upgrade():
    for entity in agents_and_processes_with_no_explicit_meta_cognition():
        entity.capabilities.setdefault("meta_cognition", {})
        entity.capabilities["meta_cognition"]["registry_search"] = True
        entity.capabilities["meta_cognition"]["self_modification"] = True
    commit()
```

Run BEFORE deploying the code change.

### 4.6 T5-6 — `meta/skill_library.py` + cron (Day 8)

```python
class SkillLibrary:
    MIN_REPEATS = 5
    LOOKBACK_RUNS = 50

    async def scan_entity(self, entity_id: UUID, company_id: UUID):
        episodes = await EpisodicTreeService(self.db, company_id) \
                          .recent_episodes(entity_id, limit=self.LOOKBACK_RUNS)
        chains = self._extract_chains(episodes)
        for chain, freq in chains.items():
            if freq >= self.MIN_REPEATS:
                await self._propose_skill(chain, freq, entity_id, company_id)

    async def _propose_skill(self, chain, freq, entity_id, company_id):
        await MetaIntelligenceTree(self.db, company_id).write(
            section="spec_patterns",
            title=f"Skill candidate: {self._chain_name(chain)}",
            content=json.dumps({"chain": chain, "frequency": freq,
                                "source_entity_id": str(entity_id)}),
            summary=f"Tool chain seen {freq}× — promote to SKILL?",
        )
```

Register cron:

```python
# core/arq_jobs.py
async def skill_promotion_scan(ctx):
    ...
```

```python
# worker.py WorkerSettings
cron_jobs = [
    cron(skill_promotion_scan, hour=4, minute=30),
    ...
]
```

UI: new endpoint `GET /api/v1/meta/skill_candidates` reads the
`spec_patterns` nodes filtered by `node_type=skill_candidate`.

### 4.7 T5-7 — Prompt evolution scaffold (Day 9)

Cron `meta_agent_prompt_evolution`:

```python
async def meta_agent_prompt_evolution(ctx):
    async with AsyncSessionLocal() as db:
        # Sample 20 recent Meta-Agent runs across companies
        runs = await sample_recent_meta_runs(db, n=20)
        for run in runs:
            critique = await _critic_of_critic(run)
            if critique.has_actionable_improvement:
                await MetaIntelligenceTree(db, run.company_id) \
                        .add_prompt_update_candidate(
                            prompt_diff=critique.diff,
                            rationale=critique.rationale,
                            evidence=[str(run.id)],
                        )
```

* `_critic_of_critic` is a small wrapper around an LLM call analyzing
  the Meta-Agent's transcripts.
* The actual prompt bump is **HITL** — the candidate sits as a node
  until an admin approves via UI.

Cron: weekly. No automatic prompt change without HITL.

### 4.8 T5-8 — DRAFT lifecycle + UI hooks (Day 9 PM)

* `entities.status` already supports `DRAFT`. The UI listing today
  filters out DRAFT — Track 5 updates `api/entities.py::list_entities`
  to return `status=DRAFT` to admins only.
* New endpoint:

  ```
  POST /api/v1/meta/promote/{entity_id}
  ```

  Admin promotes a DRAFT (bypassing Board) — should be HITL-gated and
  rare; primarily a recovery path.

### 4.9 T5-9 — Tests + canary (Day 10)

See §9.

---

## 5. Database / schema changes

### 5.1 Migration `p11t05_preserve_meta_cognition`

Per §4.5: backfill explicit `meta_cognition.registry_search /
self_modification = true` for AGENT/PROCESS that relied on the prior
default.

### 5.2 No new tables

`MetaIntelligenceTree` rides on existing CORTEX tables. `SkillLibrary`
writes nodes; no new tables.

### 5.3 `entities.status` query update

Endpoint `GET /api/v1/entities` already filters `status != "DELETED"`.
Track 5 keeps DRAFT visible only to admins; non-admin callers continue
to see only ACTIVE.

---

## 6. API changes

### 6.1 New endpoints

```
GET  /api/v1/meta/skill_candidates           (admin)
POST /api/v1/meta/promote/{entity_id}        (admin; HITL gate)
POST /api/v1/meta/spec_critic/run-on-spec    (admin; ad-hoc test)
GET  /api/v1/meta/intelligence/anti_patterns (admin)
GET  /api/v1/meta/intelligence/prompt_candidates (admin)
POST /api/v1/meta/intelligence/prompt_candidates/{id}/approve (admin)
```

### 6.2 Updated endpoints

* `GET /api/v1/entities` — admins see `status=DRAFT` rows; non-admin
  flow unchanged.
* `GET /api/v1/templates` — Meta-Agent v4 template visible.

### 6.3 SSE events

Meta-Agent runs emit new payload kinds via the agent loop stream:

```jsonc
{"type":"meta_role_started","role":"Critic","iteration":...}
{"type":"meta_role_completed","role":"Critic","verdict":"REVISE",
 "concerns_count":3}
{"type":"meta_test_case","name":"smoke","passed":true,"cost_usd":"0.04"}
{"type":"meta_promotion","outcome":"PROMOTED","entity_id":"..."}
{"type":"meta_promotion","outcome":"REJECT","reason":"...","failed_gates":["G3"]}
```

---

## 7. Telemetry events

| Event | Payload | When |
|-------|---------|------|
| `meta.role.start` | `{role, run_id}` | each role start |
| `meta.role.end` | `{role, run_id, success, cost_usd, latency_ms}` | each role end |
| `meta.spec_critic.verdict` | `{run_id, verdict, concerns_count, model_used}` | every critic call |
| `meta.testdriver.case` | `{run_id, case, passed, cost_usd}` | each test case |
| `meta.testdriver.suite_completed` | `{run_id, passed_cases, total_cases, cost_usd}` | end of suite |
| `meta.promotion.outcome` | `{run_id, entity_id, outcome, failed_gates[]}` | every promotion attempt |
| `meta.intelligence.anti_pattern_added` | `{company_id, title, severity}` | every novel anti-pattern |
| `meta.skill.candidate_proposed` | `{company_id, entity_id, chain, frequency}` | weekly cron |
| `meta.prompt.candidate_proposed` | `{company_id, run_id, rationale}` | weekly cron |
| `meta.curator.decision` | `{run_id, decision, top_candidate_id}` | per Meta-Agent run |

---

## 8. Feature flags

| Flag | Default | Notes |
|------|---------|-------|
| `meta_agent.board_routing` | OFF → flip to ON Day 5 | Master switch |
| `meta_agent.spec_critic_required` | ON when board_routing | Forces Critic gate |
| `meta_agent.draft_lifecycle` | ON when board_routing | New entities default to DRAFT |
| `meta_agent.testdriver_suite_enabled` | ON when board_routing | Multi-test suite |
| `meta_agent.testdriver_budget_usd` | 3.00 | Cap |
| `meta_agent.skill_promotion_cron` | ON | Weekly scan |
| `meta_agent.prompt_evolution_cron` | ON | Weekly scan (HITL-gated) |
| `meta_agent.curator_consolidation_enabled` | OFF | Merge-proposal feature; off by default until UI is ready |

---

## 9. Tests

### 9.1 Unit

* `test_spec_critic_extracts_concerns` — known-bad spec returns ≥1 high
  severity concern.
* `test_spec_critic_passes_clean_spec` — known-good spec returns PASS.
* `test_critic_revise_loop_terminates` — max 2 revise rounds.
* `test_validator_catches_cycle` — fixture with a child referencing
  its parent → fails.
* `test_validator_catches_missing_tool_capability` — TOOL_CALL using
  tool not in capabilities → fails.
* `test_test_driver_smoke_passes_on_minimal_spec`.
* `test_test_driver_skips_remaining_on_budget_exhaust`.
* `test_promoter_all_gates_must_pass`.
* `test_skill_library_proposes_repeated_chain`.
* `test_resolve_meta_cognition_defaults_opt_in`.

### 9.2 Integration

* `test_meta_agent_v4_create_path` — natural-language request →
  Curator decides CREATE → Architect drafts → Critic passes →
  Validator green → TestDriver green → Promoter flips to ACTIVE.
* `test_meta_agent_v4_adapt_path` — Curator decides ADAPT against
  fixture → Architect produces VERSION payload → Critic / Validator /
  TestDriver pass → Promoter flips.
* `test_meta_agent_v4_blocked_by_critic` — fixture deliberately
  hallucinates a non-existent tool → spec_critic BLOCKs → Promoter
  rejects.
* `test_meta_intelligence_tree_populated` — after several runs, the
  tree has nodes in at least four sections.
* `test_prompt_evolution_candidate_requires_hitl` — cron writes
  candidate, no auto-apply; UI approval call updates the Meta-Agent.

### 9.3 Canary

* Day 5+: route 10% of incoming Meta-Agent requests through the Board.
  Compare success rate / cost vs the legacy path for 48h. If
  success_rate_delta > -5pp AND cost_delta < +20%, ramp to 50%,
  then 100%.

---

## 10. Acceptance criteria

1. Every Meta-Agent run with the flag ON invokes the Board roles in
   order; SSE events confirm the role sequence.
2. `meta_spec_critic` is callable and writes both per-run audit nodes
   and (when severity ≥ med) MetaIntelligenceTree anti-patterns.
3. TestDriver runs at least three cases (smoke + boundary + hostile)
   on every CREATE path within the suite budget.
4. Promoter rejects when any of the 6 gates fails; non-promotion is
   visible as `meta_promotion.outcome=REJECT` event.
5. `resolve_meta_cognition` default is opt-in for sprawl tiers; the
   preserve-migration ran and no production AGENT/PROCESS silently
   lost capability.
6. After 14 days of Meta-Agent runs on the flag, the
   MetaIntelligenceTree has ≥10 anti-patterns and ≥3 skill candidates
   across the canary tenants.
7. Weekly prompt-evolution cron produces ≤3 candidate nodes per company
   per week (avoid spam); HITL approval gate enforced.
8. `mypy --strict` clean on `meta/board/` and `meta/meta_intelligence_tree.py`.

---

## 11. Effort breakdown (10 working days, 1 engineer)

| Day | Work |
|-----|------|
| 1 | T5-1: MetaIntelligenceTree + section bootstrap + tests |
| 2 | T5-2: `meta_spec_critic` tool + prompts + per-run audit |
| 3 | T5-3a: Curator role |
| 4 | T5-3b: Architect + Critic + revise-loop |
| 5 | T5-3c: Validator + TestDriver (smoke + boundary) |
| 6 | T5-3d: TestDriver (regression + hostile + comparative) + Promoter |
| 7 AM | T5-4: Meta-Agent template prompt update + re-seed |
| 7 PM | T5-5: resolve_meta_cognition flip + preserve migration |
| 8 | T5-6: SkillLibrary + scan cron + UI endpoint |
| 9 AM | T5-7: prompt-evolution cron + HITL endpoint |
| 9 PM | T5-8: DRAFT lifecycle + UI listing change |
| 10 | T5-9: integration tests + canary harness + PR |

---

## 12. Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| `resolve_meta_cognition` flip drops capability for live entities | H | Existing agents lose features silently | Preserve-migration in T5-5 runs *before* code deploy; explicit unit test that every fixture entity has the same effective config pre- and post-flip |
| `meta_spec_critic` model unavailable in tenant | M | Critic falls back to same model | Falls back to actor model with hostile prompt + warning event; alert raised |
| Board pipeline slows Meta-Agent runs by ≥30% | M | Worse UX | Suite budget cap; Critic skipped for ACTION/SKILL specs (low risk); concurrency in suite for independent test cases |
| Skill candidates spammy | M | Noisy admin UI | Cron throttled; min repeats=5; weekly dedup of identical chains |
| Anti-pattern tree grows unbounded | M | Slow critic prompts | Cap to last 200 anti-patterns; LRU by `last_seen` |
| Prompt-evolution candidates apply automatically by mistake | L | Quality regression | HITL gate hard-coded; cron writes only candidates; only the explicit POST `/approve` endpoint applies |
| Promoter rejection breaks user flow | M | User confused why no entity was created | Promoter rejection returns a structured error to the Meta-Agent's final report; UI shows reason |

---

## 13. Dependencies

* **Upstream:**
  * Track 1 (typed `PlanStep.type` used by Validator).
  * Track 3 (different-model resolver re-used by spec_critic).
  * Track 4 (SupervisorCritic patterns; bandit not strictly required but
    helpful for selecting which test case to run first).
* **Downstream:**
  * Track 7 (Planner uses MetaIntelligenceTree anti-patterns as priors).
  * Track 9 (KPI dashboard surfaces Board metrics).

---

## 14. Open questions

* Should Roles eventually become **separate AGENT entities** rather
  than internal services? Pro: composability, debug-ability. Con:
  extra LLM call overhead per Meta-Agent run. Track 5 picks the
  service approach; revisit Phase 12.
* What's the right model for the Critic by default? Initial pick: same
  family as Architect but one tier stronger (e.g. Architect on Sonnet,
  Critic on Opus). Configurable per company via IntegrationRegistry
  `*-critic` SKU convention.
* Should SkillLibrary auto-promote a chain after K successful uses, or
  always wait for human approval? Phase 11: always wait. Phase 12+
  may allow auto-promotion under a per-company "trust level."
