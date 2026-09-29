# 08. Memory, CORTEX & Retrieval — Defect Register

> **What this document is:** defects in what an agent remembers and how that memory comes
> back — the CORTEX trees, the four memory domains, embeddings, RAG and the dreaming
> pipeline — plus the improvements that would make memory pay for itself.
> **Source document:** [`08-memory-and-cortex.md`](../08-memory-and-cortex.md)
> **Compiled:** 2026-09-01, against branch `fresh-main`. **Last reviewed:** 2026-09-29, on
> branch `roadmap-development-defect-fixes`.
> **Context:** the headline finding was
> [MC-01](#mc-01--cortex-is-write-only-on-the-live-path) — CORTEX was written and never
> read. It is fixed, along with every defect that stopped memory from working or learning.
> Every remaining defect is **deferred**: none blocks memory from reaching prompts or
> Dreaming from learning.

---

## How to read this file

- **✅ Verified** — the code was read and the claim held (2026-09-01, re-checked
  2026-09-29 for every open entry).
- **📄 Doc-reported** — from `08-memory-and-cortex.md`, not independently re-checked.
- **Status** — `fixed` (with commit), or `deferred` (real, not scheduled; pick up on
  request).
- Much of `src/ai/memory/` is a thin re-export shim. The real implementation lives in
  `backend/cortex_memory/`, a local copy of the `hb-cortex-memory` package, which is
  maintained in its own repository. If a file is under ~100 lines and says "host re-export
  shim", read there. Changes to `backend/cortex_memory/` must be ported back to the package
  repository.

---

## Contents

1. [Summary](#1-summary)
2. [T0 — Memory that is written and never read](#2-t0--memory-that-is-written-and-never-read)
3. [T1 — Silent failure and silent no-ops](#3-t1--silent-failure-and-silent-no-ops)
4. [T2 — Structural gaps](#4-t2--structural-gaps)
5. [T3 — Inconsistency and cost](#5-t3--inconsistency-and-cost)
6. [Improvements](#6-improvements)
7. [Where this register stands](#7-where-this-register-stands)

---

## 1. Summary

| Tier | Theme | Count | Fixed | Deferred |
|---|---|---|---|---|
| [T0](#2-t0--memory-that-is-written-and-never-read) | Memory that is written and never read | 3 | 3 | 0 |
| [T1](#3-t1--silent-failure-and-silent-no-ops) | Silent failure and silent no-ops | 5 | 2 | 3 |
| [T2](#4-t2--structural-gaps) | Structural gaps | 5 | 1 | 4 |
| [T3](#5-t3--inconsistency-and-cost) | Inconsistency and cost | 7 | 3 | 4 |

**Total: 20 defects (9 fixed, 11 deferred), 11 improvements (4 done).**

| ID | Defect | Status |
|---|---|---|
| MC-01 | CORTEX is write-only on the live path | ✅ fixed `f8db3b0` |
| MC-02 | The scheduled dreaming job has never run | ✅ fixed `bb4f01e` |
| MC-03 | Intelligence rules are distilled and never consumed | ✅ fixed `bb4f01e` |
| MC-05 | `memory_pipeline="v1"` is accepted and ignored | ✅ fixed `a30bb85` |
| MC-06 | Every retrieval failure is silent | ⏸ deferred |
| MC-07 | `FULL` and `RUN_SCOPED` memory scopes are identical | ✅ fixed `f8db3b0` |
| MC-09 | `recurse()` creates a run and does not enqueue it | ⏸ deferred |
| MC-10 | CORTEX tables have no foreign keys to host tables | ⏸ deferred |
| MC-11 | The vector dimension is hard-coded in two places | ⏸ deferred |
| MC-12 | `document_chunks.embedding` has no ANN index | ✅ resolved `a30bb85` |
| MC-13 | The pgvector index is not in the model definition | ⏸ deferred |
| MC-14 | Two chunkers with different sizes | ⏸ deferred |
| MC-15 | The viewport's current node ignores `max_chars` | ⏸ deferred |
| MC-16 | Invariant 1 raises during ordinary development | ⏸ deferred |
| MC-18 | The legacy episodic table is still read | ✅ fixed `a30bb85` |
| MC-19 | Adding an internal context key requires two edits or a test fails | ⏸ deferred |
| MC-21 | Dreaming skips every episode it does not consolidate | ✅ fixed `a617dd3` |
| MC-22 | Dreaming's token budgets truncate thinking-model answers | ✅ fixed `a617dd3` |
| MC-23 | Episodes appear twice in the memory block | ⏸ deferred |
| MC-24 | Scheduled CORTEX resume never enqueues, and loses the schedule | ⏸ deferred |

**Removed on 2026-09-29** by product decision: MC-04 (embedding every node is accepted),
MC-08 (the 5-run / 24-hour Dreaming thresholds are intended), MC-17 (moot — nothing ever
retires a rule; see [MC-I11](#mc-i11--enforce-the-intelligence-rule-lifecycle)), and
MC-20 (carried by [MC-I10](#mc-i10--decide-where-cortex_memory-lives)). Their IDs are not
reused.

---

## 2. T0 — Memory that is written and never read

### MC-01 — CORTEX is write-only on the live path

**✅ Verified · Critical** · **Status: fixed (2026-09-28, `f8db3b0`)** — the loop
assembles memory once per run (`run_memory.assemble_run_memory`, gated by
`capabilities.memory`); `__memory__` reaches the step prompt (sandwich layer 9),
rules reach the planner and — through the Perceiver's `RunMemory` — the supervisor
critic. Episodes are recorded at run end (`a30bb85`). Child runs still drop the
parent's memory keys by design: each child assembles its own entity's memory.
Verified live on a deep-research run: a seeded Intelligence rule appeared in the
director's planner prompts, and `__memory__` held the rule, a company knowledge-base
document and past runs.

The write side is fully wired. `StepEngine` constructs a `CortexBridge` and uses it on
every step:

| Write operation | Called from |
|---|---|
| `write_step` | every step completion |
| `ingest_tool_result` | scraper and browser results become knowledge nodes |
| `write_reflection` | the reflector |
| `write_checkpoint` / `buffer_node` / `flush_buffer` | checkpointing |

The read side had **no production callers at all**:

| Read operation | Callers found in `backend/src` (2026-09-01) |
|---|---|
| `assemble_memory` — builds the whole `__memory__` block | **none** |
| `CortexBridge.get_relevant_knowledge` | **none** |
| `CortexBridge.refresh_viewport` | **none** |
| `CortexBridge.get_knowledge_tree_references` | **none** |

And the one place that would consume it was hard-wired off:

```python
self.perceiver = Perceiver(db=self.db, cortex=self.cortex, memory_assembler=None)
```

`step_executor` went further and actively **stripped** `__memory__`,
`__episodic_memory__`, `__semantic_context__`, `__memory_context__` and
`__context_sources__` out of a child's context.

So the platform wrote every step into a tree, embedded nodes at real cost, ran dreaming
to distil intelligence rules, maintained four memory domains and a semantic graph — and
injected **none of it** into any prompt. An agent's tenth run knew exactly what its first
run knew.

See also [AK-05](05-AGENT-KERNEL-DEFECTS.md#ak-05--perception-is-written-every-iteration-and-read-by-nothing)
and [AK-06](05-AGENT-KERNEL-DEFECTS.md#ak-06--the-perceivers-richest-fields-are-always-empty)
— the kernel-side view of the same gap.

---

### MC-02 — The scheduled dreaming job has never run

**✅ Verified · High** · **Status: fixed (2026-09-28, `bb4f01e`)** — `dreaming_worker` and
`graph_maintenance_worker` are registered, and graph maintenance has a daily cron
(03:45). Registering alone was not enough: the cron wrapped the worker's `ArqRedis`
in `ArqRedis(...)`, which raises on every enqueue, and it selected entities by
`capabilities.dreaming.enabled` — a key the `Capabilities` schema drops, so nothing
ever matched. It now uses the worker pool directly and selects memory-enabled
entities. Graph maintenance runs one global pass instead of re-decaying every edge
once per company. Verified live: the sweep enqueued and completed 5 dreams, and
maintenance ran. `cortex_resume_scheduled` has the same `ArqRedis(...)` bug — recorded
as [MC-24](#mc-24--scheduled-cortex-resume-never-enqueues-and-loses-the-schedule).

`dreaming_cron_trigger` is registered as a cron and fires at 00:15, 06:15, 12:15 and
18:15. It enqueued by string name:

```python
await arq.enqueue_job("dreaming_worker", entity_id, company_id, False)
```

`dreaming_worker` was **imported** by `worker.py` but did not appear in
`WorkerSettings.functions`. The worker rejected every job the cron scheduled.

Only the outcome-triggered path (`dreaming_outcome_trigger`) worked, so consolidation
happened only when a run finished, subject to the 24-hour gate.

`graph_maintenance_worker` — edge-weight decay and pruning of the semantic graph — was in
the same position and had **no caller at all**.

- Same defect as [SA-06](02-SYSTEM-ARCHITECTURE-DEFECTS.md#sa-06--the-6-hourly-dreaming-cron-enqueues-a-job-the-worker-cannot-run)

---

### MC-03 — Intelligence rules are distilled and never consumed

**✅ Verified · High** · **Status: fixed (2026-09-28, `bb4f01e`)** — with MC-01 the rules
reach the step prompt, planner and supervisor critic; the post critic now reads them too
(`RunMemory.top_rules`, rendered from rule dicts). Rules reach prompts without any
confirmation step — the lifecycle is not enforced; see
[MC-I11](#mc-i11--enforce-the-intelligence-rule-lifecycle). `CriticCalibrator` still never
writes its findings (PC-22).

Rules were meant to earn their way into prompts through a lifecycle: `candidate` →
`confirmed` at three net validations. `CriticCalibrator` writes calibration findings into
the same tree weekly.

Nothing read them. `intelligence_reader` was hard-coded to `None` in the critic pipeline
construction, and `assemble_memory` — the other consumer — had no callers
([MC-01](#mc-01--cortex-is-write-only-on-the-live-path)).

- Also recorded as [PC-04](07-PLANNING-AND-CRITICS-DEFECTS.md#pc-04--the-post-critic-never-sees-intelligence-rules)

---

## 3. T1 — Silent failure and silent no-ops

### MC-05 — `memory_pipeline="v1"` is accepted and ignored

**✅ Verified · Medium** · **Status: fixed (2026-09-28, `a30bb85`)** — the argument,
`MemoryRouter` and `LegacyEpisodicReader` were deleted.

`assemble_memory(..., memory_pipeline: str = "v2")` documented the argument as "retained
for call-site compatibility; ignored (always v2)". The memory README described
`memory_service.py` as "reachable only when `memory_pipeline='v1'`" — it was not reachable
at all.

---

### MC-06 — Every retrieval failure is silent

**✅ Verified · High** · **Status: deferred (2026-09-29)**

Every domain assembler catches broad `Exception`, logs at `debug`, and returns `[]`.

An agent whose memory retrieval is broken — bad credentials, a missing index, a schema
mismatch — behaves **exactly** like an agent that has not learned anything yet. There is
no error, no metric, and nothing on the run trace.

This is why [MC-01](#mc-01--cortex-is-write-only-on-the-live-path) could exist unnoticed:
the observable behaviour of "memory not wired" and "memory returning nothing" is
identical.

> **2026-09-29:** now that MC-01 is fixed, memory reaches every memory-enabled run, so
> this matters more than when it was written. The five swallow sites are in the package:
> knowledge, runtime references, experience, intelligence and episodic retrieval in
> `cortex_memory/assembly.py` (lines ~144–270). The host logs a `WARNING` only when the
> whole assembly fails (`run_memory.assemble_run_memory`), not when one domain does.

- [`cortex_memory/assembly.py`](../../../backend/cortex_memory/assembly.py)
- [`ai/memory/run_memory.py`](../../../backend/src/ai/memory/run_memory.py)

**Fix:** count retrieval failures and surface them on the run trace. `[]` from an error
and `[]` from an empty tree must be distinguishable.

---

### MC-07 — `FULL` and `RUN_SCOPED` memory scopes are identical

**📄 Doc-reported · Medium** · **Status: fixed (2026-09-28, `f8db3b0`)** —
`RUN_SCOPED` now means what `MemoryConfig` documents: reference knowledge only,
nothing learned from other runs.

Both mapped to all four memory domains. The builder offered them as different choices and
they produced the same behaviour.

---

### MC-09 — `recurse()` creates a run and does not enqueue it

**📄 Doc-reported · Medium** · **Status: deferred (2026-09-29)**

`recurse()` creates the CORTEX node and the `execution_runs` row, and returns. The caller
must push the job to Arq itself.

Any caller that forgets leaves a `PENDING` run that will never execute and never be
cleaned up — the same silent-stall shape as
[SA-I4](02-SYSTEM-ARCHITECTURE-DEFECTS.md#sa-i4--give-the-worker-a-health-signal).

> **2026-09-29:** the main caller, `CortexBridge` (`ai/memory/cortex_bridge.py:346`),
> does enqueue. The `cortex_router.py:259` path is the one to check.

---

### MC-24 — Scheduled CORTEX resume never enqueues, and loses the schedule

**✅ Verified · High** · **Status: deferred (2026-09-29)** — recorded 2026-09-29; first
noted while fixing MC-02.

`cortex_resume_scheduled` wakes suspended trees whose `next_resume_at` has passed. For
each tree it creates a `PENDING` run, clears `next_resume_at`, then enqueues with
`ArqRedis(ctx['redis'])`. `ctx['redis']` is already an `ArqRedis`; wrapping it again raises
— the bug MC-02 fixed in the dreaming cron.

The exception is caught per tree, and the loop's single `commit()` runs afterwards. So
every scheduled resume commits a `PENDING` run that is never enqueued **and** clears the
tree's schedule. The tree is never woken again, and nothing reports it. Even without the
wrap, the job is enqueued before the run row is committed, so a fast worker can look for a
run that does not exist yet.

- [`ai/core/arq_jobs.py:682`](../../../backend/src/ai/core/arq_jobs.py:682) — `cortex_resume_scheduled`; the wrap at `:726`

**Fix:** use `ctx['redis']` directly, commit the run before enqueueing, and only clear
`next_resume_at` once the enqueue succeeded.

---

## 4. T2 — Structural gaps

### MC-10 — CORTEX tables have no foreign keys to host tables

**📄 Doc-reported · High** · **Status: deferred (2026-09-29)** — latent: there is no
company-deletion code path today.

A deliberate design choice: the `cortex_memory` package owns its own declarative `Base`,
and external references (`company_id`, `entity_id`, `execution_run_id`) are opaque
nullable UUIDs.

The consequence is that **deleting a company leaves orphaned trees**, nodes and edges
forever. There is no cascade and no cleanup job. Referential integrity is
application-level, and no application code enforces it.

At current volume this is invisible. It becomes a data-retention and privacy problem the
first time a tenant asks for their data to be deleted.

- [`cortex_memory/db.py`](../../../backend/cortex_memory/db.py)

**Fix:** a deletion job that walks trees by `company_id` when a company is removed. It
does not need foreign keys, it needs an owner. See
[MC-I4](#mc-i4--give-cortex-data-an-owner-and-a-lifecycle).

---

### MC-11 — The vector dimension is hard-coded in two places

**✅ Verified · Medium** · **Status: deferred (2026-09-29)**

`_CORTEX_EMBEDDING_DIM = 768` in `cortex_providers.py`, and `Vector(768)` on
`cortex_nodes.embedding` in the package model.

Switching to any embedding model with a different width — which the model-resolution
chain permits, since it reads whatever is configured in `integration_registry` — breaks
every insert with a dimension mismatch. There is no validation at model-selection time.

> **2026-09-29:** the second `Vector(768)`, on `document_chunks`, went with that table
> (`a30bb85`). The two places are now the host constant and the package column.

- [`ai/memory/cortex_providers.py:28`](../../../backend/src/ai/memory/cortex_providers.py:28)
- [`cortex_memory/models.py:165`](../../../backend/cortex_memory/models.py:165)

**Fix:** validate the resolved model's dimension against the column at startup, and fail
loudly rather than at the first insert.

---

### MC-12 — `document_chunks.embedding` has no ANN index

**✅ Verified · Medium** · **Status: resolved (2026-09-28, `a30bb85`)** — the v1 RAG
path was retired: `document_chunks` is dropped and document search runs over
Knowledge Tree chunks on the HNSW-indexed `cortex_nodes.embedding`.

`cortex_nodes.embedding` gets an HNSW index. `document_chunks.embedding` got none, so
the legacy RAG search was a sequential scan computing cosine distance per row.

Same entry as [DM-07](03-DATA-MODEL-DEFECTS.md#dm-07--document_chunksembedding-has-no-ann-index).

---

### MC-13 — The pgvector index is not in the model definition

**✅ Verified · Medium** · **Status: deferred (2026-09-29)**

The HNSW index on `cortex_nodes.embedding` exists only in a migration, not in the ORM
model (`cortex_memory/models.py` declares only the tree indexes). So `alembic
autogenerate` cannot see it, and a database built by any other route will silently do
sequential scans.

There is no startup check that the index exists.

---

### MC-14 — Two chunkers with different sizes

**📄 Doc-reported · Medium** · **Status: deferred (2026-09-29)**

`KnowledgeTreeService` chunks at 500 characters with 50 overlap.
`CortexIngestionPipeline` chunks at 2000 with no overlap. Which one runs depends on which
ingestion path the document took.

So the same document ingested two ways produces different chunks, different embeddings and
different retrieval behaviour, with nothing recording which path was used.

> **2026-09-29:** uploaded documents now take only the 500/50 Knowledge Tree path
> (`process_document`, `a30bb85`). The 2000-character split remains as a fallback inside
> `cortex_memory/knowledge_tree.py` and in the ingestion pipeline used for tool results.

---

## 5. T3 — Inconsistency and cost

### MC-15 — The viewport's current node ignores `max_chars`

**📄 Doc-reported · Medium** · **Status: deferred (2026-09-29)** — still latent.

The bounded viewport exists to cap how much context memory can consume. The **current**
node is rendered outside that budget, so a node with a large summary blows the limit by
itself.

> **2026-09-29:** MC-01 delivered memory through `__memory__`, not through the viewport.
> The Perceiver still builds `viewport_text`, but no prompt consumes it
> ([AK-05](05-AGENT-KERNEL-DEFECTS.md#ak-05--perception-is-written-every-iteration-and-read-by-nothing)),
> so this stays latent until the viewport reaches a prompt. Fix it in that change.

---

### MC-16 — Invariant 1 raises during ordinary development

**📄 Doc-reported · Low** · **Status: deferred (2026-09-29)**

`write()` raises `ValueError` if the parent node has no `summary`. It is a real invariant
— an unsummarised parent breaks viewport rendering — but it fires as a hard exception at
write time, far from the code that created the parent.

**Fix:** generate a placeholder summary at node creation, or raise at creation time where
the fix is obvious.

---

### MC-18 — The legacy episodic table is still read

**📄 Doc-reported · Medium** · **Status: fixed (2026-09-28, `a30bb85`)** —
`episodic_memories`, its reader and the backfill script are gone; episodes live only
in Episodic Trees.

`episodic_memories` was v1 memory. `legacy_episodic_reader.py` still read it, and the
backfill script `episodic_to_trees.py` existed to migrate it into v2 Episodic Trees — but
it was a manual, one-off script. So there were two episodic stores, one of them frozen.

---

### MC-19 — Adding an internal context key requires two edits or a test fails

**📄 Doc-reported · Low** · **Status: deferred (2026-09-29)**

A new key must be added to both `constants.py` and `INTERNAL_KEYS.md`, or
`test_internal_keys_documented` fails.

That is a reasonable guard. The cost is that `INTERNAL_KEYS.md` is already stale in at
least one place — it documents `__completed_steps__`, which nothing writes — so the test
enforces that the list is complete, not that it is correct.

---

### MC-21 — Dreaming skips every episode it does not consolidate

**✅ Verified · High** · **Status: fixed (2026-09-28, `a617dd3`)**

`DreamingEngine.dream` stamped `last_consolidated_at` after **every** pass, and the next
pass only read episodes created after that timestamp. A pass with fewer than
`MIN_EPISODES_FOR_DREAMING` new episodes (or a failed LLM call) consolidated nothing but
still moved the watermark — so those episodes were never read again, and a backlog above
`BATCH_SIZE` lost its older half. With the cron and outcome triggers running, an entity
only learned if five runs landed inside one gate window.

**Fix:** episodes are marked individually when consumed
(`metadata_extra.consolidated_at`); each pass takes the oldest pending batch; the
timestamp (the 24-hour gate) only advances when a pass consolidated; passes that
consolidate nothing skip the pattern and distillation phases. Verified live: 5 pending
episodes produced 6 observations, 1 pattern and 1 rule, and none were left pending.

- `cortex_memory/dreaming.py`, `cortex_memory/episodic_tree.py` (package change — port it
  to the package repository)

---

### MC-22 — Dreaming's token budgets truncate thinking-model answers

**✅ Verified · High** · **Status: fixed (2026-09-28, `a617dd3`)**

Observation extraction and distillation used `max_tokens=2000`, pattern recognition 500.
Gemini 2.5 Flash spends part of that on reasoning: at 2000 it returned 79 visible tokens
with `finish=MAX_TOKENS` — a truncated JSON array that parsed as "no observations". So
with the platform's default model Dreaming could never learn anything. Budgets are now
8192 / 4096 / 8192; a live pass produced 6 observations, a pattern and a rule. The
adapter-level fix for every other call site is
[LP-25](10-LLM-PROVIDERS-DEFECTS.md#lp-25--thinking-tokens-consume-max_tokens-so-short-calls-return-truncated-answers).

- `cortex_memory/dreaming.py` (`OBSERVATION_MAX_TOKENS`, `PATTERN_MAX_TOKENS`,
  `DISTILLATION_MAX_TOKENS`) — package change, port it

---

### MC-23 — Episodes appear twice in the memory block

**✅ Verified · Medium** · **Status: deferred (2026-09-29)** — observed on a live run's
`__memory__` block, 2026-09-28.

Episodic assembly merges the five most recent episodes with up to three topic matches and
de-duplicates on `at + input[:50]`. The two lists are built in different shapes:

| List | `input` | `at` |
|---|---|---|
| recent (`get_recent_episodes`) | the run's input field | `created_at.isoformat()` |
| topic (`query_by_topic`) | the node's whole `content` (raw JSON) | `created_at` as returned by the query |

The keys never match, so an episode found by both paths appears twice — once readable,
once as raw JSON. Every memory-enabled run pays for the duplicate tokens, and the raw copy
is noise in the prompt.

- [`cortex_memory/assembly.py`](../../../backend/cortex_memory/assembly.py) — `_retrieve_episodic`, the merge loop

**Fix:** normalise both lists to one shape and de-duplicate on the episode node id. Package
change — port it.

---

## 6. Improvements

### MC-I1 — Wire the read path

**Status: done (2026-09-28, `f8db3b0`)** — see [MC-01](#mc-01--cortex-is-write-only-on-the-live-path).
Memory is assembled through `RunMemory` and delivered as `__memory__`, rather than
through `Perception.to_prompt_block()`.

### MC-I2 — Make memory failures loud

**Effect: large.** [MC-06](#mc-06--every-retrieval-failure-is-silent). Count retrieval
errors, emit a span, and show "memory unavailable" on the run trace. This is what would
have surfaced MC-01 on the first run after it was introduced.

### MC-I3 — Register the two missing worker jobs

**Status: done (2026-09-28, `bb4f01e`)** — see [MC-02](#mc-02--the-scheduled-dreaming-job-has-never-run).

### MC-I4 — Give CORTEX data an owner and a lifecycle

**Effect: medium, becomes urgent later.**
[MC-10](#mc-10--cortex-tables-have-no-foreign-keys-to-host-tables). Two jobs: delete a
company's trees when the company is deleted, and prune or archive nodes past a retention
window. Neither needs foreign keys. Decide the retention window now, while the tables are
small.

### MC-I5 — One chunker

**Effect: medium.** [MC-14](#mc-14--two-chunkers-with-different-sizes). Pick one size and
one overlap and use it on both ingestion paths. Record the chunker version on the node so
a future change can be migrated rather than mixed.

### MC-I6 — Validate the embedding dimension at startup

**Effect: small, prevents a bad day.**
[MC-11](#mc-11--the-vector-dimension-is-hard-coded-in-two-places). Resolve the model,
check its dimension against the column, refuse to start on a mismatch. An admin switching
embedding models should get an error at configuration time, not a wall of failed inserts.

### MC-I7 — Index `document_chunks.embedding` or retire the v1 path

**Status: done (2026-09-28, `a30bb85`)** — the v1 path was retired and its tables dropped.
See [MC-12](#mc-12--document_chunksembedding-has-no-ann-index).

### MC-I8 — Cache the assembled memory block per run

**Status: done (2026-09-28, `f8db3b0`)** — memory is assembled once per run and reused on
every iteration; a resumed run reuses the stored block. Refreshing it when a step writes
something new was not built.

### MC-I9 — Report what memory contributed

**Effect: medium.** Now that memory reaches prompts, the question everyone asks is "is it
helping?". Record which nodes were retrieved and whether the run succeeded; that is the
input `TrustLearner` ([PC-11](07-PLANNING-AND-CRITICS-DEFECTS.md#4-t2--built-and-never-wired))
was built to consume and currently has no source for.

### MC-I10 — Decide where `cortex_memory` lives

**Effect: medium.** Either publish the package and depend on a version, or move it into
`src/ai/memory/` and delete the shims.

The current half-state: fourteen files in `src/ai/memory/` are re-export shims over
`cortex_memory`. The code is maintained in its own repository and published as
`hb-cortex-memory`, pinned at `0.1.0` in `backend/pyproject.toml`, but a local copy lives
at `backend/cortex_memory/`. When the backend runs from `backend/`, `import cortex_memory`
resolves to that copy ahead of the installed wheel, so which implementation runs depends
on the working directory. Fixes made in the copy — MC-21, MC-22, and MC-23 when it is
fixed — must be ported to the package repository by hand. The package's CI workflow
(`.github/workflows/cortex-memory.yml`) matches `backend/cortex_memory/**` again since
`e8d9f62`.

- [`backend/pyproject.toml:53`](../../../backend/pyproject.toml:53)
- Previously recorded as MC-20 (removed 2026-09-29)

### MC-I11 — Enforce the Intelligence-rule lifecycle

**Effect: medium, and it is quality.** The design in
[`08-memory-and-cortex.md` §14](../08-memory-and-cortex.md#14-the-intelligence-rule-lifecycle)
says a distilled rule starts as a `candidate` and only becomes prompt-eligible once
`confirmed` by three net validations, and is `retired` after three net contradictions. The
policy exists (`ai/memory/rule_lifecycle.py`: `next_state`, `filter_for_prompt`), but:

- nothing records validations or contradictions, and nothing calls `next_state`, so no
  rule is ever confirmed or retired;
- Dreaming stamps no lifecycle state on the rules it creates;
- the `memory.rule_lifecycle_confirmed_only` flag defaults to `False`, and only the
  Perceiver applies `filter_for_prompt` — the `RunMemory` path that feeds the planner,
  critics and step prompt does not.

So every rule from any Dreaming pass — including one distilled from a single bad batch —
reaches the planner and critics immediately. To build it: record a validation or
contradiction when a run that used a rule succeeds or fails, advance the state with
`next_state`, and filter on the `RunMemory` path. Consider letting a retired rule return
on fresh evidence (the concern formerly recorded as MC-17).

---

## 7. Where this register stands

- Everything that stopped memory from working or learning is fixed: the read path
  (MC-01), scheduled Dreaming and graph maintenance (MC-02), rules reaching prompts
  (MC-03), and Dreaming's two learning bugs (MC-21, MC-22). The v1 memory path is gone
  (MC-05, MC-12, MC-18).
- Every open defect is **deferred** — real, understood, not scheduled. Pick them up on
  request. If one is picked up, [MC-06](#mc-06--every-retrieval-failure-is-silent) has the
  widest effect now that memory is load-bearing, and
  [MC-24](#mc-24--scheduled-cortex-resume-never-enqueues-and-loses-the-schedule) silently
  breaks every scheduled resume.
- Open improvements: MC-I2, MC-I4, MC-I5, MC-I6, MC-I9, MC-I10, MC-I11.

---

## Where to go next

- [08 — Memory, CORTEX & retrieval](../08-memory-and-cortex.md) — the source document.
- [05 — Agent kernel](05-AGENT-KERNEL-DEFECTS.md) — AK-05 and AK-06 are the loop-side view
  of MC-01 and MC-15.
- [07 — Planning & critics](07-PLANNING-AND-CRITICS-DEFECTS.md) — PC-04 and PC-11 are the
  critic-side view of MC-03.
- [02 — System architecture](02-SYSTEM-ARCHITECTURE-DEFECTS.md) — SA-06 for the unregistered
  worker jobs.
- [03 — Data model](03-DATA-MODEL-DEFECTS.md) — DM-07 and DM-I6 for the vector tables.
- [SESSION-HANDOFF.md](SESSION-HANDOFF.md) — how defect work is picked up.
