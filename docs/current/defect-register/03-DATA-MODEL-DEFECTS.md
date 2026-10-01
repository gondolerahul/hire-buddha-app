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
| [T0](#2-t0--the-database-cannot-be-rebuilt-correctly) | The database cannot be rebuilt correctly | 4 | Now — a fresh deploy is broken today |
| [T1](#3-t1--missing-constraints-and-indexes) | Missing constraints and indexes | 6 | Before data volume grows |
| [T2](#4-t2--wrong-types-and-dead-tables) | Wrong types and dead tables | 6 | Opportunistically |
| [T3](#5-t3--traps-that-produce-wrong-answers) | Traps that produce wrong answers | 5 | Document now, fix when touched |

**Total: 21 defects, 10 improvements.**

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

**✅ Verified · Critical** · **Status: fixed (2026-09-30)** — with DM-21.

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

**Done (2026-09-30)** in `dm21_schema_catch_up` (see
[DM-21](#dm-21--a-fresh-database-cannot-be-built-at-all)): the table is created if absent,
with the ORM's columns and the `tier_level` unique constraint, and — only when it holds no
rows — seeded with the wallet page's `FALLBACK_PLANS`: Starter (level 1, 29, 20 %), Growth
(2, 79, 30 %), Scale (3, 199, 40 %). The seed names every column, because a table made by
`create_all` (the local one) has no server-side defaults — the first attempt failed there on
`id`. The frontend fallback is left in place; it no longer shows once tiers exist.

**Evidence:** the schema census (below) finds the table on a fresh database. Local: the
migration seeded the three tiers into the hand-made table.

---

### DM-02 — `phone_numbers` is created by a script, not a migration

**✅ Verified · Critical** · **Status: fixed (2026-09-30)** — with DM-21.

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

**Done (2026-09-30)** in `dm21_schema_catch_up`: `phone_numbers` and its six indexes are
created if absent; rows of `phone_number_pool` and `customer_phone_numbers`, if those
tables exist, are merged in the way the script did (an assignment to a pooled number
updates it, any other becomes an `assigned` row; `ON CONFLICT DO NOTHING`), and both legacy
tables are dropped. `*_old` backups the script made are left alone.
`migrations/merge_phone_tables.py` is deleted — it also hard-coded the local database URL.
The setup sequence no longer has a manual step between `alembic upgrade head` and
`seed_admin_user.py` (half of
[ON-01](20-ONBOARDING-AND-GLOSSARY-DEFECTS.md#on-01--the-setup-sequence-omits-two-required-steps)).

---

### DM-21 — A fresh database cannot be built at all

**✅ Verified · Critical** · **Status: fixed (2026-09-30)** — found 2026-09-30 while
reproducing DM-01. The handoff had noted it as a local quirk; it was never registered.

DM-01 and DM-02 understated the problem: `alembic upgrade head` on an empty database did not
get as far as missing two tables. It **failed**:

- `m0b1e0d1a100` and `m0b1e0d1a200` read a `db-scripts/*.sql` file and passed the whole
  multi-statement string to `op.execute`. `env.py` runs migrations on asyncpg, which prepares
  every statement: *cannot insert multiple commands into a prepared statement*. The whole
  upgrade ran in one transaction, so it rolled back to an empty database.
- Past that point, eleven columns the ORM reads and writes had no migration either — they
  existed only on databases patched by hand:

| Table | Columns |
|---|---|
| `campaign_calls` | `rep_disposition`, `rep_note`, `rep_dispositioned_at`, `rep_dispositioned_by`, `disposition_source`, `callback_at` |
| `execution_runs` | `billed_amount` |
| `llm_interaction_logs` | `step_name` |
| `voice_sessions`, `whatsapp_sessions` | `session_metadata` (the migration created `metadata`) |
| `conversation_history` | `message_metadata` (the migration created `metadata`) |

So a new environment could not be deployed from the repository at all, and every
environment that worked had been patched by hand.

**Fix (2026-09-30):**

- `migrations/sql_script.py` — `execute_sql_file(path)` splits a `.sql` file into
  statements (dropping comments and `BEGIN`/`COMMIT`; refusing `$$` bodies) and executes them
  one by one. Both mobile revisions use it. The files are unchanged, so they still apply
  with `psql`.
- Revision `dm21_schema_catch_up` creates what was missing — with DM-01 and DM-02, the two
  tables — adds the eight columns, and renames the three `metadata` columns to the names the
  ORM maps. Each step checks the live schema first; where a hand-patched database has both
  `metadata` and the new name, the old values fill the new column's gaps and `metadata` is
  dropped.
- `src/common/orm_models.py` and the schema census — see DM-20.

**Evidence:** a scratch database built by `alembic upgrade head` now reaches
`dm21_schema_catch_up`, and the census finds every ORM table and column there
(`tests/integration/test_schema_census.py`, 6 cases; `tests/unit/test_orm_model_registry.py`,
7 cases). The local database (backed up first) was migrated: the three tiers were seeded,
the empty legacy phone tables dropped, the duplicate `metadata` columns merged and dropped;
it now differs from the ORM only by the census's listed exceptions.

- [`migrations/sql_script.py`](../../../backend/migrations/sql_script.py)
- [`migrations/versions/dm21_schema_catch_up.py`](../../../backend/migrations/versions/dm21_schema_catch_up.py)

---

### DM-03 — `feature_flags` has no ORM model and is optional

**✅ Verified · Medium** · **Status: fixed (2026-10-01)**

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

**Done (2026-10-01).** `ai/orm/feature_flags.py` models the table as the migration built it,
the three per-scope partial unique indexes and the company lookup index included; it is in
the shared model list, so autogenerate and the schema census see it (the census no longer
lists `feature_flags` as an exception). The service keeps its raw SQL and its fallback.
`warn_if_table_missing()` runs in the API's startup and logs *feature_flags table is
missing: every flag resolves from env vars and code defaults…* when `to_regclass` finds no
table. (Each failed lookup already logged a warning; the startup line makes the state
visible before any flag is read.)

**Evidence:** `tests/unit/test_feature_flags_table_check.py` — the startup check warns when
the table is absent and not when present; the model is registered. The schema census passes
with the model (the index check covers its four indexes); strict mypy passes over `orm` and
`core`.

---

## 3. T1 — Missing constraints and indexes

### DM-04 — `billing_events` has no unique constraint

**✅ Verified · High** · **Status: fixed (2026-09-30)** — also BC-24 in
[14 — Billing](14-BILLING-AND-CREDITS-DEFECTS.md).

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

**Done (2026-09-30).** The write had a second race besides duplicate rows: when the row
existed, both writers read it and wrote back `their read + their amount`, so one increment
was lost.

- Revision `dm04_billing_event_unique` merges existing duplicates (amounts summed into the
  oldest row of each group, the rest deleted), then adds `uq_billing_events_period_grouping
  (company_id, period_month, grouping_type, grouping_value)` with `NULLS NOT DISTINCT` —
  without it, two ungrouped rows for the same month would both be allowed. That needs
  Postgres 15 (the compose file pins `pgvector:pg15`); the revision refuses to run on an
  older server rather than add a weaker key.
- `record_billing_event` is one `INSERT … ON CONFLICT ON CONSTRAINT … DO UPDATE SET x =
  billing_events.x + excluded.x … RETURNING`, so the add happens in the database, atomically.
  The constraint is declared on the model too.

**Evidence:** `tests/integration/test_billing_event_upsert.py`, against the real Postgres with
real commits: 12 concurrent settlements from separate sessions leave one row holding 12×
every amount; four concurrent ungrouped events share one row; separate groupings and
categories stay apart. The two concurrency cases fail on the old code. The migration was run
on a scratch database seeded with six rows in three groups (two ungrouped): it left three
rows with the amounts summed. The schema census now also checks declared unique
constraints.

---

### DM-05 — `execution_runs` has no index on `company_id` or `entity_id`

**✅ Verified · High** · **Status: fixed (2026-09-30)** — with DM-06.

The only index on `execution_runs` besides the primary key is the partial idempotency
index on `idempotency_key WHERE NOT NULL`.

Every "list my runs" query filters on `company_id`. Every "runs for this agent" query
filters on `entity_id`. Both are sequential scans over the whole table, for every
tenant, forever. This is the table that grows fastest.

- [`ai/orm/execution.py`](../../../backend/src/ai/orm/execution.py) — `ExecutionRun`

**Fix:** add `(company_id, created_at DESC)` and `(entity_id, created_at DESC)`. Both
are the shape the list endpoints actually use.

**Done (2026-09-30)** in revision `dm05_run_indexes`, declared on the model too (so the
census and autogenerate see them): `ix_execution_runs_company_created (company_id,
created_at)` and `ix_execution_runs_entity_created (entity_id, created_at)` — ascending,
because a B-tree is read backwards for `ORDER BY created_at DESC` at no cost — plus
`ix_execution_runs_parent_run_id`, for child-run lookups (the `child_runs` relationship and
the wait-on-children checks).

**Evidence:** the schema census fails with the model change and without the revision (7
missing indexes), and passes with both. On the local database, with sequential scans
disabled so the tiny table does not hide it, the run list query
(`company_id = … AND parent_run_id IS NULL ORDER BY created_at DESC`) uses
`ix_execution_runs_company_created`.

---

### DM-06 — Log tables have no indexes at all

**✅ Verified · Medium** · **Status: fixed (2026-09-30)** — `run_id` is indexed on
`llm_interaction_logs`, `tool_interaction_logs`, and also `human_approvals` and
`usage_logs`, which hang off a run the same way and had no index on it either (revision
`dm05_run_indexes`; `index=True` on the models). A lookup by `run_id` uses the index on the
local database.

`llm_interaction_logs` and `tool_interaction_logs` have no indexes beyond the primary
key (`tool_interaction_logs` also has the partial idempotency one). Every query filters
on `run_id`. The trace viewer, the cost reports and the tool-efficacy dashboard all read
these tables.

- [`ai/orm/execution.py`](../../../backend/src/ai/orm/execution.py) — `LLMInteractionLog`, `ToolInteractionLog`

**Fix:** index `run_id` on both. It is a one-line migration and the tables only grow.

---

### DM-07 — `document_chunks.embedding` has no ANN index

**✅ Verified · Medium** · **Status: invalid (2026-09-28, `a30bb85`)** — the
`document_chunks` table was dropped with the rest of v1 memory. Knowledge-base search now
runs over `cortex_nodes`, which has the HNSW index. Same finding as
[MC-12](08-MEMORY-AND-CORTEX-DEFECTS.md).

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

**📄 Doc-reported · Medium** · **Status: fixed (2026-10-01)**

`company_id` is nullable on this table (NULL means a built-in tool), but `name` carries
a **global** unique constraint. So two tenants cannot both register a custom tool called
`crm_sync`. The second one gets a database error from an operation that should be
tenant-local.

- [`ai/orm/tools.py`](../../../backend/src/ai/orm/tools.py)

**Fix:** make it unique on `(company_id, name)` with a partial unique index for the
`company_id IS NULL` built-in case.

**Done (2026-10-01).** The collision is reachable today through the meta-agent's tool
synthesis, which writes `SYNTHESIZED` rows under the tenant's company (custom tools are
created only by `app_admin`, under the APP company).

- Revision `dm08_tool_name_per_company` drops the global key and adds
  `uq_tool_registry_company_name (company_id, name)` with `NULLS NOT DISTINCT` — one
  constraint instead of two, and built-in rows (no company) stay unique by name. Declared on
  the model; the plain `name` index stays.
- The built-in sync looked rows up by name alone (`get_tool_by_name`, `scalar_one_or_none`),
  which per-company names would break; it is `get_built_in_entry(name)`, built-in rows only.
- **Found while fixing:** `GET /ai/tool-registry`, `GET /ai/tool-registry/{id}` and the
  builder's `GET /ai/tools` returned every tenant's synthesized tools — with their spec,
  source and audit in `configuration` — to any signed-in user. They now show built-ins,
  the platform's own custom tools, and the tools of the companies the caller can see
  (`auth.visibility`); another tenant's tool by id is a 404; `app_admin` sees all. The
  list no longer folds same-named rows of different companies into one.

**Evidence:** `tests/integration/test_tool_registry_tenancy.py` (real Postgres, rolled back),
5 cases — two tenants share a name; one company cannot reuse one; built-in names stay
unique; a tenant lists its own and platform tools but not another tenant's, while
`app_admin` lists all; another tenant's tool is a 404. The two visibility cases fail on the
old code; the schema census passes with the new key.

---

### DM-09 — Log tables have no tenant column, so an unjoined query sees everything

**✅ Verified · High** · **Status: fixed (2026-10-01)** for the run's three log tables and
`execution_trace_events`; the other parent-scoped tables are unchanged (see below).

There is no row-level security and no global query filter. Tenant isolation is a
`WHERE company_id = ...` written by hand in every service method.

These tables have **no `company_id` at all** and can only be scoped by joining their
parent:

| Table | Must join through |
|---|---|
| `llm_interaction_logs` | `execution_runs` |
| `tool_interaction_logs` | `execution_runs` |
| `human_approvals` | `execution_runs` |
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

**Done (2026-10-01), with DM-I2.** Revision `dm09_log_company_id`:

- `llm_interaction_logs`, `tool_interaction_logs` and `human_approvals` each gain
  `company_id NOT NULL`, backfilled from the run. The key `(run_id, company_id) →
  execution_runs(id, company_id)` replaces the plain `run_id` key, so the copy cannot
  differ from the run's company (target: `uq_execution_runs_id_company`). Indexed
  `(company_id, created_at)` on the two logs and `(company_id, status)` on approvals.
- The six writers pass only `run_id`, as before. A `before_insert` hook on the three
  models copies the run's company when it is not given, so a new writer cannot forget it.
- `execution_trace_events.company_id` gets the same composite key (`ON DELETE CASCADE`).
  Its plain `run_id` key stays, because its company may be NULL.
- Readers that joined the run only to scope by company now filter on the column: the
  approvals inbox and answer (`AIService`) and the LLM-performance and tool-efficacy
  reports.
- **Deploy note:** code from before this revision cannot write these logs to a migrated
  database (it inserts no `company_id`). Migrate and restart the API and both workers
  together.

**Left as is:** `campaign_calls`, `call_content`, `cortex_nodes` and `cortex_edges` are still
scoped through their parent. They are not run logs, and the CORTEX search SQL is DM-I6's
subject.

**Evidence:** `tests/integration/test_log_company_scope.py` (real Postgres) checks that a
log written with only `run_id` gets the run's company, that each of the three tables and
trace events refuse another company's id, and that the approvals inbox and both reports
return only the caller's rows unjoined while a run still loads its logs. 5 of 6 fail on
the old code, which cannot write to the new schema. The fresh-database schema census
passes, and the migration was run up, down and up on the local database. Live on the API:
a run's page loads its 7 LLM and 9 tool logs, and `/ai/approvals/pending` plus the
llm-performance, tool-efficacy and hitl-overview reports answer 200.

---

## 4. T2 — Wrong types and dead tables

| ID | Problem | Why it matters | Status |
|---|---|---|---|
| **DM-10** | The legacy `assets` table was never dropped | The artifacts migration says it "leaves `assets` in place (dropped last after verification)". That follow-up migration does not exist. `op.drop_table('assets')` appears only in the **downgrade** path of the migration that created it | ✅ Verified · **fixed (2026-10-01)** — revision `dm10_drop_legacy_assets` drops `assets` and `call_content.audio_asset_id` (kept by the same migration "for one release"; nothing maps either). It first carries over any `call_content` reference not yet on `audio_artifact_id`, and **refuses** to run if an `assets` row has no `artifacts` row with its id, rather than lose it — checked on a scratch database seeded with one uncopied row (the upgrade stopped, the row stayed). The schema census no longer needs either exception |
| **DM-11** | ~~Four~~ Two numeric values are stored as text | `documents.file_size` is `String` and `companies.default_daily_credits` is `String`. Summing or sorting means casting in every query. *(2026-09-28: the other two, `episodic_memories.total_cost_usd` and `document_chunks.chunk_index`, went with their tables in `a30bb85`.)* | ✅ Verified · **fixed (2026-10-01)** — revision `dm11_numeric_columns`: `file_size` is `BIGINT`, `default_daily_credits` is `NUMERIC(10,4)` (the scale of `billing_config.default_daily_credits`, which fills it); a stored value that is not a number becomes NULL instead of failing the upgrade. The writers pass numbers (`knowledge_base.py`, registration and OAuth sign-up); `DocumentResponse.file_size` is an `int` and the Knowledge Base page types it so. Local: one document (652 bytes) and three companies (5.0000 each) converted. The schema census compares column types, so it fails with the models changed and the revision missing |
| **DM-12** | Every `DateTime` column is naive | No `timezone=True` anywhere. UTC is a convention held up only by `datetime.utcnow` defaults. One `datetime.now()` slipping in anywhere produces silently wrong timestamps | ✅ Verified |
| **DM-13** | `JSON` on old tables, `JSONB` on new ones | `JSON` cannot be indexed usefully and re-parses on every read. The split runs right through the entity table — the nine config columns are plain `JSON` | ✅ Verified |
| **DM-14** | Three columns are literally named `metadata` | `campaigns`, `campaign_calls` and `cortex_edges`. SQLAlchemy reserves `metadata` on the declarative class, so each maps a different Python attribute. Writing `campaign.metadata` returns the table metadata object, not the JSON, and does so **without raising** | ✅ Verified · **fixed (2026-10-01)** — the trap was live: `SemanticGraphService.create_edge` built `CortexEdge(..., metadata=metadata)`, which the constructor accepts (the class has a `metadata` attribute) and never stores, so no edge kept its metadata (locally 6 edges, 0 with any). Revision `dm14_metadata_columns` renames the columns to the attributes that map them (`campaign_metadata`, `call_metadata`, `edge_metadata`); `create_edge` passes `edge_metadata=`. `tests/unit/test_metadata_columns.py` checks that no host or CORTEX table has a `metadata` column and that `create_edge` stores what it is given; both fail on the old code. **Package change** (`cortex_memory/models.py`, `graph.py`): port it to the `hb-cortex-memory` repo. A published 0.1.0 still maps column `metadata` and would fail against a migrated database |
| **DM-15** | `clean_db.sql` truncates by a hand-maintained list | New tables are not covered until someone adds them. Currently missing: `cortex_edges`, `execution_trace_events`, `source_trust_scores`, `feature_flags`, `lead_queue`, `phone_numbers`. A "clean" dev database keeps stale rows in six tables | ✅ Verified · **fixed (2026-09-30)** — the script reads the table list from `pg_tables` and truncates everything but `alembic_version` and `subscription_tiers` in one statement. It also had a worse bug: `tool_registry_entries` references `companies` and `users`, so `TRUNCATE companies … CASCADE` emptied it and the "BUILT_IN tools preserved" step found nothing. The BUILT_IN rows are now set aside first and put back (links cleared). Run on a seeded scratch database: the old script left no tools, the new one both BUILT_IN tools, the three tiers and `alembic_version`, and nothing else |

---

## 5. T3 — Traps that produce wrong answers

### DM-16 — Soft delete has no default filter

**✅ Verified · High** · **Status: fixed (2026-09-30)**

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

**Done (2026-09-30)** — the `with_loader_criteria` default. Of 52 ORM queries that select
entities, 13 added the filter by hand; the rest did not, among them the loader that gives a
phone call its agent (`voice/agent_loader.py`), phone-number assignment, the campaign
router, the gateway dispatcher, template cloning, run refinement, the partner console's
entity list and the dashboard's entity count.

- A `do_orm_execute` listener in `ai/orm/entity.py` adds `status != 'DELETED'` to every ORM
  `SELECT` that selects `HierarchicalEntity` or its columns (`session.get` included) unless
  the statement sets `execution_options(include_deleted=True)` (`INCLUDE_DELETED`).
- **Not** filtered: relationship loads — a historical run's `run.entity` still loads, by
  `joinedload` or `selectinload` — statements that only join through entities, and raw SQL.
  The first version attached the criteria to every statement and hid deleted runs' entities
  from `selectinload`: SQLAlchemy's selectin loader copies the parent statement's options
  regardless of `propagate_to_loaders`. The criteria is now attached only when the statement
  itself selects entities.
- Opted out, because they show history: three report queries (HITL overview, a user's run
  history, per-agent error rates — which would otherwise drop deleted agents' runs from the
  totals) and the mobile campaign list (a campaign keeps its agent after deletion).
- Behaviour that changes on purpose: a deleted agent is no longer found when a call,
  campaign dial or dispatch loads it by id, so it can no longer run; it is no longer counted
  as an active entity on the dashboard or listed on the partner console.

**Evidence:** `tests/integration/test_soft_delete_filter.py` (real Postgres, rolled back),
7 cases — entity selects, id selects and `session.get` hide a deleted entity; the opt-out
sees it; a run's entity loads under `joinedload` and `selectinload`; a join through entities
is unaffected; selecting entity columns is filtered unless opted out; the per-agent
error-rate report still counts a deleted agent's run. The integration suite (106 cases)
passes.

---

### DM-17 — Run status transitions are advisory

**✅ Verified · Medium** · **Status: fixed (2026-10-01)** — enforced on every ORM write.

`validate_transition` warns but never blocks. Illegal state transitions are therefore
reachable, and the status machine in the docs is a description of intent rather than a
constraint.

Separately, `REPAIRING` is **unreachable**: no other status lists it as an allowed
target, so nothing can ever enter it.

- [`ai/schemas/enums.py`](../../../backend/src/ai/schemas/enums.py) — `VALID_TRANSITIONS`
- Also recorded as **D-35** in the platform register

**Verified (2026-10-01).** `validate_transition` had no callers at all, so not even the
warning fired. The harm is concrete: the loop's final write did not look at the stored
status, so a run the user cancelled while its last step ran was finished as `COMPLETED`.
And the session (`expire_on_commit=False`) kept a stale status, so the reload before that
write could not see the cancel either.

**Done (2026-10-01).**

- `VALID_TRANSITIONS` now lists every status. The four terminal ones (`COMPLETED`, `FAILED`,
  `PARTIAL_COMPLETE`, `CANCELLED`, exported as `TERMINAL_RUN_STATUSES`) have no outgoing
  edges. `PARTIAL_COMPLETE → RUNNING/COMPLETED/FAILED` went, because nothing used them.
  `PENDING → FAILED` was added: the credit gate fails a run before it starts. `REPAIRING`
  was removed from `RunStatus` and the frontend enum (also AK-15).
- A `set` listener on `ExecutionRun.status` refuses an unlisted transition. It keeps the
  old value and logs a warning rather than raising, so a refused status does not lose the
  rest of the write.
- `AgentLoop._reload_run` reads with `populate_existing`. The final and suspend writes
  also take `FOR UPDATE`, so the guard compares with the stored status.
- `cancel_execution` is one conditional `UPDATE … WHERE status NOT IN (terminal)`. It
  cannot overwrite a run that finished after it was loaded.

**Evidence:** `tests/unit/test_run_status_transitions.py` checks that terminal statuses
are final, that a late `COMPLETED` keeps `CANCELLED`, that the pipeline's paths (credit
refusal, child wait and resume, pause, re-delivered job) are allowed, and that the table
is closed with every status reachable. `tests/integration/test_run_cancel_race.py` (real
Postgres) covers a cancel made behind the loop's back surviving the final write (whose
cost still lands) and a cancel not overwriting a run that finished meanwhile. 23 of these
cases fail on the old code (`5e38d68`).

**Note:** the listener itself landed early, swept into `141a4df` (FE-10) from the shared
working tree. This commit completes it.

---

### DM-18 — `artifacts.campaign_id` points at the wrong table

**📄 Doc-reported · Medium** · **Status: fixed (2026-10-01)** — the FK now points at `campaigns`.

The column is called `campaign_id` and its foreign key points at
`hierarchical_entities`, not `campaigns`. Any join written from the name will be wrong,
and the database will happily accept an entity id in a column that reads like a
campaign id.

- [`ai/artifact_models.py`](../../../backend/src/ai/artifact_models.py)

**Fix:** rename the column to say what it holds, or repoint the FK. Do not leave a
column whose name contradicts its constraint.

**Done (2026-10-01) — repointed.** The name was the truth: the only writer is the artifacts
upload API, whose form field is a campaign id (the Artifacts page also filters by one); no
tool sets it. So a real campaign id violated the key, and an entity id was accepted.

- Revision `dm18_artifact_campaign_fk`: clears any value that is not a campaign id, then
  `artifacts.campaign_id → campaigns.id ON DELETE SET NULL`. The model says so; its unused
  `campaign` relationship (to `HierarchicalEntity`) is dropped rather than repointed, so the
  artifact model does not depend on the campaign model being loaded.
- Entity deletion no longer "nulls the artifacts' campaign reference" by entity id.
- **Found while fixing:** `POST /artifacts/upload` attached the file to whatever
  `campaign_id` and `agent_id` it was given — another company's included; the keys only prove
  the rows exist. It now answers 404 unless both belong to the uploader's company.

**Evidence:** `tests/integration/test_artifact_campaign_link.py` (real Postgres, rolled back)
— a campaign id is accepted and an entity id refused by the key; an upload naming another
company's campaign or agent is a 404 and saves nothing, while the uploader's own are
accepted. The upload case fails on the old code. The schema census passes.

---

### DM-19 — Two migration files share a filename prefix

**✅ Verified · Low** · **Status: fixed (2026-09-30)** — the onboarding/phone-pool file is
renamed `y2z3a4b5c6d7_add_onboarding_and_phone_pool.py`, after its `revision`. The chain is
unchanged.

`a1b2c3d4e5f6_add_voice_and_whatsapp_streaming_tables.py` and
`a1b2c3d4e5f6_add_onboarding_and_phone_pool.py` share the prefix `a1b2c3d4e5f6_`, but
the second one's `revision` variable is `y2z3a4b5c6d7`.

Alembic keys off the variable, so the chain is correct. Anyone grepping by revision id
finds the wrong file.

---

### DM-20 — Some migrations are defensively idempotent because environments drifted

**✅ Verified · Low** · **Status: fixed (2026-09-30)** — the census exists; see below.

Several migrations call `sa.inspect(bind)` and skip work when a table or column already
exists (`p11t02_feature_flags`, `y2z3a4b5c6d7`). The document is honest about why: some
environments were stamped past migrations that never actually ran.

That pattern hides the drift instead of fixing it. A database can be at head and still
be missing a column, and nothing reports it.

**Fix:** a schema-census check comparing `__tablename__` and columns against the live
database. It is the second of the four guardrails named in the platform register.

**Done (2026-09-30).** `tests/integration/test_schema_census.py` creates a scratch database,
runs `alembic upgrade head` into it, and checks every ORM table exists, every ORM column
exists with the same type (`FLOAT` and `DOUBLE PRECISION` are the same type), every declared
index exists, and every database table and column is mapped — or listed with the defect id
that explains it (at first `assets` and `call_content.audio_asset_id` for DM-10 —
dropped since — and `feature_flags` for DM-03). A stale entry in that list fails too. It takes about five
seconds. Nullability is not compared: six columns differ harmlessly (the database is
stricter on five CORTEX/entity flags, the ORM on `source_trust_scores.updated_at`).

The census compares against **every** table because the model list is now one list,
`src/common/orm_models.py`, used by it and by `migrations/env.py` — whose own import list had
lost `voice.phone_pool_models`, so autogenerate could not see `phone_numbers`.
`tests/unit/test_orm_model_registry.py` fails when a module that declares a table is
missing from it. The defensive `inspect` pattern stays in the old migrations: databases
stamped past them exist; the census is what makes the resulting drift visible. It is in
`tests/integration/`, so it runs with the integration suite, not the default host run —
wiring it into a merge gate is still [DM-I9](#dm-i9--add-a-schema-census-to-the-merge-gate).

**Evidence:** on the old code the census fails at the fixture (`alembic upgrade head`
exits non-zero at `m0b1e0d1a100`).

---

## 6. Improvements

### DM-I1 — Add the indexes the queries already assume

**Status: done (2026-09-30)** — DM-05 and DM-06.

**Effect: large, cheap.** [DM-05](#dm-05--execution_runs-has-no-index-on-company_id-or-entity_id)
and [DM-06](#dm-06--log-tables-have-no-indexes-at-all) together are four index
statements. `execution_runs`, `llm_interaction_logs` and `tool_interaction_logs` are the
three fastest-growing tables in the database and none of them is indexed on the column
every query filters by. Do this before anything else in this file.

### DM-I2 — Denormalise `company_id` onto the log tables

**Status: done (2026-10-01)** — DM-09.

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

**Status: done (2026-09-30)** — DM-15.

**Effect: small, prevents confusion.** Query `information_schema.tables` and truncate
everything except the explicit keep-list (`subscription_tiers`, built-in
`tool_registry_entries`, `alembic_version`). The current hand-maintained array is
already six tables out of date.

### DM-I8 — Cast the four text-numeric columns

**Status: done (2026-10-01)** — DM-11; two of the four had gone with v1 memory.

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
