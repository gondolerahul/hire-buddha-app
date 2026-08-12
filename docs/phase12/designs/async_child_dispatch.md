# Design — Async Child-Entity Dispatch (the prerequisite for deleting `execute_run`)

> **Status:** **Implemented behind `governance.async_child_dispatch` (default
> OFF).** The suspend/resume mechanism in §3–§4 is in tree; unit tests cover the
> state machine, snapshot round-trip, child fold, and resume guard
> (`tests/unit/test_async_child_dispatch.py`). What remains before the flag can
> flip ON (and before C4) is the **worker-driven E2E validation**: a multi-child
> PROCESS parity case + resumability chaos test (§7). The original design is
> preserved below.
>
> **Implementation map:**
> - `WAITING_ON_CHILDREN` status + transitions → `schemas/enums.py`
> - `ActionResult.awaiting_children` → `core/executors/base.py`
> - `AgentState.awaiting_children` (snapshotted) + transient `suspend_requested`
>   → `core/agent_state.py`
> - `StepExecutorService.create_child_run` (creation split from inline run)
>   → `step_executor.py`
> - `ChildEntityExecutor._dispatch_async` (create child + enqueue + return
>   marker) → `core/executors/child_entity.py`
> - loop suspend (`_iteration`/`_loop`/`_drive`), `resume`, `_fold_children`,
>   `_persist_suspended`, `_maybe_resume_parent` → `core/agent_loop.py`
> - `resume_parent_run` arq job → `core/arq_jobs.py` (+ `worker.py` registration)

> **Why this exists:** Phase 12 Stage 1 cut **C4** ("delete the legacy
> `ExecutionEngine.execute_run` plan-walker; the AgentLoop is the sole entry
> point") is **blocked**. The loop does not replace `execute_run` — it
> *delegates into it* for child-entity execution. This document specifies the
> mechanism that must ship **before** `execute_run` can be deleted.
> **Audited against:** `backend/src/ai/` on branch `phase12/stage1-consolidation`.

---

## 1. The blocker, precisely

`execute_run` is not dead code behind a flag — it is load-bearing in three ways:

1. **Top-level dispatch.** `core/arq_jobs.py` routes a run to the AgentLoop when
   `agent_loop.enabled` is true, else to `ExecutionEngine.execute_run`.
   *(Removable: make the loop unconditional.)*
2. **Loop executors delegate into the engine's step methods.** The loop's
   executors call engine internals, not `execute_run`:
   - `single_step` → `ExecutionEngine._execute_step_wrapper`
   - `dag` → `ExecutionEngine._execute_steps_dag`
   - `child_entity` → `ExecutionEngine._execute_step_wrapper`
   - `recursive` → `ExecutionEngine.execute_run` (the whole legacy run)
   *(Separable by extracting a `StepEngine` — see §6 — except for `recursive`.)*
3. **Child-entity execution callback (the real blocker).**
   `ExecutionEngine.__init__` / `_ensure_services` pass
   `execute_run_fn=self.execute_run` into `StepExecutorService`
   (`execution_engine.py:79,93`). When any step invokes a child entity, the
   step executor ultimately calls `self._execute_run_fn(child_run.id)`
   (`step_executor.py:106, 305`) — i.e. **every child entity in a PROCESS runs
   by recursively calling `execute_run`.**

The code documents why this was not already fixed
(`execution_engine.py:97-104`, verbatim):

> *child entities run via the legacy `execute_run` engine even when
> `agent_loop.enabled` is ON. Routing children through a nested inline AgentLoop
> was tried (Phase 11 follow-up) but destabilised the doc-factory pipeline: each
> child became a full retry loop running inline on the shared session, which
> amplified cost (~$11/child) and could block the worker. Driving sub-entities
> through the new loop needs a safer mechanism (e.g. async dispatch on a
> dedicated worker) and is deferred.*

**Conclusion:** deleting `execute_run` requires a child-execution mechanism that
(a) does not run a nested loop inline on the parent's session, and (b) does not
block the parent worker. That mechanism is this design.

---

## 2. What already exists (build on it, don't start over)

A partial async path is already in tree, flag-gated by
`governance.async_child_dispatch` (`step_executor.py:295-305`):

```python
use_async = governance.get("async_child_dispatch", False)
if use_async and self.redis:
    child_result = await self._dispatch_child_async(child_run, governance)
else:
    child_result = await self._execute_run_fn(child_run.id)   # legacy inline
```

`_dispatch_child_async` (`step_executor.py:62-108`):
1. subscribes to `run:{child_id}:status` on Redis pub/sub,
2. enqueues an Arq job `run_execution_recursive` for the child,
3. **`await`s the child's completion message** (up to `2 × timeout_ms`),
4. on timeout, **falls back to inline `_execute_run_fn`**.

Plus: `cortex_bridge.py:357` already enqueues `execute_run` for child runs, and
`arq_jobs.py:770` enqueues a run for **resume**. The AgentLoop already
`_snapshot`s `AgentState` every iteration (`agent_loop.py:859`), and the
`RunStatus` machine already has `PAUSED → RESUMING → RUNNING` and
`PARTIAL_COMPLETE` (`schemas/enums.py:49-54`).

**The gap:** the existing `_dispatch_child_async` still **blocks the parent
coroutine/worker** while waiting on pub/sub, and falls back to the inline path.
It is "async dispatch, synchronous wait." It does not free the worker, and
pub/sub messages are lost if the parent isn't listening (no durability). It is
also wired into the *legacy* `StepExecutor`/`execute_run` path, not the loop.

---

## 3. Target — suspend/resume, not block-and-wait

The durable fix is to make the **AgentLoop suspend** when it spawns children and
**resume** when they finish, instead of any worker blocking on a child.

```
Parent loop iteration N:
  Strategist picks a step that invokes child entities C1..Ck
        │
        ▼
  ChildEntityExecutor:
    - create child ExecutionRun rows (PENDING), link parent_run_id + a
      ``resume_token`` (parent run_id + iteration + step_id)
    - enqueue one Arq job per child on the *child* queue
    - record {pending: [C1..Ck]} into AgentState
    - return ActionResult(status=AWAITING_CHILDREN)
        │
        ▼
  Loop: persist snapshot, set run.status = WAITING_ON_CHILDREN, RELEASE worker.
        (No coroutine is parked; the worker moves on to other jobs.)

Child run finishes (its own loop/StepEngine, its own worker, own budget):
    - on terminal status, enqueue ``resume_parent`` with the resume_token
    - durably record child result on the child ExecutionRun row

resume_parent job:
    - load parent AgentState snapshot
    - mark child done; if any children still pending → return (wait for them)
    - when all children for the step are terminal → fold results into context,
      set run.status = RESUMING, re-enter AgentLoop at iteration N+1
```

Key properties that fix the prior failure mode:

| Prior failure (inline nested loop) | This design |
|------------------------------------|-------------|
| Child ran a full retry loop **inline on the parent's session** | Child runs as its **own job on its own session**, isolated |
| Parent **worker blocked** for the child's duration | Parent **suspends** (snapshot + WAITING status); worker freed |
| Cost amplification ~$11/child (nested retries on shared budget) | Child has **its own Budget**; parent folds in the *settled* child cost once, via the existing CostLedger child-run attribution |
| Lost pub/sub messages if parent not listening | **Durable**: child writes terminal status to its row + enqueues a resume job; nothing is awaited in memory |

---

## 4. Components & required changes

| Area | Change |
|------|--------|
| `schemas/enums.py` | Add `WAITING_ON_CHILDREN` run status + transitions (`RUNNING → WAITING_ON_CHILDREN → RESUMING`). |
| `core/agent_state.py` | Add `pending_children: list[ChildHandle]` (run_id, step_id, status) to the snapshotted state. |
| `core/executors/child_entity.py` | Stop calling `ExecutionEngine._execute_step_wrapper`. Instead: create child runs, enqueue child jobs, return `AWAITING_CHILDREN`. |
| `core/agent_loop.py` | On `AWAITING_CHILDREN`: snapshot, set status, **return without finalizing** (a third terminal-of-iteration outcome beyond CONTINUE/DONE). Add a `resume(run_id)` entry that rehydrates state and continues. |
| `core/arq_jobs.py` | New jobs: `run_child(child_run_id)` (drives a child via the AgentLoop) and `resume_parent(resume_token)`. Remove the legacy `execute_run` dispatch branch **only after** children no longer need it. |
| child terminal hook | In `AgentLoop._finalize` (already enqueues a post-run job, `arq_jobs.py:827`), if the run has a `parent_run_id`, enqueue `resume_parent`. |
| `step_executor.py` | Delete `_dispatch_child_async` (superseded) and the `execute_run_fn` callback once the loop owns child dispatch. |
| Worker topology | A dedicated **child queue / worker pool** so a burst of children can't starve top-level runs (and vice-versa). Config: concurrency caps per queue. |

Budget & cost: children already get a child `Budget` and the CostLedger already
has a `CHILD_RUN` attribution (`services/cost_attribution.py`). The parent folds
in the child's **final settled** cost on resume — no double-billing, no shared
running budget (this is what caused the ~$11 amplification).

---

## 5. Failure, cancellation, and idempotency

- **Child fails:** `resume_parent` sees a FAILED child; the parent step's
  `on_failure` policy (RETRY/ESCALATE/ABORT) applies at the parent iteration,
  exactly as today — but evaluated on resume, not inline.
- **Crash between dispatch and resume:** the parent sits in
  `WAITING_ON_CHILDREN` with a durable snapshot; a sweeper (reuse the existing
  resume/`run_execution_recursive` machinery) re-enqueues `resume_parent` for
  runs whose children are all terminal. No in-memory wait to lose.
- **Idempotency:** `resume_parent` keys on `(parent_run_id, step_id)`; folding a
  child result is guarded by the child's terminal status + a `folded` marker on
  the snapshot, so duplicate resume jobs are no-ops. (Mirrors the existing
  `test_arq_dispatch_idempotency` discipline.)
- **Cancellation:** the loop already checks `_check_cancelled` each iteration
  (`agent_loop.py:1000`); on resume it re-checks before continuing, and cancels
  outstanding children.

---

## 6. How this unblocks C4 (the deletion sequence, after this ships)

Once children no longer call `execute_run`:

1. **Drop the child callback.** Remove `execute_run_fn=self.execute_run` from
   `StepExecutorService` construction (`execution_engine.py:79,93`).
2. **Extract `StepEngine`.** Split `ExecutionEngine` into:
   - `StepEngine` — `_execute_step_wrapper`, `_execute_steps_dag`,
     `_ensure_services`, `_enforce_cost_cap`, `_evaluate_hitl_checkpoints`, and
     the CORTEX helpers. **No `execute_run`.** The loop's `single_step` / `dag`
     / `child_entity` executors construct `StepEngine`.
   - `ExecutionEngine(StepEngine)` — only `execute_run` + `_get_reconciled_plan`.
3. **Re-platform `recursive`.** The `RecursiveExecutor` (the last in-loop caller
   of `execute_run`) drives recursive reasoning through loop iterations /
   `StepEngine`, not `execute_run`.
4. **Make arq dispatch loop-only.** Remove the `else → execute_run` branch in
   `arq_jobs.py`; `agent_loop.enabled` stops gating engine choice.
5. **Delete** `ExecutionEngine.execute_run` (+ the now-orphaned subclass).
   - This removes the engine's `MemoryRouter` uses (`execution_engine.py:676,
     761`) → **C2** (`MemoryRouter` delete + assembler v2-only) becomes safe.
   - This removes the engine's `MetaReviewer` use (`execution_engine.py:990`);
     `MetaReviewer` stays (the loop's `RealCriticPipeline` still uses it,
     `critic_pipeline.py:490`) → **C3** reduces to the safe `CortexRouter` alias
     removal.

So this one mechanism is the keystone that unblocks **C2, C3, and C4** together.

---

## 7. Rollout & verification

- **Flag:** reuse `governance.async_child_dispatch` (already exists) but redefine
  it as the suspend/resume path; default OFF; canary one company.
- **Fallback:** while the flag is OFF, the current inline `_execute_run_fn` path
  stays. No deletion happens until the flag is ON and stable.
- **Parity coverage first (hard gate).** The parity corpus currently has a
  *strong* `simple_skill` case but the multi-child `research_process_pipeline`
  golden **FAILs under the hermetic mock** — i.e. PROCESS/child execution is
  exactly the path with no positive coverage. **Before** any deletion:
  1. extend `tests/parity/` with a PROCESS case that completes (2–3 children),
  2. record its golden on the legacy path,
  3. prove the async-dispatch loop matches it (status/cost/steps/output),
  4. add a resumability chaos test: kill the worker while a parent is
     `WAITING_ON_CHILDREN`; assert a new worker resumes and completes
     (`tests/chaos/`, alongside `snapshot_every_iteration`).
- **Cost regression guard:** assert per-run cost on a 3-child PROCESS stays
  within tolerance of the legacy golden — this is the specific guard against the
  ~$11/child amplification recurring.

---

## 8. Sequencing

```
[this design] ─▶ implement async child dispatch (flag OFF)
                      │
                      ├─ extend parity to a multi-child PROCESS (record golden)
                      ├─ resumability chaos test
                      ▼
                 canary flag ON, soak, cost guard green
                      │
                      ▼
        C4: drop child callback ▶ extract StepEngine ▶ re-platform recursive
            ▶ arq loop-only ▶ delete execute_run
                      │
                      ▼
        C2 (MemoryRouter delete) + C3 (CortexRouter alias) fall out
```

**Estimated size:** L–XL for the dispatch mechanism + tests; the subsequent
C4/C2/C3 deletions are M once the mechanism is proven. This is a multi-PR effort
in its own right, not a single Stage-1 cut — which is why Phase 11 deferred it.

---

## 9. Open questions

- **Worker topology:** dedicated child queue vs priority lanes on the existing
  worker? (Recommend a separate queue with its own concurrency cap.)
- **Fan-out limits:** a PROCESS with many children → cap concurrent child jobs
  per parent (governance field) to bound fleet load.
- **Nested depth:** children that themselves spawn children — the resume_token
  must carry the full ancestry; `max_recursion_depth` (already in governance)
  caps it.
- **Streaming/UX:** while `WAITING_ON_CHILDREN`, the SSE stream should surface
  "waiting on N children" rather than appearing stalled (ties to `01` §7).
