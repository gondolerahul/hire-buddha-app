# C4 Re-platforming — Implementation Plan (delete legacy `ExecutionEngine.execute_run`)

> **What this is.** A concrete, PR-by-PR execution plan for the C4 chain: making
> the AgentLoop the *sole* run entry point and deleting the legacy
> `ExecutionEngine.execute_run` plan-walker, which in turn unblocks **C2**
> (delete `MemoryRouter`) and the rest of **C3** (drop the `MetaReviewer`
> in-engine use).
>
> **Relationship to the design doc.** The *mechanism* (suspend/resume async child
> dispatch) and its rationale live in
> [`async_child_dispatch.md`](./async_child_dispatch.md). **That mechanism is
> already implemented in tree, flag-gated `governance.async_child_dispatch`
> (default OFF).** This document is the *delivery* plan: validate the mechanism,
> then re-platform every remaining `execute_run` caller and delete the method.
>
> **Audited against:** `backend/src/ai/` on `phase12/stage1-consolidation`,
> 2026-06-03. File:line references are from that audit — re-confirm before
> editing.

---

## Progress (updated 2026-06-04)

**C4 is COMPLETE** — Phase A (evidence gate) + the full Phase B deletion chain
landed; the G4 soak was dev-skipped by explicit decision (no live canary).
`execute_run` and `execution_engine.py` are deleted and the AgentLoop is the
sole run engine. Phase B specifics: PR-5 `StepEngine` extraction; PR-6 async
child dispatch as the loop's sole child path (parity candidate drainer-driven);
PR-7 `RecursiveExecutor` mapped onto the planner (the "recursive" name was a
misnomer — it just ran `execute_run`); PR-8 every entry point loop-only; PR-9
the irreversible deletion + child-callback plumbing + `agent_loop.enabled`.
Fallout: C2 (MemoryRouter retrieval delete, memory v2 unconditional), C3-finish,
C13 (engine_type/RecursiveReasoningEngine deleted, reasoning via reasoning_hint).
Original Phase-A notes below.

**Phase A is complete** — the suspend/resume mechanism is proven end-to-end:

- **PR-1** ✅ (`5aa0a25`) — multi-child PROCESS positive parity case (G1, inline).
  `child_fixtures` seeding + plan-step `entity_id` wiring; extract compares the
  logical output, not the uuid-laden envelope.
- **PR-1b** ✅ (`dd16a35`) — loop emits `result_data["steps"]` (snapshotted
  `AgentState.step_results`), matching legacy; the refine flow (`service.py`)
  reads it. Discovered while building PR-1.
- **PR-2** ✅ (`4b762c5`) — **first E2E** of suspend→child→resume→complete via the
  in-process arq drainer (`tests/parity/worker_sim.py`); async parity green
  (G1, async). `governance.max_concurrent_children` cap + `CHILD_RUN_QUEUE`
  config (not routed).
- **PR-3** ✅ (`4882886`) — resumability chaos (G2: crash before resume → durable
  WAITING → fresh-worker recovery → idempotency) + cost amplification guard
  (G3: async child-execution work == inline). `tests/parity/c4_resumability.py`.

All C4 gate checks (G1/G2/G3) run inside the single aggregated parity test
(`test_agent_loop_parity`) for the one-event-loop constraint. **558 unit +
parity green, lint green.**

**Not done / gating Phase B:**
- **PR-4 (G4 flag soak)** — operational: needs `governance.async_child_dispatch`
  ON for a live canary + real telemetry over time. Cannot run in the keyless dev
  env. Analogous to the Stage-0 telemetry gate that this dev build deliberately
  skipped — the human runs it in prod, or it is dev-skipped by decision.
- **Phase B (PR-5..PR-9)** — the irreversible deletion chain — remains **gated on
  G4** per §3. Not started.

---

## 0. TL;DR

- The hard part — the async child suspend/resume loop — is **already coded**
  (`child_entity._dispatch_async`, `agent_loop.{_drive,resume,_fold_children,
  _maybe_resume_parent,_persist_suspended}`, `arq_jobs.resume_parent_run`,
  `WAITING_ON_CHILDREN` status). It has **unit** coverage but **no worker-driven
  E2E validation**. The flag is OFF.
- The work that remains is therefore mostly **(a) prove the mechanism end-to-end
  (parity + chaos)**, then **(b) re-route every `execute_run` caller to the
  loop, extract `StepEngine`, re-platform the recursive path, and delete
  `execute_run`.**
- **New finding (expands the design's §6 caller list):** `execute_run` is also
  called **directly, bypassing the loop and the `agent_loop.enabled` flag**, by
  the gateway dispatcher (`gateway/dispatcher.py:272`) and the gateway-event
  worker (`arq_jobs.py:290`), plus `resume_execution` (`arq_jobs.py:719`). These
  must be re-platformed too — the design doc only listed the arq main-dispatch
  branch, the in-loop executors, and the child callback. **Full inventory in §2.**
- **Sequence is non-negotiable:** parity gate green → chaos test green → flag ON
  + soak + cost guard → *then* deletions, executor-by-executor, each revertable.

---

## 1. Current state (what is already built)

| Piece | Location | State |
|------|----------|-------|
| `WAITING_ON_CHILDREN` status + transitions | `schemas/enums.py` | ✅ in tree |
| `ActionResult.awaiting_children` | `core/executors/base.py` | ✅ |
| `AgentState.awaiting_children` (snapshotted) + transient `suspend_requested` | `core/agent_state.py` | ✅ |
| `StepExecutorService.create_child_run` (creation split from inline run) | `step_executor.py:171` | ✅ |
| `ChildEntityExecutor._dispatch_async` (create child → enqueue `run_execution_recursive` → return marker) | `core/executors/child_entity.py:129` | ✅ |
| Loop suspend/resume tail (`_drive`/`_loop`/`resume`/`_fold_children`/`_persist_suspended`/`_maybe_resume_parent`) | `core/agent_loop.py:194,252,312,1145,1178` | ✅ |
| `resume_parent_run` arq job (idempotent) | `core/arq_jobs.py:722` + `worker.py:38` | ✅ |
| Unit tests (state machine, snapshot round-trip, fold, resume guard, dispatch enqueue) | `tests/unit/test_async_child_dispatch.py` | ✅ 11 tests |
| **Worker-driven E2E (multi-child PROCESS that completes; resumability under crash)** | `tests/parity/`, `tests/chaos/` | ❌ **missing — the gate** |
| **Flag** `governance.async_child_dispatch` | default **OFF** | dormant |

**Implication:** do **not** re-build the mechanism. The first phase is to *prove*
it, then progressively retire the legacy fallbacks it sits beside.

---

## 2. Complete `execute_run` caller inventory

Every path that must be neutralized before the method can be deleted. (Grep:
`execute_run\b` minus defs/`_execute_run_fn`/`run_execution_recursive`.)

### 2a. Top-level dispatch (run entry points)
1. **arq main dispatch** — `arq_jobs.run_execution_recursive` else-branch
   (`arq_jobs.py:157-159`): `agent_loop.enabled` False → `engine.execute_run`.
2. **Gateway dispatcher (direct, flag-bypassing)** — `gateway/dispatcher.py:272`:
   constructs `ExecutionEngine` and calls `execute_run` inline. **Ignores
   `agent_loop.enabled`.**
3. **Gateway-event worker (direct, flag-bypassing)** — `arq_jobs.process_gateway_event`
   (`arq_jobs.py:290`): same pattern.
4. **`resume_execution` job** — `arq_jobs.py:719`: resumes a checkpointed run via
   `execute_run`. (Distinct from `resume_parent_run`, which already drives
   `AgentLoop.resume`.)
5. **Enqueue-by-name `"execute_run"`** — `cortex_bridge.py:357`,
   `arq_jobs.py:801`. ⚠️ **`"execute_run"` is not in `worker.py`'s registered
   `functions`** (only `run_execution_recursive`/`resume_execution`/
   `resume_parent_run`/…). These enqueues are therefore **dead or latently
   broken** today; confirm and either delete or repoint to
   `run_execution_recursive` as a pre-req cleanup.

### 2b. In-loop executors (delegate into the engine)
6. **`RecursiveExecutor`** — `core/executors/recursive.py:44`: hands the **entire
   run** back to `engine.execute_run(state.run_id)`. The deepest coupling after
   the child callback; needs a genuine re-platform (§6).
7. **`SingleStepExecutor`** — `core/executors/single_step.py:104`: calls
   `engine._execute_step_wrapper` (a step method, **not** `execute_run`).
8. **`DAGExecutor`** — `core/executors/dag.py:57`: calls
   `engine._execute_steps_dag` (step method).
9. **`ChildEntityExecutor` inline branch** — `core/executors/child_entity.py:86`:
   calls `engine._execute_step_wrapper`, which for a `CHILD_ENTITY_INVOCATION`
   step funnels through `step_executor._execute_child_invocation` →
   `self._execute_run_fn(child_run.id)` = `execute_run` (`step_executor.py:320`).
   The async branch (`_dispatch_async`) avoids this; the inline branch is the
   one C4 removes.

### 2c. The child-execution callback (the real blocker)
10. **`execute_run_fn=self.execute_run`** injected into `StepExecutorService`
    (`execution_engine.py:79,93`), consumed at `step_executor.py:106,320`. Every
    inline child runs by recursively calling `execute_run`.

### 2d. What deleting `execute_run` frees (verified)
`execute_run` is a single ~830-line method (`execution_engine.py:448`→~1280; no
other `def` in that range). **All** of the engine's `MemoryRouter` uses
(`:676,:761,:1088`) and its `MetaReviewer` use (`:990`) live **inside
`execute_run`**, never in the step methods (`_execute_step_wrapper` is `:307-429`,
`_execute_steps_dag` `:106-266`). Therefore:
- Deleting `execute_run` removes the last engine `MemoryRouter` callers → **C2**
  (`MemoryRouter` body delete + assembler v2-only) becomes safe.
- It removes the engine `MetaReviewer` use; `MetaReviewer` **stays** (the loop's
  `RealCriticPipeline` uses it, `critic_pipeline.py:490`) → **C3** reduces to the
  already-landed `CortexRouter` alias removal.
- **To-confirm during PR-5:** the extracted `StepEngine` (the step methods) has
  **zero** `MemoryRouter` references (audit says yes); if a step method pulls KB
  via `MemoryRouter`, C2 stays partially blocked until that read moves to
  `MemoryAssemblyService`.

---

## 3. The gate (must be green before ANY deletion)

This is the §7 gate from the design doc, made concrete. **No PR in §5 phase B
merges until all four are green and the flag has soaked.**

- **G1 — Parity: a multi-child PROCESS that completes.** `tests/parity/` already
  has the golden file `goldens/research_process_pipeline.json`, but per the
  README it **fails identically on both engines under the hermetic mock** — i.e.
  the child path has *no positive coverage*. Build a PROCESS case (2–3 children)
  that completes hermetically, record its legacy golden, and assert the loop +
  async dispatch reproduces status/cost/steps/output. Harness:
  `tests/parity/{harness,hermetic,extract}.py`; cases under
  `tests/regression/cases/*.yaml` (see `test_agent_loop_parity.py:38`).
- **G2 — Resumability chaos test.** New `tests/chaos/` case: drive a parent to
  `WAITING_ON_CHILDREN`, kill/drop the worker, start a fresh worker, assert
  `resume_parent_run` → `AgentLoop.resume` folds the children and completes.
  (Mirror the existing chaos tests' style.)
- **G3 — Cost regression guard.** On a 3-child PROCESS, assert per-run settled
  cost stays within tolerance of the legacy golden — the specific guard against
  the historical **~$11/child amplification**. Children each carry their own
  `Budget`; the parent folds the *settled* child cost once on resume.
- **G4 — Flag soak.** `governance.async_child_dispatch` ON for a canary entity;
  PROCESS runs complete, no orphaned `WAITING_ON_CHILDREN` rows, resume latency
  acceptable, G3 holds in the wild.

> Until G1–G4 hold, the inline `_execute_run_fn` fallback stays and nothing in
> phase B is deleted. The flag is the one-click rollback **only while
> `execute_run` still exists** — after PR-9 there is no legacy path.

---

## 4. Worker topology (decide before G4)

The design's open question, resolved as a recommendation:

- Add a **dedicated child queue** with its own concurrency cap so a fan-out burst
  of children can't starve top-level runs (and vice-versa). arq supports
  multiple queues; route `run_execution_recursive` for child runs onto a
  `children` queue, top-level onto `default`.
- **Fan-out cap** per parent (new `governance.max_concurrent_children`, default
  small) to bound fleet load.
- **Nested depth**: the resume token / `parent_run_id` chain already exists;
  cap with the existing `governance.max_recursion_depth`.

This can ship as part of PR-2 (it only affects the async path while the flag is
OFF for everyone else).

---

## 5. PR sequence

Each PR is independently revertable and independently verified
(`pytest tests/unit -o addopts="" -q` + `tests/parity` green; new tests added by
the PR pass). Phase A is safe now; **phase B is gated on §3**.

### Phase A — prove the mechanism (no deletion, flag stays OFF)

- **PR-1 — Parity: multi-child PROCESS positive case (G1).**
  Add the hermetic PROCESS fixture + record its legacy golden; assert loop parity
  with the flag OFF (inline children) first, to establish the baseline the async
  path must match. *Files:* `tests/parity/`, `tests/regression/cases/`.
  *Risk:* low. *Exit:* a green positive child-path parity case.

- **PR-2 — Async-dispatch parity + worker topology (G1 cont.).**
  Run the PR-1 case with `async_child_dispatch` ON in the hermetic harness;
  assert identical RunResult. Add the `children` queue + `max_concurrent_children`
  cap (§4). *Files:* `tests/parity/`, `core/arq_jobs.py`, `worker.py`,
  `governance/*`, `core/executors/child_entity.py`. *Risk:* low (flag-gated).

- **PR-3 — Resumability chaos test (G2) + cost guard (G3).**
  *Files:* `tests/chaos/`, `tests/parity/` (cost assertion). *Risk:* low.

- **PR-4 — Canary soak (G4).** Flag ON for one entity; collect telemetry; no code
  delete. Gate-keeper for phase B.

### Phase B — re-platform & delete (gated on §3 all-green)

- **PR-5 — Extract `StepEngine`.** Split `ExecutionEngine` into:
  - `core/step_engine.py :: StepEngine` — `_execute_step_wrapper`,
    `_execute_steps_dag`, `_ensure_services`, `_enforce_cost_cap`,
    `_evaluate_hitl_checkpoints`, CORTEX helpers. **No `execute_run`.** Audit for
    zero `MemoryRouter` refs (§2d).
  - `ExecutionEngine(StepEngine)` — keeps only `execute_run` +
    `_get_reconciled_plan` for now.
  - Repoint `single_step` / `dag` / `child_entity` executors to construct
    `StepEngine` instead of `ExecutionEngine`. *Risk:* med (broad import move);
    parity is the safety net. *Exit:* loop step execution runs on `StepEngine`;
    parity green.

- **PR-6 — Drop the child callback.** Make `async_child_dispatch` the default for
  child execution (remove the inline `_execute_run_fn` branch in
  `step_executor._execute_child_invocation` and `child_entity` inline branch);
  remove `execute_run_fn=` from `StepExecutorService` construction
  (`execution_engine.py:79,93`) and the `_execute_run_fn` field + the superseded
  `_dispatch_child_async`. *Depends:* PR-5, §3. *Risk:* high → guarded by G1–G4.

- **PR-7 — Re-platform `RecursiveExecutor`.** Replace
  `engine.execute_run(state.run_id)` (`recursive.py:44`) with recursive goal
  expansion driven through loop iterations / `StepEngine` (the
  `RecursiveReasoningEngine` already exists; wire its leaves through `StepEngine`
  rather than the full legacy run). This is the **hardest** PR — see §6.
  *Depends:* PR-5. *Risk:* high.

- **PR-8 — Make every entry point loop-only.** Re-route the §2a callers:
  - `arq_jobs.run_execution_recursive`: remove the `else → execute_run` branch;
    `agent_loop.enabled` stops gating engine choice (becomes unconditional).
  - `gateway/dispatcher.py:272` and `arq_jobs.process_gateway_event:290`: dispatch
    via `AgentLoop.run` (or enqueue `run_execution_recursive`) instead of inline
    `execute_run`.
  - `resume_execution` (`arq_jobs.py:719`): drive `AgentLoop.resume`/`run`.
  - Resolve the dead `enqueue_job("execute_run", …)` calls
    (`cortex_bridge.py:357`, `arq_jobs.py:801`). *Risk:* med. *Exit:* no caller
    of `execute_run` remains except the executors deleted in PR-6/PR-7.

- **PR-9 — Delete `execute_run`.** Remove the method (+ the now-thin
  `ExecutionEngine` subclass / merge into `StepEngine` if nothing else remains),
  the `agent_loop.enabled` master switch, and the legacy goal-guard/meta-review
  shims that only served it (`goal_guard.py:62`, `core/meta_review.py` legacy
  note). *Exit:* `grep -rn 'execute_run\b' backend/src/ai` returns only history
  comments. *Risk:* high — the keystone; no rollback after this (flag is gone).

### Phase C — the deletions that fall out

- **PR-10 — C2.** Delete the `MemoryRouter` retrieval body + the
  `memory_pipeline="v1"` branch in `memory/assembler.py`; keep
  `LegacyEpisodicReader`; make `memory.v2_canonical` unconditional. *Now safe* —
  the only engine callers lived in `execute_run`.
- **PR-11 — C3 finish.** Confirm `MetaReviewer` retained for
  `RealCriticPipeline`; remove any remaining dead `meta_review_enabled` engine
  plumbing. (`CortexRouter` alias already removed in C3-partial.)

---

## 6. The `RecursiveExecutor` re-platform (PR-7, the hard part)

`RecursiveExecutor.execute` currently calls `engine.execute_run(state.run_id)` —
it does not run *a step*, it runs *the whole legacy engine on the same run*. The
strategist selects it for a **goal-only AGENT with no static plan**
(`strategist.py:141-147`). So this is a live, reachable path, not dead code.

Re-platform options, in order of preference:
1. **Drive `RecursiveReasoningEngine` through the loop.** The recursive engine
   already decomposes a goal into a subgoal tree; route each **leaf** through
   `StepEngine._execute_step_wrapper` (or as child runs via the async dispatch
   mechanism for sub-entities), folding results into `AgentState` across loop
   iterations — never calling `execute_run`. This makes recursion "just another
   executor" that emits steps/children.
2. **Map recursion onto planning.** Have the planner expand the goal into a plan
   (it already supports goal-only planning via `_ensure_plan`,
   `agent_loop.py:948`); then the normal `single_step`/`dag` path handles it and
   `RecursiveExecutor` is retired. Cleaner long-term; larger behavioral surface.

Either way: **parity must include a goal-only AGENT recursive case** (add to G1)
before this PR, or recursion is exactly the regression risk R1 warns about.

---

## 7. Risks & rollback

| ID | Risk | Mitigation |
|----|------|-----------|
| R1 | A child/recursive workload the canary didn't cover regresses | G1 parity (incl. recursive + multi-child), staging soak, cost guard G3; phase B gated on green |
| R2 | Cost amplification recurs | G3 hard assertion; per-child `Budget`; parent folds settled cost once |
| R3 | Orphaned `WAITING_ON_CHILDREN` runs on crash | G2 chaos test; the sweeper (reuse resume machinery) re-enqueues `resume_parent_run` for runs whose children are all terminal |
| R4 | Hidden entry point still hits `execute_run` after PR-9 | §2 inventory is the checklist; PR-8 closes 2a; add a unit test asserting no `execute_run` call sites remain |
| R5 | Irreversibility | Rollback = flag OFF, valid **only before PR-9**. Land PR-5..PR-8 behind the flag; PR-9 only after a full soak with zero legacy traffic |

**Rollback posture:** every phase-B PR before PR-9 leaves the flag-OFF inline
path intact, so reverting the PR (or flipping the flag) restores legacy
behavior. PR-9 is the point of no return — treat it as a release gate.

---

## 8. Effort & sequencing

```
Phase A (prove): PR-1 parity+ ─ PR-2 async parity+topology ─ PR-3 chaos+cost ─ PR-4 soak
                                      │  (G1–G4 gate)
                                      ▼
Phase B (delete): PR-5 StepEngine ─ PR-6 drop child callback ─ PR-7 recursive
                  ─ PR-8 loop-only entry points ─ PR-9 delete execute_run
                                      │
                                      ▼
Phase C (fallout): PR-10 C2 (MemoryRouter) ─ PR-11 C3 finish
```

- Phase A: **M** (mostly tests + flag-gated topology).
- Phase B: **L–XL** (PR-5 and PR-7 are the cost centers).
- Phase C: **M** (mechanical once execute_run is gone).

This is a multi-PR programme, not a single Stage-1 cut — consistent with why
Phase 11 deferred it. The ordering constraint is absolute: **prove (A) → delete
(B) → fall out (C)**; do not reorder.

---

## 9. Pre-flight checklist (re-confirm before starting — audit may have drifted)

- [ ] `execute_run` still a single method at `execution_engine.py:448`; line refs
      in §2 still valid.
- [ ] `MemoryRouter`/`MetaReviewer` uses still entirely inside `execute_run`
      (re-run the §2d grep).
- [ ] `governance.async_child_dispatch` still default OFF; the suspend/resume tail
      in §1 still present.
- [ ] The dead `enqueue_job("execute_run", …)` calls (§2a #5) — confirm
      registered job names in `worker.py`; decide delete vs repoint.
- [ ] Parity harness still hermetic + no LLM key required; goldens re-recordable
      via `scripts/record_golden_runs.py`.
