# 08. Memory, CORTEX & Retrieval — Defect Register

> **What this document is:** defects in what an agent remembers and how that memory comes
> back — the CORTEX trees, the four memory domains, embeddings, RAG and the dreaming
> pipeline — plus the improvements that would make memory pay for itself.
> **Source document:** [`08-memory-and-cortex.md`](../08-memory-and-cortex.md)
> **Compiled:** 2026-09-01, against branch `fresh-main`.
> **Context:** the headline finding is
> [MC-01](#mc-01--cortex-is-write-only-on-the-live-path). Read it first. Almost
> everything else in this file is a consequence of it or is currently harmless because
> of it.

---

## How to read this file

- **✅ Verified** — the code was read on 2026-09-01 and the claim held.
- **📄 Doc-reported** — from `08-memory-and-cortex.md`, not independently re-checked.
- Much of `src/ai/memory/` is a thin re-export shim. The real implementation lives in
  `backend/cortex_memory_moved_to_pypi_repo/`, installed as the `hb-cortex-memory`
  package. If a file is under ~100 lines and says "host re-export shim", read there.

---

## Contents

1. [Summary](#1-summary)
2. [T0 — Memory that is written and never read](#2-t0--memory-that-is-written-and-never-read)
3. [T1 — Silent failure and silent no-ops](#3-t1--silent-failure-and-silent-no-ops)
4. [T2 — Structural gaps](#4-t2--structural-gaps)
5. [T3 — Inconsistency and cost](#5-t3--inconsistency-and-cost)
6. [Improvements](#6-improvements)
7. [Suggested order of work](#7-suggested-order-of-work)

---

## 1. Summary

| Tier | Theme | Count | When to do it |
|---|---|---|---|
| [T0](#2-t0--memory-that-is-written-and-never-read) | Memory that is written and never read | 4 | **Now** — this is the whole subsystem's value |
| [T1](#3-t1--silent-failure-and-silent-no-ops) | Silent failure and silent no-ops | 5 | Before trusting any memory behaviour |
| [T2](#4-t2--structural-gaps) | Structural gaps | 5 | Before data volume grows |
| [T3](#5-t3--inconsistency-and-cost) | Inconsistency and cost | 6 | When the area is next touched |

**Total: 20 defects, 10 improvements.**

The three to read first:

- **[MC-01](#mc-01--cortex-is-write-only-on-the-live-path)** — every step, tool result
  and reflection is written into CORTEX. **Nothing reads any of it back into a prompt.**
- **[MC-02](#mc-02--the-scheduled-dreaming-job-has-never-run)** — the cron that distils
  memory into rules enqueues a job name the worker cannot execute.
- **[MC-06](#mc-06--every-retrieval-failure-is-silent)** — broken memory and empty memory
  look identical, by design.

---

## 2. T0 — Memory that is written and never read

### MC-01 — CORTEX is write-only on the live path

**✅ Verified · Critical**

The write side is fully wired. `StepEngine` constructs a `CortexBridge` and uses it on
every step:

| Write operation | Called from |
|---|---|
| `write_step` | every step completion |
| `ingest_tool_result` | scraper and browser results become knowledge nodes |
| `write_reflection` | the reflector |
| `write_checkpoint` / `buffer_node` / `flush_buffer` | checkpointing |

The read side has **no production callers at all**:

| Read operation | Callers found in `backend/src` |
|---|---|
| `assemble_memory` — builds the whole `__memory__` block | **none** |
| `CortexBridge.get_relevant_knowledge` | **none** |
| `CortexBridge.refresh_viewport` | **none** |
| `CortexBridge.get_knowledge_tree_references` | **none** |

And the one place that would consume it is hard-wired off:

```python
self.perceiver = Perceiver(db=self.db, cortex=self.cortex, memory_assembler=None)
```

`step_executor` goes further and actively **strips** `__memory__`,
`__episodic_memory__`, `__semantic_context__`, `__memory_context__` and
`__context_sources__` out of a child's context.

So today the platform: writes every step into a tree, embeds nodes at real cost, runs
dreaming to distil intelligence rules, maintains four memory domains and a semantic
graph — and injects **none of it** into any prompt. An agent's tenth run knows exactly
what its first run knew.

- [`ai/core/agent_loop.py:766`](../../../backend/src/ai/core/agent_loop.py:766) — `memory_assembler=None`
- [`ai/memory/assembler.py:19`](../../../backend/src/ai/memory/assembler.py:19) — `assemble_memory`, no callers
- [`ai/memory/cortex_bridge.py:498`](../../../backend/src/ai/memory/cortex_bridge.py:498) — `get_relevant_knowledge`, no callers
- [`ai/step_executor.py:211`](../../../backend/src/ai/step_executor.py:211)–226 — the strip

**Fix:** pass a real assembler to the `Perceiver` and feed `Perception.to_prompt_block()`
into the prompt. This is one argument and one prompt-block insertion, and it is the
difference between having a memory system and paying for one.

See also [AK-05](05-AGENT-KERNEL-DEFECTS.md#ak-05--perception-is-written-every-iteration-and-read-by-nothing)
and [AK-06](05-AGENT-KERNEL-DEFECTS.md#ak-06--the-perceivers-richest-fields-are-always-empty)
— the kernel-side view of the same gap.

---

### MC-02 — The scheduled dreaming job has never run

**✅ Verified · High**

`dreaming_cron_trigger` is registered as a cron and fires at 00:15, 06:15, 12:15 and
18:15. It enqueues by string name:

```python
await arq.enqueue_job("dreaming_worker", entity_id, company_id, False)
```

`dreaming_worker` is **imported** by `worker.py` but does not appear in
`WorkerSettings.functions`. The worker rejects every job the cron schedules.

Only the outcome-triggered path (`dreaming_outcome_trigger`, which *is* registered) works.
So consolidation happens only when a run finishes, subject to the 24-hour gate — the
scheduled sweep across all entities has never happened.

`graph_maintenance_worker` — edge-weight decay and pruning of the semantic graph — is in
the same position and has **no caller at all**, so the graph is never maintained.

- [`ai/worker.py`](../../../backend/src/ai/worker.py) — the `functions` list
- [`ai/core/arq_jobs.py`](../../../backend/src/ai/core/arq_jobs.py) — `dreaming_worker`, `graph_maintenance_worker`
- Same defect as [SA-06](02-SYSTEM-ARCHITECTURE-DEFECTS.md#sa-06--the-6-hourly-dreaming-cron-enqueues-a-job-the-worker-cannot-run)

---

### MC-03 — Intelligence rules are distilled and never consumed

**✅ Verified · High**

Rules earn their way into prompts through a lifecycle: `candidate` → `confirmed` at three
net validations. `CriticCalibrator` writes calibration findings into the same tree weekly.

Nothing reads them. `intelligence_reader` is hard-coded to `None` in the critic pipeline
construction, and `assemble_memory` — the other consumer — has no callers
([MC-01](#mc-01--cortex-is-write-only-on-the-live-path)).

So the rule lifecycle runs to completion and the confirmed rules sit in the tree.

- [`ai/core/agent_loop.py:930`](../../../backend/src/ai/core/agent_loop.py:930) — `intelligence_reader=None`
- Also recorded as [PC-04](07-PLANNING-AND-CRITICS-DEFECTS.md#pc-04--the-post-critic-never-sees-intelligence-rules)

---

### MC-04 — Embeddings are paid for and rarely searched

**✅ Verified · Medium**

`EmbeddingService` embeds every CORTEX node, batches at 100, and writes an attributed
`usage_logs` row per batch with `attribution="embedding"`. That is real, metered spend on
every ingestion.

The search paths that would use those vectors are the ones with no callers
([MC-01](#mc-01--cortex-is-write-only-on-the-live-path)). The CORTEX explorer UI and the
`/documents/search` endpoint do search, so the spend is not entirely wasted — but the
agent-facing retrieval that justifies embedding *every node* does not happen.

- [`ai/memory/embedding_service.py`](../../../backend/src/ai/memory/embedding_service.py)

---

## 3. T1 — Silent failure and silent no-ops

### MC-05 — `memory_pipeline="v1"` is accepted and ignored

**✅ Verified · Medium**

`assemble_memory(..., memory_pipeline: str = "v2")` documents the argument as "retained
for call-site compatibility; ignored (always v2)". The memory README still describes
`memory_service.py` as "reachable only when `memory_pipeline='v1'`" — it is not reachable
at all.

So there are two documented pipelines, one implementation, and a deprecated module kept
alive by a docstring.

- [`ai/memory/assembler.py:26`](../../../backend/src/ai/memory/assembler.py:26)
- [`ai/memory/README.md`](../../../backend/src/ai/memory/README.md)

---

### MC-06 — Every retrieval failure is silent

**📄 Doc-reported · High**

Every domain assembler catches broad `Exception`, logs at `debug`, and returns `[]`.

An agent whose memory retrieval is broken — bad credentials, a missing index, a schema
mismatch — behaves **exactly** like an agent that has not learned anything yet. There is
no error, no metric, and nothing on the run trace.

This is why [MC-01](#mc-01--cortex-is-write-only-on-the-live-path) could exist unnoticed:
the observable behaviour of "memory not wired" and "memory returning nothing" is
identical.

- [`ai/memory/assembler.py:68`](../../../backend/src/ai/memory/assembler.py:68)
- `cortex_memory.assembly` in the installed package

**Fix:** count retrieval failures and surface them on the run trace. `[]` from an error
and `[]` from an empty tree must be distinguishable.

---

### MC-07 — `FULL` and `RUN_SCOPED` memory scopes are identical

**📄 Doc-reported · Medium**

Both map to all four memory domains. The builder offers them as different choices and
they produce the same behaviour.

---

### MC-08 — A new entity learns nothing for five runs, then once a day

**📄 Doc-reported · Medium**

`MIN_EPISODES_FOR_DREAMING = 5` and `CONSOLIDATION_INTERVAL_HOURS = 24`. Below five
completed runs, dreaming does nothing at all; above it, at most once per entity per day.

That is a defensible design for a mature entity and a poor one for the first day of a new
tenant, which is exactly when someone is evaluating whether the platform learns. The
admin trigger's `force=True` bypass exists, but nothing in the product surfaces it.

- `cortex_memory_moved_to_pypi_repo/dreaming.py` — the thresholds

---

### MC-09 — `recurse()` creates a run and does not enqueue it

**📄 Doc-reported · Medium**

`recurse()` creates the CORTEX node and the `execution_runs` row, and returns. The caller
must push the job to Arq itself.

Any caller that forgets leaves a `PENDING` run that will never execute and never be
cleaned up — the same silent-stall shape as
[SA-I4](02-SYSTEM-ARCHITECTURE-DEFECTS.md#sa-i4--give-the-worker-a-health-signal).

---

## 4. T2 — Structural gaps

### MC-10 — CORTEX tables have no foreign keys to host tables

**📄 Doc-reported · High**

A deliberate design choice: the `cortex_memory` package owns its own declarative `Base`,
and external references (`company_id`, `entity_id`, `execution_run_id`) are opaque
nullable UUIDs.

The consequence is that **deleting a company leaves orphaned trees**, nodes and edges
forever. There is no cascade and no cleanup job. Referential integrity is
application-level, and no application code enforces it.

At current volume this is invisible. It becomes a data-retention and privacy problem the
first time a tenant asks for their data to be deleted.

- `cortex_memory_moved_to_pypi_repo/db.py`

**Fix:** a deletion job that walks trees by `company_id` when a company is removed. It
does not need foreign keys, it needs an owner.

---

### MC-11 — The vector dimension is hard-coded in two places

**✅ Verified · Medium**

`_CORTEX_EMBEDDING_DIM = 768` in `cortex_providers.py`, and
`Vector(768)` on `document_chunks.embedding`.

Switching to any embedding model with a different width — which the model-resolution
chain permits, since it reads whatever is configured in `integration_registry` — breaks
every insert with a dimension mismatch. There is no validation at model-selection time.

- [`ai/memory/cortex_providers.py:28`](../../../backend/src/ai/memory/cortex_providers.py:28)
- [`ai/orm/document.py:47`](../../../backend/src/ai/orm/document.py:47)

**Fix:** validate the resolved model's dimension against the column at startup, and fail
loudly rather than at the first insert.

---

### MC-12 — `document_chunks.embedding` has no ANN index

**✅ Verified · Medium**

`cortex_nodes.embedding` gets an HNSW index. `document_chunks.embedding` gets none, so
the legacy RAG search is a sequential scan computing cosine distance per row.

Same entry as [DM-07](03-DATA-MODEL-DEFECTS.md#dm-07--document_chunksembedding-has-no-ann-index).

---

### MC-13 — The pgvector index is not in the model definition

**📄 Doc-reported · Medium**

The HNSW index on `cortex_nodes.embedding` exists only in a migration, not in the ORM
model. So `alembic autogenerate` cannot see it, and a database built by any other route
will silently do sequential scans.

There is no startup check that the index exists.

---

### MC-14 — Two chunkers with different sizes

**📄 Doc-reported · Medium**

`KnowledgeTreeService` chunks at 500 characters with 50 overlap.
`CortexIngestionPipeline` chunks at 2000 with no overlap. Which one runs depends on which
ingestion path the document took.

So the same document ingested two ways produces different chunks, different embeddings and
different retrieval behaviour, with nothing recording which path was used.

---

## 5. T3 — Inconsistency and cost

### MC-15 — The viewport's current node ignores `max_chars`

**📄 Doc-reported · Medium**

The bounded viewport exists to cap how much context memory can consume. The **current**
node is rendered outside that budget, so a node with a large summary blows the limit by
itself.

Since the viewport is not reaching any prompt today
([MC-01](#mc-01--cortex-is-write-only-on-the-live-path)), this is latent. It becomes live
the moment MC-01 is fixed, which is the reason to fix it in the same change.

---

### MC-16 — Invariant 1 raises during ordinary development

**📄 Doc-reported · Low**

`write()` raises `ValueError` if the parent node has no `summary`. It is a real invariant
— an unsummarised parent breaks viewport rendering — but it fires as a hard exception at
write time, far from the code that created the parent.

**Fix:** generate a placeholder summary at node creation, or raise at creation time where
the fix is obvious.

---

### MC-17 — `retired` intelligence rules can never come back

**📄 Doc-reported · Low**

The lifecycle transition is one-way. A rule retired because it looked wrong during one bad
week is gone permanently, even if later evidence supports it.

Given that `CriticCalibrator` computes false-fail rates, the data to un-retire exists.

---

### MC-18 — The legacy episodic table is still read

**📄 Doc-reported · Medium**

`episodic_memories` is v1 memory. `legacy_episodic_reader.py` still reads it, and the
backfill script `episodic_to_trees.py` exists to migrate it into v2 Episodic Trees — but
it is a manual, one-off script.

So there are two episodic stores, one of them frozen, and which one an entity's history
lives in depends on whether someone ran a script.

Same shape as the `assets` table in
[DM-10](03-DATA-MODEL-DEFECTS.md#4-t2--wrong-types-and-dead-tables): a migration that
stopped at "the new thing works".

- [`ai/memory/legacy_episodic_reader.py`](../../../backend/src/ai/memory/legacy_episodic_reader.py)
- [`backend/scripts/migrations/episodic_to_trees.py`](../../../backend/scripts/migrations/episodic_to_trees.py)

---

### MC-19 — Adding an internal context key requires two edits or a test fails

**📄 Doc-reported · Low**

A new key must be added to both `constants.py` and `INTERNAL_KEYS.md`, or
`test_internal_keys_documented` fails.

That is a reasonable guard. The cost is that `INTERNAL_KEYS.md` is already stale in at
least one place — it documents `__completed_steps__`, which nothing writes — so the test
enforces that the list is complete, not that it is correct.

---

### MC-20 — Most of `src/ai/memory/` is shims over an unversioned local package

**✅ Verified · Medium**

Fourteen files in `src/ai/memory/` are under 100 lines and re-export from
`cortex_memory`. The real code lives in `backend/cortex_memory_moved_to_pypi_repo/`,
declared in `pyproject.toml` as `hb-cortex-memory = "0.1.0"`.

The directory name says the package was moved to PyPI; the code is still in this
repository. So there are two possible sources of truth for the memory implementation and
no way to tell from the import which one is installed.

The repository's only CI workflow is pinned to `paths: ["backend/cortex_memory/**"]` — a
path that no longer exists — so this package has no test gate either. See
[19 — Testing](19-TESTING-DEFECTS.md).

- [`backend/pyproject.toml:53`](../../../backend/pyproject.toml:53)
- [`backend/cortex_memory_moved_to_pypi_repo/`](../../../backend/cortex_memory_moved_to_pypi_repo/)

---

## 6. Improvements

### MC-I1 — Wire the read path

**Effect: this is the whole subsystem.** [MC-01](#mc-01--cortex-is-write-only-on-the-live-path).
Concretely:

1. Pass a real `MemoryAssembler` into the `Perceiver`.
2. Feed `Perception.to_prompt_block()` into the step prompt.
3. Pass `intelligence_reader` into the critic pipeline.
4. Stop stripping `__memory__` from child contexts, or strip it selectively.

Until this is done, every other item in this file is about maintaining a system whose
output nobody consumes. Do it before optimising anything else here.

### MC-I2 — Make memory failures loud

**Effect: large.** [MC-06](#mc-06--every-retrieval-failure-is-silent). Count retrieval
errors, emit a span, and show "memory unavailable" on the run trace. This is what would
have surfaced MC-01 on the first run after it was introduced.

### MC-I3 — Register the two missing worker jobs

**Effect: medium.** [MC-02](#mc-02--the-scheduled-dreaming-job-has-never-run). Two names
added to `WorkerSettings.functions`, plus a cron for graph maintenance. Then check whether
four dreaming sweeps a day is actually what you want before leaving it on — with MC-I1
done, dreaming output will finally reach prompts and its quality will start to matter.

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

**Effect: medium.** [MC-12](#mc-12--document_chunksembedding-has-no-ann-index). The
cleaner answer is to finish the migration to Knowledge Trees and drop v1 entirely —
`documents_to_knowledge_trees.py` already exists as a backfill. Two RAG paths with
different indexes, different chunkers and different tenant scoping is more surface than
this feature needs.

### MC-I8 — Cache the assembled memory block per run

**Effect: medium, once MC-I1 lands.** Memory assembly runs four domain queries plus an
embedding call. Doing that every iteration of a 30-iteration run is 30× the cost for
content that changes slowly. Assemble once per run, refresh only when a step writes
something new.

### MC-I9 — Report what memory contributed

**Effect: medium.** Once memory reaches prompts, the question everyone asks is "is it
helping?". Record which nodes were retrieved and whether the run succeeded; that is the
input `TrustLearner` ([PC-11](07-PLANNING-AND-CRITICS-DEFECTS.md#4-t2--built-and-never-wired))
was built to consume and currently has no source for.

### MC-I10 — Decide where `cortex_memory` lives

**Effect: medium.** [MC-20](#mc-20--most-of-srcaimemory-is-shims-over-an-unversioned-local-package).
Either publish it and depend on a version, or move it back into `src/ai/memory/` and
delete the shims. The current half-state means the memory implementation has no test gate
and no clear source of truth.

---

## 7. Suggested order of work

| Step | Work | Why here |
|---|---|---|
| **1** | MC-I1 / MC-01 | Wire the read path. Nothing else in this file matters first |
| **2** | MC-I2 / MC-06 | Make failures loud, so step 1 stays working |
| **3** | MC-15, MC-16 | Fix the viewport budget and the write invariant — both become live the moment MC-01 lands |
| **4** | MC-I3 / MC-02 | Register the two jobs. Dreaming output now has a consumer |
| **5** | MC-I6 / MC-11, MC-13 | Startup validation for the embedding dimension and the index |
| **6** | MC-I5 / MC-14, MC-I7 / MC-12, MC-18 | Consolidate to one chunker and one RAG path |
| **7** | MC-I4 / MC-10 | Retention and deletion. Decide the policy before the tables are large |
| **8** | MC-I8, MC-I9 | Cache the memory block, then measure whether it helps |

---

## Where to go next

- [08 — Memory, CORTEX & retrieval](../08-memory-and-cortex.md) — the source document.
- [05 — Agent kernel](05-AGENT-KERNEL-DEFECTS.md) — AK-05 and AK-06 are the loop-side view
  of MC-01.
- [07 — Planning & critics](07-PLANNING-AND-CRITICS-DEFECTS.md) — PC-04 and PC-11 are the
  critic-side view of MC-03.
- [02 — System architecture](02-SYSTEM-ARCHITECTURE-DEFECTS.md) — SA-06 for the unregistered
  worker jobs.
- [03 — Data model](03-DATA-MODEL-DEFECTS.md) — DM-07 and DM-I6 for the vector tables.
