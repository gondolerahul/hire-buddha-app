# 15. Governance, HITL & Feature Flags — Defect Register

> **What this document is:** defects in what gates a run and how humans intervene — credit
> gates, HITL checkpoints, rate limiting, tool cost resolution and the feature-flag service
> — plus the improvements that would make a gate mean something.
> **Source document:** [`15-governance-and-hitl.md`](../15-governance-and-hitl.md)
> **Compiled:** 2026-09-01, against branch `fresh-main`. **Last reviewed:** 2026-10-07, on branch `roadmap-development-defect-fixes`.
> **Context:** this subsystem exists entirely to say **no**. Its defining defect is that
> **almost every gate fails open** — a broken gate is indistinguishable from a passing one.

---

## How to read this file

- **✅ Verified** — the code was read on 2026-09-01 and the claim held.
- **📄 Doc-reported** — from `15-governance-and-hitl.md`, not independently re-checked.
- One principle explains most of this file: every gate here was written to be non-fatal, so
  that a failure in the control could not break a run. The result is a control layer where
  failure and success look identical from the outside.

---

## Contents

1. [Summary](#1-summary)
2. [T0 — Gates that fail open](#2-t0--gates-that-fail-open)
3. [T1 — HITL correctness](#3-t1--hitl-correctness)
4. [T2 — Feature flags that are not controls](#4-t2--feature-flags-that-are-not-controls)
5. [T3 — Cost resolution and operability](#5-t3--cost-resolution-and-operability)
6. [Improvements](#6-improvements)
7. [Suggested order of work](#7-suggested-order-of-work)

---

## 1. Summary

| Tier | Theme | Count | Fixed | Partly fixed | Open | Closed otherwise |
|---|---|---|---|---|---|---|
| [T0](#2-t0--gates-that-fail-open) | Gates that fail open | 6 | 6 | 0 | 0 | 0 |
| [T1](#3-t1--hitl-correctness) | HITL correctness | 9 | 9 | 0 | 0 | 0 |
| [T2](#4-t2--feature-flags-that-are-not-controls) | Feature flags that are not controls | 5 | 1 | 2 | 2 | 0 |
| [T3](#5-t3--cost-resolution-and-operability) | Cost resolution and operability | 5 | 4 | 0 | 1 | 0 |

**Total: 25 defects (20 fixed, 2 partly fixed, 3 open), 10 improvements.** Re-verified against the code on 2026-10-07; what is left is scheduled in [`REMAINING-DEFECTS-PLAN.md`](REMAINING-DEFECTS-PLAN.md).

| ID | Defect | Status | Plan |
|---|---|---|---|
| GH-01 | If Redis is down, every HITL checkpoint is skipped | ✅ fixed `98af2c0` | — |
| GH-02 | Two of the four credit gates are never called | ✅ fixed `c1eecb9` (BC-05) | — |
| GH-03 | The rate limiter fails open, and has no callers anyway | ✅ fixed (2026-10-08) | — |
| GH-04 | The suspension middleware fails open and only covers one process | ✅ fixed `15191e5` (SA-18) | — |
| GH-05 | An unmapped tool costs $0 and warns once per process | ✅ fixed (2026-10-08) | — |
| GH-06 | Reject and timeout are detected by matching exception text | ✅ fixed `98af2c0` | — |
| GH-07 | A HITL wait blocks a worker slot | ✅ fixed (2026-10-08) | — |
| GH-08 | `COST_THRESHOLD` fires before the *next* step, not when the threshold is crossed | ✅ fixed (2026-10-08) | — |
| GH-09 | Malformed HITL checkpoints are skipped silently | ✅ fixed (2026-10-08) | — |
| GH-10 | `CUSTOM` expressions support two variables and two operators | ✅ fixed (2026-10-08) | — |
| GH-11 | The approvals page does not show what is being approved | ✅ fixed | — |
| GH-12 | `meta_agent.board_routing` is declared twice | ✅ fixed `b7644b7` | — |
| GH-13 | `get_float` has no env-var tier | open | [H7](REMAINING-DEFECTS-PLAN.md#h7--feature-flags-you-can-trust) |
| GH-14 | Direct SQL flag writes do not invalidate the cache | open | [H7](REMAINING-DEFECTS-PLAN.md#h7--feature-flags-you-can-trust) |
| GH-15 | Legacy alias flags that control nothing | partly — `memory_v2.canonical` remains | [H11](REMAINING-DEFECTS-PLAN.md#h11--deferred-items) |
| GH-16 | Flags declared and never read | partly — four `memory.*` flags remain | [H11](REMAINING-DEFECTS-PLAN.md#h11--deferred-items) |
| GH-17 | `ToolCostResolver` is cached per process, and has no callers | ✅ fixed `d71918d`, `902af7c` | — |
| GH-18 | Budget lives on the entity, not the company | ✅ fixed (2026-10-08) | — |
| GH-19 | The tool-call counting is off by design | ✅ fixed `73afd55` (TL-21) | — |
| GH-20 | There is no way to see why a flag has its value | open | [H7](REMAINING-DEFECTS-PLAN.md#h7--feature-flags-you-can-trust) |
| GH-21 | Almost every gate in the platform fails open | ✅ fixed (2026-10-08) | — |
| GH-22 | Every HITL checkpoint fails to subscribe, so none of them waits | ✅ fixed `98af2c0` | — |
| GH-23 | Authorize and Block Cycle always fail with 422 | ✅ fixed `1a55054` | — |
| GH-24 | Any user can answer any company's approval | ✅ fixed `1a55054` | — |
| GH-25 | A rejected step is retried, and the reviewer is asked again | ✅ fixed (2026-10-08) | — |

The three to read first:

- **[GH-01](#gh-01--if-redis-is-down-every-hitl-checkpoint-is-skipped)** — the step runs
  unapproved and the approval row stays `PENDING` forever.
- **[GH-02](#gh-02--two-of-the-four-credit-gates-are-never-called)** — a normal run has no
  pre-execution credit gate and no in-run circuit breaker.
- **[GH-06](#gh-06--reject-and-timeout-are-detected-by-matching-exception-text)** — the gate
  re-raises based on a substring of an error message.

> **Update 2026-10-07:** all three are fixed — GH-01 and GH-06 (`98af2c0`), and GH-02 with BC-05 (`c1eecb9`). The open ones to read first now are [GH-25](#gh-25--a-rejected-step-is-retried-and-the-reviewer-is-asked-again), [GH-07](#gh-07--a-hitl-wait-blocks-a-worker-slot) and [GH-05](#gh-05--an-unmapped-tool-costs-0-and-warns-once-per-process).

---

## 2. T0 — Gates that fail open

### GH-01 — If Redis is down, every HITL checkpoint is skipped

**✅ Verified · Critical** · **Status: fixed (2026-09-29, `98af2c0`)** — with GH-22: the wait
fails closed and re-reads the approval row, so a Redis outage delays a decision instead of
skipping the checkpoint.

> **Update 2026-09-29:** worse than stated. The subscribe call itself is broken, so this
> swallow fires on every checkpoint, Redis up or down — see
> [GH-22](#gh-22--every-hitl-checkpoint-fails-to-subscribe-so-none-of-them-waits).

The HITL wait subscribes to `hitl:{approval_id}` and polls to a deadline. The whole block
is wrapped in:

```python
except Exception as hitl_err:
    if "Execution blocked" in str(hitl_err) or "timed out" in str(hitl_err):
        raise
    logger.warning(f"HITL pub/sub error: {hitl_err}")
    # Non-fatal: continue execution if pub/sub fails
```

Any pub/sub failure — Redis unreachable, connection dropped, subscribe error — logs a
warning and **the step proceeds unapproved**. The `human_approvals` row stays `PENDING`
forever, so the approvals page shows a checkpoint that is still waiting for a decision on
work that already happened.

This is the safety feature the product is sold on, and it is disabled by a Redis blip with
one warning line.

- [`ai/governance/governance_service.py:392`](../../../backend/src/ai/governance/governance_service.py:392) — the swallow

**Fix:** fail closed. A checkpoint that cannot be evaluated must block the step, not skip
it. If that is too strict, at minimum mark the approval row `ERROR` so it is visible.

---

### GH-02 — Two of the four credit gates are never called

**✅ Verified · Critical** · **Status: fixed (2026-09-30, `c1eecb9`, with [BC-05](14-BILLING-AND-CREDITS-DEFECTS.md#bc-05--three-of-the-four-credit-gates-have-no-callers))** — `CreditGuard` (`ai/core/credit_guard.py`) admits every run through `check_credit_gate`, holds the estimate in `credit_holds`, and calls `check_credit_circuit_breaker` as cost accrues. The hold settles at the end, so `consume_step_cost` is no longer the design. Recorded here 2026-10-07.

Grepping `backend/src` for call sites:

| Gate | Callers |
|---|---|
| `check_credit_gate` — refuse to start on an empty wallet | **none** |
| `consume_step_cost` — incremental deduction | **none** |
| `check_credit_circuit_breaker` — stop mid-flight | **none** |
| `check_child_credit_gate` | [`step_executor.py:236`](../../../backend/src/ai/step_executor.py:236) ✅ |
| `settle_billing` | [`agent_loop.py:1134`](../../../backend/src/ai/core/agent_loop.py:1134) ✅ |

So the only two credit controls that run are the child-spawn gate and the final
settlement. A normal agent run has **no pre-execution credit gate and no in-run circuit
breaker**.

All the unused methods are implemented and unit-tested, which is exactly why nobody
noticed.

Recorded in full as
[BC-05](14-BILLING-AND-CREDITS-DEFECTS.md#bc-05--three-of-the-four-credit-gates-have-no-callers).

---

### GH-03 — The rate limiter fails open, and has no callers anyway

**📄 Doc-reported · High** · **Status: fixed (2026-10-08)** — decision HD17: `RedisRateLimiter` refuses by default when Redis is unreachable (with GH-21), and a company may start `RUNS_STARTED_PER_MINUTE` (default 60) top-level runs a minute (`governance/run_quota.py`, key `runs_started:{company}`). Past it, the API (execute, retry, refine) answers 429 with `Retry-After: 60`; a gateway event's job defers itself a minute (arq `Retry`) and is refused on its fifth try. Tool-call quotas are later work. `tests/unit/test_run_quota.py` (5), `tests/integration/test_run_quota.py`

`RedisRateLimiter` is a correct sliding-window implementation. Two problems:

1. A Redis error returns `True` (allowed) rather than blocking. That is deliberate — but it
   means a Redis outage removes rate limiting entirely, at the moment load is most likely
   to be the cause.
2. It has **zero call sites**. Its own docstring gives the example key
   `"tool:search:company_123"`; nothing constructs one.

There is no per-tenant quota anywhere in the platform.

- [`ai/governance/rate_limiter.py`](../../../backend/src/ai/governance/rate_limiter.py)
- Also [TL-28](TOOL-LAYER-DEFECTS.md#4-t2--delete)

---

### GH-04 — The suspension middleware fails open and only covers one process

**✅ Verified · High** · **Status: fixed (2026-09-30)** — the middleware is deleted (SA-18). The
remaining check, in `_authenticate_user`, fails closed on a database error, and since the
single-port merge there is only one process to cover.

`CompanySuspensionMiddleware` swallows every exception and continues. A database blip
therefore silently disables suspension enforcement rather than failing closed.

It is also registered on the **backend API only**, not on the gateway — so it protects
port 8000, which nothing external reaches directly, and not the process that actually
receives external traffic.

It costs one extra database round trip on every authenticated request to do this.

- `common/middleware.py`

The dependency-level check in `_authenticate_user` is correct and free, and is what
actually enforces suspension. See
[AU-22](04-AUTH-RBAC-TENANCY-DEFECTS.md#au-22--suspension-is-checked-twice-in-two-different-ways).

---

### GH-05 — An unmapped tool costs $0 and warns once per process

**📄 Doc-reported · High** · **Status: fixed (2026-10-08)** — a tool with no price is visible on every call: `ToolCostResolver.charge` writes a $0 `usage_logs` row marked `cost_source: missing` and a `tool.cost.missing` event each time (the warn-once set is gone). Tools that cost nothing here on purpose are in `FREE_TOOLS` with a reason — local work, the company's own account, model calls billed as LLM usage, sandbox time; a synthesized tenant tool says `free_reason`. `tests/unit/test_tool_prices.py` fails on a registered tool that is neither priced (`TOOL_SKU_MAP`, `TOOL_FIXED_COST`) nor declared free. `tests/integration/test_tool_metering.py` (2)

A tool with no SKU mapping resolves to zero cost, consumes no budget, appears in no cost
report — and logs a warning **once per process**, so on a long-lived worker the second and
subsequent occurrences are silent.

So adding a tool without adding its price makes it free, permanently and quietly. This is
the failure mode that makes
[BC-11](14-BILLING-AND-CREDITS-DEFECTS.md#bc-11--four-price-tables-and-the-intended-source-of-truth-is-unused)
expensive: four price tables, and forgetting one produces no error.

---

### GH-22 — Every HITL checkpoint fails to subscribe, so none of them waits

**✅ Verified · Critical** · **Status: fixed (2026-09-29, `98af2c0`)** — found 2026-09-29
while verifying PO-05; fixed with GH-01.

The wait calls `self.redis.client.pubsub()`. On the live path `self.redis` is the
`redis.asyncio.Redis` that `arq_jobs` builds with `redis.from_url(...)`, where `client` is a
**method** — so `.client.pubsub` raises `AttributeError: 'function' object has no attribute
'pubsub'` on every checkpoint. [GH-01](#gh-01--if-redis-is-down-every-hitl-checkpoint-is-skipped)'s
catch-all turns that into a warning and the step proceeds unapproved. The approval row is left
`PENDING` for a decision on work that has already happened.

So GH-01 is not a Redis-outage risk; it is the normal behaviour. No checkpoint in the product
has ever blocked a step. Reproduced on the local stack by firing a real `AFTER_STEP`
checkpoint through `GovernanceService.evaluate_hitl` with the worker's Redis object: the log
reads `HITL pub/sub error: 'function' object has no attribute 'pubsub'`, the call returns at
once, and the row stays `PENDING`.

- [`ai/governance/governance_service.py`](../../../backend/src/ai/governance/governance_service.py) — `pubsub = self.redis.client.pubsub()`
- [`ai/core/arq_jobs.py:35`](../../../backend/src/ai/core/arq_jobs.py:35) — `redis_pool = redis.from_url(...)`

**Fix:** `self.redis.pubsub()`, and fail closed as GH-01 asks. Add a test that runs the wait
against a real `redis.asyncio.Redis`, not a mock with a `.client` attribute.

**Done (2026-09-29).** The wait is now `GovernanceService._await_hitl_decision`:

- it subscribes with `self.redis.pubsub()`;
- it also re-reads the approval row's `status` every 2 seconds, so a lost publish or a Redis
  outage delays the decision but never skips the checkpoint — GH-01's fail-closed ask;
- it returns the decision as a value, and `evaluate_hitl` acts on it directly — the
  catch-all that let steps through, and the exception-text matching of GH-06, are gone;
- at the deadline the row is marked `TIMEOUT` (or auto-approved) with a conditional
  `UPDATE … WHERE status = 'PENDING'`, so an answer that lands at the deadline wins;
- the `HITL_PENDING` notice on `execution:{run_id}` is best-effort — the row is the record.

**Evidence:** `tests/unit/test_hitl_wait.py`, 7 cases, all failing on the old code: an
approval and a rejection over a **real** `redis.asyncio.Redis` built exactly as `arq_jobs`
builds it (the approval case asserts the step waited for the message); Redis down with the
decision arriving on the row (approve and reject); timeout with and without auto-approve;
and a decision at the deadline beating the timeout. Live, with the worker restarted on the
new code and a one-step agent carrying a `BEFORE_STEP` checkpoint: run 1 sat `RUNNING` with
no step output until **Authorize** was clicked on the approvals page, then completed with
its output; run 2, left unanswered, timed out after its 10-minute window — approval
`TIMEOUT`, run `FAILED`, step never executed; run 3, **Block Cycle** — the step failed with
*Execution blocked by human reviewer* and never ran. Run 3 also exposed
[GH-25](#gh-25--a-rejected-step-is-retried-and-the-reviewer-is-asked-again).

---

## 3. T1 — HITL correctness

### GH-06 — Reject and timeout are detected by matching exception text

**✅ Verified · High** · **Status: fixed (2026-09-29, `98af2c0`)** — by the GH-22 rewrite: the
wait returns the decision as a value and `evaluate_hitl` raises from it directly; no
exception text is matched anywhere on the HITL path. The exceptions are still plain
`Exception`s — typed ones are what
[GH-25](#gh-25--a-rejected-step-is-retried-and-the-reviewer-is-asked-again) needs.

```python
if "Execution blocked" in str(hitl_err) or "timed out" in str(hitl_err):
    raise
```

Whether a rejected approval actually blocks the run depends on a **substring of an error
message**. Reword either message — a translation, a clarification, a refactor — and the
gate silently stops re-raising, and rejections become approvals.

- [`ai/governance/governance_service.py:392`](../../../backend/src/ai/governance/governance_service.py:392)

**Fix:** typed exceptions. `HITLRejected` and `HITLTimeout` cannot be broken by an edit to
a message.

---

### GH-07 — A HITL wait blocks a worker slot

**✅ Verified · High** · **Status: fixed (2026-10-08)** — a checkpoint parks the run instead of waiting (GH-I3): `evaluate_hitl` and `ask_user` open the approval and raise `HITLPending`; the executors report it as `ActionResult.awaiting_approval` and the loop snapshots the run, sets it `PAUSED`, re-queues the unrun steps and returns the worker, keeping the credit hold (`core/approval_pause.py`). The respond endpoint, a job deferred to the deadline and the stuck-run sweep enqueue `resume_paused_run` → `AgentLoop.resume_after_approval`, which claims the run once and continues at the same step (APPROVED), or ends it CANCELLED (REJECTED) or FAILED (TIMEOUT, or auto-approves). On re-dispatch the checkpoint finds its approval (`governance/hitl_gate.py`) and uses it once (`human_approvals.consumed_at`, migration `h4_approval_consumed_at`). The blocking wait and the `hitl:{id}` channel are gone. `tests/unit/test_approval_pause.py`, `tests/integration/test_hitl_parking.py`. Live 2026-10-08 on a two-slot worker: ten runs parked `PAUSED` with an approval each while another run ran to its end; an approved run resumed after a worker restart and completed its step; a rejected one ended `CANCELLED` with the note; one past its deadline ended `FAILED` (`TIMEOUT`)

The service subscribes and then polls in a loop until `timeout_ms`. Default 5 minutes, and
the field is free — a tenant can set an hour.

That worker slot is unavailable for the whole wait. With a small pool, a handful of pending
approvals starves every other run in the company.

- [`ai/governance/governance_service.py:345`](../../../backend/src/ai/governance/governance_service.py:345)

**Fix:** park the run in `PAUSED`, release the worker, re-enqueue on approval. Also
[PO-20](01-PRODUCT-OVERVIEW-DEFECTS.md#po-20--a-long-hitl-timeout-ties-up-a-worker).

---

### GH-08 — `COST_THRESHOLD` fires before the *next* step, not when the threshold is crossed

**📄 Doc-reported · Medium** · **Status: fixed (2026-10-08)** — `COST_THRESHOLD` fires before a step when the run's spend so far (its usage rows and children, `run_spend` — not the run column, which moves only between iterations) plus the step's estimate (`planning/cost_estimator.estimate_step_cost`) reaches the threshold, so the person is asked before the line is crossed; once over, every later step asks, which is the backstop for a low estimate. The trigger names the threshold and the step, not the spend, so a parked run's step finds its approval again after a critic call spent a little (it was `$X >= $Y` and would have asked again). The approval's snapshot carries `run_cost_usd` and `step_cost_estimate_usd`. `tests/integration/test_hitl_parking.py` (2)

Only `AFTER_STEP` fires in the `AFTER` phase. `COST_THRESHOLD` is `BEFORE`-only.

So a step that blows through the threshold completes in full, and the checkpoint fires
before whatever runs next. The money is already spent by the time a human is asked.

For a threshold whose purpose is "stop before this gets expensive", firing after the
expensive thing is the wrong half of the step boundary.

---

### GH-09 — Malformed HITL checkpoints are skipped silently

**📄 Doc-reported · Medium** · **Status: fixed (2026-10-08)** — `schemas/governance.checkpoint_problem` says why a checkpoint could never fire — it does not parse, lacks the field its trigger needs, has a `CUSTOM` expression outside the grammar, a non-positive timeout, or a `step_ref` that is not a step of a static plan. The entity create and update requests (and version drafts) refuse it with a 422 naming it (`checkpoint 2 (CUSTOM): …`). One stored before that asks a person before each step (trigger `UNUSABLE CHECKPOINT n before <step>`) and writes a `hitl` span on the run's trace and the event `agent.hitl.checkpoint_unusable`. `tests/unit/test_hitl_checkpoint_validation.py`

A checkpoint that does not parse is skipped with a bare `continue` — no log line, no event,
nothing on the run trace.

A typo in the Safeguards tab therefore removes a safety gate with no feedback anywhere. The
user sees a configured checkpoint that never fires.

---

### GH-10 — `CUSTOM` expressions support two variables and two operators

**📄 Doc-reported · Medium** · **Status: fixed (2026-10-08)** — a closed grammar, `schemas/hitl_expression.py`: `step_count` and `cost` with `> >= < <= ==` and a number, or `has_key('name')`, joined by `and` / `or`; `cost` is the run's spend from its usage rows. The builder's own example, `cost > 0.50 or step_count > 5`, never worked under the old evaluator and works now. Anything else is refused on save (GH-09); the builder's help text gives the grammar. `tests/unit/test_hitl_checkpoint_validation.py`

The docstring says "Python-like boolean expression". The evaluator supports only
`step_count` and `current_cost`, with `>` and `>=`.

Anything else — `and`, `<`, a tool name, a step name — evaluates to false and the
checkpoint never fires. Silently, per
[GH-09](#gh-09--malformed-hitl-checkpoints-are-skipped-silently).

**Fix:** document the two variables and two operators in the builder's help text, and
reject anything else at save time.

---

### GH-11 — The approvals page does not show what is being approved

**✅ Verified · High** · **Status: fixed (2026-09-29, `ad74c46`)** — as PO-05.

`context_snapshot` is stored on every approval row and rendered nowhere.

Recorded in full as
[PO-05](01-PRODUCT-OVERVIEW-DEFECTS.md#po-05--a-reviewer-approves-without-seeing-what-they-are-approving).
Listed here because it is the governance half: a checkpoint that shows the reviewer nothing
is a delay, not a control.

> **Update 2026-09-29:** fixed with PO-05 (`ad74c46`). The snapshot now carries what the step
> is about to do (or produced) and the panel renders it.

---

### GH-23 — Authorize and Block Cycle always fail with 422

**✅ Verified · Critical** · **Status: fixed (2026-09-29, `1a55054`)** — found 2026-09-29 while
fixing PO-05.

`HITLPanel` posts `{status, notes}` as a JSON body. `POST /ai/approvals/{id}/respond`
declares `status` and `notes` as plain function parameters, which FastAPI reads from the
**query string**. Every click returns `422 — query.status: Field required`; the panel logs
the error to the console and shows nothing. No approval has ever been answered from the UI.

Together with [GH-22](#gh-22--every-hitl-checkpoint-fails-to-subscribe-so-none-of-them-waits)
this hides itself: the worker never waits, so nothing appears stuck.

- [`frontend/src/pages/ai/HITLPanel.tsx`](../../../frontend/src/pages/ai/HITLPanel.tsx) — `handleRespond`
- [`ai/router.py`](../../../backend/src/ai/router.py) — `respond_to_approval`

**Fix:** accept a request body (a small Pydantic model), validate `status` against
`APPROVED | REJECTED`, and show the error in the panel.

**Done (2026-09-29).** The endpoint takes `ApprovalDecision` — `status: Literal["APPROVED",
"REJECTED"]`, optional `notes`, unknown keys forbidden — as its JSON body. The panel shows
the API's error message, and refreshes the list on a 404 or 409.

**Evidence:** `tests/integration/test_hitl_respond.py` — the panel's exact request is
accepted and recorded (fails on the old code); a bad status, an unknown key or an empty body
is a 422 and leaves the approval `PENDING`. Live: **Authorize** and **Block Cycle** on the
approvals page both returned 200 and the waiting runs acted on them (see GH-22).

---

### GH-24 — Any user can answer any company's approval

**✅ Verified · High** · **Status: fixed (2026-09-29, `1a55054`)** — found 2026-09-29 while
fixing PO-05; fixed with GH-23.

`respond_to_approval` loads the approval by id alone — no join to `execution_runs`, no
`company_id` check — then updates it and publishes on `hitl:{id}`. The list endpoint is
company-scoped; the write is not. A user of one tenant who has another tenant's approval id
can approve or reject that tenant's run.

- [`ai/service.py`](../../../backend/src/ai/service.py) — `AIService.respond_to_approval`

**Fix:** load the approval joined to its run and require `run.company_id ==
current_user.company_id` (`app_admin` excepted), as `get_pending_approvals` does. Refuse a
second answer to an approval that is no longer `PENDING`.

**Done (2026-09-29).** `AIService.respond_to_approval` loads the approval joined to its run
and requires `run.company_id == current_user.company_id` — for every role, `app_admin`
included, matching the pending list (which is also own-company only). The decision is
written with `UPDATE … WHERE status = 'PENDING'`: a second answer, or an answer after the
worker timed out, is a 409 naming the current status.

**Evidence:** `tests/integration/test_hitl_respond.py` — another company gets 404 and the
approval stays `PENDING`; a second answer is 409 and the first stands; an answer to a
`TIMEOUT` approval is 409. All three fail on the old code.

---

### GH-25 — A rejected step is retried, and the reviewer is asked again

**✅ Verified · High** · **Status: fixed (2026-10-08)** — decision HD7: `evaluate_hitl` and `ask_user` raise `HITLRejected` / `HITLTimeout` (`ai/core/exceptions.py`); the SingleStep and DAG executors report them as `ActionResult.blocked`, and the loop ends the run there — CANCELLED with the reviewer's notes on a rejection, FAILED on a timeout — before any critic or retry (`AgentLoop._end_on_human_decision`, event `agent.loop.human_decision`). A decision outranks other failures in a parallel DAG level. `tests/unit/test_hitl_decision_ends_run.py`

**Block Cycle** fails the step with *Execution blocked by human reviewer*. The loop cannot
tell that failure from any other: the post critic judges it (an LLM call — it answered
`REJECT`, tag `BLOCKED_DEPENDENCY`, *"Unblock to proceed"*), the retry strategy retries the
step, and the checkpoint fires again with a new approval. On the live run the reviewer was
asked three times in a row for the same step before the run was cancelled.

So a rejection is a *request to be asked again*, not a stop — and each round costs a critic
call and holds the worker for another wait.

- [`ai/core/executors/single_step.py`](../../../backend/src/ai/core/executors/single_step.py) — any step exception becomes `success=False`
- [`ai/governance/governance_service.py`](../../../backend/src/ai/governance/governance_service.py) — raises a plain `Exception`

**Fix:** raise a typed `HITLRejected` (and `HITLTimeout`), carry it to the loop as a
distinct outcome, and end the run — or at least that plan branch — without a critic call or
a retry. Decide with the product owner whether a rejection ends the whole run.

---

## 4. T2 — Feature flags that are not controls

| ID | Problem | Notes | Status |
|---|---|---|---|
| **GH-12** | `meta_agent.board_routing` is declared twice | Both `True`, at [`feature_flags.py:53`](../../../backend/src/ai/core/feature_flags.py:53) and [`:71`](../../../backend/src/ai/core/feature_flags.py:71). Harmless — the second wins — and it makes the file look unreviewed. Also **D-29** | ✅ Verified · **fixed (2026-10-03, `b7644b7`)** — the flag went with the unused Board roles (MI-20); no declaration remains. |
| **GH-13** | `get_float` has no env-var tier | Boolean flags resolve entity → company → global → `AI_FLAG_*` → default. Numeric flags skip the env tier entirely, so a numeric knob **cannot** be set without a database row. The documented five-tier resolution is only four tiers for half the flags | ✅ Verified · **open** (re-verified 2026-10-07) — `FeatureFlags.get_float` still resolves entity → company → global → `NUMERIC_DEFAULTS`, with no env tier · plan [H7](REMAINING-DEFECTS-PLAN.md#h7--feature-flags-you-can-trust) |
| **GH-14** | Direct SQL flag writes do not invalidate the cache | Up to 60 seconds of staleness **per worker**, and the invalidation is process-local. The runbook says to use `FeatureFlags.set()`; the admin UI and any manual SQL do not | 📄 Doc-reported · **open** (re-verified 2026-10-07) — the admin flag endpoint (`ai/api/admin.py:516`) still upserts with raw SQL and invalidates nothing · plan [H7](REMAINING-DEFECTS-PLAN.md#h7--feature-flags-you-can-trust) |
| **GH-15** | Legacy alias flags that control nothing | `critic_pipeline.enabled` and `memory_v2.canonical` are aliases that do **not** control the modern paths — those are `critic_pipeline.v2_enabled` and `memory.v2_canonical`. Toggling the alias changes nothing and reads as though it should | 📄 Doc-reported · **partly fixed** (re-verified 2026-10-07) — `critic_pipeline.enabled` is deleted (`eecad67`, AK-10); `memory_v2.canonical` remains, known-unread in `test_feature_flag_census.py` (register 08, deferred) · plan [H11](REMAINING-DEFECTS-PLAN.md#h11--deferred-items) |
| **GH-16** | Flags declared and never read | At least eight: `agent_loop.perception_bounded_viewport`, `agent_loop.snapshot_every_iteration`, the three `agent_loop.executor_*_enabled`, `tools.cost_resolver_v2_enabled` (deleted 2026-09-30, BC-17), `sandbox.container_runtime_enabled` (never threaded into context), and `tools.experimental.*` (gates a function nothing calls). All appear on the admin Feature Flags page | ✅ Verified · **partly fixed** (re-verified 2026-10-07) — the dead kernel flags are deleted and `test_feature_flag_census.py` fails on any new unread flag (`eecad67`); four `memory.*` flags remain known-unread, deferred with register 08 · plan [H11](REMAINING-DEFECTS-PLAN.md#h11--deferred-items) |

> The cross-cutting lesson, worth stating once: **adding a flag is not the same as wiring a
> control.** Eight flags on the admin page do nothing at all, and an operator has no way to
> tell which.

---

## 5. T3 — Cost resolution and operability

### GH-17 — `ToolCostResolver` is cached per process, and has no callers

**✅ Verified · High** · **Status: fixed (2026-09-30, `d71918d`, with BC-07; 2026-10-02, `902af7c`)** — every tool call, on the step executor and on voice, is priced by `ToolCostResolver`, and prices are cached per run, not per process. Recorded here 2026-10-07.

Two facts that compound:

1. It has **zero production call sites** — only its own unit test imports it. The live
   logic is two hand-copied literal blocks in `step_executor.py` plus a fourth table in
   `planning/cost_estimator.py`.
2. Its cache is per process, so even once wired, a rate change requires a restart of every
   worker.

The flag intended to switch it on, `tools.cost_resolver_v2_enabled`, defaults to `True` and
is never read.

- [`ai/governance/tool_cost_resolver.py`](../../../backend/src/ai/governance/tool_cost_resolver.py)
- Also [TL-19](TOOL-LAYER-DEFECTS.md#tl-19--four-price-tables-one-of-which-is-the-unused-source-of-truth)
  and [BC-11](14-BILLING-AND-CREDITS-DEFECTS.md#bc-11--four-price-tables-and-the-intended-source-of-truth-is-unused)

---

### GH-18 — Budget lives on the entity, not the company

**📄 Doc-reported · Medium** · **Status: fixed (2026-10-08)** — decision HD8: `companies.monthly_spend_cap_usd` (migration `h4_company_spend_cap`; empty means no cap) is what the company may be billed in a calendar month — its `billing_events`, every settled run and call (`CreditService.spend_cap_refusal`). At the cap a run's admission (`check_credit_gate`), a call, a campaign or a mobile run (`check_sufficient_for_execution`) is refused with `SpendCapReached` (an `InsufficientCreditsError`), and a running run stops at its breaker, counting its bill so far. Set it with `PATCH /api/v1/companies/{id}` or in Platform Management → Edit (whoever may rename the company). `tests/integration/test_spend_cap.py` (5)

"Raise a tenant's budget" means editing the `governance` block of **every** entity that
tenant owns. There is no company-level cost cap anywhere.

For an operator responding to a runaway spend, there is no single lever to pull. For a
tenant with 40 entities, a budget change is 40 edits.

---

### GH-19 — The tool-call counting is off by design

**📄 Doc-reported · Low** · **Status: fixed (2026-10-01, `73afd55`, with [TL-21](TOOL-LAYER-DEFECTS.md#tl-21--max_tool_calls-is-a-prompt-string-not-a-limit))** — `max_tool_calls` is a limit counted per run from the run's log rows (`ToolAccess.load(..., run_id=)`), and the prompt shows `calls_left()`, which stops at zero. Recorded here 2026-10-07.

`max_tool_calls` renders "Tool calls remaining: N of M" into the prompt, and the counter is
reset at the start of every **step** rather than per run. So the number shown to the model
restarts repeatedly within one run, and can go negative.

It is a prompt hint, not a limit — see
[TL-21](TOOL-LAYER-DEFECTS.md#tl-21--max_tool_calls-is-a-prompt-string-not-a-limit). Listed
here because the arithmetic is visibly wrong in the prompt an operator may be reading while
debugging.

---

### GH-20 — There is no way to see why a flag has its value

**📄 Doc-reported · Medium** · **Status: open** — re-verified 2026-10-07: the flags page still shows only the effective value. Plan: [H7](REMAINING-DEFECTS-PLAN.md#h7--feature-flags-you-can-trust).

Resolution is entity → company → global → env → default. The admin page shows the
**effective** value. It does not show which tier produced it.

So "why is this off for this tenant?" requires querying the table by hand across three
scopes and then checking the process environment. The runbook has a section for exactly
this, which is the tell.

**Fix:** return the winning tier alongside the value. It is already known at the moment of
resolution.

---

### GH-21 — Almost every gate in the platform fails open

**✅ Verified · High · the pattern** · **Status: fixed (2026-10-08)** — with GH-I2: `src/common/gates.py` lists every control that can refuse and what it does when it cannot decide; each failure path calls `gate_failed`, which logs and emits `gate.failed {gate, decision, error}` (the event replaces `meta.gate.failed`). Wired: `rate_limiter` (now refusing by default, GH-03), `semantic_duplicate`, `hitl_checkpoint`, `credit_admission`, `credit_breaker`, `webhook_signature`, `webhook_duplicate`, `voice_call_credit`. All fail closed except two that name their reason: the credit breaker (settlement still bills) and the voice call credit check (VT-01, until H5). `tests/unit/test_gate_inventory.py` fails on an unlisted gate, a listed gate nothing reports, or an open gate without a reason

Collected in one place, because individually each looks defensible:

| Gate | Failure behaviour |
|---|---|
| HITL pub/sub | ~~continues unapproved~~ — fails closed since 2026-09-29 (GH-01, GH-22) |
| `RedisRateLimiter` | returns allowed |
| API slowapi limit | ~~not attached to most routes~~ — every REST route since 2026-09-30; counts in memory if Redis is down |
| ~~`CompanySuspensionMiddleware`~~ | ~~continues~~ — deleted 2026-09-30 (SA-18); the dependency check fails closed |
| `check_semantic_duplicate` | returns "not a duplicate" |
| Webhook signature validation | logs and processes |
| Anti-sprawl in the Curator | `except Exception: pass` |

Every one of these was written so a broken control could not break a run. Together they
mean the platform has **no way to know whether its controls are working**, because a
failing gate and a passing gate produce identical observable behaviour.

---

## 6. Improvements

### GH-I1 — Decide fail-open vs fail-closed once, deliberately

**Effect: the most important change in this register.**
[GH-21](#gh-21--almost-every-gate-in-the-platform-fails-open). Not every gate should fail
closed — a rate limiter arguably should not. But the decision should be made per gate and
written down, rather than inherited from "make sure the control cannot break a run".

The two that clearly must fail closed are HITL
([GH-01](#gh-01--if-redis-is-down-every-hitl-checkpoint-is-skipped)) and webhook signatures
([GW-01](13-GATEWAY-AND-REALTIME-DEFECTS.md#gw-01--no-webhook-signature-is-ever-verified-and-a-failure-would-not-block)).

### GH-I2 — Emit a metric whenever a gate fails to evaluate

> **Done 2026-10-08 with GH-21:** every gate's failure path emits `gate.failed {gate,
> decision, error}` through `src/common/gates.py`; the event reaches the structured log and
> the OTel exporter, which is where a counter per gate is read.

**Effect: large, and it is the prerequisite for everything else.** Whatever a gate does on
failure, it must be **countable**. One counter per gate, incremented on the exception path.

Without this, [GH-01](#gh-01--if-redis-is-down-every-hitl-checkpoint-is-skipped) and
[GH-02](#gh-02--two-of-the-four-credit-gates-are-never-called) can persist indefinitely,
which is exactly what happened.

### GH-I3 — Pause instead of blocking on HITL

**Effect: large on throughput.** [GH-07](#gh-07--a-hitl-wait-blocks-a-worker-slot). Park the
run in `PAUSED`, release the worker, re-enqueue when the approval is answered. `PAUSED` and
`RESUMING` already exist in the status machine, and `resume_execution` is already a
registered arq job.

This also makes long approval windows a feature — an overnight approval becomes reasonable
instead of a capacity problem.

### GH-I4 — Typed exceptions for HITL outcomes

**Effect: medium.** [GH-06](#gh-06--reject-and-timeout-are-detected-by-matching-exception-text).
Two exception classes replace two substring matches. The current code is one message edit
away from turning every rejection into an approval.

### GH-I5 — Call the credit gates that exist

**Effect: large.** [GH-02](#gh-02--two-of-the-four-credit-gates-are-never-called). Two call
sites in `AgentLoop`. See
[BC-I1](14-BILLING-AND-CREDITS-DEFECTS.md#bc-i1--call-the-credit-gates-that-already-exist).

### GH-I6 — Add a company-level budget

**Effect: medium.** [GH-18](#gh-18--budget-lives-on-the-entity-not-the-company). One
`max_monthly_spend_usd` on the company, checked in the same place as the credit gate. Gives
an operator a single lever, and gives a tenant admin a cap they can reason about without
editing 40 entities.

### GH-I7 — Show the winning tier on the flags page

**Effect: medium.** [GH-20](#gh-20--there-is-no-way-to-see-why-a-flag-has-its-value). The
resolver already knows which tier answered. Returning it turns a multi-query investigation
into a glance.

### GH-I8 — Audit the flag catalogue and delete what does nothing

**Effect: medium.** [GH-16](#4-t2--feature-flags-that-are-not-controls). At least eight
flags on the admin page have no reader. A test asserting every key in `DEFAULTS` appears in
a `get_bool` call somewhere would keep the catalogue honest, and would have caught
`sandbox.container_runtime_enabled` — the one where the flag says "on" and the runtime says
"off"
([TX-01](09-TOOLS-DEFECTS.md#tx-01--the-per-company-sandbox-flag-is-never-read)).

### GH-I9 — Give numeric flags an env tier

**Effect: small.** [GH-13](#4-t2--feature-flags-that-are-not-controls). `get_float` skips
`AI_FLAG_*`. Adding it makes numeric knobs settable in an incident without a database
write, which is the whole point of the env tier.

### GH-I10 — Wire `RedisRateLimiter` as the per-tenant quota

**Effect: medium.** [GH-03](#gh-03--the-rate-limiter-fails-open-and-has-no-callers-anyway).
A correct sliding-window limiter with no callers, and no per-tenant quota anywhere in the
platform. Its own docstring names the key format. Use it for tool calls per company, and
for entity creation ([MI-I9](11-META-INTELLIGENCE-DEFECTS.md#mi-i9--rate-limit-entity-creation-within-the-day)).

---

## 7. Suggested order of work

| Step | Work | Why here |
|---|---|---|
| **1** | GH-I2 | Metrics on gate failure. Nothing else here is verifiable without it |
| **2** | GH-01, GH-I4 / GH-06 | Make HITL fail closed and use typed exceptions. Two changes, one file |
| **3** | GH-I5 / GH-02 | Call the two credit gates that already exist |
| **4** | GH-12, GH-I8 / GH-16 | Delete the duplicate key and the flags that do nothing |
| **5** | GH-I3 / GH-07 | Pause instead of blocking. The biggest throughput win |
| **6** | GH-09, GH-10, GH-11 | Make HITL configuration honest: log skips, validate expressions, show the snapshot |
| **7** | GH-I10 / GH-03, GH-I6 / GH-18 | Per-tenant quotas and a company-level budget |
| **8** | GH-I1 | The written fail-open/fail-closed policy, once the individual cases are understood |

---

## Where to go next

- [15 — Governance, HITL & feature flags](../15-governance-and-hitl.md) — the source
  document, including the full flag catalogue.
- [`DEFECT-REGISTER.md`](../DEFECT-REGISTER.md) — GH-12 is D-29.
- [14 — Billing & credits](14-BILLING-AND-CREDITS-DEFECTS.md) — BC-05 is the billing view
  of GH-02.
- [05 — Agent kernel](05-AGENT-KERNEL-DEFECTS.md) — where the gates should be called from.
- [13 — Gateway & real-time](13-GATEWAY-AND-REALTIME-DEFECTS.md) — GW-01 and GW-02 are the
  edge instances of GH-21.
- [`TOOL-LAYER-DEFECTS.md`](TOOL-LAYER-DEFECTS.md) — TL-19 and TL-28 for GH-03 and GH-17.
