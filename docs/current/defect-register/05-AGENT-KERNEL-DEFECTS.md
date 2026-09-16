# 05. The Agent Kernel — Defect Register

> **What this document is:** defects in the control loop itself — the perceive →
> strategise → critique → act → observe → reflect → decide cycle in
> `core/agent_loop.py` and the layers around it — plus the improvements that would make
> a run cheaper and more honest about what it did.
> **Source document:** [`05-agent-kernel.md`](../05-agent-kernel.md)
> **Compiled:** 2026-09-01, against branch `fresh-main`.
> **Context:** the kernel is the most expensive code in the platform. Every defect here
> costs either money per run or truthfulness in what the run reports.

---

## How to read this file

- **✅ Verified** — the code was read on 2026-09-01 and the claim held.
- **📄 Doc-reported** — from `05-agent-kernel.md`, not independently re-checked.
- A recurring shape in this file: **a layer was built, wired in, and then bypassed.**
  `Perception`, `blockers`, `hypotheses`, the pre-critic and the child cap are all fully
  implemented and all effectively inert. Read
  [§1.1](#11-the-three-root-causes) before picking up individual items.

---

## Contents

1. [Summary](#1-summary)
2. [T0 — The run reports the wrong thing](#2-t0--the-run-reports-the-wrong-thing)
3. [T1 — Built, wired, and inert](#3-t1--built-wired-and-inert)
4. [T2 — Delete or fix the name](#4-t2--delete-or-fix-the-name)
5. [T3 — Correctness and cost](#5-t3--correctness-and-cost)
6. [Improvements](#6-improvements)
7. [Suggested order of work](#7-suggested-order-of-work)

---

## 1. Summary

| Tier | Theme | Count | When to do it |
|---|---|---|---|
| [T0](#2-t0--the-run-reports-the-wrong-thing) | The run reports the wrong thing | 3 | Before anyone bills or reports on runs |
| [T1](#3-t1--built-wired-and-inert) | Built, wired, and inert | 7 | Each one is a decision: finish it or delete it |
| [T2](#4-t2--delete-or-fix-the-name) | Delete or fix the name | 5 | **Now** — free |
| [T3](#5-t3--correctness-and-cost) | Correctness and cost | 6 | Needs design |

**Total: 21 defects, 10 improvements.**

The three to read first:

- **[AK-01](#ak-01--a-run-where-every-step-failed-can-report-completed)** — status is
  decided by "no steps left to run", not "the steps worked".
- **[AK-04](#ak-04--the-pre-critic-almost-never-runs)** — the safety gate in front of
  every action is skipped on the path that covers nearly all iterations.
- **[AK-11](#4-t2--delete-or-fix-the-name)** — two event names differ by one word between
  publisher and map, so the browser never gets replan or resume frames.

### 1.1 The three root causes

Most of this file is a symptom of one of these. Fixing the three is a smaller job than
fixing the twenty-one.

| Cause | Description | Symptoms |
|---|---|---|
| **A** — The typed state was built but the dict bridge still drives everything | `AgentState` is the designed contract. In practice the per-step executors, the tool executor and the memory assembler all still take a plain `context_state: dict`, and the loop keeps both in sync by hand | AK-03, AK-05, AK-06, AK-16 |
| **B** — Layers were added without being made mandatory | The pre-critic, the child cap, the perceiver's rich fields and the executor flags were each added, then given a bypass so nothing broke on rollout. The bypass became the normal path | AK-04, AK-07, AK-08, AK-09 |
| **C** — Cost is tracked in three places and reconciled by `max()` | The loop's `Budget`, `run.total_cost_usd` written by nested step code, and `usage_logs` written by the critics. `_sync_budget_cost` pulls them together with `max()` at the end of each iteration, in an order that matters | AK-13, AK-14, AK-15 |

---

## 2. T0 — The run reports the wrong thing

### AK-01 — A run where every step failed can report `COMPLETED`

**✅ Verified · Critical**

`_final_status` decides the run's outcome like this:

```python
if state.all_subgoals_achieved() or (
    state.has_plan() and not state.plan_ready_steps()
):
    return RunStatus.COMPLETED.value
```

`plan_ready_steps()` returns the steps that are still *ready to run*. A step that ran and
failed is no longer ready. So a plan whose every step failed has no ready steps left, and
the run is stamped `COMPLETED`.

Step failures do land in `result_data["steps"]` and in the health records. They do **not**
reach the run status, which is the field the dashboards, the reports and the customer
see.

Consequence: runs that produced nothing are billed, reported as successes, and counted
in the execution-health success rate.

- [`ai/core/agent_loop.py:1477`](../../../backend/src/ai/core/agent_loop.py:1477) — `_final_status`
- Also recorded as **D-34** in the platform register

**Fix:** require that the plan's required steps actually succeeded. `PARTIAL_COMPLETE`
already exists and is exactly the right status for this case.

---

### AK-02 — The budget under-counts spend unless three separate syncs all fire

**✅ Verified · High**

Most spend never flows back through `ActionResult.cost_usd`. The nested step path bills
by mutating `run.total_cost_usd` **on its own session**, and the critic pipeline writes
`usage_logs` rows without touching the run's cost column at all.

The loop compensates at the end of every iteration with three operations that must run in
this exact order:

```python
state.budget.consume(usd=action_result.cost_usd, wall_s=...)
await self._sync_budget_cost(state)          # pulls run.total_cost_usd UP via max()
if iter_critic_cost > 0:
    state.budget.consume(usd=iter_critic_cost)
```

`_sync_budget_cost` uses `max()`, so adding critic cost *before* it silently discards the
critic spend. The ordering is load-bearing and nothing enforces it.

Any path that skips an iteration's bookkeeping — an exception, an early return —
leaves the budget believing the run is cheaper than it is, and the cost cap does not
fire.

- [`ai/core/agent_loop.py:670`](../../../backend/src/ai/core/agent_loop.py:670)–688
- [`ai/core/agent_loop.py:838`](../../../backend/src/ai/core/agent_loop.py:838) — `_sync_budget_tokens`

**Fix:** one write path for cost. Every spender writes an attributed `usage_logs` row and
the budget reads the sum. Cause **C** above.

---

### AK-03 — A suspended run skips finalisation entirely

**✅ Verified · High**

When a run suspends to wait on children, `_drive` returns **before** `_finalize_bandit`,
the dreaming trigger, `_persist_final` and billing settlement.

That is correct for a run that will be resumed. It is wrong for a run that never is —
and a run can fail to resume for several reasons: the child's `resume_parent_run`
enqueue fails, the worker dies, Redis loses the job.

The run then sits in `WAITING_ON_CHILDREN` forever: never settled, never billed, never
reported as failed, and invisible to any "failed runs" query.

- [`ai/core/agent_loop.py:227`](../../../backend/src/ai/core/agent_loop.py:227) — the early return

**Fix:** a sweeper that finds runs stuck in `WAITING_ON_CHILDREN` past their timeout and
finalises them as `FAILED`. `resume_parent_run` is already idempotent, so a late resume
after the sweep is harmless.

---

## 3. T1 — Built, wired, and inert

Each of these reads as a working control. None of them is one. Every item is a decision:
**finish it or delete it** — but do not leave it looking functional.

### AK-04 — The pre-critic almost never runs

**📄 Doc-reported · High**

The pre-critic is the gate that inspects a proposed action *before* it is executed. Any
move carrying a `plan_fragment` is given a synthetic `PASS` instead.

In practice every plan-driven iteration carries a plan fragment. So the pre-critic only
ever sees `Recursive` moves and no-fragment `SingleStep` moves — a small minority of
iterations.

The safety gate in front of every action is skipped on the path that covers nearly all
actions.

- [`ai/planning/critic_pipeline.py`](../../../backend/src/ai/planning/critic_pipeline.py)
- [`ai/core/agent_loop.py`](../../../backend/src/ai/core/agent_loop.py) — phase 3

---

### AK-05 — `Perception` is written every iteration and read by nothing

**✅ Verified · Medium**

`state.perception = perception` is assigned at `agent_loop.py:422`. Grepping the whole
kernel for any other read returns only the module docstring telling new code to use it.

`Strategist.next_move` accepts a `perception` argument and ignores it.
`Perception.to_prompt_block()` has no production caller.

So the platform pays for building a perception object every iteration and then throws it
away.

- [`ai/core/agent_loop.py:422`](../../../backend/src/ai/core/agent_loop.py:422) — the only write
- [`ai/core/perceiver.py`](../../../backend/src/ai/core/perceiver.py)
- [`ai/core/strategist.py`](../../../backend/src/ai/core/strategist.py) — `next_move`

---

### AK-06 — The Perceiver's richest fields are always empty

**📄 Doc-reported · Medium**

The loop passes `memory_assembler=None`, and nothing ever sets `state.cortex_cursor`. So
on every real run:

| Field | Value in production |
|---|---|
| `viewport_text` | `""` |
| `intelligence_rules` | `[]` |
| `similar_past_runs` | `[]` |

Those three are the entire point of the Perceiver — they are what would let an agent
benefit from memory and from what previous runs learned. Together with
[AK-05](#ak-05--perception-is-written-every-iteration-and-read-by-nothing) it means the
memory system is wired to the loop and contributes nothing to it.

- [`ai/core/perceiver.py`](../../../backend/src/ai/core/perceiver.py)

---

### AK-07 — The child concurrency cap does not cap anything

**✅ Verified · High**

`within_child_dispatch_cap` is computed, the result is logged, and then the executor
dispatches anyway. The code says so:

```python
if not within_child_dispatch_cap(state, governance):
    # The cap is now advisory: with the inline backpressure path retired,
    # we dispatch anyway and let the child queue absorb the fan-out.
    logger.info("Child dispatch cap reached for parent %s (%d in flight); dispatching anyway.", ...)
```

`max_concurrent_children` is configurable in the entity builder's Safeguards tab and
enforces nothing. The default is 8, and a `PROCESS` with 50 children will dispatch all 50
at once.

The queue that was supposed to absorb the fan-out —
`CHILD_RUN_QUEUE` — is also not routed. See
[SA-07](02-SYSTEM-ARCHITECTURE-DEFECTS.md#sa-07--the-child-run-queue-is-declared-and-not-used).
So both halves of the fan-out control are inactive.

- [`ai/core/executors/child_entity.py`](../../../backend/src/ai/core/executors/child_entity.py) — `within_child_dispatch_cap` and the advisory branch
- Also recorded as **D-13** in the platform register

---

### AK-08 — `state.blockers` is written by a branch that cannot be reached

**✅ Verified · Medium**

`blockers` is appended only by `apply_observation`, and only when
`observation.outcome == "blocked"`. `Observer._outcome` can only return `success`,
`partial` or `fail`.

So the list is always empty. The SupervisorCritic renders blockers into its prompt and
therefore always sees none — it is reasoning about a run with a permanently blank field
that was meant to tell it what is stuck.

- [`ai/core/agent_state.py:346`](../../../backend/src/ai/core/agent_state.py:346) — the append
- [`ai/core/observer.py`](../../../backend/src/ai/core/observer.py) — `_outcome`
- [`ai/planning/supervisor_critic.py:203`](../../../backend/src/ai/planning/supervisor_critic.py:203) — the consumer

---

### AK-09 — `state.hypotheses` is never written by anything

**✅ Verified · Low**

`hypotheses` is declared on `AgentState`, serialised into every snapshot, and
deserialised on restore. Nothing ever appends to it.

It costs a little snapshot size and a lot of reader confusion.

- [`ai/core/agent_state.py:190`](../../../backend/src/ai/core/agent_state.py:190)

---

### AK-10 — Five feature flags are declared and read nowhere

**✅ Verified · Medium**

| Flag | Default | Read by |
|---|---|---|
| `agent_loop.perception_bounded_viewport` | `True` | nothing |
| `agent_loop.snapshot_every_iteration` | `True` | nothing |
| `agent_loop.executor_dialog_enabled` | `False` | nothing |
| `agent_loop.executor_skill_enabled` | `False` | nothing |
| `agent_loop.executor_tool_burst_enabled` | `False` | nothing |

All five appear in the admin Feature Flags page. Toggling any of them does nothing at
all. An operator turning `snapshot_every_iteration` off to reduce write load will see no
change and no error.

- [`ai/core/feature_flags.py:41`](../../../backend/src/ai/core/feature_flags.py:41)–45

**Fix:** delete them, or wire them. Adding a flag is not the same as adding a control —
the same lesson as `tools.cost_resolver_v2_enabled` in the tool layer.

---

## 4. T2 — Delete or fix the name

| ID | Problem | Notes | Status |
|---|---|---|---|
| **AK-11** | **Two SSE event names do not match, so the UI never sees them** | The map has `agent.loop.resume` and `agent.loop.replan`. The loop emits `agent.loop.resumed` (line 308) and `agent.replan.triggered` (line 1414). Neither `resume` nor `replan_triggered` frames ever reach the browser, so the live trace silently omits both events | ✅ Verified |
| **AK-12** | `Budget.can_afford` is fully implemented with zero call sites | The `budget.py` module docstring claims "Strategist consults `pressure` and `can_afford`". It consults only `pressure` | ✅ Verified |
| **AK-13** | The `budget.py` docstring says the critic self-skips on pressure | It does not. The critic degrades on a **cost-share** rule (`critic_cost / run_cost > 0.20`), not on budget pressure. Anyone tuning cost from the docstring will tune the wrong knob | 📄 Doc-reported |
| **AK-14** | `core/README.md` documents two files that do not exist | It lists `execution_engine.py` as "still reachable when `agent_loop.enabled=false`" and `recursive_engine.py` as a supporting service. Neither file exists; neither does the flag. `worker.py`'s docstring repeats the same stale reference | ✅ Verified |
| **AK-15** | `RunStatus.REPAIRING` is unreachable | No other status lists it as an allowed target, so nothing can enter it | 📄 Doc-reported |

---

## 5. T3 — Correctness and cost

### AK-16 — A pre-critic `BLOCK` still burns an iteration and a critic call

**📄 Doc-reported · Medium**

`budget.consume(iter_step=True)` runs **before** the pre-critic. So three consecutive
blocks — the circuit-breaker threshold — cost three iterations *and* three critic LLM
calls before the breaker trips and the run aborts.

The mechanism designed to stop waste is itself one of the more expensive paths in the
loop.

- [`ai/core/agent_loop.py`](../../../backend/src/ai/core/agent_loop.py) — phase 3

---

### AK-17 — `_handle_replan` wipes completed step ids for dynamic plans

**📄 Doc-reported · Medium**

The wipe is guarded for static-plan entities. A **dynamic**-plan entity whose supervisor
keeps recommending `REPLAN` loses its record of completed steps each time, and re-runs
work it has already paid for.

That is a compounding cost: each replan makes the next iteration more expensive, which
makes budget pressure rise, which makes the supervisor more likely to intervene again.

- [`ai/core/agent_loop.py`](../../../backend/src/ai/core/agent_loop.py) — `_handle_replan`

---

### AK-18 — Two of three executors share the loop's database session

**📄 Doc-reported · Medium**

`SingleStepExecutor` opens its own `AsyncSessionLocal` specifically because using the
loop's shared session can corrupt it. `DAGExecutor` and `ChildEntityExecutor` still use
the passed-in `db`.

So the problem was diagnosed, the fix was written, and it was applied to one of the three
places that has it.

A corrupted session surfaces as a `PendingRollbackError` several operations later, in
code that did nothing wrong.

- [`ai/core/executors/`](../../../backend/src/ai/core/executors/)

---

### AK-19 — `ChildEntity` moves are never retried

**📄 Doc-reported · Low**

Deliberate, and recorded here so it is not re-litigated: re-running a whole sub-agent on a
`REVISE` verdict is expensive and rarely changes the verdict.

The cost is that a child failing for a transient reason — a rate limit, a timeout — fails
the parent with no second attempt. A narrow retry on *transient* failure classes only
would be worth having.

---

### AK-20 — Child dispatch hard-fails without Redis

**✅ Verified · Medium**

`ChildEntityExecutor` returns an error when `redis is None`, because async dispatch is now
the sole child path — the inline fallback was deliberately retired to stop a
"~$11/child amplification".

That is the right trade. The consequence is that **any Redis blip fails every composite
entity**, and the error text ("child-entity dispatch requires Redis") reads like a
configuration problem rather than an outage.

- [`ai/core/executors/child_entity.py`](../../../backend/src/ai/core/executors/child_entity.py)

---

### AK-21 — The context bridge means two sources of truth for every value

**📄 Doc-reported · Medium**

`materialise_context_dict` copies state into a dict, the executors mutate the dict in
place, and `absorb_context_dict` copies it back. Budget pressure reaches the step prompt
by being written into `__agent_state__` and read back out by `step_executor`.

Every value that matters therefore exists in two forms, and they are reconciled once per
iteration. `INTERNAL_CONTEXT_KEYS` exists purely to stop loop plumbing leaking into an
LLM prompt through this path — which tells you how leaky it is.

The `agent_state.py` docstring is explicit that this is transitional. It is cause **A**
above.

- [`ai/core/agent_state.py`](../../../backend/src/ai/core/agent_state.py) — the two bridge methods
- [`ai/constants.py:31`](../../../backend/src/ai/constants.py:31) — `INTERNAL_CONTEXT_KEYS`

---

## 6. Improvements

### AK-I1 — One cost write path

**Effect: large.** Cause **C**. Today spend is recorded by the loop's `Budget`, by nested
step code mutating `run.total_cost_usd` on a different session, and by the critic pipeline
writing `usage_logs`. They are reconciled with `max()` in an order that is easy to break.

Make every spender write an attributed `usage_logs` row and nothing else. The budget then
reads a sum. This closes
[AK-02](#ak-02--the-budget-under-counts-spend-unless-three-separate-syncs-all-fire),
removes `_sync_budget_cost` entirely, and makes the cost dashboards agree with the run
row by construction.

### AK-I2 — Decide the fate of the Perceiver

**Effect: large, either way.** Right now the platform builds a `Perception` every
iteration, fills its three most valuable fields with empty values, assigns it to state,
and reads it nowhere ([AK-05](#ak-05--perception-is-written-every-iteration-and-read-by-nothing),
[AK-06](#ak-06--the-perceivers-richest-fields-are-always-empty)).

Two honest options:

1. **Finish it** — pass the memory assembler, set `cortex_cursor`, and feed
   `to_prompt_block()` into the strategist prompt. This is the feature that makes CORTEX
   worth its cost.
2. **Delete it** — remove the Perceiver, `Perception` and the assignment.

Doing neither is the expensive choice, because it keeps the maintenance cost of a memory
system whose output nothing consumes.

### AK-I3 — Make the pre-critic run on the path that matters

**Effect: medium.** [AK-04](#ak-04--the-pre-critic-almost-never-runs). The synthetic
`PASS` for plan-fragment moves was almost certainly a cost decision. If so, make it an
explicit sampling rule — critique one in N plan steps, or critique any step calling a
write-capable tool — rather than a blanket skip that reads like a bug.

### AK-I4 — Enforce or remove the child cap

**Effect: large under load.** [AK-07](#ak-07--the-child-concurrency-cap-does-not-cap-anything).
Enforcing it needs the dedicated child queue that `worker.py` already declares and does
not route. Two changes, one outcome: a fan-out `PROCESS` stops being able to starve every
other run in the system.

### AK-I5 — Stop building the state dict twice per iteration

**Effect: medium.** `materialise_context_dict` copies the whole context dict on every
iteration and `absorb_context_dict` copies it back. For a run with large step outputs
that is two full copies of everything the run has produced, per iteration, purely to
bridge two representations of the same data.

Cause **A**. The fix is the typed-state migration the docstring already promises.

### AK-I6 — Sweep runs stuck in `WAITING_ON_CHILDREN`

**Effect: medium.** [AK-03](#ak-03--a-suspended-run-skips-finalisation-entirely). One
cron, one query: runs in `WAITING_ON_CHILDREN` whose `started_at` is older than their
governance timeout. Finalise them as `FAILED` and settle. Without it, a lost resume is
invisible forever.

### AK-I7 — Cache the token rollup

**Effect: medium.** `_sync_budget_tokens` runs a **recursive CTE over the whole run
subtree** at the end of every iteration. For a deep `PROCESS` that is an increasingly
expensive query, repeated up to 50 times per run, to compute a number that only changes
when a child finishes.

Recompute it when a child folds in, not every iteration.

### AK-I8 — Make the iteration budget adaptive

**Effect: medium.** `max_iterations` is a flat 50 for every entity, from an `ACTION` with
one step to a `PROCESS` orchestrating three agents. The `ACTION` will never use its 50
and the `PROCESS` may need more.

Derive the ceiling from the plan size, and keep the flat number as an absolute backstop.

### AK-I9 — Emit one iteration event, not many

**Effect: small.** Every iteration publishes `iteration_start`, `budget_pressure`,
`executor_invoked`, `executor_completed`, up to four critic events, retry events and
`iteration_end` — each a separate Redis publish and a separate JSON serialisation.

Batching per iteration would cut publish volume several-fold with no loss of information
to the UI, which reduces them to one slice anyway.

### AK-I10 — Test the event-name contract

**Effect: small, prevents a recurring bug.**
[AK-11](#4-t2--delete-or-fix-the-name) is two typos that made two features invisible in
the UI with no error anywhere. A test asserting that every key in `_SSE_EVENT_TYPES`
matches a name actually emitted somewhere in `agent_loop.py` would catch it, and would
catch the next one.

---

## 7. Suggested order of work

| Step | Work | Why here |
|---|---|---|
| **1** | AK-11, AK-14 | Two typos and a stale README. Minutes each, and AK-14 is actively misleading every new reader |
| **2** | AK-01 | The run status must tell the truth before anything else is measured from it |
| **3** | AK-10, AK-12, AK-09 | Delete the five dead flags, `can_afford`, and `hypotheses`. Free |
| **4** | AK-I6 / AK-03 | The stuck-run sweeper. One cron, closes a silent-loss path |
| **5** | AK-I1 / AK-02 | One cost write path. The largest correctness win in the kernel |
| **6** | AK-I2 | Decide the Perceiver's fate. Do not defer this again — it is carrying cost either way |
| **7** | AK-I4 / AK-07 | Enforce the child cap, with the dedicated queue |
| **8** | AK-I5 / AK-21 | Finish the typed-state migration and delete the dict bridge |

---

## Where to go next

- [05 — The agent kernel](../05-agent-kernel.md) — the source document.
- [`DEFECT-REGISTER.md`](../DEFECT-REGISTER.md) — AK-01 is D-34, AK-07 is D-13.
- [06 — Execution pipeline](06-EXECUTION-PIPELINE-DEFECTS.md) — what the executors call.
- [07 — Planning & critics](07-PLANNING-AND-CRITICS-DEFECTS.md) — for AK-04, AK-13, AK-17.
- [08 — Memory & CORTEX](08-MEMORY-AND-CORTEX-DEFECTS.md) — for AK-06 and AK-I2.
- [14 — Billing & credits](14-BILLING-AND-CREDITS-DEFECTS.md) — for AK-02 and AK-I1.
