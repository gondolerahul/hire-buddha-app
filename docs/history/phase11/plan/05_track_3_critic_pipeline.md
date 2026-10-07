# Track 3 — Critic Pipeline v2 (Week 5)

> **Owner:** Agent kernel engineer.
> **Duration:** 5 working days.
> **Behaviour change:** Replaces the per-step critic + the same-model
>   retry loop. Behind `critic_pipeline.v2_enabled` (default ON for
>   any entity that also has `agent_loop.enabled = true`).
> **Risk:** Medium. Critic quality and cost both move; we ship calibrated.
> **Goal mapping:** G3 (calibrated critic), G4 (unify the four checking
>   layers), G8 (budget-aware critics).

This Track replaces the NoOp critic plumbed in Track 2 with a real
**Critic Pipeline** that uses a different-model post-action critic,
emits structured failure tags, and shares state across all four critic
stages.

---

## 1. Objectives (functional)

After Track 3:

1. Every iteration runs four critic stages from a unified pipeline:
   * **Pre-action** — cheap "is this move sensible?"
   * **Post-action** — different-model, structured-tag review of the
     action's output.
   * **Alignment** — periodic goal alignment (folds in GoalGuard's step
     check).
   * **Supervisor** — periodic high-level CONTINUE/REPLAN/ABORT/PAUSE
     verdict (replaces the Track 2 NoOp; Track 4 makes it learning-aware).
2. All four stages write to a shared **`StepHealthRecord`** persisted in
   CORTEX (one record per executed step).
3. **Retry is the Strategist's job, not the critic's.** The legacy
   `_review_step_output` retry loop (which re-ran the same model with
   feedback) is **deleted**. Strategist picks one of seven retry
   strategies based on the `FailureTag` set.
4. Critic LLM calls SHOULD use a `critic_model_override` distinct from
   the actor's model.
5. The pipeline enforces its own **budget**:
   `governance.critic_cost_share_pct` (default 20%). When the critic
   would push run cost above this share, it auto-degrades (Pre+Align off,
   Post stripped down).
6. Calibration: a weekly job samples PASS verdicts vs downstream
   refinement / user-flag outcomes and writes the false-pass rate into
   the IntelligenceTree per task class.

---

## 2. Scope

### In scope

* New file: `planning/critic_pipeline.py` (the four critics + shared
  record).
* New file: `planning/retry_strategies.py` (the seven strategies + the
  picker).
* Refactor: `step_executor.py` — delete `_review_step_output`;
  delegate to `CriticPipeline.post_action`. The legacy flag remains
  available for safety, gated behind `critic_pipeline.v1_compat`
  (default OFF).
* Refactor: `planning/goal_guard.py` — `GoalGuard` becomes a thin
  delegator to `CriticPipeline.alignment`.
* DB migration: `step_health_records` table (or CORTEX subtype — see
  §5).
* Weekly cron job: `critic_calibration_job` (writes false-pass rate).
* Telemetry events for every verdict.
* Updated AgentLoop wiring to use the real `CriticPipeline` instead of
  the NoOp.

### Out of scope

* Multi-model debate. The "second pass with a third model" pattern is a
  P2 follow-up.
* Self-consistency sampling. Same.
* Replacing `MetaReviewer` (Track 4 does that).
* Replacing the Meta-Agent's internal critic (Track 5 does that).

---

## 3. Architecture (technical)

### 3.1 Class diagram

```
              ┌──────────────────────────┐
              │     CriticPipeline       │
              │                          │
              │  + pre_action()          │
              │  + post_action()         │
              │  + alignment()           │
              │  + supervisor()          │
              │  + budget_remaining()    │
              └────────────┬─────────────┘
                           │
            ┌──────────────┼──────────────┐
            ▼              ▼              ▼
    ┌─────────────┐ ┌─────────────┐ ┌─────────────┐
    │ PreCritic   │ │ PostCritic  │ │ AlignCritic │
    │ (cheap LLM) │ │ (DIFF model)│ │ (existing   │
    └─────────────┘ └─────────────┘ │  GoalGuard) │
                                    └─────────────┘
                                           │
                                    ┌──────▼──────┐
                                    │ SupervisorCritic│
                                    │ (Track 4 will  │
                                    │ replace this)  │
                                    └────────────────┘

       ┌─────────────────────────────────────────────┐
       │ All four stages emit into the same          │
       │ StepHealthRecord (one per executed step).   │
       │ Persisted under CORTEX subtree 🩺 Health.   │
       └─────────────────────────────────────────────┘

  Strategist consumes the record to pick a retry strategy:
       (planning/retry_strategies.py::pick_retry)
```

### 3.2 `StepHealthRecord` lifecycle

```
Iteration N — step S is about to execute
  1. PostCritic / Align / Supervisor write into the same record:
     - move_id, iteration, step_id assigned at creation
     - pre_critic_verdict filled  (kind, concerns, cost_usd)
     - executor runs → ActionResult
     - post_critic_verdict + tags + suggestion fill
     - alignment verdict fills (every goal_validation_interval)
     - supervisor verdict fills (every meta_review_interval)
  2. Record persisted to CORTEX (one node per record, under the run's
     Health subtree).
  3. Record appended to state.health_records (capped to last 20).
  4. Strategist reads record on a REVISE / REJECT verdict, picks retry.
```

### 3.3 Different-model resolution

```python
def resolve_critic_model(entity, task_type, actor_model_name):
    # Priority:
    # 1. entity.logic_gate.review_mechanism.critic_model_override
    # 2. company-level setting for {task_type}-critic in IntegrationRegistry
    # 3. heuristic: if actor on Flash → critic on Sonnet,
    #              if actor on Sonnet → critic on Opus,
    #              if actor on Opus  → critic on a *different provider*
    # 4. fallback: same-model with hostile system prompt (warning logged)
    ...
```

### 3.4 Retry strategies

```python
# planning/retry_strategies.py
class RetryStrategy(str, Enum):
    NONE             = "NONE"
    RETRY_AS_IS      = "RETRY_AS_IS"
    RETRY_DIFFERENT_MODEL = "RETRY_DIFFERENT_MODEL"
    RETRY_DIFFERENT_PROMPT = "RETRY_DIFFERENT_PROMPT"
    RETRY_DIFFERENT_TOOL = "RETRY_DIFFERENT_TOOL"
    ASK_USER         = "ASK_USER"
    ABANDON          = "ABANDON"


def pick_retry(record: StepHealthRecord,
               state: AgentState) -> RetryStrategy:
    """
    Decide a retry strategy from the StepHealthRecord and AgentState.
    Pure function — no LLM call, no DB call.
    """
    if record.post_critic_verdict == "PASS":
        return RetryStrategy.NONE

    tags = set(record.post_critic_tags)
    if state.budget.pressure > 0.85:
        return RetryStrategy.ABANDON
    if FailureTag.NEEDS_CLARIFICATION in tags:
        return RetryStrategy.ASK_USER
    if FailureTag.TOOL_FAILURE in tags:
        return RetryStrategy.RETRY_DIFFERENT_TOOL
    if FailureTag.WRONG_FORMAT in tags:
        return RetryStrategy.RETRY_DIFFERENT_PROMPT
    if FailureTag.OFF_TOPIC in tags or FailureTag.CONTRADICTION in tags:
        return RetryStrategy.RETRY_DIFFERENT_MODEL
    if FailureTag.HALLUCINATION in tags:
        return RetryStrategy.RETRY_DIFFERENT_MODEL
    if FailureTag.INCOMPLETE in tags and state.budget.pressure < 0.5:
        return RetryStrategy.RETRY_AS_IS
    return RetryStrategy.ABANDON   # default to "fail forward"
```

This is **deterministic, testable, and fast**. The LLM picks the
*verdict and tags*; the table above picks the *strategy*.

### 3.5 Budget enforcement

```python
class CriticPipeline:
    async def _check_budget(self, state: AgentState) -> Mode:
        share_cap = state.entity_config.get("governance",{}).get(
                       "critic_cost_share_pct", 0.20)
        run_cost = float(state.budget.usd_used)
        critic_cost = float(self._cumulative_critic_cost)
        if run_cost == 0:
            return Mode.FULL
        if critic_cost / run_cost > share_cap:
            return Mode.DEGRADED   # skip pre + align; minimal post
        return Mode.FULL
```

---

## 4. Detailed deliverables

### 4.1 T3-1 — `planning/critic_pipeline.py` (Days 1-2)

```python
"""
planning/critic_pipeline.py — Unified four-stage critic.

Replaces:
  - step_executor._review_step_output (post-action critic w/ retry)
  - planning/goal_guard.GoalGuard step-level alignment
  - core/meta_review.MetaReviewer (Track 4 will upgrade)
"""
from __future__ import annotations
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal
from uuid import UUID, uuid4

from src.ai.planning.failure_tags import FailureTag
from src.ai.core.agent_state import AgentState, PreCriticVerdict, \
    PostCriticVerdict, AlignmentVerdict, SupervisorVerdict


@dataclass
class StepHealthRecord:
    record_id: str = field(default_factory=lambda: str(uuid4()))
    step_id: str = ""
    iteration: int = 0
    move_id: str = ""
    pre_critic_verdict: Literal["PASS","BLOCK","REVISE"] | None = None
    pre_critic_concerns: list[str] = field(default_factory=list)
    pre_critic_cost_usd: Decimal = Decimal("0")
    post_critic_verdict: Literal["PASS","REVISE","REJECT"] | None = None
    post_critic_tags: list[FailureTag] = field(default_factory=list)
    post_critic_suggestion: str = ""
    post_critic_cost_usd: Decimal = Decimal("0")
    alignment_aligned: bool | None = None
    alignment_drift: float | None = None
    alignment_cost_usd: Decimal = Decimal("0")
    supervisor_recommendation: Literal["CONTINUE","REPLAN","ABORT","PAUSE"] | None = None
    supervisor_reasoning: str = ""
    supervisor_cost_usd: Decimal = Decimal("0")
    total_latency_ms: int = 0


class CriticPipeline:
    def __init__(self, db, llm_router, cortex_service,
                 intelligence_reader, config: dict):
        self.db = db
        self.llm = llm_router
        self.cortex = cortex_service
        self.intel = intelligence_reader
        self.config = config
        self._cumulative_critic_cost = Decimal("0")
        self._health_root_id: UUID | None = None

    # ------------------------------------------------------------------
    # Public API — called by AgentLoop
    # ------------------------------------------------------------------

    async def pre_action(self, move, state) -> PreCriticVerdict:
        if self._budget_mode(state) == Mode.DEGRADED:
            return PreCriticVerdict(kind="PASS")
        return await self._pre_critic(move, state)

    async def post_action(self, state, observation) -> PostCriticVerdict:
        return await self._post_critic(state, observation)

    async def alignment(self, state, observation) -> AlignmentVerdict:
        if state.iteration % state.goal_validation_interval != 0:
            return AlignmentVerdict(aligned=True, drift=0.0)
        if self._budget_mode(state) == Mode.DEGRADED:
            return AlignmentVerdict(aligned=True, drift=0.0)
        return await self._alignment_critic(state, observation)

    async def supervisor(self, state) -> SupervisorVerdict:
        if state.iteration % state.meta_review_interval != 0:
            return SupervisorVerdict(recommendation="CONTINUE")
        # Track 4 replaces this with the learning-aware version
        return await self._supervisor_critic(state)
```

Implementation notes (each `_*_critic` method is ~50-80 LoC):

* `_pre_critic`: single LLM call, ≤200 input tokens, ≤120 output tokens,
  temperature 0.1, prompt asks for `{"verdict": "PASS|BLOCK|REVISE",
  "concerns": [str]}`.
* `_post_critic`:
  * Resolves `critic_model_override` (see §3.3).
  * Builds prompt with: entity goal, step description, success criteria,
    observation summary, **prior StepHealthRecord history** (last 3),
    **intelligence rules** (top 3).
  * Asks for `{"verdict": "PASS|REVISE|REJECT", "tags": [FailureTag],
    "suggestion": str}`.
  * Parses tags through `FailureTag.from_string`.
* `_alignment_critic`: thin wrapper around the existing
  `GoalAlignmentVerifier.verify_step_alignment` — but augments output
  to also emit a `drift` score (0..1).
* `_supervisor_critic`: simplified Track 3 version — passes
  AgentState's last 5 reflections + budget pressure to the existing
  `MetaReviewer.review_execution`. Track 4 replaces it with the
  learning-aware version.

### 4.2 T3-2 — `planning/retry_strategies.py` (Day 2 PM)

Implement the `pick_retry` function from §3.4 plus per-strategy
executors:

```python
class RetryExecutor:
    """Maps a RetryStrategy to a concrete action."""

    async def execute(self, strategy, move, state, db) -> Move:
        if strategy == RetryStrategy.RETRY_AS_IS:
            return replace(move, move_id=str(uuid4()))
        if strategy == RetryStrategy.RETRY_DIFFERENT_MODEL:
            return replace(move,
                           move_id=str(uuid4()),
                           plan_fragment=[
                               replace(s, target=replace(s.target,
                                       model_override=self._next_model(s)))
                               for s in move.plan_fragment or []
                           ])
        if strategy == RetryStrategy.RETRY_DIFFERENT_PROMPT:
            ...  # ask LLM to rewrite prompt_template; cap to 1 rewrite
        if strategy == RetryStrategy.RETRY_DIFFERENT_TOOL:
            ...  # use ai.tool_fallback (already exists)
        if strategy == RetryStrategy.ASK_USER:
            ...  # raise UncertaintySignal
        if strategy == RetryStrategy.ABANDON:
            ...  # write structured failure into context_state
        raise ValueError(strategy)
```

The Strategist (Track 2) calls into this when it sees a non-PASS post
verdict.

### 4.3 T3-3 — AgentLoop wiring (Day 3 AM)

Replace `NoOpCriticPipeline` with the real one in `core/agent_loop.py`:

```python
def _compose(self, state, db):
    ...
    self.critic_pipeline = CriticPipeline(
        db=db,
        llm_router=LLMRouter(db, state.company_id),
        cortex_service=self.cortex,
        intelligence_reader=IntelligenceReader(self.db, state.company_id),
        config={
            "critic_cost_share_pct":
                state.entity_config.get("governance",{}).get(
                    "critic_cost_share_pct", 0.20),
            "critic_model_override":
                state.entity_config.get("logic_gate",{})
                                   .get("review_mechanism",{})
                                   .get("critic_model_override"),
        },
    )
```

After post-action verdict, AgentLoop's iteration code adds:

```python
# Pick retry strategy if not PASS
strategy = pick_retry(record, state)
if strategy != RetryStrategy.NONE:
    state.queue_retry(move, strategy)
    # The next iteration will pop this retry move via the Strategist
```

The Strategist now consults `state.retry_queue` before generating a
fresh move.

### 4.4 T3-4 — Delete `_review_step_output` retry loop (Day 3 PM)

In `step_executor.py`:

* Keep `_review_step_output` ONLY behind `critic_pipeline.v1_compat`
  (default OFF). Strip its retry path; it now only logs a deprecation
  warning and returns the original result. This is the "kill switch
  remains" pattern — the function exists for one release in case we
  need to flip back.
* In Track 9 the entire function is removed.

### 4.5 T3-5 — GoalGuard → CriticPipeline.alignment (Day 4 AM)

`planning/goal_guard.py` becomes:

```python
class GoalGuard:
    """
    DEPRECATED in favour of CriticPipeline.alignment.
    Retained as a thin compatibility shim through Track 8.
    """
    def __init__(self, db, company_id, entity_goal, task_description,
                 planner=None, confidence_threshold=0.85):
        self._delegate = AlignmentCritic(db=db, company_id=company_id,
                                          entity_goal=entity_goal,
                                          task_description=task_description)
        ...

    async def check(self, step_result, step_name, step_idx, all_results,
                    total_steps, is_autonomous=False, goal_interval=2):
        # Convert legacy args into AgentState-like object, delegate
        ...
```

This keeps the legacy execution path alive (since the flag is off by
default for the agent loop) while routing the alignment logic through
the new home.

### 4.6 T3-6 — Calibration job (Day 4 PM)

```python
# core/arq_jobs.py — add:
async def critic_calibration_job(ctx):
    """
    Weekly: for each (entity_id, task_class), compute
    false_pass_rate over the last 200 StepHealthRecords vs final
    ExecutionRun outcome and any user_refinement flag.
    Write result as an Intelligence rule (scope=entity_class).
    """
    async with AsyncSessionLocal() as db:
        await CriticCalibrator(db).run()
```

`CriticCalibrator` lives in `planning/critic_calibration.py`. ~150 LoC.

Register in `WorkerSettings.cron_jobs`:

```python
cron_jobs = [
    cron(critic_calibration_job, hour=3, minute=15),   # Sunday-ish UTC
    ...
]
```

### 4.7 T3-7 — Persistence: where does StepHealthRecord live? (Day 5 AM)

**Decision:** As CORTEX nodes (no new SQL table). Reasons:

* Tightly coupled to one run; tree per run already exists.
* Querying for KPIs goes through `CortexService.search_in_tree`.
* No need for an Alembic migration this Track.

```python
async def _persist_record(self, record: StepHealthRecord, state):
    health_root_id = await self._ensure_health_root(state)
    await self.cortex.write(
        parent_id=health_root_id,
        node_type="health_record",
        title=f"🩺 step={record.step_id} iter={record.iteration}",
        summary=f"post={record.post_critic_verdict} "
                f"align={record.alignment_aligned} "
                f"super={record.supervisor_recommendation}",
        content=json.dumps(asdict(record), default=str),
        status="complete",
        source_ref={"type": "step_health_record",
                    "record_id": record.record_id,
                    "tags": [t.value for t in record.post_critic_tags]},
    )
```

`_ensure_health_root` creates a `🩺 Health` subtree under the run's
root the first time a record is written.

### 4.8 T3-8 — Tests (Day 5 PM)

Detailed in §9.

---

## 5. Database / schema changes

### 5.1 New CORTEX node type

* Add `"health_record"` to `CortexNodeType` enum
  (`schemas/enums.py`).
* No SQL migration required (existing CORTEX schema uses free-text
  column).

### 5.2 New CORTEX section

When a run starts (or on first record write), `CriticPipeline` ensures a
`🩺 Health` node exists under the tree's root. No migration; this is a
runtime create.

### 5.3 IntegrationRegistry: critic-model mapping (optional)

Companies that want a global "default critic = Opus" setting can store:

```
service_category = "ai_model"
service_sku      = "<task_type>-critic"     ← new convention
```

`resolve_critic_model` (§3.3) looks this up before falling back to the
heuristic. Pure read; no schema change.

---

## 6. API changes

### 6.1 SSE events

```jsonc
// agent.critic.pre_verdict
{"type":"critic_pre","iteration":7,"verdict":"PASS","cost_usd":"0.001"}

// agent.critic.post_verdict
{"type":"critic_post","iteration":7,"verdict":"REVISE",
 "tags":["INCOMPLETE","WRONG_FORMAT"],"suggestion":"...",
 "cost_usd":"0.012"}

// agent.critic.alignment
{"type":"critic_align","iteration":7,"aligned":true,"drift":0.07}

// agent.critic.supervisor
{"type":"critic_super","iteration":7,"recommendation":"CONTINUE","confidence":0.74}

// agent.retry.queued
{"type":"retry_queued","iteration":7,"strategy":"RETRY_DIFFERENT_MODEL"}
```

### 6.2 Read-only debug

```
GET /api/v1/executions/{id}/health_records
```

Returns the list of `StepHealthRecord` JSON blobs from CORTEX under
`🩺 Health`. Superadmin only.

---

## 7. Telemetry events

| Event | Payload | When |
|-------|---------|------|
| `agent.critic.pre_verdict` | `{run_id, iter, verdict, concerns_count, cost_usd, latency_ms}` | every pre call |
| `agent.critic.post_verdict` | `{run_id, iter, verdict, tags[], cost_usd, latency_ms, model_used}` | every post call |
| `agent.critic.alignment` | `{run_id, iter, aligned, drift, cost_usd}` | every alignment call |
| `agent.critic.supervisor` | `{run_id, iter, recommendation, confidence, cost_usd}` | every supervisor call |
| `agent.critic.budget_degraded` | `{run_id, iter, share, cap}` | when mode flips to DEGRADED |
| `agent.retry.picked` | `{run_id, iter, strategy, tags[]}` | when pick_retry returns non-NONE |
| `agent.retry.exhausted` | `{run_id, iter, last_strategy}` | after max retries |
| `agent.calibration.run` | `{week, entities_scored}` | weekly |
| `agent.calibration.false_pass_rate` | `{entity_id, task_class, rate, sample_size}` | one event per row |

---

## 8. Feature flags

| Flag | Default | Notes |
|------|---------|-------|
| `critic_pipeline.v2_enabled` | ON for entities with `agent_loop.enabled=true`, else OFF | Master switch |
| `critic_pipeline.different_model_critic` | ON | Resolves a distinct critic model |
| `critic_pipeline.pre_critic_enabled` | ON | Cheap pre-action critic |
| `critic_pipeline.budget_share_cap` | 0.20 | Float, not a boolean — fed through `governance.critic_cost_share_pct` |
| `critic_pipeline.v1_compat` | OFF | Re-enables the old `_review_step_output` retry loop in emergencies |
| `critic_pipeline.calibration_enabled` | ON | Weekly cron |

---

## 9. Tests

### 9.1 Unit

* `test_pick_retry_table` — every (verdict, tag set, budget pressure)
  input from a fixture maps to the expected `RetryStrategy`.
* `test_pre_critic_pass_on_obvious_good` — a sensible move + clean state
  yields PASS.
* `test_pre_critic_block_on_obvious_bad` — `entity.goal = "research
  Brain modeling"`, move is `TOOL_CALL[image_generation]` → BLOCK.
* `test_post_critic_tag_parsing` — LLM emits "Off-topic" → parses as
  `FailureTag.OFF_TOPIC`; unknown tag is ignored, not crashed.
* `test_resolve_critic_model_priority` — entity-override > company
  setting > heuristic > fallback.
* `test_budget_degraded_skips_pre_and_align` — pipeline in DEGRADED
  mode returns synthetic PASS verdicts without calling the LLM.
* `test_step_health_record_serialise` — round-trip through
  CORTEX content blob is lossless.
* `test_alignment_drift_calculation` — drift `=` `1 - alignment_score`,
  clamped to `[0, 1]`.

### 9.2 Integration

* `test_loop_with_real_critic_blocks_off_topic` — a real LLM call (or a
  mock-server) → off-topic move → BLOCK → strategy=ABANDON.
* `test_retry_different_model_uses_distinct_model` — observe the
  `model_used` event payload differs between original and retry.
* `test_calibration_writes_intelligence_rule` — seed 200 fake health
  records with known false-pass distribution; cron job writes a
  matching rule.

### 9.3 Cost regression

* `test_critic_cost_share_under_cap` — over 50 fixture runs the
  cumulative critic cost / total cost is ≤ 0.25 (allows 5pp slack).

### 9.4 Parity

* Parity harness from Track 2 re-run with `critic_pipeline.v2_enabled =
  ON`. Acceptance: cost may rise ≤15%; output similarity must be
  ≥0.85; *catch rate on injected errors* must rise ≥10pp.

  An "injected error" test fixture is a known-bad entity (e.g. forces
  hallucination). Track 3 acceptance requires the Critic to catch it.

---

## 10. Acceptance criteria

1. `CriticPipeline.{pre_action,post_action,alignment,supervisor}` are
   live and reachable from `AgentLoop`.
2. `_review_step_output` retry path is gated off in production
   (`critic_pipeline.v1_compat = false`).
3. For at least one fixture, the new pipeline catches a hallucination
   that the legacy v1 critic missed.
4. Cumulative critic cost share ≤25% on the regression fixtures.
5. `StepHealthRecord` JSON appears under `🩺 Health` for every run on
   the new path.
6. Weekly calibration cron runs and writes one Intelligence rule per
   entity class with ≥30 records.
7. SSE events flow: `critic_pre`, `critic_post`, `critic_align`,
   `critic_super`, `retry_queued` are all observed in dev runs.
8. `mypy --strict` clean on `planning/critic_pipeline.py` and
   `planning/retry_strategies.py`.

---

## 11. Effort breakdown (5 working days)

| Day | Work |
|-----|------|
| 1 | T3-1 part 1: skeleton `CriticPipeline`, dataclasses, `_pre_critic` |
| 2 AM | T3-1 part 2: `_post_critic` with different-model resolution + parsing |
| 2 PM | T3-2: `retry_strategies.py` + `pick_retry` + executors |
| 3 AM | T3-3: AgentLoop wiring (replace NoOp) |
| 3 PM | T3-4: gate `_review_step_output` retry behind v1_compat |
| 4 AM | T3-5: GoalGuard shim |
| 4 PM | T3-6: calibration job + cron |
| 5 AM | T3-7: persistence + `🩺 Health` subtree |
| 5 PM | T3-8: tests + parity rerun + PR |

---

## 12. Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Different-model critic adds latency that dominates | M | UX slow | The pipeline already runs critic *after* the action; tail latency rises by 1 LLM call (~1-3s). Cap with `governance.critic_cost_share_pct` budget. |
| LLM emits tags outside the closed enum | H | Tag list comes back empty | `FailureTag.from_string` lenient + lowercase + space normalisation; tests for top-5 variants |
| Critic flags PASS but human disagrees | M | False-pass | The calibration job *measures* this and drives a per-task-class adjustment of the strict/lenient setting |
| Strategist gets stuck retrying with different-model and burns budget | M | Cost blow-up | `max_retries_per_step` (default 2); each retry consumes Budget; ABANDON forced when `pressure > 0.85` |
| Removing v1 critic regresses some entity | L | Outputs degrade | `v1_compat` flag remains for one release; a knob to flip back |
| `_ensure_health_root` race condition on first record | M | Two roots created | `INSERT … ON CONFLICT DO NOTHING` plus a unique constraint on `(tree_id, node_type='health_root')` |

---

## 13. Dependencies

* **Upstream:**
  * Track 1 (`FailureTag` enum).
  * Track 2 (`AgentState`, `Budget`, AgentLoop wiring slot).
* **Downstream:**
  * Track 4 (Meta-Review v2 reads `StepHealthRecord`).
  * Track 5 (Meta-Agent's internal critic re-uses the same primitives).
  * Track 7 (Planner uses calibration intelligence rules).

---

## 14. Open questions

* Should the **alignment critic** also use a different model? Cost-wise
  it's an extra call every N steps; quality lift is real but not as
  big as post-action. **Default:** same model, low temperature. Promote
  to different-model in Track 9 if calibration shows poor precision.
* Should `pick_retry` itself be LLM-driven? Phase 12 if needed; Track 3
  ships it deterministic for predictability.
* Where do the supervisor's `REPLAN` directives go? Today they bubble
  up via the Strategist's `decide_next`. Track 4 wires them more deeply
  through the planner.
