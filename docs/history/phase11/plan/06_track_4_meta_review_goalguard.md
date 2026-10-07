# Track 4 — Meta-Review v2 + GoalGuard Merge + Plan-Style Bandit (Week 6)

> **Owner:** Agent kernel engineer.
> **Duration:** 5 working days.
> **Behaviour change:** Supervisor critic becomes learning-aware. Plan
>   adaptation gains priors. Behind `meta_review.v2_enabled` (default
>   ON when `critic_pipeline.v2_enabled` is ON).
> **Risk:** Medium. Real LLM cost moves; bandit decisions affect plan
>   selection.
> **Goal mapping:** G1, G3, G4, G7 (per-level meta-cognition tuning).

This Track upgrades the **supervisor** stage of the Critic Pipeline
from a naive "look at the last few steps" prompt to a learning-aware
reviewer that consumes the full `AgentState` (reflections, budget,
health records, intelligence rules). It also folds the legacy GoalGuard's
periodic alignment into the Critic Pipeline cleanly, and adds the first
**plan-style bandit** that selects between plan variants based on
historical outcomes.

---

## 1. Objectives (functional)

After Track 4:

1. The supervisor critic emits **calibrated** recommendations:
   `{CONTINUE, REPLAN, ABORT, PAUSE}` with a confidence and a written
   rationale, computed from `AgentState` (reflections + open subgoals +
   budget + health records + intelligence rules) — not from a static
   "last 5 steps" prompt.
2. **`MetaReviewer.review_execution`** (today's one-shot LLM call) is
   replaced by **`SupervisorCritic.assess(state)`** living in the Critic
   Pipeline.
3. GoalGuard exists only as a *back-compat shim* into `AlignmentCritic`.
   No production code path calls it directly.
4. A new **plan-style bandit** (`planning/plan_style_bandit.py`) chooses
   between DAG / Recursive / SingleStep when the Strategist faces a
   strategic decision; selection is biased by historical win-rate per
   *task class* (recorded in the IntelligenceTree by Track 3's
   calibration job).
5. The `MetaReviewer` legacy file is reduced to a 5-line back-compat
   shim that points to the new code.

---

## 2. Scope

### In scope

* New: `planning/supervisor_critic.py` (replaces the legacy
  MetaReviewer's `review_execution`).
* New: `planning/plan_style_bandit.py` (epsilon-greedy bandit + recorder).
* New: `memory/task_classifier.py` (classifies a run/goal into a
  *task class*; used by bandit + calibration).
* Refactor: `core/meta_review.py` → 5-line shim.
* Refactor: `planning/goal_guard.py` → 5-line shim into
  `AlignmentCritic`.
* Refactor: `core/strategist.py` — consults the bandit before choosing
  an executor when more than one strategy fits.
* DB: Bandit state lives in IntelligenceTree (no new table); see §5.
* Telemetry: supervisor verdicts + bandit selections + bandit
  exploration events.

### Out of scope

* LLM-driven Strategist (Track 7).
* MetaIntelligenceTree platform-scope (Track 5).
* Skill promotion (Track 5).
* Cross-tenant bandit state sharing.

---

## 3. Architecture (technical)

### 3.1 Supervisor critic input contract

```
Inputs:
  - AgentState
    * iteration, budget
    * open_subgoals, achieved
    * blockers
    * reflections[-N]
    * health_records[-N]   ← from Track 3
    * task_class            ← from new TaskClassifier
  - IntelligenceRules (filtered by task_class, top-K)
  - Recent ExecutionRun cost telemetry (this entity, last 30 runs)
  - Past supervisor verdicts on this run

Output:
  SupervisorVerdict {
    recommendation: CONTINUE | REPLAN | ABORT | PAUSE
    confidence: float in [0,1]
    reasoning: str
    proposed_subgoals: list[Subgoal]    # optional, populated on REPLAN
  }
```

### 3.2 Plan-style bandit

A simple ε-greedy bandit per `(entity_id, task_class)`:

```
Arms:
  PLAN_STYLE_DAG_PARALLEL     = "DAG_PARALLEL"
  PLAN_STYLE_DAG_SEQUENTIAL   = "DAG_SEQUENTIAL"
  PLAN_STYLE_RECURSIVE        = "RECURSIVE"
  PLAN_STYLE_SINGLE_TOOL      = "SINGLE_TOOL"
  PLAN_STYLE_DIALOG           = "DIALOG"  (Track 5+)

State per arm (stored in IntelligenceTree under 🎯 Strategies):
  pulls:    int
  successes: int
  avg_cost_usd: float
  last_pull_at: datetime
```

Selection:

```python
def select_arm(arms, epsilon: float = 0.10):
    if random.random() < epsilon:
        return random.choice(arms)           # exploration
    return max(arms, key=lambda a: arm_score(a))

def arm_score(arm):
    # Win-rate / cost
    win_rate = (arm.successes + 1) / (arm.pulls + 2)
    return win_rate / max(arm.avg_cost_usd, 0.01)
```

After a run completes, the run's final outcome (COMPLETED w/ no
refinement vs failed/refined) updates the chosen arm's counts.

### 3.3 Task classifier

```python
class TaskClassifier:
    """
    Maps a run's task description + entity to a task class.
    Used by:
      - Plan-style bandit
      - Critic calibration
      - IntelligenceRules filter
    """
    async def classify(self, *, task_description: str,
                       entity: HierarchicalEntity) -> str:
        # Day 1 v1: rule-based (entity.tags + heuristic on description).
        # Day 4 v2: cheap embedding-similarity into a small fixed
        # vocabulary (~30 task classes) seeded from existing entities.
        ...
```

The class is a **stable string identifier** (e.g.
`"research_topic"`, `"extract_from_url"`, `"draft_email"`).

### 3.4 Sequence inside one iteration (deltas vs Track 3)

```
... (Track 3 pre / executor / post / alignment ran) ...

await CriticPipeline.supervisor(state)
   │
   ▼
SupervisorCritic.assess(state)
   │
   ├─ build input prompt with last-N reflections, budget pressure,
   │    open_subgoals, top intelligence rules, recent health records
   ├─ LLM call (model=critic_model_override if set, else stronger model)
   ├─ parse JSON {recommendation, confidence, reasoning, proposed_subgoals}
   └─ return SupervisorVerdict
   │
   ▼
Strategist.decide_next(state, supervisor_verdict)
   │
   ├─ If recommendation=REPLAN:
   │     await Planner.replan(state, supervisor_verdict.proposed_subgoals)
   │     state.replace_plan(new_plan)
   ├─ If recommendation=ABORT:
   │     decision = ABORT
   └─ default: CONTINUE
```

### 3.5 Bandit hooks

Strategist consults the bandit only when multiple plan styles fit:

```python
async def next_move(self, state, perception):
    candidates = self._candidate_styles(state)
    if len(candidates) > 1:
        arm = await self.bandit.select_arm(
            entity_id=state.entity_id,
            task_class=state.task_class,
            candidates=candidates,
        )
        event("agent.bandit.arm_selected", arm=arm, candidates=candidates)
        return self._build_move_for(arm, state)
    return self._build_move_for(candidates[0], state)
```

After the run finishes, AgentLoop's `_finalize` records the outcome:

```python
await self.bandit.update_arm(
    entity_id=state.entity_id,
    task_class=state.task_class,
    arm=state.chosen_executor_summary(),
    success=state.is_success(),
    cost_usd=float(state.budget.usd_used),
)
```

---

## 4. Detailed deliverables

### 4.1 T4-1 — `memory/task_classifier.py` (Day 1)

```python
class TaskClassifier:
    def __init__(self, db, company_id, embedding_service):
        self.db = db
        self.company_id = company_id
        self.emb = embedding_service
        self._vocab: list[str] | None = None    # lazy

    async def classify(self, *, task_description: str,
                       entity: HierarchicalEntity) -> str:
        # 1. Fast path: entity.metadata_extensions.task_class
        cls = (entity.metadata_extensions or {}).get("task_class")
        if cls:
            return cls

        # 2. Tag-based fallback
        tags = entity.tags or []
        for tag in tags:
            if tag in _TAG_TO_CLASS:
                return _TAG_TO_CLASS[tag]

        # 3. Heuristic: keyword match on task_description
        td = (task_description or "").lower()
        for kw, cls in _KEYWORD_TO_CLASS:
            if kw in td:
                return cls

        # 4. v2 (Day 4): embedding nearest-neighbour into _vocab
        return "general"


_TAG_TO_CLASS = {
    "research":     "research_topic",
    "extract":      "extract_from_url",
    "email":        "draft_email",
    "social":       "post_social_content",
    "report":       "generate_report",
    # … seed with existing entity tags ...
}

_KEYWORD_TO_CLASS = [
    ("research",  "research_topic"),
    ("scrape",    "extract_from_url"),
    ("summari",   "summarise_content"),
    ("draft email","draft_email"),
    # …
]
```

The v1 classifier is rule-based; the v2 embedding classifier (Day 4)
fills in `general` cases.

### 4.2 T4-2 — `planning/supervisor_critic.py` (Days 1-2)

```python
class SupervisorCritic:
    """
    Replaces core/meta_review.MetaReviewer.review_execution.

    Reads the full AgentState (reflections, health, budget, etc.) and
    emits a calibrated SupervisorVerdict.
    """

    def __init__(self, db, llm_router, intelligence_reader, telemetry):
        self.db = db
        self.llm = llm_router
        self.intel = intelligence_reader
        self.telemetry = telemetry

    async def assess(self, state: AgentState) -> SupervisorVerdict:
        budget_pressure = state.budget.pressure
        if budget_pressure >= 0.95:
            return SupervisorVerdict(
                recommendation="ABORT",
                confidence=0.95,
                reasoning="Budget exhausted (pressure≥0.95)",
            )

        # Fast path: if last 3 health records all show PASS, CONTINUE.
        recent_health = state.health_records[-3:]
        if (len(recent_health) >= 3
            and all(h.post_critic_verdict == "PASS" for h in recent_health)
            and all((h.alignment_aligned is None or h.alignment_aligned)
                    for h in recent_health)):
            return SupervisorVerdict(
                recommendation="CONTINUE",
                confidence=0.85,
                reasoning="Three consecutive clean steps.",
            )

        # LLM call only when fast paths inconclusive
        prompt = self._build_prompt(state)
        resp = await self.llm.call_llm(
            task_type="text_generation",
            system_prompt=self._SYSTEM,
            user_prompt=prompt,
            temperature=0.2,
            max_tokens=600,
            model_override=state.critic_model_override,
        )
        parsed = self._parse(resp.output)
        verdict = SupervisorVerdict(
            recommendation=parsed["recommendation"],
            confidence=parsed["confidence"],
            reasoning=parsed["reasoning"],
            proposed_subgoals=[
                Subgoal(id=str(uuid4()),
                        description=s["description"],
                        priority=s.get("priority", 0))
                for s in parsed.get("proposed_subgoals", [])
            ],
        )
        await self.telemetry.emit("agent.critic.supervisor", state=state,
                                  verdict=verdict, cost=resp.cost_usd)
        return verdict

    _SYSTEM = """You are a Supervisor reviewing an autonomous AI agent.
You assess whether the run is on track, drifting, or should stop.
Be conservative. Recommend ABORT only on clear failure or budget risk.
Recommend PAUSE only when human input is essential."""

    def _build_prompt(self, state: AgentState) -> str:
        lines = []
        lines.append(f"## Run iteration: {state.iteration} / {state.budget.iters_max}")
        lines.append(f"## Budget: USD ${state.budget.usd_used} / ${state.budget.usd_max}, "
                     f"tokens {state.budget.tokens_used}/{state.budget.tokens_max}, "
                     f"wall {state.budget.wall_used_s}s/{state.budget.wall_max_s}s")
        lines.append(f"## Goal: {state.entity_goal}")
        lines.append(f"## Open subgoals ({len(state.open_subgoals)}):")
        for g in state.open_subgoals[:10]:
            lines.append(f"  - {g.description}"
                         + (f" (blocked: {g.blocked_on})" if g.blocked_on else ""))
        lines.append(f"## Recent reflections ({len(state.reflections[-3:])}):")
        for r in state.reflections[-3:]:
            lines.append(f"  - {r.what_worked or '∅'} / {r.what_didnt or '∅'}")
        lines.append(f"## Recent step health ({len(state.health_records[-5:])}):")
        for h in state.health_records[-5:]:
            tags = ",".join(t.value for t in h.post_critic_tags)
            lines.append(f"  - step={h.step_id} post={h.post_critic_verdict} tags=[{tags}]")
        lines.append(f"## Intelligence rules (top 3):")
        for ir in (state.perception.intelligence_rules or [])[:3]:
            lines.append(f"  - {ir.text}")
        lines.append("\nRespond with JSON:")
        lines.append('{"recommendation":"CONTINUE|REPLAN|ABORT|PAUSE",'
                     '"confidence":0.0-1.0,"reasoning":"…",'
                     '"proposed_subgoals":[{"description":"…","priority":1}]}')
        return "\n".join(lines)

    def _parse(self, output: str) -> dict:
        ...   # safe JSON extraction; fallback to CONTINUE on parse error
```

### 4.3 T4-3 — Critic Pipeline plug-in (Day 2 PM)

`CriticPipeline.supervisor` now delegates to the new class:

```python
async def supervisor(self, state) -> SupervisorVerdict:
    if state.iteration == 0:
        return SupervisorVerdict(recommendation="CONTINUE")
    if state.iteration % state.meta_review_interval != 0:
        return SupervisorVerdict(recommendation="CONTINUE")
    if self._budget_mode(state) == Mode.DEGRADED:
        return SupervisorVerdict(recommendation="CONTINUE")
    return await self._supervisor_critic.assess(state)
```

### 4.4 T4-4 — `planning/plan_style_bandit.py` (Day 3)

```python
class PlanStyleBandit:
    """
    Epsilon-greedy bandit over plan styles, keyed by (entity_id, task_class).
    Arm state persists in IntelligenceTree under 🎯 Strategies.
    """

    def __init__(self, db, company_id, intelligence_writer, epsilon=0.10):
        self.db = db
        self.company_id = company_id
        self.intel = intelligence_writer
        self.epsilon = epsilon

    async def select_arm(self, *, entity_id, task_class, candidates) -> str:
        arms = await self._load_arms(entity_id, task_class, candidates)
        if random.random() < self.epsilon:
            chosen = random.choice(candidates)
        else:
            chosen = max(candidates, key=lambda c: self._score(arms[c]))
        return chosen

    async def update_arm(self, *, entity_id, task_class, arm,
                         success: bool, cost_usd: float):
        arms = await self._load_arms(entity_id, task_class, [arm])
        st = arms[arm]
        st["pulls"] += 1
        if success:
            st["successes"] += 1
        # Exponential running average for cost
        alpha = 0.2
        st["avg_cost_usd"] = (1-alpha)*st["avg_cost_usd"] + alpha*cost_usd
        st["last_pull_at"] = datetime.utcnow().isoformat()
        await self._save_arms(entity_id, task_class, arms)

    def _score(self, st):
        win_rate = (st["successes"] + 1) / (st["pulls"] + 2)
        return win_rate / max(st["avg_cost_usd"], 0.01)

    async def _load_arms(self, entity_id, task_class, candidates):
        # Read from IntelligenceTree under section "🎯 Strategies",
        # node title "Bandit: <task_class>"; content is a JSON dict
        # {arm: state}.
        node = await self.intel.find_or_create_strategy_node(
            entity_id=entity_id,
            title=f"Bandit: {task_class}",
        )
        data = json.loads(node.content) if node.content else {}
        for c in candidates:
            data.setdefault(c, {"pulls": 0, "successes": 0,
                                "avg_cost_usd": 0.05,
                                "last_pull_at": None})
        return data

    async def _save_arms(self, entity_id, task_class, arms):
        await self.intel.update_strategy_node(
            entity_id=entity_id,
            title=f"Bandit: {task_class}",
            content=json.dumps(arms, default=str),
            summary=self._render_summary(arms),
        )
```

### 4.5 T4-5 — Strategist wiring (Day 3 PM)

```python
class Strategist:
    def __init__(self, ..., bandit: PlanStyleBandit):
        ...
        self.bandit = bandit

    async def next_move(self, state, perception) -> Move:
        # Existing logic identifies one or more candidate plan styles.
        candidates = self._candidate_styles(state)
        if len(candidates) == 1:
            return self._build_move_for(candidates[0], state)
        arm = await self.bandit.select_arm(
            entity_id=state.entity_id,
            task_class=state.task_class,
            candidates=[c.style for c in candidates],
        )
        chosen = next(c for c in candidates if c.style == arm)
        return self._build_move_for(chosen, state)
```

### 4.6 T4-6 — Outcome update on run completion (Day 4 AM)

```python
# core/agent_loop.py — at end of run
async def _finalize(self, state, db):
    success = state.is_success()
    for chosen_arm in state.chosen_arms_by_iteration:
        await self.bandit.update_arm(
            entity_id=state.entity_id,
            task_class=state.task_class,
            arm=chosen_arm,
            success=success,
            cost_usd=float(state.budget.usd_used) /
                     max(len(state.chosen_arms_by_iteration), 1),
        )
    ...
```

`AgentState` now tracks `chosen_arms_by_iteration: list[str]` so the
bandit can update each arm's stats fairly.

### 4.7 T4-7 — Replanning (Day 4 PM)

When `SupervisorVerdict.recommendation == "REPLAN"`:

```python
# Strategist.decide_next
if super_verdict and super_verdict.recommendation == "REPLAN":
    new_plan = await self.planner.replan(
        state=state,
        proposed_subgoals=super_verdict.proposed_subgoals,
    )
    state.replace_plan(new_plan)
    return Decision(next="CONTINUE", reason="REPLAN by supervisor")
```

`PlannerService.replan` already exists as `adapt_plan`; we extend its
signature to take an `AgentState` plus `proposed_subgoals` (Track 7
refactors further):

```python
async def replan(self, state, proposed_subgoals) -> list[PlanStep]:
    # Wrap adapt_plan, adding intelligence rules + proposed subgoals
    failed_step = (state.last_observation.summary if state.last_observation else "")
    return await self.adapt_plan(
        original_plan=state.plan,
        completed_steps=state.completed_step_results,
        failed_step={"name": "supervisor_request", "error": failed_step},
        goal="\n".join(g.description for g in proposed_subgoals)
             or state.entity_goal,
    )
```

### 4.8 T4-8 — Legacy shims (Day 5 AM)

`core/meta_review.py`:

```python
"""
DEPRECATED — use planning.supervisor_critic.SupervisorCritic via
CriticPipeline.supervisor instead.

Retained for backwards-compat. Will be deleted in Track 9.
"""
from src.ai.planning.supervisor_critic import SupervisorCritic
from src.ai.core.agent_state import SupervisorVerdict  # noqa: F401

class MetaReviewer:
    def __init__(self, db, company_id):
        self._impl = SupervisorCritic(db=db, ...)

    async def review_execution(self, *, entity_goal, completed_steps,
                                remaining_steps, total_cost_usd=0,
                                context_summary=""):
        # Build a minimal AgentState from legacy args, delegate
        ...
```

`planning/goal_guard.py`: already became a shim in Track 3. Confirm.

### 4.9 T4-9 — Tests + parity (Day 5)

Detailed in §9.

---

## 5. Database / schema changes

### 5.1 Bandit state — no new table

Bandit arms persist as **IntelligenceTree nodes** under a per-entity
section `🎯 Strategies`:

* Section node title: `🎯 Strategies`.
* Per-task-class child: title `Bandit: <task_class>`, content = JSON
  arm state, summary = compact human-readable.

This re-uses existing schema; the only change is a new `node_type`
value:

* Add `"bandit_arm_state"` to `CortexNodeType` enum.

### 5.2 IntelligenceTree section convention

Make `🎯 Strategies` a first-class section in
`memory/intelligence_tree_service.py` (it already exists as a constant).
Track 4 only requires that the section is created if missing.

### 5.3 Calibration rules → IntelligenceTree

Existing Track 3 calibration job already writes rules; Track 4 just
reads them via `IntelligenceReader.filter_by_task_class(...)`.

---

## 6. API changes

### 6.1 SSE events

```jsonc
// agent.critic.supervisor          (already in Track 3, payload extended)
{"type":"critic_super","iteration":10,"recommendation":"REPLAN",
 "confidence":0.78,"reasoning":"Two off-topic steps in a row",
 "proposed_subgoals":[{"description":"Narrow scope to original goal"}]}

// agent.bandit.arm_selected
{"type":"bandit_arm","iteration":3,"task_class":"research_topic",
 "candidates":["DAG_PARALLEL","RECURSIVE"],"chosen":"DAG_PARALLEL"}

// agent.bandit.arm_updated         (post-run)
{"type":"bandit_arm_updated","arm":"DAG_PARALLEL","pulls":17,
 "successes":12,"avg_cost_usd":0.084,"score":0.78}
```

### 6.2 Read-only debug

```
GET /api/v1/entities/{id}/bandit_state?task_class=research_topic
```

Returns the current arm table for that entity / task class. Superadmin.

---

## 7. Telemetry events

| Event | Payload | When |
|-------|---------|------|
| `agent.critic.supervisor` (Track 3 event, payload extended) | extends with `proposed_subgoals_count` | every supervisor call |
| `agent.bandit.arm_selected` | `{run_id, iter, task_class, candidates, chosen, exploration}` | every bandit pull |
| `agent.bandit.arm_updated` | `{entity_id, task_class, arm, success, cost_usd, new_score}` | per run finalize |
| `agent.replan.triggered` | `{run_id, iter, by, proposed_subgoals_count}` | every REPLAN action |
| `agent.task_class.classified` | `{run_id, entity_id, task_class, classifier_version}` | every run start |

---

## 8. Feature flags

| Flag | Default | Notes |
|------|---------|-------|
| `meta_review.v2_enabled` | ON when critic_pipeline.v2_enabled is ON | Master switch for SupervisorCritic |
| `meta_review.fast_path_enabled` | ON | 3-clean-steps fast path skips the LLM call |
| `bandit.enabled` | ON | Plan-style bandit |
| `bandit.epsilon` | 0.10 | Float — sampled from FF service |
| `task_classifier.v2_enabled` | OFF | Day-4 embedding classifier; rolled on per company |

---

## 9. Tests

### 9.1 Unit

* `test_supervisor_abort_on_budget_exhaustion` — pressure 0.96 →
  always ABORT.
* `test_supervisor_fast_path_continue` — three clean recent
  `StepHealthRecord` → CONTINUE without LLM call.
* `test_supervisor_replan_includes_proposed_subgoals` — when LLM
  emits proposed_subgoals, they parse and surface.
* `test_bandit_score_orders_correctly` — higher win-rate / lower
  cost → higher score.
* `test_bandit_exploration_rate` — over 1000 selections with ε=0.10,
  exploration is 10±2%.
* `test_bandit_update_running_average` — cost EMA matches expected
  formula.
* `test_task_classifier_known_tag` — entity with `tags=["research"]`
  → `research_topic`.
* `test_task_classifier_fallback` — unknown entity, generic
  description → `general`.

### 9.2 Integration

* `test_replan_triggers_planner_replan` — supervisor returns REPLAN
  → planner.replan called with proposed_subgoals.
* `test_run_finalize_updates_bandit` — completed run increments
  the chosen arm's `pulls` and `successes`.
* `test_bandit_state_persisted_in_intelligence_tree` — `🎯 Strategies`
  / `Bandit: research_topic` node exists after a run.

### 9.3 Parity (against Track 3 baseline)

* Same 3 fixtures. Acceptance: total cost within ±10% of Track 3;
  catch rate on injected errors ≥ Track 3's; replan_rate observed > 0
  on at least one fixture (i.e. the supervisor *can* trigger replan).

---

## 10. Acceptance criteria

1. `SupervisorCritic.assess` is the only code path called by
   `CriticPipeline.supervisor`.
2. `core/meta_review.py` is a 5-line shim.
3. `planning/goal_guard.py` is a 5-line shim into AlignmentCritic.
4. For any entity with ≥2 candidate plan styles, the bandit's choice
   appears in telemetry; after ≥10 runs the highest-scoring arm is
   chosen ≥ (1-ε) of the time.
5. After ≥30 runs on a fixture entity the bandit's chosen arm shows a
   measurable cost-per-success advantage vs deterministic Strategist
   from Track 2.
6. On the regression suite, supervisor LLM cost is < 8% of total run
   cost (the fast-path skips most calls).
7. `mypy --strict` clean on new files.

---

## 11. Effort breakdown (5 working days)

| Day | Work |
|-----|------|
| 1 AM | T4-1: TaskClassifier v1 |
| 1 PM | T4-2 start: SupervisorCritic prompt + parse |
| 2 AM | T4-2 cont'd: fast-paths, integration in CriticPipeline |
| 2 PM | T4-3: pipeline plug-in + AgentState plumb-through |
| 3 | T4-4: PlanStyleBandit + persistence in IntelligenceTree |
| 4 AM | T4-5: Strategist consults bandit |
| 4 PM | T4-6 + T4-7: outcome update + replan path |
| 5 AM | T4-8: legacy shims (meta_review, goal_guard) |
| 5 PM | T4-9: tests + parity + PR |

---

## 12. Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Supervisor LLM call expensive | M | Cost rises | Fast path + `meta_review_interval` (default 5); budget mode degrade |
| Bandit converges to a bad arm early | M | Worse runs for a while | ε exploration; min arm sample size 5 before exploitation; reset arm if cost > 3× expected |
| Task classifier mis-classifies → wrong bandit table | H | Stat leakage across classes | Keep classifier conservative; bandit per (entity_id, task_class) so leakage is bounded |
| Replan triggers a bad new plan that loops | M | Wasted budget | Hard cap `max_replanning_attempts` (already in schema) honoured at the Strategist level |
| IntelligenceTree write contention | L | Lost updates | `update_strategy_node` uses row-level lock or upsert |
| Supervisor's proposed_subgoals conflict with existing subgoals | M | Confused state | `state.replace_plan` *replaces*, not merges; explicit decision in code |

---

## 13. Dependencies

* **Upstream:**
  * Track 1 (FailureTag for fast-path checks).
  * Track 2 (AgentState, AgentLoop).
  * Track 3 (CriticPipeline supervisor slot, StepHealthRecord, calibration).
* **Downstream:**
  * Track 5 (Meta-Agent uses SupervisorCritic-style review for spec
    quality).
  * Track 7 (PlannerGenerator v2 uses bandit priors).

---

## 14. Open questions

* Should the bandit be **per-user**, per-company, or per-entity? Default
  per-entity (covers most cases; per-user adds high cardinality with
  little benefit until ≫ 1000 runs/user/class).
* Should the supervisor be allowed to *reduce* the budget (e.g. PAUSE
  with proposed cap)? Track 4 says no — budget is the user's contract.
  Phase 12+ may revisit.
* Should the bandit consider **per-iteration arms** instead of
  per-run? Track 4 picks per-iteration because Strategist picks each
  iter; outcome attribution is averaged over the run. A more advanced
  contextual bandit lives in P3 backlog.
