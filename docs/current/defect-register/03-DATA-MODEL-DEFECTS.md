# 03. Database & Data Model — Defect Register

> **What this document is:** defects in the schema itself — missing migrations, missing
> constraints, missing indexes, wrong column types — plus the improvements that would
> make the database cheaper to query and safer to change.
> **Source document:** [`03-data-model.md`](../03-data-model.md)
> **Compiled:** 2026-09-01, against branch `fresh-main`.
> **Context:** ~40 live tables, 52 Alembic revisions, one head. There are no paying
> tenants, so a schema change today is far cheaper than the same change later.

---

## How to read this file

- **✅ Verified** — the model file, migration or SQL script was read on 2026-09-01.
- **📄 Doc-reported** — from `03-data-model.md`, not independently re-checked.
- Schema defects are different from code defects: most of them are invisible until the
  data grows or two writers collide. Severity here reflects **what happens when the
  platform gets busy**, not what happens today.

---

## Contents

1. [Summary](#1-summary)
2. [T0 — The database cannot be rebuilt correctly](#2-t0--the-database-cannot-be-rebuilt-correctly)
3. [T1 — Missing constraints and indexes](#3-t1--missing-constraints-and-indexes)
4. [T2 — Wrong types and dead tables](#4-t2--wrong-types-and-dead-tables)
5. [T3 — Traps that produce wrong answers](#5-t3--traps-that-produce-wrong-answers)
6. [Improvements](#6-improvements)
7. [Suggested order of work](#7-suggested-order-of-work)

---

## 1. Summary

| Tier | Theme | Count | When to do it |
|---|---|---|---|
| [T0](#2-t0--the-database-cannot-be-rebuilt-correctly) | The database cannot be rebuilt correctly | 3 | Now — a fresh deploy is broken today |
| [T1](#3-t1--missing-constraints-and-indexes) | Missing constraints and indexes | 6 | Before data volume grows |
| [T2](#4-t2--wrong-types-and-dead-tables) | Wrong types and dead tables | 6 | Opportunistically |
| [T3](#5-t3--traps-that-produce-wrong-answers) | Traps that produce wrong answers | 5 | Document now, fix when touched |

**Total: 20 defects, 10 improvements.**

The three worth reading first:

- **[DM-01](#dm-01--subscription_tiers-has-no-migration)** — a table the code depends on
  is created by no migration at all.
- **[DM-02](#dm-02--phone_numbers-is-created-by-a-script-not-a-migration)** — the same
  problem for the phone inventory.
- **[DM-04](#dm-04--billing_events-has-no-unique-constraint)** — the monthly billing
  table has no unique key, so every revenue report can over-count.

---

## 2. T0 — The database cannot be rebuilt correctly

A fresh database built with `alembic upgrade head` is **missing two tables the running
code needs**. This is the highest-value group in this file because it is invisible on
an existing database and fatal on a new one.

### DM-01 — `subscription_tiers` has no migration

**✅ Verified · Critical**

The table is referenced by the ORM (`SubscriptionTier` in `billing_models.py`), by the
credits router, and by the seed path. Nothing in `backend/migrations/` creates it.

Reproduce:

```bash
grep -rl subscription_tiers backend/migrations/
```

That returns nothing. A database built purely from Alembic will not have the table, and
every subscription route fails at the first query.

- [`billing/billing_models.py`](../../../backend/src/billing/billing_models.py) — `SubscriptionTier`
- Also recorded as **D-06** in the platform register

**Fix:** write the migration. It should also seed the three tiers the frontend falls
back to, so the fallback stops being load-bearing.

---

### DM-02 — `phone_numbers` is created by a script, not a migration

**✅ Verified · Critical**

`phone_numbers` — the whole phone-number inventory — is created by
`backend/migrations/merge_phone_tables.py`, a **standalone Python script** that lives
next to the Alembic `versions/` folder but is not part of the chain. It runs raw
`CREATE TABLE` SQL.

The only thing the Alembic chain creates is the legacy `phone_number_pool`, which the
script then drops.

So the documented setup sequence has a manual step between `alembic upgrade head` and
`seed_admin_user.py`, and forgetting it leaves the platform without a phone inventory.

- [`backend/migrations/merge_phone_tables.py`](../../../backend/migrations/merge_phone_tables.py) — the `CREATE TABLE` at line 49
- [`backend/migrations/versions/a1b2c3d4e5f6_add_onboarding_and_phone_pool.py`](../../../backend/migrations/versions/a1b2c3d4e5f6_add_onboarding_and_phone_pool.py) — creates the *legacy* table only

**Fix:** convert the script into a real Alembic revision. Keep it idempotent so
existing databases are unaffected.

---

### DM-03 — `feature_flags` has no ORM model and is optional

**✅ Verified · Medium**

The table exists only in a migration and is queried with raw SQL from
`core/feature_flags.py`. There is no SQLAlchemy model, so `alembic autogenerate` cannot
see it and will never propose changes to it.

The service is written to tolerate the table being absent — lookups fall through to env
vars and code defaults rather than raising. That is good for resilience and bad for
diagnosis: a database missing the table behaves exactly like a database where every
flag happens to be at its default.

- [`backend/migrations/versions/p11t02_feature_flags.py`](../../../backend/migrations/versions/p11t02_feature_flags.py)
- [`ai/core/feature_flags.py`](../../../backend/src/ai/core/feature_flags.py)

**Fix:** add the ORM model. Keep the fallback, but log once at startup when the table is
missing.

---

## 3. T1 — Missing constraints and indexes

### DM-04 — `billing_events` has no unique constraint

**✅ Verified · High**

`class BillingEvent` has no `__table_args__` and no `UniqueConstraint`. The logical
upsert key is `(company_id, period_month, grouping_type, grouping_value)` and nothing
enforces it.

Two consequences:

1. Two settlements running concurrently for the same month insert **two rows** instead
   of one updating the other.
2. Every report that sums this table over-counts by exactly the number of duplicates,
   silently.

The only index on the table is `idx_billing_events_grouping` on
`(grouping_type, grouping_value)` — which does not help.

- [`billing/billing_models.py`](../../../backend/src/billing/billing_models.py) — `class BillingEvent`
- Also recorded as **D-07** in the platform register

**Fix:** add the unique constraint and switch the write to `ON CONFLICT DO UPDATE`.
De-duplicate existing rows in the same migration.

---

### DM-05 — `execution_runs` has no index on `company_id` or `entity_id`

**✅ Verified · High**

The only index on `execution_runs` besides the primary key is the partial idempotency
index on `idempotency_key WHERE NOT NULL`.

Every "list my runs" query filters on `company_id`. Every "runs for this agent" query
filters on `entity_id`. Both are sequential scans over the whole table, for every
tenant, forever. This is the table that grows fastest.

- [`ai/orm/execution.py`](../../../backend/src/ai/orm/execution.py) — `ExecutionRun`

**Fix:** add `(company_id, created_at DESC)` and `(entity_id, created_at DESC)`. Both
are the shape the list endpoints actually use.

---

### DM-06 — Log tables have no indexes at all

**✅ Verified · Medium**

`llm_interaction_logs` and `tool_interaction_logs` have no indexes beyond the primary
key (`tool_interaction_logs` also has the partial idempotency one). Every query filters
on `run_id`. The trace viewer, the cost reports and the tool-efficacy dashboard all read
these tables.

- [`ai/orm/execution.py`](../../../backend/src/ai/orm/execution.py) — `LLMInteractionLog`, `ToolInteractionLog`

**Fix:** index `run_id` on both. It is a one-line migration and the tables only grow.

---

### DM-07 — `document_chunks.embedding` has no ANN index

**✅ Verified · Medium**

`cortex_nodes.embedding` gets a proper HNSW index (`vector_cosine_ops`, `m=16`,
`ef_construction=64`). `document_chunks.embedding` gets nothing.

So the legacy knowledge-base search — the one behind the `/knowledge` page and the
`DOCUMENT` context source — is a **full sequential scan with a cosine distance computed
per row** on every query. It is fast today only because the table is small.

- [`ai/orm/document.py`](../../../backend/src/ai/orm/document.py) — `DocumentChunk`

**Fix:** add the same HNSW index. Or, better, finish the migration to CORTEX Knowledge
Trees and drop the v1 path — see
[08 — Memory & CORTEX](08-MEMORY-AND-CORTEX-DEFECTS.md).

---

### DM-08 — `tool_registry_entries.name` is globally unique across tenants

**📄 Doc-reported · Medium**

`company_id` is nullable on this table (NULL means a built-in tool), but `name` carries
a **global** unique constraint. So two tenants cannot both register a custom tool called
`crm_sync`. The second one gets a database error from an operation that should be
tenant-local.

- [`ai/orm/tools.py`](../../../backend/src/ai/orm/tools.py)

**Fix:** make it unique on `(company_id, name)` with a partial unique index for the
`company_id IS NULL` built-in case.

---

### DM-09 — Log tables have no tenant column, so an unjoined query sees everything

**✅ Verified · High**

There is no row-level security and no global query filter. Tenant isolation is a
`WHERE company_id = ...` written by hand in every service method.

These tables have **no `company_id` at all** and can only be scoped by joining their
parent:

| Table | Must join through |
|---|---|
| `llm_interaction_logs` | `execution_runs` |
| `tool_interaction_logs` | `execution_runs` |
| `human_approvals` | `execution_runs` |
| `document_chunks` | `documents` |
| `campaign_calls` | `campaigns` |
| `call_content` | `call_logs` |
| `cortex_nodes`, `cortex_edges` | `cortex_trees` |

Any query on one of them that forgets the join has **no tenant filter whatsoever**. It
returns every tenant's rows and looks perfectly correct in review.

`execution_trace_events` has a `company_id` but it is denormalised with **no foreign
key**, so nothing stops it drifting from the run's real owner.

**Fix:** add a denormalised `company_id` to the high-traffic log tables and index it.
Redundancy is the right trade here — a forgotten join becomes a wrong-but-scoped query
instead of a cross-tenant leak.

---

## 4. T2 — Wrong types and dead tables

| ID | Problem | Why it matters | Status |
|---|---|---|---|
| **DM-10** | The legacy `assets` table was never dropped | The artifacts migration says it "leaves `assets` in place (dropped last after verification)". That follow-up migration does not exist. `op.drop_table('assets')` appears only in the **downgrade** path of the migration that created it | ✅ Verified |
| **DM-11** | Four numeric values are stored as text | `episodic_memories.total_cost_usd` is `String(20)`, `documents.file_size` is `String`, `document_chunks.chunk_index` is `String`, `companies.default_daily_credits` is `String`. Sorting `chunk_index` gives `1, 10, 11, 2`. Summing a cost means casting in every query | ✅ Verified |
| **DM-12** | Every `DateTime` column is naive | No `timezone=True` anywhere. UTC is a convention held up only by `datetime.utcnow` defaults. One `datetime.now()` slipping in anywhere produces silently wrong timestamps | ✅ Verified |
| **DM-13** | `JSON` on old tables, `JSONB` on new ones | `JSON` cannot be indexed usefully and re-parses on every read. The split runs right through the entity table — the nine config columns are plain `JSON` | ✅ Verified |
| **DM-14** | Three columns are literally named `metadata` | `campaigns`, `campaign_calls` and `cortex_edges`. SQLAlchemy reserves `metadata` on the declarative class, so each maps a different Python attribute. Writing `campaign.metadata` returns the table metadata object, not the JSON, and does so **without raising** | ✅ Verified |
| **DM-15** | `clean_db.sql` truncates by a hand-maintained list | New tables are not covered until someone adds them. Currently missing: `cortex_edges`, `execution_trace_events`, `source_trust_scores`, `feature_flags`, `lead_queue`, `phone_numbers`. A "clean" dev database keeps stale rows in six tables | ✅ Verified |

---

## 5. T3 — Traps that produce wrong answers

### DM-16 — Soft delete has no default filter

**✅ Verified · High**

Only `hierarchical_entities` is soft-deleted. Deletion sets `status = 'DELETED'` and
`deleted_at`, recursively across descendants.

There is **no default query filter**. Every query must add
`.where(status != "DELETED")` itself. Any query that forgets returns deleted agents as
if they were live — in the entity list, in a template clone, in a child resolution.

- [`ai/service.py:203`](../../../backend/src/ai/service.py:203) — the delete path
- [`ai/orm/entity.py`](../../../backend/src/ai/orm/entity.py) — no filter

**Fix:** a SQLAlchemy `with_loader_criteria` default, or a query helper that every
service is required to use. Relying on discipline has already failed once — the index
`idx_entities_not_deleted` exists precisely because someone noticed the scans.

---

### DM-17 — Run status transitions are advisory

**📄 Doc-reported · Medium**

`validate_transition` warns but never blocks. Illegal state transitions are therefore
reachable, and the status machine in the docs is a description of intent rather than a
constraint.

Separately, `REPAIRING` is **unreachable**: no other status lists it as an allowed
target, so nothing can ever enter it.

- [`ai/schemas/enums.py`](../../../backend/src/ai/schemas/enums.py) — `VALID_TRANSITIONS`
- Also recorded as **D-35** in the platform register

---

### DM-18 — `artifacts.campaign_id` points at the wrong table

**📄 Doc-reported · Medium**

The column is called `campaign_id` and its foreign key points at
`hierarchical_entities`, not `campaigns`. Any join written from the name will be wrong,
and the database will happily accept an entity id in a column that reads like a
campaign id.

- [`ai/artifact_models.py`](../../../backend/src/ai/artifact_models.py)

**Fix:** rename the column to say what it holds, or repoint the FK. Do not leave a
column whose name contradicts its constraint.

---

### DM-19 — Two migration files share a filename prefix

**✅ Verified · Low**

`a1b2c3d4e5f6_add_voice_and_whatsapp_streaming_tables.py` and
`a1b2c3d4e5f6_add_onboarding_and_phone_pool.py` share the prefix `a1b2c3d4e5f6_`, but
the second one's `revision` variable is `y2z3a4b5c6d7`.

Alembic keys off the variable, so the chain is correct. Anyone grepping by revision id
finds the wrong file.

---

### DM-20 — Some migrations are defensively idempotent because environments drifted

**✅ Verified · Low**

Several migrations call `sa.inspect(bind)` and skip work when a table or column already
exists (`p11t02_feature_flags`, `y2z3a4b5c6d7`). The document is honest about why: some
environments were stamped past migrations that never actually ran.

That pattern hides the drift instead of fixing it. A database can be at head and still
be missing a column, and nothing reports it.

**Fix:** a schema-census check comparing `__tablename__` and columns against the live
database. It is the second of the four guardrails named in the platform register.

---

## 6. Improvements

### DM-I1 — Add the indexes the queries already assume

**Effect: large, cheap.** [DM-05](#dm-05--execution_runs-has-no-index-on-company_id-or-entity_id)
and [DM-06](#dm-06--log-tables-have-no-indexes-at-all) together are four index
statements. `execution_runs`, `llm_interaction_logs` and `tool_interaction_logs` are the
three fastest-growing tables in the database and none of them is indexed on the column
every query filters by. Do this before anything else in this file.

### DM-I2 — Denormalise `company_id` onto the log tables

**Effect: large.** See [DM-09](#dm-09--log-tables-have-no-tenant-column-so-an-unjoined-query-sees-everything).
Adding `company_id` to `llm_interaction_logs`, `tool_interaction_logs` and
`human_approvals` does two things at once: it removes a join from every reporting query,
and it turns a forgotten filter from a cross-tenant leak into a scoped query.

### DM-I3 — Partition or archive `execution_trace_events`

**Effect: large over time.** This table gets one row per span — dozens per iteration,
hundreds per run — and it is pure observability. It is deliberately kept out of CORTEX
so it can be pruned independently, but **nothing prunes it**.

Add a retention job, or partition by month and drop old partitions. Decide the retention
window now, while the table is small.

### DM-I4 — Move the nine entity JSON columns to `JSONB`

**Effect: medium.** They are the most-read JSON in the system — every dispatch reads
`capabilities`, `planning` and `governance`. `JSONB` parses once at write instead of on
every read, and supports GIN indexing so "which entities use tool X" stops being a full
scan with Python-side filtering.

### DM-I5 — One `updated_at` trigger instead of `onupdate` in Python

**Effect: small.** `onupdate=datetime.utcnow` only fires on ORM updates. Any raw SQL
update — and there is plenty of raw SQL, especially around `feature_flags` and pgvector
— leaves `updated_at` stale. A database trigger is correct for both paths.

### DM-I6 — Give the CORTEX tables a tenant column

**Effect: medium.** `cortex_nodes` and `cortex_edges` can only be scoped by joining
`cortex_trees`. They are also the biggest tables in the memory subsystem and the target
of every vector search. The same argument as DM-I2 applies, with more force because the
search SQL is hand-written and easy to get wrong.

### DM-I7 — Make `clean_db.sql` derive its table list

**Effect: small, prevents confusion.** Query `information_schema.tables` and truncate
everything except the explicit keep-list (`subscription_tiers`, built-in
`tool_registry_entries`, `alembic_version`). The current hand-maintained array is
already six tables out of date.

### DM-I8 — Cast the four text-numeric columns

**Effect: medium.** [DM-11](#4-t2--wrong-types-and-dead-tables) is four `ALTER COLUMN
... USING ...::numeric` statements. Doing it now, with little data, is a five-minute
migration. Doing it after a year of rows is a maintenance window.

### DM-I9 — Add a schema census to the merge gate

**Effect: medium.** Compare every `__tablename__` and column against the database built
from `alembic upgrade head` on a clean instance. That single check would have caught
[DM-01](#dm-01--subscription_tiers-has-no-migration) and
[DM-02](#dm-02--phone_numbers-is-created-by-a-script-not-a-migration) the day they were
introduced. Blocked on there being any CI at all — see
[19 — Testing](19-TESTING-DEFECTS.md).

### DM-I10 — Store money as one type everywhere

**Effect: small.** Today there are three scales in use: `Numeric(10,4)` for run cost,
`Numeric(18,6)` for usage cost, `Numeric(14,6)` for billed amount. Sums across them
round at different points. Pick one scale for internal cost and one for customer-facing
charges, and use them consistently.

---

## 7. Suggested order of work

| Step | Work | Why here |
|---|---|---|
| **1** | DM-I1 — the four missing indexes | Minutes of work, immediate effect, zero risk |
| **2** | DM-01, DM-02 | A fresh database is broken today. These two migrations fix it |
| **3** | DM-04 | The unique constraint on `billing_events`, before any real revenue is reported |
| **4** | DM-11 / DM-I8, DM-13 / DM-I4 | Type migrations, cheapest while the tables are small |
| **5** | DM-09 / DM-I2, DM-I6 | Tenant columns on the log and memory tables |
| **6** | DM-16 | A default soft-delete filter, so the next forgotten `WHERE` is not a bug |
| **7** | DM-I3 | Decide the trace retention policy before the table forces the decision |

---

## Where to go next

- [03 — Data model](../03-data-model.md) — the source document.
- [`DEFECT-REGISTER.md`](../DEFECT-REGISTER.md) — DM-01 is D-06, DM-04 is D-07,
  DM-10 is D-28, DM-17 is D-35.
- [04 — Auth, RBAC & tenancy](04-AUTH-RBAC-TENANCY-DEFECTS.md) — the enforcement side of
  DM-09 and DM-16.
- [14 — Billing & credits](14-BILLING-AND-CREDITS-DEFECTS.md) — what DM-04 costs.
- [08 — Memory & CORTEX](08-MEMORY-AND-CORTEX-DEFECTS.md) — for DM-07 and DM-I6.
