# Track 7 — Planner With Priors + Invariants (Week 10)

> **Owner:** Agent kernel engineer.
> **Duration:** 5 working days.
> **Behaviour change:** Dynamic planner produces N candidates, checks
>   deterministic invariants, consults IntelligenceTree priors, and
>   judges between candidates. Behind `planner.v2_enabled`.
> **Risk:** Medium. Planner output drives everything downstream.
> **Goal mapping:** G1, G3, G7.

This Track replaces the single-shot dynamic plan with **PlanGenerator
v2** — a multi-candidate, prior-aware, invariant-checked planner. It
also consolidates the `CHILD_ENTITY_INVOCATION.entity_id` resolution
logic that today lives in two places.

---

## 1. Objectives (functional)

After Track 7:

1. Dynamic planning generates **N candidate plans** (default 3), runs
   **deterministic invariants** on each, then asks an LLM judge (or
   uses bandit priors) to pick the best.
2. Each candidate's expected cost (estimated per-step) is recorded;
   plans projected to exceed `governance.max_cost_usd` are filtered
   out.
3. **PlanInvariants** catches structural problems early: cycle in
   children, dangling step refs, missing tool capabilities, prompt
   variables not resolvable, planning-cost > budget.
4. **`planning/child_resolver.py`** is the single source of truth for
   resolving dropped `entity_id` in `CHILD_ENTITY_INVOCATION` steps;
   both `PlannerService` and `step_executor` use it.
5. Plan-style priors from Track 4's bandit + Intelligence rules from
   Track 3's calibration feed into the planner prompt.
6. The legacy `PlannerService.adapt_plan` becomes a thin wrapper around
   `PlanGenerator v2`'s `replan(...)` flow.

---

## 2. Scope

### In scope

* New: `planning/plan_generator.py` (`PlanGenerator` class).
* New: `planning/plan_invariants.py` (`validate_plan(...)`).
* New: `planning/child_resolver.py` (single function).
* New: `planning/plan_judge.py` (LLM judge for best-of-N).
* Refactor: `planning/planner_service.py` — `PlannerService.reconcile`
  delegates to `PlanGenerator`. `adapt_plan` becomes a wrapper.
* Refactor: `step_executor._execute_child_invocation` (Strategy 1-3)
  → call `child_resolver.resolve_child_entity_id(...)`.
* Refactor: `PlannerService._reconcile_child_invocations` → same.
* Telemetry events for plan selection / invariant failure / cost
  rejection.

### Out of scope

* LLM-driven Strategist itself (Phase 12).
* Replacing static-plan support entirely.
* Cross-entity planner sharing.

---

## 3. Architecture (technical)

### 3.1 PlanGenerator flow

```
                  PlanContext
                     │
                     ▼
              ┌──────────────────────┐
              │  PlanGenerator.run   │
              └──────────┬───────────┘
                         │ N=3
                         ▼
              ┌───────────────────────────────────────────┐
              │  generate_candidates(ctx, N, varied_temp) │  ← LLM calls
              └──────────┬────────────────────────────────┘
                         │ candidates: list[PlanCandidate]
                         ▼
              ┌───────────────────────────────────────────┐
              │  apply_invariants(each candidate)         │  ← deterministic
              │  - cycle in children                      │
              │  - dangling step refs                     │
              │  - tools all in capabilities              │
              │  - prompt vars resolvable                 │
              │  - cost estimate <= budget                │
              │  - no plan_step.type = THOUGHT followed   │
              │    by undefined {{step}} ref              │
              └──────────┬────────────────────────────────┘
                         │ kept = candidates passing invariants
                         ▼
              ┌───────────────────────────────────────────┐
              │  if kept == 1:        chosen = kept[0]    │
              │  else if no priors:   chosen = judge()    │
              │  else:                chosen = priors+judge|
              └──────────┬────────────────────────────────┘
                         │
                         ▼
                  PlanCandidates(chosen=..., alternates=...)
```

### 3.2 PlanContext / PlanCandidate

```python
@dataclass
class PlanContext:
    entity: HierarchicalEntity
    input_data: dict
    static_plan: dict
    intelligence_rules: list[IntelRule]    # from Intelligence Tree
    anti_patterns: list[Rule]               # from MetaIntelligenceTree
    task_class: str
    budget: Budget
    company_id: UUID


@dataclass
class PlanCandidate:
    steps: list[PlanStep]
    style: PlanStyleArm                     # DAG_PARALLEL / SEQUENTIAL / …
    estimated_cost_usd: Decimal
    estimated_latency_s: int
    rationale: str
    invariant_violations: list[str] = field(default_factory=list)
    judge_score: float | None = None


@dataclass
class PlanCandidates:
    chosen: PlanCandidate
    alternates: list[PlanCandidate]
```

### 3.3 Invariants

```python
# planning/plan_invariants.py
@dataclass
class Invariant:
    name: str
    passed: bool
    detail: str | None = None


def validate_plan(plan: list[PlanStep],
                   entity: HierarchicalEntity,
                   budget: Budget) -> list[Invariant]:
    return [
        no_cycle_in_child_invocations(plan, entity),
        all_required_tools_in_capabilities(plan, entity),
        no_dangling_variable_refs(plan),
        no_dangling_step_dependencies(plan),
        cost_estimate_within_budget(plan, budget),
        no_orphaned_outputs(plan),
        child_invocations_have_entity_id(plan, entity),
        prompt_templates_are_strings(plan),
    ]
```

Each function is pure, ≤30 LoC, testable in isolation.

### 3.4 Cost estimator (deterministic)

```python
# planning/cost_estimator.py
def estimate_step_cost(step: PlanStep, entity, llm_router) -> Decimal:
    if step.type == StepType.TOOL_CALL:
        return TOOL_BASELINE_COST.get(step.target.tool_id, Decimal("0.01"))
    if step.type == StepType.CHILD_ENTITY_INVOCATION:
        return ENTITY_AVG_COST.get(step.target.entity_id, Decimal("0.10"))
    # THOUGHT / ACTION → token-budget × model cost
    model = step.target.model_name or default_model_for(entity)
    return Decimal("0.005") * MODEL_PRICE.get(model, Decimal("1.0"))
```

Baseline tables seed from the last 30 days of actual telemetry; cron
job `cost_estimator_refresh` updates them nightly. For Track 7 a
hardcoded baseline is acceptable.

### 3.5 ChildResolver

```python
# planning/child_resolver.py
async def resolve_child_entity_id(
    step: PlanStep,
    parent_entity: HierarchicalEntity,
    db,
) -> UUID:
    """
    Single source of truth for resolving CHILD_ENTITY_INVOCATION.entity_id.

    Strategies tried in order:
      1. step.target.entity_id (if already a UUID)
      2. Match step.name against parent_entity.planning.static_plan.steps
         where type=CHILD_ENTITY_INVOCATION
      3. Match step name's order-among-invocation-steps against
         parent_entity.hierarchy.children[]
      4. step.target.entity_name_hint → DB lookup by HierarchicalEntity.name

    Raises EntityNotFoundError if none resolve.
    """
    ...
```

`PlannerService._reconcile_child_invocations` and
`step_executor._execute_child_invocation` both replace their inline
logic with one call to this function.

### 3.6 Replan flow (consolidated)

`PlanGenerator.replan(state, *, proposed_subgoals=None,
failed_step=None)` returns a `PlanCandidates`. AgentLoop's strategist
(from Track 4) consumes the chosen candidate.

---

## 4. Detailed deliverables

### 4.1 T7-1 — `planning/child_resolver.py` (Day 1 AM)

Move all the entity_id resolution code from
`step_executor._execute_child_invocation:129-184` and
`planner_service._reconcile_child_invocations:456-522` into the new
module.

Tests:

* `test_child_resolver_uuid_passthrough`
* `test_child_resolver_static_plan_match`
* `test_child_resolver_hierarchy_index_match`
* `test_child_resolver_name_hint_db_lookup`
* `test_child_resolver_raises_on_no_match`

Update both call sites to use the function. Remove the dead inline
strategies.

### 4.2 T7-2 — `planning/plan_invariants.py` (Day 1 PM)

Implement the eight invariant functions per §3.3.

Tests, one per invariant (positive + negative cases):

* Cycle detection — fixture with `A → B → A` (via children) → fails.
* Tool capability — step uses `web_search`; entity capabilities lack
  it → fails; entity has it → passes.
* Variable resolution — `{{step_99}}` referenced but no step_99 →
  fails.
* Step dependency dangling — `input_dependencies: ["step_99"]` →
  fails.
* Cost estimate — sum of estimated step costs > `entity.governance.max_cost_usd`
  → fails.

### 4.3 T7-3 — `planning/cost_estimator.py` (Day 2 AM)

Hardcoded baselines for Track 7. Make it a small module:

```python
TOOL_BASELINE_COST = {
    "web_search":       Decimal("0.005"),
    "batch_web_search": Decimal("0.015"),
    "scraper_tool":     Decimal("0.02"),
    "headless_browser": Decimal("0.05"),
    "pdf_generator":    Decimal("0.01"),
    "image_generation": Decimal("0.04"),
    "video_generation": Decimal("0.10"),
    ...
}

MODEL_PRICE_FACTOR = {
    "gemini-2.5-flash": Decimal("1.0"),
    "gemini-2.5-pro":   Decimal("3.0"),
    "claude-haiku":     Decimal("1.0"),
    "claude-sonnet":    Decimal("2.5"),
    "claude-opus":      Decimal("8.0"),
    "gpt-4o":           Decimal("2.0"),
}
```

A nightly cron `cost_estimator_refresh` can later overwrite these from
`ToolInteractionLog` averages; out of scope for Track 7.

### 4.4 T7-4 — `planning/plan_generator.py` (Days 2-3)

```python
class PlanGenerator:
    def __init__(self, db, company_id, llm_router,
                 intelligence_reader, meta_intelligence_reader,
                 cost_estimator):
        ...

    async def generate(self, ctx: PlanContext, n: int = 3) -> PlanCandidates:
        priors = await self._load_priors(ctx)
        candidates = await self._generate_candidates(ctx, priors, n=n)
        # Apply invariants
        kept = []
        for cand in candidates:
            inv = validate_plan(cand.steps, ctx.entity, ctx.budget)
            cand.invariant_violations = [i.name for i in inv if not i.passed]
            if not cand.invariant_violations:
                kept.append(cand)
        if not kept:
            # All candidates failed invariants → fall back to static or
            # re-prompt once
            kept = await self._repair_candidates(candidates, ctx)
        if len(kept) == 1:
            chosen = kept[0]
        else:
            chosen = await self._select_best(kept, ctx, priors)
        return PlanCandidates(chosen=chosen,
                               alternates=[c for c in kept if c is not chosen])

    async def replan(self, state, *, proposed_subgoals=None,
                     failed_step=None) -> PlanCandidates:
        ctx = self._ctx_from_state(state, proposed_subgoals, failed_step)
        return await self.generate(ctx, n=2)

    async def _generate_candidates(self, ctx, priors, n):
        # n LLM calls in parallel, varied temperature 0.2/0.5/0.8
        async def one(temp):
            prompt = self._build_prompt(ctx, priors, variant=temp)
            resp = await self.llm.call_llm(
                task_type="thinking",
                system_prompt=DEFAULT_PLANNING_SYSTEM_PROMPT,
                user_prompt=prompt,
                temperature=temp,
            )
            steps = self._parse_plan(resp.output)
            steps = self._reconcile_child_invocations(steps, ctx)
            style = classify_plan_style(steps)
            cost = sum(self.cost_estimator.estimate_step_cost(s, ctx.entity)
                       for s in steps)
            return PlanCandidate(steps=steps, style=style,
                                  estimated_cost_usd=cost,
                                  estimated_latency_s=
                                    self.cost_estimator.estimate_latency(steps),
                                  rationale=f"temp={temp}")
        temps = [0.2, 0.5, 0.8][:n]
        return await asyncio.gather(*(one(t) for t in temps))

    async def _select_best(self, kept, ctx, priors):
        # If priors strongly prefer one style → use it
        if priors.recommended_style and \
           any(c.style == priors.recommended_style for c in kept):
            return next(c for c in kept if c.style == priors.recommended_style)
        # Else LLM judge between top-2
        ranked = sorted(kept, key=lambda c: c.estimated_cost_usd)[:2]
        return await self.judge.pick(ranked, ctx)
```

### 4.5 T7-5 — `planning/plan_judge.py` (Day 3 PM)

```python
class PlanJudge:
    """LLM judge for best-of-2 plan candidates."""
    async def pick(self, candidates: list[PlanCandidate],
                   ctx: PlanContext) -> PlanCandidate:
        prompt = self._build_prompt(candidates, ctx)
        resp = await self.llm.call_llm(
            task_type="text_generation",
            system_prompt=("You evaluate AI agent plans. "
                           "Pick the better plan. Reply with JSON only."),
            user_prompt=prompt,
            temperature=0.1,
            max_tokens=400,
        )
        parsed = parse_json_object(resp.output)
        idx = max(0, min(int(parsed.get("winner", 0)), len(candidates)-1))
        for i, c in enumerate(candidates):
            c.judge_score = float(parsed.get("scores", [0]*len(candidates))[i])
        return candidates[idx]
```

Judge prompt highlights: original goal, intelligence rules, both
candidates' steps + estimated cost, ask for winner + reasoning.

### 4.6 T7-6 — PlannerService refactor (Day 4 AM)

```python
class PlannerService:
    def __init__(self, db, company_id):
        ...
        self._gen = PlanGenerator(db=db, company_id=company_id, ...)

    async def reconcile(self, run, entity, input_data) -> dict:
        static_plan = entity.planning.get("static_plan", {})
        if not entity.planning.get("dynamic_planning", {}).get("enabled"):
            return static_plan

        ctx = PlanContext(
            entity=entity, input_data=input_data,
            static_plan=static_plan,
            intelligence_rules=await self._load_intel(entity),
            anti_patterns=await self._load_anti(entity),
            task_class=await self._classify_task(entity, input_data),
            budget=Budget.from_governance(entity.governance),
            company_id=entity.company_id,
        )
        candidates = await self._gen.generate(ctx, n=3)
        return {"steps": [s.model_dump() for s in candidates.chosen.steps],
                "_plan_meta": {
                    "style": candidates.chosen.style,
                    "estimated_cost_usd": str(candidates.chosen.estimated_cost_usd),
                    "alternates": [c.style for c in candidates.alternates],
                }}

    async def adapt_plan(self, original_plan, completed_steps,
                         failed_step, goal):
        # Backwards-compat shim — delegates to PlanGenerator.replan
        state = self._pseudo_state(...)
        result = await self._gen.replan(state, failed_step=failed_step)
        return [s.model_dump() for s in result.chosen.steps]
```

### 4.7 T7-7 — Telemetry + KPI (Day 4 PM)

Per §7.

### 4.8 T7-8 — Tests + parity (Day 5)

Per §9.

---

## 5. Database / schema changes

### 5.1 No new tables

`PlanCandidate` lives in memory; only the chosen plan is persisted into
`ExecutionRun.dynamic_plan`. The alternates appear in
`dynamic_plan["_plan_meta"]` for forensics.

### 5.2 Optional: `plan_telemetry` table

For longer-term plan-style analytics. **Deferred to Phase 12.**

---

## 6. API changes

### 6.1 SSE events

```jsonc
{"type":"plan_candidates","candidates_kept":2,"chosen_style":"DAG_PARALLEL",
 "estimated_cost_usd":"0.084"}
{"type":"plan_invariant_violations","candidates_rejected":1,
 "violations":["cost_estimate_within_budget"]}
{"type":"plan_judge_decision","winner_idx":1,"scores":[0.62,0.78]}
{"type":"plan_replan","reason":"supervisor","new_steps":4}
```

### 6.2 Read endpoint

```
GET /api/v1/executions/{id}/plan_candidates
```

Returns the candidate set used to choose the plan. Superadmin.

---

## 7. Telemetry events

| Event | Payload | When |
|-------|---------|------|
| `agent.plan.generation_start` | `{run_id, n_candidates, task_class}` | every reconcile |
| `agent.plan.candidate_generated` | `{run_id, style, estimated_cost_usd, latency_estimate_s}` | per candidate |
| `agent.plan.invariant_violation` | `{run_id, candidate_idx, violations}` | every violation |
| `agent.plan.judge_decision` | `{run_id, winner_idx, scores}` | every judge call |
| `agent.plan.chosen` | `{run_id, style, expected_cost_usd, alternates}` | per reconcile |
| `agent.plan.replan` | `{run_id, by, reason, new_steps}` | every replan |
| `agent.child_resolver.fallback` | `{strategy_used}` (1/2/3/4) | per resolution |
| `agent.child_resolver.failed` | `{step_name, parent_entity_id}` | rare |

---

## 8. Feature flags

| Flag | Default | Notes |
|------|---------|-------|
| `planner.v2_enabled` | ON for entities with `agent_loop.enabled=true` | Master switch |
| `planner.n_candidates` | 3 | Cap; 1 disables multi-candidate effectively |
| `planner.invariants_enforced` | ON | Off only to debug a regression |
| `planner.judge_enabled` | ON | Off → pick lowest-cost candidate |
| `planner.priors_enabled` | ON | Reads Intelligence + bandit priors |

---

## 9. Tests

### 9.1 Unit

* Invariant tests per §4.2.
* `test_cost_estimator_table_values` — synthetic plans match expected
  costs.
* `test_plan_generator_invariant_repair` — all candidates fail; repair
  loop produces ≥1 valid candidate or returns static plan.
* `test_plan_judge_picks_higher_score` — synthetic scores, deterministic.
* `test_child_resolver_strategies` — all four strategies on
  controlled fixtures.

### 9.2 Integration

* `test_planner_v2_emits_3_candidates` — telemetry has 3
  `agent.plan.candidate_generated` events.
* `test_planner_v2_filters_overcost` — entity with low max_cost rejects
  high-cost candidate.
* `test_planner_v2_uses_intelligence_rule` — fixture rule "PROCESS
  with >5 children rarely completes" → candidate with 7 children is
  rejected (via cost / via judge).
* `test_replan_consumes_proposed_subgoals` — supervisor's
  proposed_subgoals appear in the new plan.

### 9.3 Parity / KPI

* Re-run regression suite. Acceptance: cost per success drops ≥10%;
  re-plan rate within ±25% of Track 4.

---

## 10. Acceptance criteria

1. Every dynamic-plan call generates ≥2 candidates (events confirm).
2. Each candidate has invariants applied; rejected candidates emit
   violation events.
3. `child_resolver.resolve_child_entity_id` is the only call site;
   no inline resolution remains in `step_executor` or
   `planner_service`.
4. `adapt_plan` is a 5-line shim calling `PlanGenerator.replan`.
5. Plan judge picks the winner with rationale stored in telemetry.
6. Cost-per-success on regression fixtures drops ≥10% vs Track 4.
7. `mypy --strict` clean on new files.

---

## 11. Effort breakdown (5 working days)

| Day | Work |
|-----|------|
| 1 AM | T7-1: ChildResolver + tests + call site replacements |
| 1 PM | T7-2: PlanInvariants + tests |
| 2 AM | T7-3: Cost estimator + tests |
| 2 PM | T7-4 start: PlanGenerator skeleton + generate_candidates |
| 3 | T7-4 cont'd: invariants integration + repair loop |
| 3 PM | T7-5: PlanJudge |
| 4 AM | T7-6: PlannerService refactor + adapt_plan shim |
| 4 PM | T7-7: telemetry events + KPI hooks |
| 5 | T7-8: integration + parity + PR |

---

## 12. Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| 3x LLM calls for planning blow cost up | M | UX expense | Cap to 2 candidates for entities with `governance.max_cost_usd < 0.20`; use varied temperatures on **the same** model rather than multi-model |
| Invariants too strict (reject all candidates) | M | Repair loop spins | Cap 1 repair attempt; if still no valid plan → fall back to static plan + warning event |
| Judge confidently picks the wrong candidate | M | Worse plan chosen | Use estimated cost as tiebreaker when judge scores are within 0.1; alternates persisted for post-mortem |
| ChildResolver edge-case (entity renamed between runs) | L | Resolution miss | Add Strategy 5 (parent_entity name-hint refresh from current DB) — Phase 12 |
| Cost estimator baselines stale | M | Plan filtering off | Nightly cron updates from telemetry — listed in §3.4 but deferred to Phase 12; for now, baselines are conservative |
| Intelligence rules dominate the prompt and reduce diversity | L | All candidates identical | Cap injected rules to 5; vary temperature ensures diversity |

---

## 13. Dependencies

* **Upstream:**
  * Track 3 (FailureTag-derived intelligence rules).
  * Track 4 (bandit priors for `recommended_style`).
  * Track 6 (Intelligence candidate→confirmed lifecycle).
* **Downstream:**
  * Track 8 (ToolCostResolver telemetry feeds the cost estimator
    refresh).
  * Track 9 (KPIs).

---

## 14. Open questions

* Should each candidate use a **different** model? Cost ↑ but diversity
  ↑. Phase 11: same model, varied temperature.
* Should the judge see **invariant violations** explicitly when one
  candidate has slight issues? Yes — pass the invariant report into the
  judge prompt.
* Should the planner consider **HITL ask** as a candidate move?
  Logically yes — but until DialogExecutor lands (Track 5/8), not
  actionable. Phase 12.
