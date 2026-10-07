# 05 — Dynamic Planning, Review Mechanism, and Meta-Cognition (per-hierarchy-level)

This document focuses on the **three central knobs** that determine
whether an agent acts intelligently:

1. **Dynamic planning** — how a plan is generated, adapted, replanned
2. **Review mechanism** — how outputs are critiqued and corrected
3. **Meta-cognition** — the agent's awareness of the platform and itself

For each of the four entity types (ACTION / SKILL / AGENT / PROCESS) we
recommend a calibrated configuration and the missing primitives.

---

## 1. Dynamic Planning

### 1.1 Current state

`planning/planner_service.py` does three things well:

* Reconciles static + dynamic plan, preserving `CHILD_ENTITY_INVOCATION`
  steps the LLM might drop.
* Generates a dynamic plan with **platform manifest** + **children
  descriptions** injected.
* Has `adapt_plan()` for mid-execution re-planning after a failure.

It does **not** do:

* Plan-style track record (no priors).
* Plan-cost prediction (no estimated cost per step).
* Plan-quality calibration (no telemetry on which plan styles succeed).
* Plan diff / multi-candidate selection.
* Plan invariants checking (only Pydantic — no "this PROCESS has a cycle").

### 1.2 Failure modes observed in code

* `_parse_plan_output` (`planner_service.py:421-454`) is forgiving but
  silent. A malformed plan returns `[]` and `reconcile()` falls back to
  the static plan with no signal that the dynamic plan was junk.
* `_generate_dynamic_plan` does not include **past similar plans** for
  this entity (or entity class). It re-derives from scratch every time.
* `has_parallel_steps` is correct but only used to choose between DAG and
  sequential — there is no concept of "this plan is bad" that
  short-circuits execution.

### 1.3 Proposed: PlanGenerator v2

```python
# planning/plan_generator.py  (NEW, supersedes _generate_dynamic_plan)
class PlanGenerator:
    async def generate(self, ctx: PlanContext) -> PlanCandidates:
        # 1. Pull priors: previous successful/failed plans for similar tasks
        priors = await self.intelligence.retrieve_plan_priors(ctx.task_class)

        # 2. Generate N candidate plans (LLM, N=3, varied temperature)
        candidates = await self.llm.gen_candidates(ctx, priors, n=3)

        # 3. Score each candidate locally:
        #    - Has cycle? (cheap deterministic)
        #    - Tool capabilities cover all TOOL_CALL steps?
        #    - Sum(estimated_cost_per_step) ≤ budget?
        #    - Matches Critic Intelligence rules?
        scored = self._local_score(candidates)

        # 4. Optional LLM judge: pick best of top-3
        best = await self._llm_judge_best(scored[:3])

        return PlanCandidates(chosen=best, alternates=scored[1:])
```

`PlanContext` is the perception payload from §03 plus intelligence rules.

The Strategist (§03) picks from `PlanCandidates`, recording the choice into
the Intelligence Tree along with the eventual outcome.

### 1.4 Bandits across plan styles

After a few weeks of data, the Strategist can use a simple multi-armed
bandit to favour the plan styles that historically work best for a given
*task class*:

| Task class | Plan styles seen | Win rate | Avg cost |
|------------|------------------|----------|----------|
| "research a topic" | DAG-3step | 0.82 | $0.08 |
| | DAG-5step | 0.71 | $0.14 |
| | Recursive | 0.55 | $0.21 |
| "extract from URL" | SingleTool | 0.95 | $0.01 |

Task classification can use the existing `RegistrySearchService`'s
semantic search machinery against past successful runs.

### 1.5 Plan invariants checker

Add `planning/plan_invariants.py`:

```python
def validate_plan(plan: list[PlanStepDict],
                  entity: HierarchicalEntity,
                  budget: Budget) -> list[Invariant]:
    return [
        no_cycle_in_child_invocations(plan, entity),
        all_required_tools_in_capabilities(plan, entity),
        no_dangling_variable_refs(plan),
        cost_estimate_within_budget(plan, budget),
        no_orphaned_outputs(plan),
        ...
    ]
```

This runs *before* execution. A failed invariant → bounce back to the
PlanGenerator (one revision attempt) → if still failing, fall back to
static plan or escalate.

### 1.6 Dynamic *plan adaptation* (the existing `adapt_plan`)

`adapt_plan` is one prompt. It works, but:

* It re-includes the *full* remaining plan in the prompt. This grows
  quadratically.
* It cannot drop steps that were redundant — only mutate / add.
* It does not know about Intelligence rules.

Fix: refactor it to consume the **Reflection** record from §03 instead of
just the failed step.

```python
async def adapt_plan(self,
                     state: AgentState,  # has reflections, open_subgoals
                     failed_step: dict) -> AdaptedPlan: ...
```

---

## 2. Review Mechanism

Today's review is **a single critic LLM call per step**, with the same
model, same prompt context, and retries that re-run the original step
with critic feedback appended.

This is the single highest-cost lowest-leverage subsystem.

### 2.1 What's broken specifically

| Issue | Location | Cost |
|-------|----------|------|
| Same model as actor | `step_executor._review_step_output:1407` | High false-pass rate |
| Retry runs **the same** `_execute_thought` with feedback in `retry_context["input"]` | `step_executor.py:1466-1474` | Often converges to same answer |
| Critic strictness is `strict | lenient`, no in-between | `step_executor.py:1360-1377` | Wrong on most real tasks |
| No structured "failure tags" — only `passed: bool` + free-text `reason` | `step_executor.py:1437-1450` | No data for learning |
| `success_criteria` are free-text strings, not structured | `schemas.py:249-266` | Critic must subjectively interpret |
| No critic budget; can spend hours on retries | `step_executor.py:1379-1394` (wallclock guard exists, but no $/token guard) | Cost blowouts |

### 2.2 Proposed: Critic Pipeline

A four-stage pipeline that *shares state* via a `StepHealthRecord`:

```
                        ┌──────────────┐
   Move (proposed)  ───▶│ Pre-Critic   │  ── cheap, 1 call
                        │  (block/pass)│
                        └──────┬───────┘
                               │ pass
                               ▼
                        ┌──────────────┐
                        │  Executor    │
                        └──────┬───────┘
                               │ result
                               ▼
                        ┌──────────────┐
   Last result + state ▶│ Post-Critic  │  ── different model
                        │ (pass/revise │
                        │  /reject)    │
                        └──────┬───────┘
                               │
                  ┌────────────┼─────────────┐
                  ▼            ▼             ▼
              ┌───────┐   ┌────────┐    ┌────────┐
              │ Align │   │ Super  │    │ Skill  │
              │ Critic│   │ Critic │    │Promote?│
              └───┬───┘   └───┬────┘    └────┬───┘
                  └──────┬────┴──────────────┘
                         ▼
                   StepHealthRecord
                   (persisted in CORTEX)
```

* **Pre-Critic** (very cheap, <300 tokens): "Given the current state, does
  this move look right? Reply YES or NO + reason." Stops obvious mistakes
  before the executor spends money.
* **Post-Critic** (the today's critic, but with a different model): does
  the output satisfy success criteria *and* not contradict any
  Intelligence rule?
* **Alignment Critic** (the GoalGuard work, but reading the StepHealthRecord
  from earlier critics so it doesn't duplicate them).
* **Supervisor Critic** (today's MetaReviewer, run every N iterations,
  consuming the *aggregated* record, never re-deriving).
* **Skill Promotion check** (new, lightweight): "Has this chain of
  successful steps appeared >= K times across this entity's history? If
  so, propose promoting to a SKILL."

### 2.3 StepHealthRecord schema

```python
@dataclass
class StepHealthRecord:
    step_id: str
    iteration: int
    pre_critic_pass: bool
    pre_critic_concerns: list[str]
    post_critic_verdict: Literal["PASS", "REVISE", "REJECT"]
    post_critic_tags: list[str]   # structured: "off_topic","hallucination","incomplete","wrong_format"
    alignment_aligned: bool
    alignment_drift: float
    cost_usd: Decimal
    latency_ms: int
```

Tags are *structured* (an enum) so we can aggregate ("entity X drifts
off-topic 30% of the time on step 3" — that becomes an Intelligence Rule).

### 2.4 Calibration loop

Every 100 runs of Post-Critic:

1. Sample 20 of its PASS verdicts.
2. Compare against actual downstream success (final run COMPLETED, no
   refinement, no user feedback flag).
3. If false-positive rate > 20%, **tighten the critic's threshold** for
   this entity class.

A pluggable `CriticCalibrator` writes calibrated thresholds into the
Intelligence Tree per task class.

### 2.5 Retry logic — do NOT re-run with same model + feedback

Replace `_review_step_output`'s retry path with explicit *strategies*:

* `RETRY_AS_IS` — same call, deterministic (`seed=N`). Useful for flaky
  tools, not LLM mistakes.
* `RETRY_WITH_CRITIC_PERSONA` — bump model to a stronger one, re-run.
* `RETRY_WITH_DIFFERENT_PROMPT` — ask Architect-like role to rewrite
  the step prompt, then run.
* `RETRY_WITH_DIFFERENT_TOOL` — invoke fallback tool chain.
* `RETRY_WITH_HUMAN_CLARIFICATION` — raise `UncertaintySignal` to user.
* `ABANDON_GRACEFULLY` — write a structured failure into the result and
  move on.

The Strategist picks the retry strategy from the StepHealthRecord tags.

### 2.6 Cost discipline

The Critic Pipeline must have its **own budget** under the run's overall
budget. Default 20% of `governance.max_cost_usd` for critic work.

If critic-cost / total-cost > 30% for any entity over 50 runs, that
entity's review_mechanism is auto-downgraded by the platform (a candidate
Meta-Intelligence rule).

---

## 3. Meta-Cognition (per hierarchical level)

Currently, `resolve_meta_cognition` (in `platform_schema_compiler.py`)
auto-enables tiers based on entity type:

* Tier 1 (`platform_awareness`) — on when REACT or dynamic planning.
* Tier 2 (`registry_search`) — on for AGENT and PROCESS.
* Tier 3 (`self_modification`) — on for AGENT and PROCESS.

This is too coarse. Below is a proposed per-level matrix.

### 3.1 ACTION (atomic, 1 step)

| Meta-cognition | Recommended | Why |
|----------------|-------------|-----|
| Platform awareness | **OFF by default** | One step, one tool — knowing the platform doesn't help. |
| Self-introspection (NEW) | **OFF** | No iteration, nothing to introspect. |
| Registry search | OFF | Cannot delegate. |
| Self-modification | OFF | Should never create more agents. |
| Reflection (NEW) | OFF | Single step. |

But: **expose its `description`, `target.tool_id`, `input` to telemetry**
so its outcomes feed the Intelligence Tree of its parent SKILL/AGENT.

### 3.2 SKILL (2-5 step chain, no children)

| Meta-cognition | Recommended | Why |
|----------------|-------------|-----|
| Platform awareness | **OFF** (skill knows its own tools) | Reduces prompt overhead. |
| Self-introspection | **ON** | "How am I doing? Budget left?" relevant. |
| Registry search | OFF | Skills don't delegate. |
| Self-modification | OFF | Skills don't synthesise. |
| Reflection | **MINIMAL** ("run-scoped" only) | Skills do one job; entity-level reflections rare. |

Skills are where **Voyager-style skill promotion** lands: if a chain of
ad-hoc TOOL_CALLs gets repeated 5+ times, the platform proposes promoting
it to a real SKILL entity.

### 3.3 AGENT (3-10 steps, autonomous-capable)

| Meta-cognition | Recommended | Why |
|----------------|-------------|-----|
| Platform awareness | **ON** | Needs to know its tool surface. |
| Self-introspection | **ON** | Critical for autonomous loop. |
| Registry search | **OPT-IN** (default OFF) | Only delegate if entity is genuinely a meta-orchestrator. Default off prevents sprawl. |
| Self-modification | **OPT-IN** (default OFF) | Only the Meta-Agent should create new entities by default. |
| Reflection | **ON** | This is the heart of autonomy. |
| Self-questioning (NEW) | **ON** | Allowed to ask user via `UncertaintySignal`. |

### 3.4 PROCESS (orchestrator with children)

| Meta-cognition | Recommended | Why |
|----------------|-------------|-----|
| Platform awareness | **ON** | Knows its children + tools. |
| Self-introspection | **ON** | |
| Registry search | **ON** (PROCESS *should* be able to find replacements for missing children) | Useful for repair workflows. |
| Self-modification | **OPT-IN** | Default off; opt-in for "self-healing PROCESS." |
| Reflection | **ON** | |
| Child-feedback aggregation (NEW) | **ON** | Reads `StepHealthRecord`s of children to decide whether to re-invoke / replace. |
| Cross-child memory | **ON** | Already works via shared CORTEX tree; should be documented in the contract. |

### 3.5 Concrete fix: change the default in `resolve_meta_cognition`

```python
# meta/platform_schema_compiler.py (proposed)

def resolve_meta_cognition(entity) -> Dict[str, Any]:
    ...
    # Tier 2: registry_search — OPT-IN (NOT auto-on for AGENT/PROCESS)
    if "registry_search" not in explicit:
        config["registry_search"] = False   # was: entity_type in (AGENT, PROCESS)

    # Tier 3: self_modification — RESERVED for Meta-Agent unless opted-in
    if "self_modification" not in explicit:
        is_meta = (entity.metadata_extensions or {}).get("is_meta_agent", False)
        config["self_modification"] = is_meta
```

This is a **one-line behaviour change** that closes a meaningful sprawl
vector (F-13).

---

## 4. Per-hierarchy-level "meta abilities" (NEW)

Beyond meta-cognition flags, each level deserves a small set of
*introspection tools*:

```python
# tools/meta/agent_introspect.py  (NEW)
class AgentIntrospectTool(Tool):
    """
    Lets the agent ask, mid-loop:
      - what's my budget remaining?
      - what is my current viewport node id?
      - what intelligence rules apply right now?
      - what failures has this entity had in the last 7 days?
    """
```

```python
# tools/meta/agent_reflect.py  (NEW)
class AgentReflectTool(Tool):
    """
    Persists a structured reflection from the current step into:
      - run-scoped state (next iteration's perception)
      - entity-scoped Intelligence Tree (status=candidate)
    """
```

These are **opt-in** capabilities. Together with the AgentLoop they make
agents *introspective* without needing engine-side magic.

### 4.1 Meta-abilities matrix

| Ability | ACTION | SKILL | AGENT | PROCESS |
|---------|--------|-------|-------|---------|
| Read budget | – | r/o | r/o | r/o |
| Read viewport | – | r/o | r/w | r/w |
| Read intelligence rules | – | r/o | r/o | r/o |
| Write reflection | – | – | yes | yes |
| Propose skill promotion | – | – | yes | yes |
| Request HITL clarification | – | yes | yes | yes |
| Request budget extension | – | – | yes | yes (subject to HITL) |
| Delegate to sibling | – | – | – | yes |
| Spawn child entity | – | – | – | yes |
| Synthesise tool (advanced) | – | – | – | yes (Meta-Agent only) |

---

## 5. The dynamic-planner / reviewer / meta-cognition triangle

These three subsystems must *talk to each other* via the Intelligence Tree:

```
   PlanGenerator
       │   writes plan candidate
       ▼
   IntelligenceTree
       ▲           ▲
       │           │ reads rules
       │ writes    │
       │ tags      │ writes verdicts
       │           │
   CriticPipeline    Strategist (meta-cognition)
       │
       └─ executes Plan
       └─ records outcomes
       └─ Reflector closes the loop
```

Today the three are **siloed**:

* PlanGenerator never sees Critic verdicts.
* Critic never sees plan-style priors.
* Strategist (implicit) never sees either.

§03's AgentLoop with §05's CriticPipeline and Intelligence Tree integration
removes those silos.

---

## 6. Quick wins in this domain (≤2 weeks each)

1. **Critic on different model** — single config knob in `_review_step_output`
   to pick a `critic_model_override`. Default: stronger than actor model.
2. **Structured failure tags** — add `tags: List[str]` to the critic JSON
   schema; map to a closed enum.
3. **Critic budget cap** — read `governance.critic_cost_share_pct` (default
   20%); skip review when exceeded.
4. **Plan invariants** — `validate_plan` runs after `reconcile`; failures
   bounce to one re-plan attempt before execution.
5. **`resolve_meta_cognition` defaults** — flip `self_modification` and
   `registry_search` to opt-in (with migration to preserve existing
   opted-in entities).
6. **Intelligence rules into planner prompt** — `_generate_dynamic_plan`
   already injects platform manifest; add `intelligence_rules` retrieval.

These six together would lift the platform from "intelligent on a good
day" to "consistently intelligent."

---

## 7. KPI definitions (so we can measure if it worked)

Define metrics per entity-class, weekly:

| Metric | Formula |
|--------|---------|
| Goal-hit rate | runs marked complete AND no refinement / OK_OUTPUT user flag / Σ runs |
| Plan adherence | (steps actually executed ∩ planned) / (steps planned) |
| Re-plan rate | runs with ≥1 adapt_plan call / runs |
| Critic catch rate | Σ post_critic_verdict ∈ {REVISE, REJECT} / Σ steps |
| False-pass rate | (PASS critic verdicts → run flagged bad later) / PASS verdicts |
| Cost per success | Σ cost_usd / goal_hit_count |
| Budget overshoot rate | runs with `pressure > 1.0` / runs |
| Reflection persistence | new Intelligence rules per 100 runs |

Without these, every improvement is anecdotal.
