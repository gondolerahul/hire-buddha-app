# Defect-Fixing Session Handoff

> **What this document is:** the state of the defect-fixing work on branch
> `roadmap-development-defect-fixes`. It covers what was fixed, what became invalid, and
> how to pick the work up in a new session. It spans three sessions: the 2026-09-28 →
> 2026-09-29 memory/planner session; the 2026-09-29 → 2026-09-30 session that added
> the HITL, entity-config and health-endpoint fixes and the PO-06 tool-stack audit; and
> the 2026-09-30 session that worked register 02 (System Architecture) and merged every
> endpoint onto port 8000; and the 2026-09-30 → 2026-10-01 session that worked registers
> 03 (Data Model) and 04 (Auth, RBAC and Tenancy).
> **It does not choose what to fix next.** Defects are fixed one at a time, as the
> product owner names them. The registers in this folder are the backlog.
>
> **Where the work is paused (2026-10-01, end of the fourth session):** register 03 is
> done — 20 defects fixed, DM-07 invalid; improvements DM-I1/I2/I4/I7/I8 done, DM-I9
> partly, DM-I3/I5/I6/I10 open. Register 04 has 22 fixed, AU-16 and AU-19 won't fix, and
> **AU-24** and **AU-25** open (AU-24 waits on a key-rotation decision); AU-I2…I6 done,
> AU-I9 partly, AU-I1/I7/I8/I10 open. Registers 01 and 02 are as the third session left
> them (**PO-07** open). Resume on the product owner's next pick. (End of the third
> session, for reference: register 02 done, SA-I1/I3/I7/I8/I9 open.) Left running locally, started with
> `start_services.ps1`: Docker, the API (:8000), both Arq workers and the frontend
> (:3000); `stop_services.ps1` stops them. The previous session's `-alt` servers
> (:8010 API, :3010 frontend) also run; its stale Arq worker was stopped while
> testing the stop script.

---

## Contents

1. [Where things stand](#1-where-things-stand)
2. [Defects fixed in this session](#2-defects-fixed-in-this-session)
3. [Defects that became invalid](#3-defects-that-became-invalid)
4. [Other register changes](#4-other-register-changes)
5. [How a defect is worked](#5-how-a-defect-is-worked)
6. [Register conventions](#6-register-conventions)
7. [Local environment](#7-local-environment)
8. [Testing](#8-testing)
9. [Live end-to-end testing](#9-live-end-to-end-testing)
10. [Things that will bite you](#10-things-that-will-bite-you)

---

## 1. Where things stand

| | |
|---|---|
| Branch | `roadmap-development-defect-fixes`, cut from `main` at `9896b8b` |
| Commits on the branch | Listed below, **none pushed** |
| Working tree | Clean, apart from two spreadsheets the product owner is editing: `Consolidated-Defect-Register.xlsx` and `HireBuddha-Roadmap-Backlog.xlsx`. Leave them uncommitted. Another session may have uncommitted frontend work in progress |
| Alembic head | `au26_email_lowercase`; the local database is at it |
| Host tests | 1315 passed, 7 known failures (see [§8](#8-testing)) |
| Integration tests | 181 passed, 2 known failures (`test_cost_attribution.py`) |
| CORTEX package tests | 49 passed |
| Type check, layout lint | Pass |

Commits, oldest first. The first session (memory/planner):

| Commit | Change |
|---|---|
| `f1f87d0` | Removed stale markdown files outside `docs/` and the design system. The root `README.md` and `mobile/android/README.md` were kept |
| `2189713` | `backend/db-scripts/seed_integration_registry.py`: an idempotent registry seed for local environments |
| `f8db3b0` | MC-01, MC-07 — memory read path |
| `a30bb85` | MC-05, MC-18, MC-12 — legacy v1 memory removed, tables dropped |
| `d894c98` | Docs for the two commits above |
| `bb4f01e` | MC-02 / SA-06, MC-03 / PC-04 — dreaming sweep, graph maintenance, rules to the post critic |
| `e8d9f62` | In-repo CORTEX copy renamed `cortex_memory_moved_to_pypi_repo/` → `backend/cortex_memory/` |
| `a617dd3` | MC-21, MC-22 — Dreaming episode skipping and token budgets |
| `01e35e2` | PC-23 — planner candidates sharing one DB session |
| `dce3040` | LP-25 — thinking tokens truncating capped Gemini calls |
| `a0990da` | PC-24 — planner child roster |
| `bb9e978` | LP-06 — thinking tokens billed |
| `338a0c2` | Register maintenance: invalidated defects |
| `1e0a6f3` | This handoff document |

The second session (register 01 — Product Overview — plus the tools/HITL work), oldest
first. The register-01 deletions (PO-12…PO-17) and the earlier PO-01/02/04/05 fixes are
recorded in [`01-PRODUCT-OVERVIEW-DEFECTS.md`](01-PRODUCT-OVERVIEW-DEFECTS.md); the
headline commits since:

| Commit | Change |
|---|---|
| `98af2c0` | GH-22, GH-01 — HITL checkpoints wait for a decision and fail closed |
| `1a55054` | GH-23, GH-24 — reviewers can answer approvals; own company only; once |
| `3fadd76` | PO-09 — an unknown entity-config key is a 422; runtime knobs declared (also EP-11, PC-16) |
| `0fd3b29` | PO-10 — a router that fails to import is reported on `GET /api/v1/health` (also SA-I10, PO-I9, API-09, API-I2) |
| `579c14f` | PO-06 — the tool stack audit (`PO-06-TOOL-STACK-AUDIT.md`); 18 new defects TL-50…TL-67 |

Docs-only follow-ups record each commit id in the registers (`3e20b89`, `396e84a`,
`5101339`, `6624778`).

The third session (register 02 — System Architecture — plus the single-port merge),
oldest first:

| Commit | Change |
|---|---|
| `6d8de1c` | SA-04, SA-05, SA-15 — every arq connection uses all of `REDIS_URL` (`common/job_queue.py`) |
| `19f57bb` | Every endpoint on one port, 8000: the Unified Gateway (:8001) and voice service (:8002) folded into the API. Closes SA-01…03, SA-11…13, SA-16, SA-17, SA-19, SA-I2 and the gateway half of SA-10 |
| `24650e7` | SA-08 — the lead queue nothing drained is deleted (and the unauthenticated `transcript_api`) |
| `610aeeb` | SA-09 — a webhook is acknowledged only once its job is in Redis |
| `8163907` | SA-20 — a placeholder `INTERNAL_TOKEN` disables `/internal/event` |
| `15191e5` | SA-18 — suspension is checked once, by the auth dependency (SA-I5 moot) |
| `f4e3abd` | SA-14 — `app.hirebuddha.com` has one port-80 vhost |
| `c0863a6` | SA-21 — Python 3.12 everywhere |
| `4f708bc` | SA-10 — every worker job is a span in the trace of the request that queued it |
| `702d772` | SA-I4 — `/api/v1/health` reports whether a worker is consuming |
| `5fe35fd` | SA-07 — child runs have their own queue and worker |

The fourth session (registers 03 — Data Model — and 04 — Auth, RBAC and Tenancy), oldest
first. It ran alongside a second session working registers 14 (billing) and 16 (frontend)
in the same checkout; that session's commits are interleaved on the branch and recorded in
its registers.

| Commit | Change |
|---|---|
| `d70675e` | AU-01 — no one raises their own role through `PATCH /users` |
| `072b0bb` | AU-03, AU-15 — only admins rename a company; partner admins manage their tenants; no one suspends their own |
| `ccbfc6e` | AU-02 — the email-connection API needs a user and stays in its company |
| `ecb9ba4` | AU-04, AU-14 — only an active user's access token signs in |
| `fd3eb83` | DM-21, DM-01, DM-02, DM-19, DM-20 — a fresh database builds from Alembic and matches the ORM (schema census) |
| `4d18973` | DM-05, DM-06 — run and run-log indexes |
| `80b22ed` | DM-04 — one `billing_events` row per company, month and grouping |
| `945f79b` | DM-15 — `clean_db.sql` derives its table list and keeps built-in tools |
| `b82cbc3` | AU-10 — refresh tokens stored as SHA-256 hashes |
| `d00fbd6` | DM-16 — soft-deleted entities hidden by default |
| `6127c33` | AU-05, AU-09, AU-12 — logout, logout everywhere, reuse detection (`token_version`) |
| `8842901` | AU-06, AU-07, AU-08 — password reset, password policy and login throttle, verified sign-in |
| `a608183` | AU-17, AU-18, AU-21 — one role guard; `app_admin` always passes |
| `cbb8a06` | `company_router.py` line endings back to LF |
| `f10300d` | AU-20, AU-I5, PO-I6 — one visibility rule for company-scoped reads |
| `d7fd9ac` | DM-08 — tool names unique per company; tenants see only their tools |
| `ae0226f` | DM-10 — legacy `assets` dropped |
| `c6597db` | DM-11, DM-I8 — numbers stored as numbers |
| `c9b6577` | DM-03 — `feature_flags` has a model; a missing table is logged |
| `5e38d68` | DM-18 — `artifacts.campaign_id` references `campaigns`; uploads stay in their company |
| `4a30627` | DM-17 — run status follows the state machine; terminal statuses are final |
| `a99ae44` | DM-09, DM-I2 — run logs carry their run's company (composite key) |
| `b362241` | DM-14 — no column named `metadata`; CORTEX edges keep their metadata |
| `8e181b2` | DM-13, DM-I4 — JSONB except three order-sensitive columns |
| `2c4bd36` | DM-12 — `timestamptz` everywhere in the host; naive UTC in Python |
| `a65d18d` | AU-23 — an OAuth login signs in only as a provider-verified address |
| `aa7045d` | AU-26 — one account per address in any letter case |
| `a10d41e` | AU-23 follow-up — the OAuth code exchange forwards a PKCE `code_verifier` (for FE-11) |

---

## 2. Defects fixed in this session

Every fix was verified with a unit test that fails on the old code, and — where the
defect is observable at runtime — against the local stack with real Gemini calls.

| ID | Register | Defect | Commit | Live evidence |
|---|---|---|---|---|
| **MC-01** | [08](08-MEMORY-AND-CORTEX-DEFECTS.md) | CORTEX was write-only on the live path | `f8db3b0` | A seeded Intelligence rule appeared in the director's planner prompts. `__memory__` held the rule, a company knowledge-base document and past runs. Episodes were written per run |
| **MC-07** | 08 | `FULL` and `RUN_SCOPED` memory scopes were identical | `f8db3b0` | Unit-tested per-scope domain selection |
| **MC-05** | 08 | `memory_pipeline="v1"` accepted and ignored | `a30bb85` | Argument removed with v1 |
| **MC-18** | 08 | Legacy episodic table still read | `a30bb85` | Reader and `episodic_memories` table removed |
| **MC-12** | 08 | `document_chunks.embedding` had no ANN index | `a30bb85` | Resolved by removal: knowledge-base upload and search now run through CORTEX Knowledge Trees (HNSW-indexed `cortex_nodes`). Upload → search verified live |
| **MC-02 / SA-06** | 08, [02](02-SYSTEM-ARCHITECTURE-DEFECTS.md) | Scheduled dreaming never ran; graph maintenance never ran | `bb4f01e` | Cron enqueued 5 dreams, all completed; a graph-maintenance pass ran |
| **MC-03 / PC-04** | 08, [07](07-PLANNING-AND-CRITICS-DEFECTS.md) | Intelligence rules distilled and never consumed; post critic never saw them | `bb4f01e` | Rules reach the planner and the post critic |
| **MC-21** *(new)* | 08 | Dreaming skipped every episode it did not consolidate | `a617dd3` | 5 pending episodes → 6 observations, 1 pattern, 1 rule; 0 left pending |
| **MC-22** *(new)* | 08 | Dreaming's token budgets truncated thinking-model answers | `a617dd3` | Same run as MC-21 |
| **PC-23** *(new)* | 07 | Parallel plan candidates broke the run's DB session | `01e35e2` | 6 of 6 planner usage rows written (was 1 of 6); no session errors on a live run |
| **LP-25** *(new)* | [10](10-LLM-PROVIDERS-DEFECTS.md) | Thinking tokens consumed `max_tokens`; short calls returned cut-off answers | `dce3040` | 200-token critic call: 6 cut-off tokens → 122 tokens, valid JSON. 400-token judge: 16 → 78. All calls in a live run finished `STOP` |
| **PC-24** *(new)* | 07 | Dynamic planner never told which children exist | `a0990da` | The director's plan targeted its real gatherer, analyst and writer, and delegated to them |
| **LP-06** | 10 | Gemini thinking tokens not counted or billed | `bb9e978` | A plan candidate billed 1313 output tokens, 852 of them thinking (was 461) |

*New* means the defect was found during this session and added to the register.

**Second session (register 01 and the tools/HITL work).** Same discipline — a unit test
that fails on the old code, plus live verification where observable.

| ID | Register | Defect | Commit | Live evidence |
|---|---|---|---|---|
| **GH-22 / GH-01** | [15](15-GOVERNANCE-AND-HITL-DEFECTS.md) | HITL checkpoints never waited; the wait failed open | `98af2c0` | Restarted worker: an authorized run waited then completed; an unanswered run timed out and failed; the step never ran on a block |
| **GH-06** | 15 | Rejections were detected by matching error text | `98af2c0` | Closed with GH-22 — the decision is read from the row, not the message |
| **GH-23 / GH-24** | 15 | Authorize/Block returned 422; any company could answer | `1a55054` | Authorize and Block work; a foreign company gets 404; a second answer gets 409; the approvals page shows the error |
| **PO-09 / EP-11 / PC-16** | [01](01-PRODUCT-OVERVIEW-DEFECTS.md), [06](06-EXECUTION-PIPELINE-DEFECTS.md), [07](07-PLANNING-AND-CRITICS-DEFECTS.md) | A mistyped entity-config key was dropped silently; runtime knobs undeclared | `3fadd76` | A `PUT` with `meta_review_intreval` → 422 naming the key; `meta_review_interval: 5` stored; the builder and every seed still save |
| **PO-10 / SA-I10 / PO-I9 / API-09 / API-I2** | 01, [02](02-SYSTEM-ARCHITECTURE-DEFECTS.md), [17](17-API-REFERENCE-DEFECTS.md) | A broken router import turned a feature area into silent 404s | `0fd3b29` | `GET /api/v1/health` → `ok`; the real app booted with `social_router` broken → `degraded` naming it, its routes 404, other routers up |
| **PO-06** | 01 | Audit of the whole tools stack (deliverable, not a code change) | `579c14f` | [`PO-06-TOOL-STACK-AUDIT.md`](PO-06-TOOL-STACK-AUDIT.md) — 55 entries re-verified, 18 new (TL-50…TL-67), fix list; dev-DB evidence in its §4 |

**Third session (register 02 and the single-port merge).** Same discipline.

| ID | Defect | Commit | Live evidence |
|---|---|---|---|
| *merge* | Three HTTP processes on 8000/8001/8002 | `19f57bb` | Every HTTP route and WebSocket handshake answered on :8000; a webhook and an internal event reached the worker |
| **SA-04 / SA-05** | Enqueues and the worker ignored parts of `REDIS_URL` | `6d8de1c` | Worker reloaded against `rediss://:secret@…:6380/2` keeps password, TLS and db index (unit); jobs flow on the local stack |
| **SA-09** | Events were acknowledged before they were durable | `610aeeb` | 202 with Redis up; 503 with Redis stopped; a job queued while the worker was down ran after restart |
| **SA-20** | `/internal/event` guarded by a published placeholder | `8163907` | Placeholder token → 503, health `internal_events: disabled`, boot warning |
| **SA-18** | Suspension checked twice per request | `15191e5` | One authenticated `GET /api/v1/users`: 4 SQL statements → 3 |
| **SA-14** | Two port-80 vhosts for one name | `f4e3abd` | Config test only (no Apache locally) |
| **SA-21** | Three Python versions | `c0863a6` | Docker builder stage on 3.12 installed 144 packages; `poetry install --dry-run` changes nothing |
| **SA-10** | The worker exported no traces | `4f708bc` | Local OTLP receiver: four webhooks → four `arq process_gateway_event` spans, each a child of its request span |
| **SA-I4** | A dead worker was invisible | `702d772` | Hard-killed worker → health `degraded` / worker `down` 32 s later |
| **SA-07** | Child runs shared the default queue | `5fe35fd` | A child run waited on `children` with no child worker (health `down`, `due_jobs: 1`); the child worker ran it on start |

**Fourth session (registers 03 and 04).** Same discipline: each fix has a test that
fails on the old code (run against an export of the previous commit), the gates, and a
live check where the defect is observable. The registers' status tables carry every ID and
commit; the highlights:

| ID | Defect | Commit | Live evidence |
|---|---|---|---|
| **AU-01** | A `tenant_user` could make themselves `app_admin` with one PATCH | `d70675e` | The PATCH is a 403; an admin can only assign roles at or below their own |
| **AU-02** | Five SMTP/IMAP credential routes had no authentication | `ccbfc6e` | Unauthenticated 401; another company's connection 404 |
| **DM-21** *(new)* | `alembic upgrade head` on an empty database failed at `m0b1e0d1a100` | `fd3eb83` | A scratch database builds; `tests/integration/test_schema_census.py` compares it with the models |
| **AU-05 / AU-09 / AU-12** | Sessions could not be ended | `6127c33` | Logout, logout-everywhere and reuse detection checked against the live API |
| **AU-06 / AU-08** | No password reset; `is_verified` gated nothing; no verification email was ever sent | `8842901` | Register → emailed link (logged locally, `EMAIL_LINKS_IN_LOG=true`) → verify → sign in |
| **DM-17** | Run status was advisory; a late finish overwrote a cancel | `4a30627` | Unit and Postgres race tests |
| **DM-09** | Run logs had no tenant column | `a99ae44` | A run's page loads its logs through the composite key; reports answer |
| **DM-14** | `CortexEdge(metadata=…)` was silently dropped | `b362241` | No edge had stored metadata (6 of 6 empty) |
| **DM-13** | `json`/`jsonb` split | `8e181b2` | Entities, runs and reports read live; `kpi_daily_rollup` rebuilt |
| **DM-12** | Naive timestamps; three local-clock bugs | `2c4bd36` | KPI, wallet, stats and run endpoints live; values unchanged by the migration |
| **AU-23** *(new)* | An OAuth login could sign in as any existing account (Microsoft `mail`) | `a65d18d` | Router test against a fake provider |
| **AU-26** *(new)* | Two accounts per address, one per letter case | `aa7045d` | Mixed-case register → lower-case; re-register refused |

Also new and fixed: the tool registry leaked other tenants' tools (with DM-08), artifact
uploads could attach to another company's campaign or agent (with DM-18), `clean_db.sql`
emptied the built-in tools (with DM-15), and `migrations/env.py` missed
`phone_pool_models` (with DM-21).

**Decisions taken with the product owner:** DM-12 and DM-13 done now, not deferred; AU-06
and AU-08 built, with unverified sign-in blocked; partner admins may rename, suspend and
reactivate their own tenants (AU-15); AU-19 (`app_user`) left as is and documented. AU-16
(the unread refresh cookie) is won't-fix, with AU-I7 as the real change.

**Package changes to port.** MC-21 and MC-22 changed the CORTEX package itself:
`backend/cortex_memory/dreaming.py`, `episodic_tree.py` and
`tests/test_dreaming_consolidation.py`. The package is maintained in its own repository
(`hb-cortex-memory`); these changes must be carried back there and republished.
DM-14 (fourth session) changed `cortex_memory/models.py` and `graph.py`: the column is
`edge_metadata` and `create_edge` passes `edge_metadata=`. A published 0.1.0 still maps
column `metadata` and fails against a migrated database, and a standalone database needs
the same rename (done on the local `cortex_test`). The CORTEX tables keep naive
`timestamp` columns (DM-12) and have no tenant column (DM-I6); both are package changes.

---

## 3. Defects that became invalid

Each is marked in its register with `Status: invalid` and the reason.

| ID | Register | Why it no longer holds |
|---|---|---|
| **DM-07** | [03](03-DATA-MODEL-DEFECTS.md) | `document_chunks` was dropped (`a30bb85`); search runs over HNSW-indexed `cortex_nodes`. Same finding as MC-12 |
| **TS-01** | [19](19-TESTING-DEFECTS.md) | The CI `paths` filter targets `backend/cortex_memory/**`, which exists again after `e8d9f62`, with a `pyproject.toml` the install step needs. Not yet exercised: the branch is unpushed |
| **ON-05** | [20](20-ONBOARDING-AND-GLOSSARY-DEFECTS.md) | The onboarding doc's `__memory__` block is real since MC-01 |
| **ON-12** | 20 | The `cortex_memory_moved_to_pypi_repo/` folder name is gone |

Partly stale — text updated, the defect itself still stands:

| ID | Register | What changed |
|---|---|---|
| PO-01 | [01](01-PRODUCT-OVERVIEW-DEFECTS.md) | The delete route must now remove Knowledge Tree chunk nodes, not `document_chunks` rows |
| DM-11 | 03 | Two of the four text-typed numeric columns went with their tables |
| IN-05 | [18](18-INFRASTRUCTURE-AND-DEPLOYMENT-DEFECTS.md) | The cortex workflow's filter matches again; there is still no CI for `backend/tests/` |
| TS-I7, README §1 | 19, [README](README.md) | `assemble_memory` is no longer a "never called" example |

---

## 4. Other register changes

These entries were added while testing live, so the registers record what the fixes
exposed. They are part of the backlog like any other entry.

| ID | Register |
|---|---|
| PC-25 | 07 |
| EP-25 | [06](06-EXECUTION-PIPELINE-DEFECTS.md) |
| MC-23, MC-24 (deferred), MC-I11 (improvement) | 08 |

Recorded in the second session while fixing/auditing, not yet scheduled:

| ID | Register | What |
|---|---|---|
| GH-25 | [15](15-GOVERNANCE-AND-HITL-DEFECTS.md) | Block Cycle blocks the step but the loop retries and re-asks the reviewer (3× before cancel) |
| FE-24 | [16](16-FRONTEND-DEFECTS.md) | The Vite dev proxy sends full-page `/reports/*` loads to the gateway host |
| FE-25 | 16 | Saving the entity builder with no change rewrites config it does not show |
| BC-26 | [14](14-BILLING-AND-CREDITS-DEFECTS.md) | Any user can read the billing multiplier and base costs |
| TL-50…TL-67 | [PO-06 audit](PO-06-TOOL-STACK-AUDIT.md) | 18 tool-layer defects; the biggest is TL-50 (execution is not restricted to an entity's granted tools) |

Found in the third session:

| What | Where recorded / done |
|---|---|
| The CORTEX RECURSE child enqueue had never worked (`ArqRedis(self.redis.client)` raised every call); its child runs stayed `PENDING` | Fixed with SA-07; MC-09's note in [08](08-MEMORY-AND-CORTEX-DEFECTS.md) corrected. **Behaviour change:** those child runs now run |
| Runbook said `redis-cli LLEN arq:queue`; the queue is a sorted set | Corrected in `18-infrastructure-and-deployment.md` §16.4 (with SA-I4) |
| The backend image had no `.dockerignore`: `COPY . .` copied `.env` and a host `.venv` into it | **IN-22** in [18](18-INFRASTRUCTURE-AND-DEPLOYMENT-DEFECTS.md) — fixed: `backend/.dockerignore` |
| The Dockerfile's Poetry 1.7.1 warns that the Poetry 2.x lock "might not be compatible" (it installed correctly) | Noted in the SA-21 commit |
| `cortex_resume_scheduled` wraps `ctx['redis']` in `ArqRedis` again (MC-24, deferred) | Unchanged |

Found in the fourth session and recorded, not fixed:

| ID | Register | What |
|---|---|---|
| AU-24 | [04](04-AUTH-RBAC-TENANCY-DEFECTS.md) | `ENCRYPTION_MASTER_KEY` defaults to a string in the repo and is padded, not derived. Fixing it re-keys stored credentials — decide the rotation first |
| AU-25 | 04 | Social-connection client secrets sit unencrypted in `oauth_metadata` |
| AU-23 (frontend half) | 04 → FE-11 in [16](16-FRONTEND-DEFECTS.md) | The SPA sends no OAuth `state` and the buttons are unwired; the other session took it. The backend accepts a PKCE `code_verifier` |
| PC-26 | [07](07-PLANNING-AND-CRITICS-DEFECTS.md) | The nightly `cost_estimator_refresh` reads `tool_interaction_logs.cost_usd`, which does not exist; it has never refreshed anything |
| IN-23 | [18](18-INFRASTRUCTURE-AND-DEPLOYMENT-DEFECTS.md) | The OTLP exporter retries `localhost:4317` for about a minute when nothing listens, stalling every `--reload` and worker stop |
| BC-31 | [14](14-BILLING-AND-CREDITS-DEFECTS.md) | The daily credit job's error handler read an expired instance; fixed by the other session (`3473bb5`) |
| e2e suite | — | `tests/e2e` assumed the old register/login contract (tokens on register, 9-character passwords); a separate session is updating it |

On 2026-09-29 the memory register (08) was reviewed with the product owner.
- MC-04, MC-08, MC-17 and MC-20 were removed by product decision; MC-20's facts moved into
  MC-I10.
- Every other open MC defect was marked **deferred**.
- The register carries a status table at the top.

The Summary table and **Total** line of every register touched were kept in step.

---

## 5. How a defect is worked

The product owner names a defect; work it end to end before starting another.

1. **Read the register entry**, then the code it cites. Registers are dated 2026-09-01
   and line numbers drift — confirm the claim still holds. If it does not, mark it
   invalid ([§6](#6-register-conventions)) rather than fixing something already fixed.
2. **Reproduce it.** Prefer a small script against the local database or a live call
   over reasoning alone. Several defects here only showed up live (PC-23, LP-25, PC-24).
3. **Fix at the root, in one place.** For example, LP-25 was fixed once in the Gemini
   adapter, not by raising 19 call-site budgets.
4. **Write a unit test that fails on the old code.** Check that by running it against
   `git show HEAD:<file>`.
5. **Verify live** when the defect is observable at runtime (see [§9](#9-live-end-to-end-testing)).
   Clean up any rows your test scripts write.
6. **Run the gates:** affected tests, the type check, the layout lint, and the full host
   suite before committing.
7. **Update the docs:** the design doc in `docs/current/` for the area, plus the register
   status line. Record new defects the fix exposes as new register entries; do not fix
   them unasked.
8. **Commit per defect**, message `fix(<area>): <what is now true> (<ID>)`, with a body
   explaining cause, fix and evidence. Do not push unless asked.

For a defect in the CORTEX package (`backend/cortex_memory/`), keep the package
boundary — the package never imports `src.ai.*`; the host injects providers — and flag
the change for porting to the package repository.

---

## 6. Register conventions

Status goes on the line under the heading:

```markdown
**✅ Verified · High** · **Status: fixed (2026-09-29, `abc1234`)** — one-line summary.
**✅ Verified · Medium** · **Status: invalid (2026-09-28, `abc1234`)** — why it no longer holds.
**✅ Verified · High** · **Status: open** — found 2026-09-29 while …
```

- **Fixed:** keep the original description. Replace or extend the **Fix:** paragraph with
  what was done and the live evidence.
- **Partly stale:** add a dated `> **Update …**` note instead of rewriting history.
- **New entry:** next free number in that register, placed in the matching tier section.
  Update that register's Summary tier count and **Total** line.
- Table-row defects (e.g. `ON-12`) carry their status in the last column.
- Cross-register links use the heading anchor, e.g.
  `07-PLANNING-AND-CRITICS-DEFECTS.md#pc-24--the-dynamic-planner-is-never-told-which-children-exist`.
- `Consolidated-Defect-Register.xlsx` is maintained by the product owner; it was not
  updated from this session.

---

## 7. Local environment

Windows 11, Git Bash and PowerShell. All paths below are relative to the repo root.

| Piece | How |
|---|---|
| Postgres (pgvector) + Redis | `docker compose up -d db redis` in `backend/`. Containers `hirebuddha-db` (**port 5433**) and `hirebuddha-redis` (6379) |
| Backend venv | `backend/.venv` — Python 3.12 via uv, dependencies from `poetry.lock` |
| Whole stack | `powershell -ExecutionPolicy Bypass -File .\start_services.ps1` / `.\stop_services.ps1` at the repo root (Windows development only; the VMs use the `.sh` pair). `-Only docker,api,workers,frontend` picks services; `stop_services.ps1 -WhatIf` lists what it would stop. See `18-infrastructure-and-deployment.md` §6.3 |
| API + frontend | Or `.claude/launch.json`: `backend-api` (uvicorn :8000) and `frontend` (vite :3000) |
| Arq workers | Two since SA-07: `WorkerSettings` and `ChildWorkerSettings`. **Restart both after any backend change** — they do not reload: `.\stop_services.ps1 -Only workers; .\start_services.ps1 -Only workers`. `curl -s localhost:8000/api/v1/health` shows each queue's live workers |
| One port | Everything — REST, webhooks, `/internal/event`, media-stream WebSockets — is on :8000 since `19f57bb`. `backend/.env` has `STREAMING_HOST=localhost:8000`; its `INTERNAL_TOKEN` is still the placeholder, so `/internal/event` answers 503 locally |
| Vertex AI | Application Default Credentials: `gcloud auth application-default login`. Project `hirebuddha-production`, region `us-central1` (`backend/.env`) |
| Seeds | `db-scripts/seed_admin_user.py` (admin@hirebuddha.com), `db-scripts/seed_integration_registry.py` (gemini-2.5-flash and text-embedding-005 SKUs + task defaults). Deep-research entities: `scripts/seeds/deep_research/DeepResearchSetup/create_v2.py` |

A fresh database **is** buildable from Alembic since DM-21 (`fd3eb83`):
`alembic upgrade head` on an empty database creates everything the models declare, and
`tests/integration/test_schema_census.py` checks that on a scratch database each run.
Restart both workers after any migration: models and schema move together (DM-09,
DM-12, DM-14 each made the old worker code fail against the migrated database).

`backend/.env` has `EMAIL_LINKS_IN_LOG=true`. With no SMTP configured locally, the
verification and password-reset links are written to the API log, so a registered
account can be verified by hand (AU-08: unverified accounts cannot sign in).

Local gaps that make a deep-research run fail for environmental reasons:

- Web-search tool keys (Firecrawl, SerpAPI) are not in the registry, so research tools
  fail until they are added through the UI.
- `docx_generator` is not registered as a tool, and PDF generation needs `weasyprint` and
  `markdown`, which are not installed in `backend/.venv`.

The last live run (2026-09-29) got as far as these. The director planned and delegated
to all three children. The report writer produced a full Markdown report on the requested
topic, then failed on the DOCX and PDF steps, which failed the run.

> **These two are now formal defects, not just local gaps.** The PO-06 audit found the
> real name is `docx_tool` (the seed/fixture names `docx_generator`, `scraper`,
> `batch_search` — none of which are registered) — **TL-67**; and `weasyprint`, `markdown`,
> `playwright` and the DuckDuckGo library are undeclared in `pyproject.toml`, so
> `pdf_generator`, `headless_browser` and `web_search`'s free fallback are dead on any
> clean install — **TL-66**. See [`PO-06-TOOL-STACK-AUDIT.md`](PO-06-TOOL-STACK-AUDIT.md).

---

## 8. Testing

From `backend/`:

```bash
PYTHONUTF8=1 .venv/Scripts/python.exe -m pytest tests -q -p no:cacheprovider --ignore=tests/integration --ignore=tests/e2e
```

Expected: **1315 passed, 7 failed** (1017 at the first handoff, 1059 at the second, 1126
at the third; the fourth added the auth, RBAC and data-model tests).
The integration suite runs against the local Postgres in rolled-back transactions:
`pytest tests/integration` — expect 2 failures in `test_cost_attribution.py`. Two more
can flake when another session shares the database or the machine is loaded:
`test_billing_crons` when a company is deleted mid-run (fixed by BC-31), and
`test_worker_heartbeat` under heavy load. Both pass alone. Add `OTEL_SDK_DISABLED=true` to silence the
trace exporter's retries when nothing listens on :4317. The 7 fail identically on `main`
and are not regressions:

- `tests/ai/core/test_meta_review.py::TestMetaReviewerDefaults::test_graceful_fallback_on_error`
- `tests/chaos/test_feature_flags_table_unavailable.py::test_pool_exhaustion_falls_through_to_default`
- `tests/unit/test_doc_factory_redesign_fixes.py::test_document_save_resolves_sandbox_relative_path` (Windows path separator)
- `tests/unit/test_sandbox_runtime.py` × 4 (Windows)

`tests/integration/test_cost_attribution.py` has 2 failures locally only, because the
registry seed already created the embedding SKU the tests insert. `tests/e2e/` needs a
fully running environment and is not part of the baseline.

Other gates:

```bash
PYTHONUTF8=1 .venv/Scripts/python.exe -m pytest tests/unit/test_typecheck.py -q
```

```bash
PYTHONUTF8=1 .venv/Scripts/python.exe scripts/lint_ai_layout.py
```

The layout lint enforces per-directory line caps: `core/` 1500, `meta/` 900, `planning/`
700. Both `agent_loop.py` and `platform_schema_compiler.py` sit close to their caps.

CORTEX package tests need a scratch database, because the host database's company
foreign keys reject the package tests' random UUIDs:

```bash
CORTEX_TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5433/cortex_test PYTHONUTF8=1 .venv/Scripts/python.exe -m pytest cortex_memory/tests -q
```

---

## 9. Live end-to-end testing

Start a run without logging in, through the service layer (from `backend/`):

```python
import asyncio, sys
from uuid import UUID
sys.path.insert(0, ".")
import src.main  # noqa: F401 — registers every ORM mapper
from src.common.database import AsyncSessionLocal
from src.ai.schemas.execution import ExecutionRunCreate
from src.ai.service import AIService

async def main():
    async with AsyncSessionLocal() as db:
        run = await AIService(db).trigger_execution(
            ExecutionRunCreate(entity_id=UUID("<entity id>"), input_data={"input": "<request>"}),
            UUID("<company id>"), UUID("<user id>"), user_role="app_admin",
        )
        print(run.id, run.status)

asyncio.run(main())
```

Cancel it the same way with `AIService(db).cancel_execution(run_id, company_id, "app_admin")`.
Deep-research entity ids differ per database; read them from `hierarchical_entities`.

Inspect what the model actually saw and returned — every LLM call is a trace span:

```sql
select seq, name, tokens_in, tokens_out, payload->>'thinking_tokens' as thinking,
       payload->>'finish_reason' as finish, left(payload->>'user_prompt', 200)
from execution_trace_events
where run_id = '<run id>' and kind = 'llm'
order by seq;
```

The worker log (`logs/arq_worker.log`) warns on truncated Gemini answers
(`answer truncated at max_tokens=…`), failed usage writes, and plan-reconcile fallbacks.

To see OpenTelemetry spans without Jaeger, run a throwaway OTLP/gRPC receiver on
127.0.0.1:4317 — `grpcio` and `opentelemetry-proto` are already in the venv, and a
`TraceServiceServicer` whose `Export` prints each span's service, name, trace id and
parent is about 30 lines. Start it before the API and workers.

A deep-research run spends real Vertex money — a few cents to tens of cents. Cancel a
run that is looping.

---

## 10. Things that will bite you

- **One `AsyncSession`, one coroutine.** Never run DB writes on a shared session under
  `asyncio.gather`. Plain reads are serialised by the asyncpg adapter; commits are not
  (PC-23). Parallel work that writes needs its own session, as `StepEngine` does.
- **Thinking models.** On Gemini 2.5/3, `max_tokens` is now the *answer* budget; a capped
  call gets `service_metadata.thinking_budget` (default 1024) on top. `completion_tokens`
  includes thinking; `thinking_tokens` is the split.
- **Children are linked two ways.** `parent_id` and `hierarchy.children`, plus static-plan
  targets. `load_entity_children` is the single source for the first two.
- **`import cortex_memory` resolves to `backend/cortex_memory/`,** not the installed
  wheel, when run from `backend/`.
- **Arq context:** `ctx['redis']` is already an `ArqRedis`; wrapping it again raises. In
  the child-run worker its default queue is `children`, so name `_queue_name` when a
  job there enqueues anything else. Enqueue child runs with
  `common.job_queue.enqueue_child_run`, everything else with `enqueue_job` /
  `enqueue_on` — they carry the trace context.
- **`@limiter.exempt` and `from __future__ import annotations` do not mix.** FastAPI
  resolves the string annotations against slowapi's wrapper module and the endpoint
  422s. The webhook and internal-event modules leave the future import out on purpose.
- **Health is always 200.** `status: degraded` is the signal — a missing router, no
  live worker on `arq:queue` or `children`, or a due job waiting over 600 s.
- **Unknown entity-config keys are a 422 since PO-09** (API create/update only); before,
  Pydantic dropped them silently — a mistyped setting was a
  no-op that returns `200 OK`.
- **Shell quoting on Windows:** Python heredocs in Git Bash mangle `\n` escapes, and
  `\u0000` became a real NUL in a doc once. Use the editor, or a script file, for
  escape-sensitive edits.
- **Timestamps are naive UTC in Python, `timestamptz` in the database (DM-12).** A codec on
  every asyncpg connection converts both ways, and the session zone is pinned to UTC.
  Never call `datetime.now()`, `date.today()` or `fromtimestamp()` without a zone;
  `tests/unit/test_utc_timestamps.py` fails if you do. New columns are
  `DateTime(timezone=True)`.
- **An illegal run-status write is silently refused (DM-17).** The model keeps the old
  status and logs a warning. Read the status back if it matters. Terminal statuses are
  final.
- **`Model(metadata=…)` is accepted and dropped** on every SQLAlchemy model (DM-14). Pass
  the real attribute name.
- **New JSON columns are `JSONB`** unless their key order is content (DM-13); add the
  reason to `tests/unit/test_json_columns.py`.
- **Log rows get their company from the run (DM-09).** `llm_interaction_logs`,
  `tool_interaction_logs` and `human_approvals` need only `run_id`; a hook fills
  `company_id`, and a composite key keeps it right.
- **User emails are lower-case (AU-26).** A fixture that inserts `Owner@x.com` directly
  fails the check constraint.
- **Unverified accounts cannot sign in (AU-08)**, and registration returns no tokens.
  Test users need `is_verified=True`.
- **Two sessions in one checkout:** stage by path (or by hunk with `git apply --cached`),
  never `git add -A`, never `git stash`. A whole-file add once swept one session's
  half-done change into the other's commit (`141a4df`).
- **Docker Desktop** will not start while
  `%LOCALAPPDATA%\Docker\run\userAnalyticsOtlpHttp.sock` is stale; move the `run` folder
  aside.
- **ADC expires.** "Reauthentication is needed" from every LLM call means
  `gcloud auth application-default login` again.
