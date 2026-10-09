# 19. Testing & Quality Gates — Defect Register

> **What this document is:** defects in the test suite and the gates around it — what runs,
> what silently does not, and what a green result actually proves — plus the improvements
> that would make the suite trustworthy.
> **Source document:** [`19-testing.md`](../19-testing.md)
> **Compiled:** 2026-09-01, against branch `fresh-main`. **Last reviewed:** 2026-10-07, on branch `roadmap-development-defect-fixes`.
> **Context:** there are **1,063 backend tests and no CI that runs them**. The suite is
> good. Nothing enforces it.

---

## How to read this file

- **✅ Verified** — the file or config was read on 2026-09-01 and the claim held.
- **📄 Doc-reported** — from `19-testing.md`, not independently re-checked.
- The central problem is not test quality. The backend suite is substantial and
  well-organised. The problem is that **a green run does not mean what it appears to
  mean**: three whole tiers skip rather than fail when their infrastructure is absent, and
  nothing runs any of it automatically.

---

## Contents

1. [Summary](#1-summary)
2. [T0 — Nothing enforces any of it](#2-t0--nothing-enforces-any-of-it)
3. [T1 — A green run can be an empty run](#3-t1--a-green-run-can-be-an-empty-run)
4. [T2 — Dead scaffolding](#4-t2--dead-scaffolding)
5. [T3 — Traps and drift](#5-t3--traps-and-drift)
6. [Improvements](#6-improvements)
7. [Suggested order of work](#7-suggested-order-of-work)

---

## 1. Summary

| Tier | Theme | Count | Fixed | Partly fixed | Open | Closed otherwise |
|---|---|---|---|---|---|---|
| [T0](#2-t0--nothing-enforces-any-of-it) | Nothing enforces any of it | 4 | 1 | 0 | 2 | 1 |
| [T1](#3-t1--a-green-run-can-be-an-empty-run) | A green run can be an empty run | 4 | 3 | 0 | 1 | 0 |
| [T2](#4-t2--dead-scaffolding) | Dead scaffolding | 5 | 5 | 0 | 0 | 0 |
| [T3](#5-t3--traps-and-drift) | Traps and drift | 6 | 3 | 0 | 2 | 1 |

**Total: 19 defects (12 fixed, 5 open, 2 accepted or invalid), 10 improvements.** Re-verified against the code on 2026-10-07; what is left is scheduled in [`REMAINING-DEFECTS-PLAN.md`](REMAINING-DEFECTS-PLAN.md).

| ID | Defect | Status | Plan |
|---|---|---|---|
| TS-01 | The only CI workflow has never fired | invalid (the gap is IN-05) | — |
| TS-02 | 1,063 backend tests run only when someone remembers | open — Critical | [H1](REMAINING-DEFECTS-PLAN.md#h1--turn-on-the-lights) |
| TS-03 | Three working quality gates have no trigger either | open | [H1](REMAINING-DEFECTS-PLAN.md#h1--turn-on-the-lights) |
| TS-04 | `npm run lint` cannot run, and there is no frontend test runner | ✅ fixed (2026-10-09) — lint and `npm test` both run (FE-02, FE-03) | — |
| TS-05 | Three test tiers skip instead of failing | ✅ fixed (2026-10-09) — `REQUIRE_DB=1` fails what would skip | — |
| TS-06 | An unmocked LLM call returns a `STUB:` string, not an error | open | [H1](REMAINING-DEFECTS-PLAN.md#h1--turn-on-the-lights) |
| TS-07 | `e2e/` does not roll back | ✅ fixed `3352625` | — |
| TS-08 | The frontend tests cannot run at all | ✅ fixed (2026-10-09) — `npm test`; test files type-checked (FE-03) | — |
| TS-09 | The root `tests/` directory | ✅ fixed `c9edbfd` | — |
| TS-10 | The `kpi` marker and its CI step | ✅ fixed (2026-10-09) — marker and lane deleted | — |
| TS-11 | The `needs_redis` marker | ✅ fixed (2026-10-09) — deleted | — |
| TS-12 | `backend/tests/phase9/` | ✅ fixed `ebdb54b` | — |
| TS-13 | One of the two `MockLLMRouter` classes | ✅ fixed `d3497d6` | — |
| TS-14 | `@pytest.mark.integration` is used and not registered | ✅ fixed (2026-10-09) — registered; `--strict-markers` | — |
| TS-15 | Marker usage is far below marker registration | ✅ fixed (2026-10-09) — every test carries its directory's tier | — |
| TS-16 | The parity suite leaves tenants behind | ✅ fixed (2026-10-09) — the session deletes what it seeded | — |
| TS-17 | Fixture loading is coupled to the entity schema | open — decision HD18 | [H1](REMAINING-DEFECTS-PLAN.md#h1--turn-on-the-lights) |
| TS-18 | Documentation and reality have drifted in three places | open | [H10](REMAINING-DEFECTS-PLAN.md#h10--documentation-and-onboarding) |
| TS-19 | The engine fixture is function-scoped, deliberately | accepted — keep function scope | — |

The three to read first:

- **[TS-01](#ts-01--the-only-ci-workflow-has-never-fired)** — the `paths` filter points at
  a directory that no longer exists.
- **[TS-05](#ts-05--three-test-tiers-skip-instead-of-failing)** — `integration`, `e2e` and
  `parity` all call `pytest.skip()` when Postgres is unreachable.
- **[TS-08](#ts-08--the-frontend-tests-cannot-run-at-all)** — two test files importing a
  package that is not installed.

> **Update 2026-10-07:** TS-01 is invalid, because the cortex workflow's filter matches again. The gap it pointed at — no CI for `backend/tests/` — is TS-02 and IN-05, and it is open. TS-05 is open. TS-08 is partly fixed: `vitest` is installed but not wired in.

---

## 2. T0 — Nothing enforces any of it

### TS-01 — The only CI workflow has never fired

**✅ Verified · Critical** · **Status: invalid (2026-09-28, `e8d9f62`)** — the in-repo
package copy was renamed back to `backend/cortex_memory/`, which has its own
`pyproject.toml`, so the `paths` filter and `pip install -e "cortex_memory[dev]"` both
match again. Not yet exercised in CI (the branch is unpushed). The wider gap — no CI for
`backend/tests/` — is [IN-05](18-INFRASTRUCTURE-AND-DEPLOYMENT-DEFECTS.md#in-05--the-repository-has-no-functioning-ci).

One GitHub Actions workflow exists, triggering on:

```yaml
paths: ["backend/cortex_memory/**"]
```

That directory is now `backend/cortex_memory_moved_to_pypi_repo/`. The filter matches
nothing, so the workflow **has never run** — and its `working-directory: backend` plus
`pip install -e cortex_memory[dev]` would fail if it did.

The workflow looks present and green in the repository listing precisely because it has no
runs.

- [`.github/workflows/cortex-memory.yml:11`](../../../.github/workflows/cortex-memory.yml:11)
- Also recorded as **D-14** in the platform register

---

### TS-02 — 1,063 backend tests run only when someone remembers

**✅ Verified · Critical** · **Status: open** — re-verified 2026-10-07: nothing runs the suite on push; it is now ~1,840 unit tests plus ~375 integration and parity tests. Plan: [H1](REMAINING-DEFECTS-PLAN.md#h1--turn-on-the-lights).

| Tier | Files | Test functions |
|---|---|---|
| `unit/` | 89 | 745 |
| `e2e/` | 17 | 183 |
| `ai/` | 9 | 72 |
| `integration/` | 9 | 44 |
| `eval/` | 1 | 14 |
| `chaos/` | 2 | 5 |
| `parity/` | 2 | 2 |
| `regression/` | 1 | 1 |

That is a genuinely good suite — 745 pure unit tests is a lot, and the parity and
regression functions each iterate internally over many cases.

**None of it runs on push or pull request.** `scripts/run_ci_matrix.sh` defines three lanes
— fast, full, typing — wired to no trigger. The instruction in the docs is to run
`scripts/run_ci_matrix.sh fast` manually before pushing.

---

### TS-03 — Three working quality gates have no trigger either

**📄 Doc-reported · High** · **Status: open** — re-verified 2026-10-07: unchanged; blocked on IN-05. Plan: [H1](REMAINING-DEFECTS-PLAN.md#h1--turn-on-the-lights).

| Gate | What it enforces |
|---|---|
| [`lint_ai_layout.py`](../../../backend/scripts/lint_ai_layout.py) | 271 lines of architecture policy — package line caps, forbidden imports, the comment-narration and canary-label bans, the `tools/` root rule |
| [`typecheck_ai.py`](../../../backend/scripts/typecheck_ai.py) | incremental strict typing |
| ruff / black | formatting and lint |

All three are real, working and invoked by hand only. The layout lint in particular encodes
decisions that are expensive to unwind once violated — package caps are described in the
file as a ratchet.

---

### TS-04 — `npm run lint` cannot run, and there is no frontend test runner

**✅ Verified · High** · **Status: ✅ fixed (2026-10-09)** — `npm run lint` runs and passes
([FE-02](16-FRONTEND-DEFECTS.md#fe-02--npm-run-lint-cannot-run), 2026-10-01), and `npm test`
runs the vitest suite in jsdom
([FE-03](16-FRONTEND-DEFECTS.md#fe-03--there-is-no-test-runner), 2026-10-09). Running both in
CI is H1.3's workflow.

`package.json` declares a `lint` script and installs `eslint`, `@typescript-eslint/*`,
`eslint-plugin-react-hooks` and `eslint-plugin-react-refresh`. There is **no ESLint config
file** anywhere, so the command fails immediately.

There is no `test` script and neither `vitest` nor `jest` is installed.

So the frontend has **zero** automated checking of any kind, beyond `tsc` during a build
that production does not run.

- [`frontend/package.json`](../../../frontend/package.json)
- Also **D-39** and **D-40**; see
  [FE-02](16-FRONTEND-DEFECTS.md#fe-02--npm-run-lint-cannot-run) and
  [FE-03](16-FRONTEND-DEFECTS.md#fe-03--there-is-no-test-runner)

---

## 3. T1 — A green run can be an empty run

### TS-05 — Three test tiers skip instead of failing

**✅ Verified · High** · **Status: ✅ fixed (2026-10-09)** — `REQUIRE_DB=1` turns every missing-infrastructure skip into a failure. The CI job that sets it is IN-05.

`integration/`, `e2e/` and `parity/` all call `pytest.skip()` from their fixtures when the
database is unreachable:

```python
pytest.skip("DATABASE_URL not set; integration suite skipped")
pytest.skip(f"Postgres unreachable; integration suite skipped ({exc})")
pytest.skip("DATABASE_URL not set — parity gate needs a Postgres.")
pytest.skip("Could not create app_admin user – check if DB is reachable")
```

So a developer — or a future CI job — with no Postgres gets a **green run** that executed
745 unit tests and skipped 229 of the tests that touch real infrastructure. The exit code
is 0.

The parity suite is the sharpest case: it is described as the legacy-deletion gate, and it
silently does not run.

- [`backend/tests/integration/conftest.py:56`](../../../backend/tests/integration/conftest.py:56), [`:65`](../../../backend/tests/integration/conftest.py:65)
- [`backend/tests/parity/conftest.py:88`](../../../backend/tests/parity/conftest.py:88), [`:96`](../../../backend/tests/parity/conftest.py:96)
- [`backend/tests/e2e/conftest.py:74`](../../../backend/tests/e2e/conftest.py:74)

**Fix:** keep skipping locally, but fail in CI. An environment variable —
`REQUIRE_DB=1` — that turns the skip into a failure is enough.

**Fixed (2026-10-09).** `tests/harness/infra.py` has `infra_unavailable(reason)`: a skip by
default, `pytest.fail` when `REQUIRE_DB` is `1`/`true`/`yes`/`on`. Every fixture that
skipped for missing infrastructure calls it — the integration `_engine` (no URL, no
`SELECT 1`), the parity `db` and `redis_client`, the four integration tests' Redis probes
(`test_agent_cache_bus`, `test_flag_invalidation`, `test_run_quota`, `test_run_stream_redis`)
and the schema census's scratch database. The e2e suite no longer skips on a missing
database (its `app_admin` skip went with `3352625`); it errors. Skips that are not about
infrastructure stay: the mobile suite's *disposable `_test` database* guard, the Docker
image tests (their own job, H1.1) and the e2e suite's chained-data skips.

Evidence: `tests/unit/test_require_db.py` (5). With `DATABASE_URL` on a dead port,
`test_run_credit_guard.py` gives 8 skipped (exit 0) without the switch and 8 errors with
it; with `REDIS_URL` on a dead port, `test_run_stream_redis.py` gives 3 errors under
`REQUIRE_DB=1`.

---

### TS-06 — An unmocked LLM call returns a `STUB:` string, not an error

**📄 Doc-reported · High** · **Status: open** — re-verified 2026-10-07: `tests/harness/mock_llm.py:172` still answers `STUB::…`. Plan: [H1](REMAINING-DEFECTS-PLAN.md#h1--turn-on-the-lights).

When a test path reaches the LLM without a mock configured, the harness returns a response
beginning `STUB:` rather than raising.

So a test can exercise a code path, assert on an output that was never generated, and pass.
The advice in the docs is to grep the output for `STUB:` when results look wrong — which
means the failure mode is a **passing test that proves nothing**.

- [`backend/tests/harness/mock_llm.py`](../../../backend/tests/harness/mock_llm.py)

**Fix:** raise by default and require an explicit opt-in for stub mode.

---

### TS-07 — `e2e/` does not roll back

**📄 Doc-reported · Medium** · **Status: fixed (2026-10-01, `3352625`)** — `tests/e2e/conftest.py` records the companies its session creates and `_e2e_cleanup` deletes them and every row that references them at teardown. Recorded here 2026-10-07.

`integration/` wraps each test in a SAVEPOINT and rolls back. `e2e/` does not — it leaves
users, companies and runs in the database on every run.

Two consequences: the database accumulates test data indefinitely, and tests can pass or
fail depending on residue from earlier runs. The 183 e2e tests are also the slowest tier, so
this is the one most likely to be run repeatedly against one database.

---

### TS-08 — The frontend tests cannot run at all

**✅ Verified · High** · **Status: ✅ fixed (2026-10-09)** — with FE-03: `npm test` (`vitest run`, jsdom) runs every `src/**/*.test.ts(x)` — 8 files, 35 tests — and `tsconfig.json` no longer excludes them, so `tsc` type-checks the tests too.

Two `.test.ts` files exist and both import from `vitest`, which is not installed.

Worse, `tsconfig.json` **excludes** `*.test.ts`, so they are not type-checked either. One of
them is already broken: `useExecutionEvents.test.ts`'s local `_INITIAL` object is missing
the `spans` field added later to `ExecutionEventState`.

So the frontend has two test files that cannot execute and would not compile.

- [`frontend/src/hooks/useExecutionEvents.test.ts`](../../../frontend/src/hooks/useExecutionEvents.test.ts)
- `frontend/src/components/agent/cortex-helpers.test.ts` — deleted 2026-10-01 with the unused module it tested ([FE-14](16-FRONTEND-DEFECTS.md#4-t2--dead-code-and-unused-dependencies))

---

## 4. T2 — Dead scaffolding

| ID | Delete | Notes | Status |
|---|---|---|---|
| **TS-09** | The root `tests/` directory | Four directories containing nothing but `__init__.py` — `fixtures/`, `harness/`, `parity/`, `regression/`. Mirrors four `backend/tests/` names and holds nothing. A leftover from a package-layout experiment | ✅ Verified · **fixed (2026-10-07, `c9edbfd`)** — deleted; all tests live in `backend/tests/` (`19-testing.md` §3.1) |
| **TS-10** | The `kpi` marker and its CI step | Registered in `pytest.ini`, used **0 times**, and `backend/tests/kpi/` does not exist. Both the marker and the CI lane are placeholders | ✅ Verified · **fixed (2026-10-09)** — the marker and `run_ci_matrix.sh`'s `run_kpi` lane are deleted; `test_marker_census.py` fails on a registered marker nothing carries |
| **TS-11** | The `needs_redis` marker | Registered, used **0 times** | ✅ Verified · **fixed (2026-10-09)** — deleted; the Redis-backed tests are in `integration/` and carry that tier |
| **TS-12** | `backend/tests/phase9/` | Two legacy scripts, **no pytest tests**. Also violates the canary-label ban that `lint_ai_layout.py` enforces on `src/ai/` | 📄 Doc-reported · **fixed (2026-10-07, `ebdb54b`)** — deleted; neither script was a test or was referenced (`19-testing.md` §12) |
| **TS-13** | One of the two `MockLLMRouter` classes | Defined in both [`tests/harness/mock_llm.py`](../../../backend/tests/harness/mock_llm.py) and [`tests/fixtures/llm_fixture.py`](../../../backend/tests/fixtures/llm_fixture.py). Which one a test gets depends on its conftest | ✅ Verified · **fixed (2026-10-07, `d3497d6`)** — one double, `tests/harness/mock_llm.py`; `tests/fixtures/llm_fixture.py` keeps only the embedding helpers, and the integration `mock_llm` fixture returns the harness router. `tests/unit/test_one_mock_llm_router.py` |

---

## 5. T3 — Traps and drift

### TS-14 — `@pytest.mark.integration` is used and not registered

**✅ Verified · Medium** · **Status: ✅ fixed (2026-10-09)** — `integration` is registered (and applied by directory); the three uses in `test_egress_proxy_docker.py` became the module's new `docker` marker, with `test_container_runtime_docker.py`; `pytest.ini` has `addopts = --strict-markers`. `test_marker_census.py` collects a probe with `@pytest.mark.needs_dbb` and expects a collection error.

`pytest.ini` registers `parity`, `regression`, `chaos`, `kpi`, `slow`, `needs_db`,
`needs_redis` and `needs_llm`. It does **not** register `integration` — which is used three
times.

An unregistered marker emits a warning and, under `--strict-markers`, fails the run. So the
suite cannot adopt strict markers without a fix, and a typo'd marker today is silently
ignored — a test filtered by it simply never runs.

- [`backend/pytest.ini`](../../../backend/pytest.ini)

---

### TS-15 — Marker usage is far below marker registration

**✅ Verified · Low** · **Status: ✅ fixed (2026-10-09)** — `tests/conftest.py` marks every test under `integration/`, `e2e/`, `parity/`, `regression/` and `chaos/` with its directory (the chaos conftest's own auto-mark folded in), so `-m` selection separates the tiers: 2,129 unit, 455 integration (14 of them `docker`), 203 e2e, 5 chaos, 2 parity, 1 regression — 2,795 in all, each in exactly one tier. `run_ci_matrix.sh`'s fast integration lane is `-m "not (slow or docker)"`. `test_marker_census.py` (6).

| Marker | Registered | Used |
|---|---|---|
| `needs_db` | yes | 8 |
| `chaos` | yes | 3 |
| `slow` | yes | 2 |
| `parity` | yes | 1 |
| `regression` | yes | 1 |
| `needs_llm` | yes | 1 |
| `kpi` | yes | **0** |
| `needs_redis` | yes | **0** |
| `integration` | **no** | 3 |

The CI lanes select by marker (`-m "not (parity or regression or chaos)"`). With 8
`needs_db` markers across 229 infrastructure-dependent tests, marker-based selection cannot
actually separate the fast tier from the slow one — the real separation is by directory.

---

### TS-16 — The parity suite leaves tenants behind

**📄 Doc-reported · Medium** · **Status: ✅ fixed (2026-10-09)** — the parity session deletes the companies it seeded.

Parity runs create `parity-*` tenants and do not clean them up. The advice is to use a
disposable Postgres.

Combined with [TS-07](#ts-07--e2e-does-not-roll-back), two of the eight tiers pollute the
database they run against, and the suite has no teardown story.

**Fixed (2026-10-09).** The e2e teardown's foreign-key walk moved to
`tests/harness/purge.py` (`purge_companies`) and both suites use it. `seed_parity_run`
records each company its `INSERT … RETURNING id` actually created (`SEEDED_COMPANY_IDS`;
a caller's existing company is never recorded), and the session fixture
`_purge_parity_companies` deletes them on a NullPool engine of its own (the app pool's
connections can belong to a loop the in-process worker drainer has closed). The walk now
breaks a reference cycle by setting the back-reference to NULL first:
`hierarchical_entities.active_version_id` → `entity_versions` → `hierarchical_entities`
made every purge of a company with a versioned entity fail — the e2e teardown included,
whenever a test had created one.

Evidence: a parity run left `parity-*` companies, runs and entities at 238 / 589 / 410 —
the counts it found (before: +7 companies, +17 runs, +12 entities a run).
`integration/test_purge_companies.py` (2): a company with a versioned entity and a run is
deleted, another company's rows are untouched; it fails without the cycle handling. An e2e
subset (`test_01`, `02`, `05`, `06`, `10`) left the company and user counts as it found
them. One e2e teardown deadlocked against a live Arq worker still writing `test_06`'s run
and left its rows, with the warning naming its `TEST_ID` — the race the e2e conftest
describes. The 238 `parity-*` companies earlier runs left in the dev database are still
there.

---

### TS-17 — Fixture loading is coupled to the entity schema

**📄 Doc-reported · Medium** · **Status: open** — re-verified 2026-10-07: unchanged. Plan: [H1](REMAINING-DEFECTS-PLAN.md#h1--turn-on-the-lights).

Loading an entity fixture validates it against `HierarchicalEntityCreate`. Any schema change
breaks fixture loading across every tier that uses fixtures.

That coupling is deliberate and useful — it catches drift. The cost is that one schema
change can turn a large part of the suite red at once, which is a strong incentive to
*avoid* schema changes rather than to fix fixtures.

---

### TS-18 — Documentation and reality have drifted in three places

**📄 Doc-reported · Low** · **Status: open** — re-verified 2026-10-07: unchanged. Plan: [H10](REMAINING-DEFECTS-PLAN.md#h10--documentation-and-onboarding).

| Claim | Reality |
|---|---|
| `ONBOARDING.md` says "~420 passed" | `tests/unit/` alone has 745 test functions |
| The eval README says the cases are `*.yml` | they are `*.yaml` |
| 503 tests still carry `@pytest.mark.asyncio` | `asyncio_mode = auto` makes it unnecessary |

Individually trivial. Together they are the reason a newcomer cannot tell whether a run
looks right.

---

### TS-19 — The engine fixture is function-scoped, deliberately

**📄 Doc-reported · Low · accept** · **Status: accepted** — accepted, as the entry decides.

A performance cost accepted for isolation. Recorded so it is not "optimised" into a
session-scoped fixture — that change reintroduces the
`attached to a different loop` failures the session-scoped event loops exist to prevent.

---

## 6. Improvements

### TS-I1 — Turn on CI

**Effect: this is the whole file.** [TS-01](#ts-01--the-only-ci-workflow-has-never-fired),
[TS-02](#ts-02--1063-backend-tests-run-only-when-someone-remembers). Concretely:

1. Fix the `paths` filter on the existing workflow.
2. Add a second workflow that runs `scripts/run_ci_matrix.sh fast` on every pull request,
   with a Postgres service container.
3. Add `lint_ai_layout.py`, ruff and the frontend build to the same job.

There is nothing to write — the lanes, the tests and the gates all exist.

### TS-I2 — Make skips fail in CI

**Effect: large.** [TS-05](#ts-05--three-test-tiers-skip-instead-of-failing). A green run
that skipped 229 infrastructure tests is worse than a red one, because it is believed.

An environment variable that converts the fixture skips into failures gives local
developers the convenience and CI the guarantee.

### TS-I3 — Make an unmocked LLM call fail loudly

**Effect: large.** [TS-06](#ts-06--an-unmocked-llm-call-returns-a-stub-string-not-an-error).
A `STUB:` string that flows through assertions is a test that passes without testing. Raise
by default; keep stub mode behind an explicit fixture.

### TS-I4 — Add teardown to `e2e/` and `parity/`

**Effect: medium.** [TS-07](#ts-07--e2e-does-not-roll-back),
[TS-16](#ts-16--the-parity-suite-leaves-tenants-behind). Either a transactional wrapper like
`integration/` uses, or a fixture that deletes what the test created. Without it, the two
slowest tiers depend on database state nobody controls.

### TS-I5 — Enable `--strict-markers`

**Effect: medium.** [TS-14](#ts-14--pytestmarkintegration-is-used-and-not-registered),
[TS-15](#ts-15--marker-usage-is-far-below-marker-registration). Register `integration`,
delete `kpi` and `needs_redis`, and turn on strict markers so a typo fails instead of
silently excluding a test from every lane.

### TS-I6 — Add the four census tests

**Effect: large — they catch what unit tests structurally cannot.** The platform register
names four mechanical checks, and between them they would have caught eight defects across
this register set:

| Check | Would have caught |
|---|---|
| Route census | [API-05](17-API-REFERENCE-DEFECTS.md#api-05--the-frontend-calls-a-delete-route-that-does-not-exist), [API-08](17-API-REFERENCE-DEFECTS.md#api-08--apiv1phone-pool-does-not-exist-at-runtime) |
| Schema census | [DM-01](03-DATA-MODEL-DEFECTS.md#dm-01--subscription_tiers-has-no-migration), [DM-02](03-DATA-MODEL-DEFECTS.md#dm-02--phone_numbers-is-created-by-a-script-not-a-migration) |
| Registry census | [PO-17](01-PRODUCT-OVERVIEW-DEFECTS.md#4-t2--dead-code-and-dead-surfaces), [TX-04](09-TOOLS-DEFECTS.md#tx-04--meta_spec_critic-is-a-tool-that-is-not-in-the-registry) |
| Dependency census | [LP-07](10-LLM-PROVIDERS-DEFECTS.md#lp-07--any-claude-integration-fails-on-its-first-call), [GW-10](13-GATEWAY-AND-REALTIME-DEFECTS.md#gw-10--aiortc-is-not-installed-and-the-video-path-has-a-second-bug-behind-it) |

### TS-I7 — Add a "declared but never called" check

**Effect: large for this codebase specifically.** The single most common defect shape across
all twenty registers is **a module that is complete, unit-tested, and has no production
call site**: `ToolCostResolver`, `RedisRateLimiter`, `TrustLearner`,
`FailurePatternService`, `check_credit_gate`, `assemble_memory` *(called since MC-01)*, `PlanGenerator.replan`,
`Budget.can_afford`, `get_reasoning`.

A test that asserts every public entry point in a declared "service" module is referenced
from `src/` outside its own tests would have caught all nine — and would have prevented
[BC-05](14-BILLING-AND-CREDITS-DEFECTS.md#bc-05--three-of-the-four-credit-gates-have-no-callers)
and [MC-01](08-MEMORY-AND-CORTEX-DEFECTS.md#mc-01--cortex-is-write-only-on-the-live-path),
the two most consequential findings in this set.

**Being unit-tested is not evidence that a module runs.** That is the lesson this codebase
teaches most clearly, and it is testable.

### TS-I8 — Add a feature-flag census

**Effect: medium.** Assert every key in `DEFAULTS` and `NUMERIC_DEFAULTS` appears in a
`get_bool` or `get_float` call somewhere in `src/`. Eight flags currently fail that check
([GH-16](15-GOVERNANCE-AND-HITL-DEFECTS.md#4-t2--feature-flags-that-are-not-controls)),
including the one where the flag says "on" and the runtime says "off"
([TX-01](09-TOOLS-DEFECTS.md#tx-01--the-per-company-sandbox-flag-is-never-read)).

### TS-I9 — Set up the frontend suite

**Effect: medium.** [TS-08](#ts-08--the-frontend-tests-cannot-run-at-all),
[TS-04](#ts-04--npm-run-lint-cannot-run-and-there-is-no-frontend-test-runner).
`npm i -D vitest jsdom`, add the `test` script, add `.eslintrc.cjs`, drop the `exclude` from
`tsconfig.json`. An afternoon, and it takes the frontend from zero checks to three.

### TS-I10 — Speed up the fast lane so people actually run it

**Effect: medium.** Today the advice is "run `run_ci_matrix.sh fast` before pushing", which
depends on discipline. Two things make it stick: run it automatically
([TS-I1](#ts-i1--turn-on-ci)), and make the local run fast enough that nobody skips it —
`pytest-xdist` on the 745 unit tests plus directory-based selection would put the fast lane
in seconds.

---

## 7. Suggested order of work

| Step | Work | Why here |
|---|---|---|
| **1** | TS-I1 / TS-01, TS-02 | Turn on CI. Everything else in this file is unenforceable without it |
| **2** | TS-I2 / TS-05, TS-I3 / TS-06 | Make silent skips and stub responses fail. A green run must mean something first |
| **3** | T2 deletions — TS-09 to TS-13 | Free. Empty scaffolding, unused markers, a duplicate mock |
| **4** | TS-I5 / TS-14, TS-15 | Register `integration`, enable strict markers |
| **5** | TS-I9 / TS-04, TS-08 | Frontend lint and test runner |
| **6** | TS-I7 | The "declared but never called" check — the highest-value new test for this codebase |
| **7** | TS-I6, TS-I8 | The four censuses and the flag census |
| **8** | TS-I4 / TS-07, TS-16 | Teardown for the two polluting tiers |

---

## Where to go next

- [19 — Testing & quality gates](../19-testing.md) — the source document, including the
  fixture chain and the command cheat-sheet.
- [`DEFECT-REGISTER.md`](../DEFECT-REGISTER.md) — TS-01 is D-14, TS-04 is D-39/D-40, and §9
  Guardrails is TS-I6.
- [18 — Infrastructure & deployment](18-INFRASTRUCTURE-AND-DEPLOYMENT-DEFECTS.md) — IN-05
  and IN-18 are the operations view of TS-01 and TS-03.
- [16 — Frontend](16-FRONTEND-DEFECTS.md) — FE-02 and FE-03 for the frontend half.
