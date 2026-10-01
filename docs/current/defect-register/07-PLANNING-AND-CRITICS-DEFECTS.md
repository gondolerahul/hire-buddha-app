# 07. Planning, Critics & Self-Correction — Defect Register

> **What this document is:** defects in how the platform makes a plan, checks its own
> work, and recovers from failure — plus the improvements that would make criticism
> cheaper and self-correction actually correct something.
> **Source document:** [`07-planning-and-critics.md`](../07-planning-and-critics.md)
> **Compiled:** 2026-09-01, against branch `fresh-main`.
> **Context:** this subsystem spends real money on every iteration. Several of the
> defects below mean the platform is **paying for a critic whose verdict is thrown
> away**.

> **2026-10-01 — consolidated.** This register is now worked through
> [`CONSOLIDATED-KERNEL-TOOLS-PLAN.md`](CONSOLIDATED-KERNEL-TOOLS-PLAN.md), which merges
> registers 05, 06, 07, 09, 10, 11, TOOL-LAYER and PO-06 into one deduplicated list,
> adds the six-level hierarchy (R1) and the skill-first tool stack (R2), and orders the
> fixes in phases. Use the canonical id from its merge map in commits; status lines here
> are still updated as fixes land.

---

## How to read this file

- **✅ Verified** — the code was read on 2026-09-01 and the claim held.
- **📄 Doc-reported** — from `07-planning-and-critics.md`, not independently re-checked.
- The pattern to hold in mind: four critic stages exist, three of them produce a verdict
  the loop does not act on, and all four are billed. That is the shape of most of
  [§2](#2-t0--paying-for-criticism-that-is-discarded).

---

## Contents

1. [Summary](#1-summary)
2. [T0 — Paying for criticism that is discarded](#2-t0--paying-for-criticism-that-is-discarded)
3. [T1 — Self-correction that does not correct](#3-t1--self-correction-that-does-not-correct)
4. [T2 — Built and never wired](#4-t2--built-and-never-wired)
5. [T3 — Planning correctness](#5-t3--planning-correctness)
6. [Improvements](#6-improvements)
7. [Suggested order of work](#7-suggested-order-of-work)

---

## 1. Summary

| Tier | Theme | Count | When to do it |
|---|---|---|---|
| [T0](#2-t0--paying-for-criticism-that-is-discarded) | Paying for criticism that is discarded | 5 | Now — this is money per run |
| [T1](#3-t1--self-correction-that-does-not-correct) | Self-correction that does not correct | 5 | Before claiming the platform self-corrects |
| [T2](#4-t2--built-and-never-wired) | Built and never wired | 6 | Each is a decision: wire it or delete it |
| [T3](#5-t3--planning-correctness) | Planning correctness | 10 | When the area is next touched |

**Total: 26 defects, 10 improvements.** (PC-26 was found on 2026-10-01.)

The three to read first:

- **[PC-01](#pc-01--the-pre-critic-is-skipped-on-almost-every-iteration)** — the gate in
  front of every action passes automatically on the normal path.
- **[PC-06](#pc-06--every-retry-strategy-executes-identically)** — seven retry
  strategies are chosen, logged, and then all executed the same way.
- **[PC-03](#pc-03--alignment-drift-is-measured-and-discarded)** — goal drift is
  detected, a correction hint is written, and the loop drops it.

---

## 2. T0 — Paying for criticism that is discarded

### PC-01 — The pre-critic is skipped on almost every iteration

**✅ Verified · High**

```python
if move.plan_fragment:
    pre_verdict = PreCriticVerdict(kind="PASS")
else:
    pre_verdict = await self.critic_pipeline.pre_action(move, state)
```

Any move carrying a plan fragment gets a synthetic `PASS`. On a plan-driven run that is
every iteration.

The comment explains why, and the reasoning is sound: the deterministic Strategist
re-proposes the *identical* move each iteration, so one genuine `BLOCK` becomes three
consecutive blocks and trips the circuit breaker with zero work done. The bypass was a
fix for a real incident.

But the outcome is that the safety gate in front of every action is disabled on the path
that covers nearly all actions, and the code still reads as though it is enabled.

- [`ai/core/agent_loop.py:457`](../../../backend/src/ai/core/agent_loop.py:457)

**Fix:** the underlying problem is that a blocked move is re-proposed unchanged. Make a
`BLOCK` mutate the move — or mark the step so the strategist proposes something else —
and the bypass is no longer needed.

---

### PC-02 — `REVISE` from the pre-critic does nothing

**📄 Doc-reported · Medium**

The loop branches only on `BLOCK`. A `REVISE` verdict — the critic saying "this is
nearly right, change it like this" — is produced, billed, and ignored.

So the pre-critic is effectively a binary gate with three declared outcomes.

- [`ai/core/agent_loop.py`](../../../backend/src/ai/core/agent_loop.py) — phase 3

---

### PC-03 — Alignment drift is measured and discarded

**📄 Doc-reported · High**

`AlignmentVerdict.correction_hint` is populated by the alignment critic and dropped on the
AgentLoop path. Only the legacy step engine acts on drift, through
`__alignment_correction__`.

So on the live path the platform pays an LLM call to detect that the agent has wandered
off goal, records the number, and then does nothing about it.

Worse, `AlignmentVerdict` has **no cost field**, so alignment cost never reaches
`run.total_cost_usd` either. The call is billed to the provider and invisible in the
platform's own accounting.

- [`ai/planning/critic_pipeline.py`](../../../backend/src/ai/planning/critic_pipeline.py) — `alignment`
- [`ai/core/agent_loop.py`](../../../backend/src/ai/core/agent_loop.py) — the caller that drops the hint

---

### PC-04 — The post critic never sees intelligence rules

**✅ Verified · Medium** · **Status: fixed (2026-09-28)** — the loop passes its
`RunMemory` as `intelligence_reader`, and the post critic renders
`RunMemory.top_rules`. See
[MC-03](08-MEMORY-AND-CORTEX-DEFECTS.md#mc-03--intelligence-rules-are-distilled-and-never-consumed).

`_build_real_critic_pipeline` passes `intelligence_reader=None`, with the comment
`# wired in Track 6`.

`CriticPipeline` accepts the reader, stores it, and passes it to the supervisor. With it
`None`, `intel_rules` renders as `"(none)"` in every critic prompt.

The IntelligenceTree — where `CriticCalibrator` writes its weekly false-pass and
false-fail findings — is therefore write-only from the critic's point of view. The
platform learns and then does not read what it learned.

- [`ai/core/agent_loop.py:930`](../../../backend/src/ai/core/agent_loop.py:930) — `intelligence_reader=None`
- [`ai/planning/critic_pipeline.py:241`](../../../backend/src/ai/planning/critic_pipeline.py:241)

---

### PC-05 — `DEGRADED` mode still runs the post critic

**📄 Doc-reported · Medium**

The budget guard switches to `CriticMode.DEGRADED` when
`critic_cost / run_cost > critic_cost_share_pct`. The module docstring says degraded mode
runs a "minimal post" critic. It runs the full one.

So the cost control that exists to stop criticism eating the run's budget does not
actually reduce the most expensive stage.

- [`ai/planning/critic_pipeline.py`](../../../backend/src/ai/planning/critic_pipeline.py) — `_budget_mode`

Note also that the threshold `governance.critic_cost_share_pct` is **not a declared
Pydantic field**, so it cannot be set through the API — see
[PC-16](#pc-16--every-critic-knob-in-governance-is-undeclared).

---

## 3. T1 — Self-correction that does not correct

### PC-06 — Every retry strategy executes identically

**✅ Verified · High**

`pick_retry` chooses between seven strategies:

| Strategy | What it is supposed to change |
|---|---|
| `RETRY_AS_IS` | nothing |
| `RETRY_DIFFERENT_TOOL` | use the fallback tool |
| `RETRY_DIFFERENT_PROMPT` | rewrite the prompt |
| `RETRY_DIFFERENT_MODEL` | escalate to a stronger model |
| `ASK_USER` | pause for clarification |
| `ABANDON` | stop |
| `NONE` | no retry needed |

The choice is made, logged, and emitted as an `agent.retry.picked` event. Then
`_move_from_retry` rehydrates the queued retry into a `Move`:

```python
return Move(
    move_id=...,
    goal_id=state.current_goal_id(),
    executor=queued.get("executor", "SingleStep"),
    plan_fragment=plan_fragment,
    rationale=queued.get("rationale", "queued retry"),
)
```

`force_model_escalation`, `prompt_rewrite_hint`, `use_fallback_tool` and `ask_user` are
all dropped. **Every queued retry behaves like `RETRY_AS_IS`** — the same tool, the same
prompt, the same model.

So the platform diagnoses *why* a step failed, picks the right remedy, and then retries
identically. The retry telemetry in the UI shows a strategy that was never applied.

- [`ai/core/agent_loop.py:1464`](../../../backend/src/ai/core/agent_loop.py:1464) — `_move_from_retry`
- [`ai/planning/retry_strategies.py`](../../../backend/src/ai/planning/retry_strategies.py) — `pick_retry`

**Fix:** carry the strategy fields onto the `Move` and have the executor honour them.
This is the single highest-value change in this register.

---

### PC-07 — There is no retry backoff

**✅ Verified · Medium**

`LogicGate.retry_policy` — with `max_retries`, `backoff_strategy` and `retry_on` — is
schema-only. Nothing reads it (see
[EP-05](06-EXECUTION-PIPELINE-DEFECTS.md#ep-05--eight-settings-in-the-builder-have-no-runtime-reader)).

Retries are immediate. Against a rate-limited API — the most common transient failure —
an immediate retry is the one thing guaranteed not to work.

---

### PC-08 — `FailureTag.severity` is dead

**📄 Doc-reported · Low**

`pick_retry` branches on tag identity, not severity. The severity field is populated by
the critic and never consulted, so a `CRITICAL` hallucination and a `LOW` formatting
wobble follow the same path if they carry the same tag.

---

### PC-09 — `REPLAN` clears completed step ids for dynamic entities

**📄 Doc-reported · Medium**

The wipe is guarded for static-plan entities only. A dynamic-plan entity whose supervisor
recommends `REPLAN` really does restart its plan from scratch, re-running and re-paying
for work already done.

Same defect as [AK-17](05-AGENT-KERNEL-DEFECTS.md#ak-17--_handle_replan-wipes-completed-step-ids-for-dynamic-plans),
recorded here because the trigger lives in the supervisor.

---

### PC-10 — Only one of `GoalGuard`'s four actions is reachable

**📄 Doc-reported · Medium**

`MetaReviewer`, `GoalGuard` and `AlignmentCritic` are all shims over the new pipeline.
Only `GoalGuard` has a live caller, and only its `RETRY` branch is reachable — the other
three actions cannot fire.

Three classes remain in the tree looking like working components. Two have no live caller
at all.

- [`ai/planning/goal_guard.py`](../../../backend/src/ai/planning/goal_guard.py)
- [`ai/core/meta_review.py`](../../../backend/src/ai/core/meta_review.py)

---

## 4. T2 — Built and never wired

Everything here is complete: the code, the maths, the migration and the tests. What is
missing is a production call site.

| ID | Component | State | Status |
|---|---|---|---|
| **PC-11** | `TrustLearner` + `source_trust_scores` | Beta-posterior trust learning per knowledge source. Table, migration, maths and unit tests all shipped. Grep finds `TrustLearner` referenced **only from its own module and its test**. The flag `memory.trust_score_learning` defaults `False` | ✅ Verified |
| **PC-12** | `FailurePatternService` | Mines an entity's recent failures into prompt-injectable warnings, with seven classifiers. Its own docstring says "Usage (from `worker.py`)" — `worker.py` no longer contains that call. **Zero production callers** | ✅ Verified |
| **PC-13** | `PlanGenerator.replan` | **No callers.** Re-planning goes through `PlannerService.adapt_plan`, which passes `entity=None` and therefore disables three of the eight plan invariants and skips billing the replan tokens | ✅ Verified |
| **PC-14** | `PlanGenerator` telemetry | Always constructed as `PlanGenerator(llm_router=..., db=...)` with no `emit_event`, so **no `agent.plan.*` event ever fires**. Planning is invisible in the trace | ✅ Verified |
| **PC-15** | Six of eight bandit arms | `PlanStyleBandit` declares eight plan styles. The selection path only ever decides `DAG_PARALLEL` vs `DAG_SEQUENTIAL`. The other arms are recorded in the table and never chosen | 📄 Doc-reported |
| **PC-26** | `cost_estimator_refresh` | The nightly cron (02:30, scheduled in `worker.py`) is meant to refresh `planning/cost_estimator.py`'s per-tool baselines from telemetry. Its SQL reads `tool_interaction_logs.cost_usd`, which has never existed. Tool cost lives in `usage_logs`. Every run raises `column "cost_usd" does not exist`, the job logs `cost_estimator_refresh error` and returns, and the estimator keeps its seeded constants forever | ✅ Verified · **fixed (2026-10-01)** — deleted, with its cron. Tool calls are charged a fixed price each, so a per-tool median only restates the price the estimator already reads from `ToolCostResolver` (BC-11); the job never persisted anything (the `refresh_from_db` its docstring cites does not exist); and the run's credit hold already averages the entity's recent bills. The estimator's keys were fixed with it (TL-64) |

---

## 5. T3 — Planning correctness

### PC-16 — Every critic knob in `governance` is undeclared

**✅ Verified · Medium** · **Status: fixed (2026-09-29, `3fadd76`)** — all four are declared
with the runtime's defaults, and a typo is now a 422 (PO-09).

`critic_cost_share_pct`, `goal_validation_interval`, `meta_review_interval` and
`review_mechanism.critic_model_override` are all read by the runtime and have **no
Pydantic field**.

Because the entity schema is closed and drops unknown keys silently, setting any of them
through the API is a no-op that returns `200 OK`. A typo fails the same silent way.

These are the four knobs you would reach for to tune critic cost — the most expensive
part of a run — and none of them can be set.

---

### PC-17 — Two different `goal_validation_interval` settings

**📄 Doc-reported · Medium**

One lives in `governance` (read by the AgentLoop, default 2). The other lives in
`logic_gate.reasoning_config` (read by the legacy step engine; the schema default is 2
but the raw dict is read as 0, i.e. off).

Only the governance one affects the live loop. Setting the other has no effect, and both
appear in the builder.

---

### PC-18 — `_assign_step_ids` breaks the LLM's own placeholders

**📄 Doc-reported · High** · **Status: fixed (2026-10-01)** — `assign_step_ids` rewrites
`{{old}}` / `{{old.…}}` placeholders in every string and `target.input_dependencies` in
the same pass as the ids. The new face held: the dependencies were not rewritten either,
so a dependent step never became ready. Test: `tests/unit/test_step_ids.py`.

The planner asks the LLM for a plan whose steps reference each other with `{{step_1}}`
placeholders. `_assign_step_ids` then rewrites **every** generated `step_id`.

The placeholders still say `{{step_1}}`; the step is now called something else. So on the
dynamic-planning path, inter-step references silently stop resolving and downstream steps
run with missing input.

- [`ai/planning/plan_generator.py`](../../../backend/src/ai/planning/plan_generator.py) — `_assign_step_ids`

**Fix:** rewrite the placeholders in the same pass that rewrites the ids.

---

### PC-19 — One plan invariant fails for every tool-bearing entity

**📄 Doc-reported · Medium** · **Status: fixed (2026-10-01)** — `declared_tool_ids`
normalises `{"tool_id": …}` dicts and bare ids; the invariant and the Meta board
validator's `_all_tools_listed` (same bug) both use it. Test:
`tests/unit/test_plan_invariants.py`.

`all_required_tools_in_capabilities` stringifies tool dicts before comparing them. For a
real entity — whose `capabilities.tools` is a list of `{"tool_id": ...}` dicts, not
strings — the comparison never matches, so the invariant fails for exactly the entities it
exists to protect.

- [`ai/planning/plan_invariants.py`](../../../backend/src/ai/planning/plan_invariants.py)

---

### PC-20 — `adapt_plan` disables three invariants and skips billing

**✅ Verified · Medium**

`PlannerService.adapt_plan` calls the generator with `entity=None`. Three of the eight
invariants need the entity and are skipped. The replan's tokens are also not billed to the
run.

So a run that replans repeatedly gets progressively less-validated plans, for free — which
removes the cost signal that would otherwise discourage replan loops.

- [`ai/planning/planner_service.py:283`](../../../backend/src/ai/planning/planner_service.py:283)

---

### PC-21 — Bandit reward is run-level and blames every arm equally

**📄 Doc-reported · Medium**

All arms used in a failed run are penalised the same amount, and per-arm cost is computed
as the run total divided by the iteration count.

So an arm that was used once in a 40-iteration run that failed for an unrelated reason
takes a full penalty. With ε-greedy selection over a small number of runs, that is enough
to push a good arm out of contention permanently.

- [`ai/planning/plan_style_bandit.py`](../../../backend/src/ai/planning/plan_style_bandit.py)

---

### PC-22 — Calibration groups by a key the bandit does not use

**📄 Doc-reported · Medium**

`CriticCalibrator` buckets by `entity_id` plus a `task_class` derived as
`entity_type:{type}` or `run:{execution_mode}`. The bandit keys on `state.task_class`,
which is produced by the task classifier.

The two grouping keys do not line up, so calibration findings and bandit statistics can
never be joined. The write is also duck-typed — it looks for `upsert_calibration_rule`,
then `record_rule`, and logs-and-returns if neither exists.

- [`ai/planning/critic_calibration.py:73`](../../../backend/src/ai/planning/critic_calibration.py:73)

---

### PC-23 — Parallel plan candidates broke the run's database session

**✅ Verified · High** · **Status: fixed (2026-09-28)** — found while testing the
deep-research process end to end.

`PlanGenerator._generate_candidates` ran each candidate as a coroutine under
`asyncio.gather`. Each candidate called the LLM, then logged `planner` usage.
`UsageService.log_usage` does `db.add(row)` plus `await db.commit()` on the **run's
shared `AsyncSession`**, and the three coroutines committed at the same time:

- one candidate's commit flushed another candidate's pending row, and the second insert
  failed with `duplicate key value violates unique constraint "usage_logs_pkey"`;
- or SQLAlchemy refused the second commit (`Method 'commit()' can't be called here;
  method '_prepare_impl()' is already in progress`).

`log_llm_response_usage` swallowed the error at `DEBUG` level, so the only visible
symptoms were downstream. Five of the six usage rows for a three-candidate plan were
lost, and the session was left in a failed transaction. The next query in
`PlannerService.reconcile` then raised, it logged `PlanGenerator reconcile failed;
falling back to static`, and an entity with no static plan — the deep-research director
— got an **empty plan and did nothing**. The run later died on the same
`IntegrityError` when the loop next committed.

- [`ai/planning/plan_generator.py`](../../../backend/src/ai/planning/plan_generator.py) — `_generate_candidates`
- [`ai/services/attributed_usage.py`](../../../backend/src/ai/services/attributed_usage.py) — the swallowed error

**Fix:** only the LLM calls run concurrently. Parsing and usage logging then run one
candidate at a time, in temperature order. A candidate whose LLM call raises falls back
to the static plan's steps and is not billed. A failed usage write now logs at
`WARNING`, because a lost usage row is a lost charge. Plain reads on a shared session
are safe — the asyncpg adapter serialises statements — so the router's concurrent
adapter lookup in the same `gather` was not part of the bug.

Verified against the local database. Before the fix, a three-candidate plan wrote 1 of its 6 usage
rows and raised the `commit()` state error; after it, all 6. A live deep-research run then
planned the director with no session error and every `planner` row written. It still did
no research, for a separate reason: every answer was truncated by thinking tokens
([LP-25](10-LLM-PROVIDERS-DEFECTS.md#lp-25--thinking-tokens-consume-max_tokens-so-short-calls-return-truncated-answers)).

---

### PC-24 — The dynamic planner is never told which children exist

**✅ Verified · High** · **Status: fixed (2026-09-29)** — found 2026-09-29 once LP-25 let
the deep-research director's plans come back complete. See the fix at the end of this
entry.

`_PLAN_SYSTEM` tells the model that `target.entity_id` "must be the EXACT child UUID from
the provided child roster". `PlanGenerator._build_prompt` never provides one: it sends
the goal, rules, anti-patterns and static plan, but no children. So on a static-less
router the model invents ids. Live, the research director's chosen plan targeted
`child_1234`, `child_5678` and `child_9012`, and dispatch failed with `Child invocation
missing entity_id for step Initial Data Collection`.

The safety net does not catch it. `PlannerService._maybe_enforce_router` should replace
a plan with no real child invocation, but it finds children through
`load_entity_children`, which reads **only** `hierarchy.children`. The deep-research
seed (`create_v2.py`) links its children through the `parent_id` column alone, so
`hierarchy` is `null`, the child list is empty, and enforcement returns the invented plan
unchanged. This is the same three-discovery-path split as
[EP-19](06-EXECUTION-PIPELINE-DEFECTS.md#ep-19--convert_to_template-misses-plan-only-children)
and [PO-I4](01-PRODUCT-OVERVIEW-DEFECTS.md#po-i4--make-the-template-clone-report-what-it-cloned).

- [`ai/planning/plan_generator.py`](../../../backend/src/ai/planning/plan_generator.py) — `_build_prompt`, no roster section
- [`ai/meta/platform_schema_compiler.py:718`](../../../backend/src/ai/meta/platform_schema_compiler.py:718) — `load_entity_children` reads only `hierarchy.children`

**Fix:**

- `load_entity_children` counts a child linked through `hierarchy.children` **or** its own
  `parent_id`, and excludes archived and deleted children. Router enforcement and the
  roster share it, so a `parent_id`-only seed is now enforced too.
- `PlannerService._child_roster` renders the roster with the existing, previously
  uncalled `describe_entity_children`. It passes the roster and the known child ids —
  live children plus any child the static plan already targets — in `PlanContext`.
  `_build_prompt` adds the roster after the goal.
- New invariant `child_invocations_target_known_children` rejects a candidate that
  invokes an unknown `entity_id`. A step carrying only an `entity_name_hint` is left to
  downstream resolution. When the roster could not be loaded the check is skipped.

Live: the same director's plan targeted the real research-gatherer, research-analyst and
report-writer ids, in that order, and the run delegated to them.

---

### PC-25 — The dynamic planner never sees the user's request

**✅ Verified · High** · **Status: fixed (2026-10-01)** — found 2026-09-29 on a live
deep-research run. `PlanContext.request` (`run_request(input_data)`) renders as
`## Request` in the plan prompt and the PlanJudge prompt, on reconcile and on replan.
Test: `tests/unit/test_plan_request.py`.

`PlanContext` carries `input_data`, but `PlanGenerator._build_prompt` never renders it.
The `## Goal` section is `ctx.goal`, which `PlannerService` fills with the **entity's**
standing goal. So every dynamic plan is made without knowing what this run was asked to
do.

Live: asked for "a short research brief on how long-term memory is designed in LLM agent
frameworks", the research director's plan passed the gatherer
`{"research_topic": "Produce a world-class, McKinsey-caliber research report by
orchestrating …"}` — its own goal, not the question. The children only got the question
because the loop forwards the run's `input` separately (and then lost it again, see
[EP-25](06-EXECUTION-PIPELINE-DEFECTS.md#ep-25--a-step-whose-template-omits-input-never-sees-the-task)).

- [`ai/planning/plan_generator.py`](../../../backend/src/ai/planning/plan_generator.py) — `_build_prompt`
- [`ai/planning/planner_service.py`](../../../backend/src/ai/planning/planner_service.py) — `_generate_dynamic_plan_v2` sets `goal=entity.goal`

**Fix:** render the run's request (`input_data["input"]`, internal keys stripped) as a
`## Request` section, and tell the model to pass it to child steps. The PlanJudge prompt
has the same gap.

---

## 6. Improvements

### PC-I1 — Make retries actually differ

**Effect: the largest win in this register.**
[PC-06](#pc-06--every-retry-strategy-executes-identically). All the diagnosis work is
already done and correct — `pick_retry` is a clean pure function with good logic. Only the
last step, carrying the decision into the `Move`, is missing.

Four fields on `Move` and four branches in the executor turn a decorative retry system
into a working one.

### PC-I2 — Charge alignment and give it an effect

**Effect: medium.** [PC-03](#pc-03--alignment-drift-is-measured-and-discarded). Two
changes: add a cost field to `AlignmentVerdict` so the spend is visible, and act on
`correction_hint` on the loop path the way the legacy engine did. Right now this stage is
pure cost.

### PC-I3 — Decide the critic budget properly

**Effect: large on cost.** Today the only cost control is the cost-share rule, which
switches to a `DEGRADED` mode that still runs the expensive stage
([PC-05](#pc-05--degraded-mode-still-runs-the-post-critic)). Make `DEGRADED` mean
something — skip the supervisor, use a cheaper model, or sample.

Then declare the knob ([PC-16](#pc-16--every-critic-knob-in-governance-is-undeclared)) so
a tenant can actually set it.

### PC-I4 — Wire `intelligence_reader`

**Effect: medium.** [PC-04](#pc-04--the-post-critic-never-sees-intelligence-rules). One
argument. The `CriticCalibrator` cron already runs weekly and writes findings into the
IntelligenceTree; nothing reads them back. Wiring the reader closes the loop and makes the
weekly job worth running.

### PC-I5 — Fix the placeholder rewrite

**Effect: medium.** [PC-18](#pc-18--_assign_step_ids-breaks-the-llms-own-placeholders).
This is a silent data-flow break on the dynamic-planning path — the hardest kind of bug to
notice, because the plan looks right and the steps run.

### PC-I6 — Emit planning telemetry

**Effect: medium.** [PC-14](#4-t2--built-and-never-wired). `PlanGenerator` has full event
support and is always constructed without it. Planning is currently a black box in the
trace: you can see the plan that came out, not how many candidates were generated, which
was chosen, or what it cost.

### PC-I7 — Cache the plan for repeat runs

**Effect: large on cost.** An entity run twice on similar input generates a fresh plan
each time, with the multi-candidate path costing several LLM calls. For entities with a
static plan this is pure waste; for dynamic ones, a cache keyed on
`(entity_id, entity_version, input_shape)` would cut planning cost sharply on the runs that
repeat — which for a campaign or a scheduled agent is most of them.

### PC-I8 — Decide the fate of the unwired learning surfaces

**Effect: medium.** [PC-11](#4-t2--built-and-never-wired) and
[PC-12](#4-t2--built-and-never-wired) are two complete learning systems with no callers,
plus a database table and a migration carried for one of them.

Both would improve results if wired: trust scores would let the memory layer down-weight
unreliable sources, and failure patterns would stop an entity repeating the same mistake.
Both should be finished or deleted; carrying them costs maintenance and reader confusion.

### PC-I9 — Attribute bandit reward per arm

**Effect: medium.** [PC-21](#pc-21--bandit-reward-is-run-level-and-blames-every-arm-equally).
Record which arm was active for which iterations and split the reward accordingly. With
per-iteration cost already tracked, the data is there.

### PC-I10 — One task-class key

**Effect: small, unlocks the rest.** [PC-22](#pc-22--calibration-groups-by-a-key-the-bandit-does-not-use).
Use `state.task_class` in the calibrator too. Then calibration, bandit statistics and
step-health records all group the same way and can be reported together.

---

## 7. Suggested order of work

| Step | Work | Why here |
|---|---|---|
| **1** | PC-I1 / PC-06 | Retries that actually differ. All the hard work is already done |
| **2** | PC-18 | The placeholder break — a silent data-flow bug on the dynamic path |
| **3** | PC-I4 / PC-04, PC-I6 / PC-14 | Two one-argument fixes: read intelligence rules, emit planning events |
| **4** | PC-I2 / PC-03, PC-I3 / PC-05, PC-16 | Make the alignment stage earn its cost, and make the critic budget real |
| **5** | PC-01 | Fix the pre-critic bypass properly, by making a `BLOCK` change the move |
| **6** | PC-I8 / PC-11, PC-12, PC-13 | Decide on the unwired components. Wire or delete, no third option |
| **7** | PC-I7 | Plan caching — the biggest cost reduction available in this subsystem |

---

## Where to go next

- [07 — Planning, critics & self-correction](../07-planning-and-critics.md) — the source
  document.
- [05 — Agent kernel](05-AGENT-KERNEL-DEFECTS.md) — AK-04 and AK-17 are the loop-side view
  of PC-01 and PC-09.
- [06 — Execution pipeline](06-EXECUTION-PIPELINE-DEFECTS.md) — EP-05 for the dead retry
  policy behind PC-07.
- [08 — Memory & CORTEX](08-MEMORY-AND-CORTEX-DEFECTS.md) — where PC-11's trust scores
  would be consumed.
- [11 — Meta-intelligence](11-META-INTELLIGENCE-DEFECTS.md) — the IntelligenceTree that
  PC-04 does not read.
