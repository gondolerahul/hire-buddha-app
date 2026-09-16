# 07. Planning, Critics & Self-Correction — Defect Register

> **What this document is:** defects in how the platform makes a plan, checks its own
> work, and recovers from failure — plus the improvements that would make criticism
> cheaper and self-correction actually correct something.
> **Source document:** [`07-planning-and-critics.md`](../07-planning-and-critics.md)
> **Compiled:** 2026-09-01, against branch `fresh-main`.
> **Context:** this subsystem spends real money on every iteration. Several of the
> defects below mean the platform is **paying for a critic whose verdict is thrown
> away**.

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
| [T2](#4-t2--built-and-never-wired) | Built and never wired | 5 | Each is a decision: wire it or delete it |
| [T3](#5-t3--planning-correctness) | Planning correctness | 7 | When the area is next touched |

**Total: 22 defects, 10 improvements.**

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

**✅ Verified · Medium**

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

---

## 5. T3 — Planning correctness

### PC-16 — Every critic knob in `governance` is undeclared

**📄 Doc-reported · Medium**

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

**📄 Doc-reported · High**

The planner asks the LLM for a plan whose steps reference each other with `{{step_1}}`
placeholders. `_assign_step_ids` then rewrites **every** generated `step_id`.

The placeholders still say `{{step_1}}`; the step is now called something else. So on the
dynamic-planning path, inter-step references silently stop resolving and downstream steps
run with missing input.

- [`ai/planning/plan_generator.py`](../../../backend/src/ai/planning/plan_generator.py) — `_assign_step_ids`

**Fix:** rewrite the placeholders in the same pass that rewrites the ids.

---

### PC-19 — One plan invariant fails for every tool-bearing entity

**📄 Doc-reported · Medium**

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
