# 19. Testing & Quality Gates

> **What this document covers:** every test tier in the repository, the shared harness and fixtures, how to run each suite, how to write new tests, and the lint/type gates that must pass before a merge.
> **Who should read it:** anyone about to change backend code, and anyone wondering why a suite is skipping.
> **Prerequisites:** [18 — Infrastructure and deployment](18-infrastructure-and-deployment.md) for a working local stack (several suites need Postgres).

---

## Table of contents

1. [The 60-second version](#1-the-60-second-version)
2. [Configuration and markers](#2-configuration-and-markers)
3. [The test pyramid as it actually exists](#3-the-test-pyramid-as-it-actually-exists)
4. [`tests/unit/` — the bulk of the suite](#4-testsunit--the-bulk-of-the-suite)
5. [`tests/ai/` — kernel-focused unit tests](#5-testsai--kernel-focused-unit-tests)
6. [`tests/integration/` — real Postgres, mock LLM](#6-testsintegration--real-postgres-mock-llm)
7. [`tests/e2e/` — the HTTP surface](#7-testse2e--the-http-surface)
8. [`tests/parity/` — the legacy-deletion gate](#8-testsparity--the-legacy-deletion-gate)
9. [`tests/regression/` — YAML cases and an LLM judge](#9-testsregression--yaml-cases-and-an-llm-judge)
10. [`tests/eval/` — offline A/B evaluation](#10-testseval--offline-ab-evaluation)
11. [`tests/chaos/` — fault injection](#11-testschaos--fault-injection)
12. [`tests/phase9/` — legacy scripts](#12-testsphase9--legacy-scripts)
13. [The shared harness](#13-the-shared-harness)
14. [Fixtures on disk](#14-fixtures-on-disk)
15. [Command cheat-sheet](#15-command-cheat-sheet)
16. [How to write a new test](#16-how-to-write-a-new-test)
17. [Quality gates](#17-quality-gates)
18. [Frontend testing](#18-frontend-testing)
19. [Key files reference](#19-key-files-reference)
20. [Gotchas](#20-gotchas)

---

## 1. The 60-second version

There are **1,063 test functions across 130 files** in
`backend/tests/`, split into nine directories by *what infrastructure they
need* rather than by what code they cover.

```mermaid
flowchart TB
    subgraph Hermetic["No infrastructure - always runnable"]
        U["unit/ - 89 files, 745 tests"]
        AI["ai/ - 9 files, 72 tests"]
    end
    subgraph NeedsDB["Needs Postgres"]
        I["integration/ - 9 files, 43 tests"]
        E["e2e/ - 17 files, 181 tests"]
        C["chaos/ - 2 files, 5 tests"]
    end
    subgraph Special["Specialised gates"]
        P["parity/ - golden snapshots"]
        R["regression/ - YAML cases + LLM judge"]
        EV["eval/ - offline A/B with statistics"]
    end

    Hermetic --> NeedsDB --> Special
```

Three things to internalise before you run anything:

1. **`asyncio_mode = auto`.** You do not need `@pytest.mark.asyncio` on new
   tests — though 503 existing tests carry it anyway.
2. **DB-dependent suites skip rather than fail** when Postgres is unreachable.
   A green run does not mean everything ran. Always read the skip count.
3. **No LLM is ever called by default.** `MockLLMRouter` and the hermetic
   `DeterministicAdapter` stand in. `needs_llm` is skipped unless you ask for it.

```bash
cd backend && .venv/bin/python -m pytest tests/unit/ -q
```

> [backend/src/ai/ONBOARDING.md](../../backend/src/ai/ONBOARDING.md) says this
> should print *"~420 passed (Phase 11 baseline)"*. The `tests/unit/` directory
> now contains **745** test functions, so that figure is stale — it was written
> at the Phase 11 baseline and the suite has roughly doubled since. I could not
> execute the suite to confirm the current pass count; the numbers in this
> document are static counts from the source, not from a run.

---

## 2. Configuration and markers

All pytest configuration lives in [backend/pytest.ini](../../backend/pytest.ini)
— **not** in `pyproject.toml`, which only declares `pytest` and
`pytest-asyncio` as dev dependencies.

```ini
# backend/pytest.ini
[pytest]
asyncio_mode = auto
asyncio_default_fixture_loop_scope = session
asyncio_default_test_loop_scope = session
```

`asyncio_mode = auto` means every `async def test_*` is collected and run
without a decorator. Both loop scopes are `session`, which matters for a reason
the parity suite documents at length — see [§8.3](#83-the-single-event-loop-constraint).

### 2.1 The marker catalogue

```ini
# backend/pytest.ini
markers =
    parity: parity tests comparing legacy ExecutionEngine vs new AgentLoop (Track 2+); slow, requires DB+Redis or golden snapshot
    regression: nightly regression suite cases under tests/regression/
    chaos: chaos / fault-injection suites under tests/chaos/
    kpi: KPI drift tests under tests/kpi/
    slow: any test that takes more than 5s on a clean machine
    needs_db: requires a real Postgres connection
    needs_redis: requires a real Redis connection
    needs_llm: makes a real LLM API call (default: skipped)
```

| Marker | Meaning | Where used |
|---|---|---|
| `parity` | Legacy-vs-loop equivalence | `tests/parity/` |
| `regression` | Nightly YAML cases | `tests/regression/` |
| `chaos` | Fault injection | `tests/chaos/` (auto-applied) |
| `kpi` | KPI drift | ⚠️ `tests/kpi/` does not exist |
| `slow` | > 5s on a clean machine | Sparingly |
| `needs_db` | Real Postgres | Sparingly |
| `needs_redis` | Real Redis | Declared, not observed in use |
| `needs_llm` | Real LLM call — **skipped by default** | Declared, not observed in use |

Actual usage across the tree is much thinner than the catalogue suggests:

| Decorator | Occurrences |
|---|---|
| `@pytest.mark.asyncio` | 503 |
| `@pytest.mark.parametrize` | 20 |
| `@pytest.mark.skipif` | 3 |
| `@pytest.mark.integration` | 3 |
| `@pytest.mark.chaos` | 2 |
| `@pytest.mark.slow` | 1 |
| `@pytest.mark.needs_db` | 1 |

> ⚠️ **`@pytest.mark.integration` is used but not registered** in `pytest.ini`.
> With `--strict-markers` that would error; without it, it warns. Conversely
> `needs_redis`, `needs_llm` and `kpi` are registered but effectively unused.
>
> The real skip mechanism is **not markers** — it is `pytest.skip()` called from
> inside conftest fixtures when infrastructure is missing. See
> [§6.1](#61-the-db-fixture-chain).

The comment in `pytest.ini` records the intended CI split:

```ini
# Default pytest run executes everything; CI restricts via `-m "not (parity or regression or chaos)"`
# for fast PRs and `-m "parity or regression"` for nightly.
```

---

## 3. The test pyramid as it actually exists

```mermaid
graph TB
    E2E["e2e/ - 181 tests<br/>real FastAPI app + live Postgres"]
    INT["integration/ - 43 tests<br/>real Postgres, mock LLM, SAVEPOINT rollback"]
    AIT["ai/ - 72 tests<br/>kernel units"]
    UNIT["unit/ - 745 tests<br/>pure, no infrastructure"]

    UNIT --> AIT --> INT --> E2E

    SPEC["parity 2 - regression 1 - eval 14 - chaos 5<br/>specialised gates"]

    style UNIT fill:#2d4a2d,stroke:#5a9
    style E2E fill:#4a3a2d,stroke:#a85
```

| Directory | Files | Test functions | Needs | Runtime |
|---|---|---|---|---|
| `unit/` | 89 | 745 | nothing | seconds |
| `e2e/` | 17 | 183 | Postgres + app | minutes |
| `ai/` | 9 | 72 | nothing | seconds |
| `integration/` | 9 | 44 | Postgres | tens of seconds |
| `eval/` | 1 | 14 | nothing (pure metric tests) | seconds |
| `chaos/` | 2 | 5 | varies by fault | seconds |
| `parity/` | 2 | 2 | Postgres + Redis + goldens | minutes |
| `regression/` | 1 | 1 | Postgres + LLM judge | minutes |
| `phase9/` | 0 | 1 | — | — |
| `fixtures/`, `harness/` | 0 | 0 | — | support code |

The shape is healthy at the base — 745 pure unit tests is a lot — but note the
**183 e2e tests** are unusually numerous for the top of a pyramid, and they are
the slowest and most infrastructure-dependent tier.

The `parity` and `regression` directories have only 1–2 test *functions* each,
but each function iterates internally over every golden or YAML case, so the
function count understates their coverage.

### 3.1 The duplicate `tests/` at the repo root

There is a second, near-empty `tests/` tree at the repository root:

```
tests/
├── fixtures/__init__.py
├── harness/__init__.py
├── parity/__init__.py
└── regression/__init__.py
```

Four directories containing nothing but `__init__.py` files. It mirrors four of
the `backend/tests/` subdirectory names but holds no tests, no fixtures and no
harness code.

> ⚠️ This appears to be a leftover from a package-layout experiment. **All real
> tests live in `backend/tests/`.** Do not add anything to the root `tests/`.

---

## 4. `tests/unit/` — the bulk of the suite

89 files, 745 test functions, no infrastructure. This is where the majority of
coverage lives and where your new tests should go by default.

```bash
cd backend && .venv/bin/python -m pytest tests/unit/ -q
```

Representative files, by subsystem:

| File | Covers |
|---|---|
| `test_agent_loop_integration.py` | Drives `AgentLoop` against stub executors; `test_agent_loop_runs_one_step_to_completion` is the canonical "what one iteration looks like" test |
| `test_tool_status.py` | Tool visibility and feature-flag gating |
| `test_regression_suite.py` | The **loader** for regression YAML cases — run this after adding a case |
| `test_internal_keys_documented.py` | Enforces `constants.py::INTERNAL_CONTEXT_KEYS` matches `core/INTERNAL_KEYS.md` |

That last one is worth calling out: it is a **documentation test**. Adding a key
to `INTERNAL_CONTEXT_KEYS` without updating the markdown table fails CI. See
[08 — Memory and CORTEX §12.1](08-memory-and-cortex.md#121-internal-key-scrubbing).

There is **no `tests/unit/conftest.py`** — unit tests construct their own
doubles inline, which is why they run anywhere.

---

## 5. `tests/ai/` — kernel-focused unit tests

9 files, 72 tests, organised by AI subpackage:

```
tests/ai/
├── core/       # AgentLoop, AgentState, executors
├── memory/     # CORTEX, domains, assembly
└── planning/   # planner, critics, bandit
```

```bash
cd backend && .venv/bin/python -m pytest tests/ai/ -q
```

The split between `tests/unit/` and `tests/ai/` is historical rather than
principled — both are hermetic. `tests/ai/` mirrors the `src/ai/` package
structure; `tests/unit/` is a flat directory. When adding a test for AI code,
follow whichever convention the neighbouring tests for that module already use.

---

## 6. `tests/integration/` — real Postgres, mock LLM

9 files, 43 tests. The contract is stated at the top of
[tests/integration/conftest.py](../../backend/tests/integration/conftest.py):

```python
# backend/tests/integration/conftest.py
"""
These tests:
  * Hit a real Postgres (``DATABASE_URL`` from env, same as the app).
  * Use the MockLLMRouter fixture so no live LLM calls are made.
  * Each test runs in its own SAVEPOINT and rolls back at teardown so
    the DB stays clean across the suite.
"""
```

### 6.1 The DB fixture chain

```mermaid
flowchart TD
    URL["_db_url()<br/>settings.DATABASE_URL or env"] --> CHK{"URL present?"}
    CHK -->|no| SKIP1["pytest.skip - suite skipped"]
    CHK -->|yes| ENG["_engine fixture<br/>create_async_engine per test"]
    ENG --> PING{"SELECT 1 succeeds?"}
    PING -->|no| SKIP2["pytest.skip - Postgres unreachable"]
    PING -->|yes| DB["db fixture<br/>connect + begin transaction"]
    DB --> SESS["AsyncSession bound to the connection"]
    SESS --> TEST["Test body"]
    TEST --> RB["close session + trans.rollback()"]
    RB --> CLEAN["DB unchanged"]
```

The rollback pattern:

```python
# backend/tests/integration/conftest.py
@pytest_asyncio.fixture
async def db(_engine) -> AsyncIterator[Any]:
    """Per-test async session wrapped in a SAVEPOINT.

    Every write the test does is rolled back at teardown, so the
    suite is order-independent and doesn't leak fixture rows.
    """
    from sqlalchemy.ext.asyncio import AsyncSession
    async with _engine.connect() as conn:
        trans = await conn.begin()
        async_session = AsyncSession(bind=conn, expire_on_commit=False)
        try:
            yield async_session
        finally:
            await async_session.close()
            await trans.rollback()
```

**The engine is function-scoped**, and the conftest explains why:

```python
# backend/tests/integration/conftest.py
"""Function-scoped async engine.

asyncpg can't share connections across event loops, and
pytest-asyncio gives each test its own loop. A new engine per test
is the price of clean isolation; the reconnect overhead is
negligible against the DB ops the tests do.
"""
```

This asyncpg/event-loop constraint recurs across the whole test suite — it is
the single most important thing to understand about async testing here.

### 6.2 Fixtures provided

| Fixture | Scope | Provides |
|---|---|---|
| `_engine` | function | Async engine, skips if DB unreachable |
| `db` | function | `AsyncSession` in a transaction, rolled back at teardown |
| `test_company_id` | function | A throwaway `TENANT` company row |
| `mock_llm` | function | `MockLLMRouter()` |

`test_company_id` inserts via raw SQL and returns the UUID:

```python
# backend/tests/integration/conftest.py
await db.execute(
    text(
        """
        INSERT INTO companies (id, name, type, status, created_at, updated_at)
        VALUES (:id, :name, 'TENANT', 'active', now(), now())
        """
    ),
    {"id": str(cid), "name": f"integration-test-{cid.hex[:8]}"},
)
```

Run:

```bash
cd backend && DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5433/hirebuddha .venv/bin/python -m pytest tests/integration/ -q
```

Note port **5433** — see [18 — Infrastructure](18-infrastructure-and-deployment.md).

---

## 7. `tests/e2e/` — the HTTP surface

17 files, 181 tests — the largest tier after `unit/`. These drive the **real
FastAPI app** through an in-process ASGI transport.

```python
# backend/tests/e2e/conftest.py
"""
Shared fixtures for E2E tests.
Uses httpx.AsyncClient against the real FastAPI app + live PostgreSQL.
"""
```

```mermaid
sequenceDiagram
    participant T as Test
    participant C as httpx.AsyncClient
    participant A as FastAPI app (in-process ASGI)
    participant DB as Live PostgreSQL

    T->>C: POST /api/v1/auth/register
    C->>A: ASGITransport - no network
    A->>DB: INSERT user
    T->>C: POST /api/v1/auth/login
    C->>A: ASGITransport
    A-->>C: {access_token, refresh_token}
    T->>C: GET /api/v1/ai/entities (Bearer token)
    C->>A: ASGITransport
    A->>DB: SELECT scoped by company_id
    A-->>T: response
```

The client is **session-scoped** and uses `ASGITransport`, so no socket is
opened — but the database is real and **writes are not rolled back**.

Isolation comes from a per-session unique suffix instead:

```python
# backend/tests/e2e/conftest.py
TEST_ID = uuid.uuid4().hex[:8]

def _email(role: str) -> str:
    return f"e2e_{role}_{TEST_ID}@test.hirebuddha.com"
```

Every run creates fresh users at `e2e_<role>_<random>@test.hirebuddha.com`.

> ⚠️ **The e2e suite leaves data behind.** Unlike `integration/`, there is no
> transaction rollback. Repeated runs accumulate companies, users, entities and
> runs in your database. Use a disposable Postgres, or periodically clean rows
> matching `%@test.hirebuddha.com`.

The `register_and_login` helper ignores duplicate registration and returns both
tokens, and `auth_headers(token)` builds the `Authorization` header — most e2e
tests start with those two calls.

```bash
cd backend && .venv/bin/python -m pytest tests/e2e/ -q
```

---

## 8. `tests/parity/` — the legacy-deletion gate

The most conceptually interesting suite. Its purpose, from
[tests/parity/README.md](../../backend/tests/parity/README.md):

> Parity = "the new `AgentLoop` produces functionally-equivalent output to the
> legacy `ExecutionEngine`." This is the evidence gate that must be **green
> before the C4 legacy-deletion** … once the legacy engine is deleted there is
> no fallback, so we prove equivalence first.

```mermaid
flowchart LR
    CASE["regression YAML case"] --> REC["record_golden_runs.py<br/>runs the LEGACY engine"]
    REC --> GOLD["goldens/case.json<br/>checked in"]
    GOLD --> CMP["test_agent_loop_parity.py"]
    CAND["Fresh AgentLoop run"] --> CMP
    CMP --> TOL{"within ParityTolerance?"}
    TOL -->|yes| PASS["Parity proven"]
    TOL -->|no| FAIL["Engine regression"]
```

### 8.1 Hermetic by construction

The gate runs with **no API keys and no network**:

> * `hermetic.py::DeterministicAdapter` replaces `LLMRouter._resolve_adapter`,
>   so every `call_llm` / `call_llm_react` returns canned, fixed-token
>   responses while the real tracing / usage / cost code still runs.
> * the network-bound `web_search` tool is stubbed with a fixed result.

The reasoning is exact: *"Because the LLM is held constant, any parity violation
is attributable to the **engine** (planning / orchestration / critics)."* Holding
the non-deterministic component fixed is what makes the comparison meaningful.

### 8.2 What is compared

| Dimension | Enforced? |
|---|---|
| Run status | ✅ |
| Cost band | ✅ |
| Step-count delta | ✅ |
| Output cosine similarity | ✅ |
| Wall-clock time | ❌ disabled — *"mock timing is infra-noise"* |

Output similarity compares `result_data["output"]` only, not the whole envelope,
because the envelope embeds run-specific `child_run_id` UUIDs *"that would
penalize even identical engines under the hashed-token cosine."*

### 8.3 The single-event-loop constraint

The README explains why all cases run in one test function:

> All cases run inside a **single event loop** on purpose: the kernel's global
> `AsyncSessionLocal` engine binds to the loop it is first used on and asyncpg
> connections cannot cross loops, so one-test-per-loop parametrisation trips
> "attached to a different loop." The test iterates internally and aggregates
> per-case results instead.

This is also why `pytest.ini` sets both `asyncio_default_fixture_loop_scope` and
`asyncio_default_test_loop_scope` to `session`.

**If you see "attached to a different loop" in any async test, this is your
cause.** Do not parametrise a test that touches the global session factory.

### 8.4 Running it

```bash
cd backend && .venv/bin/python -m scripts.record_golden_runs --output tests/parity/goldens
```

```bash
cd backend && .venv/bin/python -m pytest tests/parity -o addopts="" -q
```

The gate **skips cleanly** when goldens are missing or Postgres/Redis are
unreachable. With a real LLM key, `--no-hermetic` records from live provider
runs instead.

### 8.5 Files and cases

| File | Role |
|---|---|
| `hermetic.py` | `DeterministicAdapter`, `hermetic_llm_and_tools()`, `seed_parity_run()` |
| `extract.py` | Builds a `RunResult` from a finished `ExecutionRun` |
| `harness.py` | `run_parity_case()` — seed → run → extract → compare |
| `conftest.py` | Engine adapters, DB/Redis fixtures, autouse hermetic patches |
| `worker_sim.py` | Simulates worker dispatch |
| `c4_resumability.py` | Suspend/resume checks |
| `test_agent_loop_parity.py` | The gate |
| `test_async_child_parity.py` | Child-run equivalence |

Three goldens, matching three regression cases:

| Case | Entity type | What it proves |
|---|---|---|
| `simple_skill_topic_easy` | SKILL | Strong positive — matching cost, steps, output |
| `research_agent_brief` | AGENT | Both COMPLETE |
| `research_process_pipeline` | PROCESS | Multi-child fan-out — the child-execution coverage |

### 8.6 Known limitations

The README is candid, and these matter operationally:

- **Seeded `parity-*` tenants are not torn down** — the run spawns CORTEX
  nodes and trees with FK chains. Use a disposable test Postgres.
- **The loop persists thinner run metadata than legacy** for static PROCESS runs
  (no `result_data["steps"]`, no `dynamic_plan` steps).

---

## 9. `tests/regression/` — YAML cases and an LLM judge

Nightly suite. Each case is a YAML file declaring what to run and how to grade
it, validated against `case_schema.py::RegressionCase`.

```yaml
# backend/tests/regression/cases/simple_skill_topic_easy.yaml
case_id: simple_skill_topic_easy
entity_fixture: simple_skill
track_min: 0
timeout_seconds: 120
input:
  topic: "post-quantum cryptography 2025 progress"
expected_status: COMPLETED
expected_min_cost_usd: 0.005
expected_max_cost_usd: 0.30
expected_must_mention:
  - "NIST"
  - "lattice"
expected_must_not_mention:
  - "asset management"
tags: ["skill", "research", "smoke"]
acceptance:
  llm_judge_threshold: 0.7
  output_min_chars: 80
```

```mermaid
flowchart TD
    Y["cases/*.yaml"] --> L["loader.py<br/>validate against RegressionCase"]
    L --> F["Load entity_fixture from tests/fixtures/entities/"]
    F --> RUN["runner.py - execute"]
    RUN --> G1{"status == expected_status?"}
    G1 --> G2{"cost within min/max band?"}
    G2 --> G3{"all must_mention present?"}
    G3 --> G4{"no must_not_mention present?"}
    G4 --> G5{"output_min_chars met?"}
    G5 --> J["judge.py - LLM judge"]
    J --> G6{"score >= llm_judge_threshold?"}
    G6 -->|yes| PASS["Case passes"]
    G6 -->|no| FAIL["Case fails"]
```

The grading is layered: cheap deterministic checks (status, cost band, string
presence/absence, length) run first, and only then does the LLM judge score
quality against `llm_judge_threshold`.

### 9.1 Adding a case

From [tests/regression/README.md](../../backend/tests/regression/README.md):

1. Pick an entity fixture from `tests/fixtures/entities/` (or add one).
2. Drop a YAML at `cases/<your_case_id>.yaml` with at minimum `case_id`,
   `entity_fixture`, `input`, `expected_status`, `expected_must_mention`.
3. Confirm the loader accepts it:
   ```bash
   cd backend && .venv/bin/python -m pytest tests/unit/test_regression_suite.py -q
   ```
4. CI nightly picks it up automatically.

Step 3 is the important one — a malformed YAML fails at load time, and that unit
test is the fast feedback loop.

`track_min` gates a case to a minimum implementation track, so cases can be
added before the feature that satisfies them exists.

---

## 10. `tests/eval/` — offline A/B evaluation

14 tests, all pure. This is not a pass/fail suite — it is a **measurement
harness**. From [tests/eval/README.md](../../backend/tests/eval/README.md):

> Turns "we think config B is better" into **"+6pp goal-hit at −9% cost,
> p<0.05"**. Replays a fixed corpus through two named configs and reports the
> deltas *with* significance.

```mermaid
flowchart LR
    CORPUS["Corpus = tests/regression/cases/*.yml"] --> A["Replay under EvalConfig A"]
    CORPUS --> B["Replay under EvalConfig B"]
    A --> MA["RunMetrics per case"]
    B --> MB["RunMetrics per case"]
    MA --> AGG["ConfigAggregate"]
    MB --> AGG
    AGG --> DELTA["delta_report<br/>two-proportion z for rates<br/>Welch's t for cost and latency"]
    DELTA --> REP["render_report"]
```

| File | Role | Pure? |
|---|---|---|
| `metrics.py` | Aggregate `RunMetrics` → `ConfigAggregate`; `delta_report`; `render_report` | ✅ |
| `runner.py` | `grade` (pure) and `run_corpus` (injected `run_fn`) | `grade` ✅ |
| `config.py` | `EvalConfig` — a named bundle of flag/numeric overrides | ✅ |

Significance testing is hand-rolled — *"p via `math.erfc` — no scipy"* — which
keeps the dependency footprint small.

### 10.1 The four headline metrics

| Metric | Definition |
|---|---|
| `goal_hit_rate` | Fraction reaching the expected outcome (status + mentions) |
| `cost_per_success` | Total USD / successful cases — the efficiency lever |
| `false_pass_rate` | Critic said "good" but the corpus check fails — calibration |
| `mean_latency_ms` | Wall-clock per case |

`false_pass_rate` is the one that feeds critic calibration — see
[07 — Planning and critics](07-planning-and-critics.md).

### 10.2 Config pairs it is built to compare

- Deterministic vs **LLM Strategist** — `agent_loop.llm_strategist_enabled`
- Task classifier **v1-rules vs v2-embedding** — `task_classifier.v2_enabled`

Both are feature flags from [15 — Governance and flags](15-governance-and-hitl.md).

Note the corpus is *"just `tests/regression/cases/*.yml`… no separate format"* —
adding a regression case automatically enlarges the eval corpus.

> ⚠️ The eval README refers to `*.yml` while the actual case files use `*.yaml`.
> Check the loader's glob if a case is not picked up.

---

## 11. `tests/chaos/` — fault injection

2 files, 5 tests. The template is stated in the conftest:

```python
# backend/tests/chaos/conftest.py
"""Each chaos case follows the same template:

  1. Set up a baseline that should work.
  2. Inject a fault (DB unreachable, tool 500, missing table, …).
  3. Assert the system DEGRADES gracefully — emits a structured event,
     does not crash, returns a defined error envelope.
"""
```

```mermaid
stateDiagram-v2
    [*] --> Baseline: set up working state
    Baseline --> Fault: inject fault
    Fault --> Degraded: system handles it
    Fault --> Crash: system does not
    Degraded --> [*]: test passes
    Crash --> [*]: test fails
    note right of Degraded
        Assert: structured event emitted,
        no crash, defined error envelope
    end note
```

| File | Fault injected |
|---|---|
| `test_feature_flags_table_unavailable.py` | The `feature_flags` table does not exist |
| `test_tool_returns_500.py` | A tool returns HTTP 500 |

The first directly exercises the "DB table is OPTIONAL" property of the
feature-flag service documented in
[15 — Governance §12.2](15-governance-and-hitl.md#122-the-db-table-is-optional).

Markers are applied automatically so contributors cannot forget:

```python
# backend/tests/chaos/conftest.py
def pytest_collection_modifyitems(config, items):
    """Auto-mark every test under tests/chaos as @pytest.mark.chaos so a
    contributor doesn't have to remember to add the decorator."""
    for item in items:
        if "tests/chaos" in str(item.fspath):
            item.add_marker(pytest.mark.chaos)
```

```bash
cd backend && .venv/bin/python -m pytest tests/chaos/ -q -m chaos
```

> Given how many code paths in this platform **fail open** (see the gotchas in
> [15](15-governance-and-hitl.md) and [08](08-memory-and-cortex.md)), five chaos
> tests is thin coverage. This directory is the natural home for tests asserting
> that a swallowed exception still emits an observable signal.

---

## 12. `tests/phase9/` — legacy scripts

Two files, and they are **not pytest tests**:

| File | What it is |
|---|---|
| `check_run.py` | A manual run-inspection script |
| `run_all_tests.py` | A pre-pytest test runner |

No `test_*.py` files, so `pytest tests/phase9/` collects nothing. Treat this
directory as historical. It predates the current suite layout.

---

## 13. The shared harness

[tests/harness/](../../backend/tests/harness/) is support code, not tests.

```mermaid
classDiagram
    class MockLLMRouter {
        +fixtures dict
        +call_llm(...) MockLLMResponse
        +call_llm_react(...) MockLLMResponse
    }
    class MockLLMResponse {
        +str output
        +int prompt_tokens
        +int completion_tokens
        +float cost_usd
        +int latency_ms
        +str model_name
        +str model_provider
        +dict metadata
    }
    class RunResult {
        +compare_run_results(...)
    }
    MockLLMRouter --> MockLLMResponse
```

| File | Lines | Provides |
|---|---|---|
| `mock_llm.py` | 183 | `MockLLMRouter`, `MockLLMResponse` |
| `run_result.py` | 256 | `RunResult`, `compare_run_results`, `ParityTolerance` |
| `embeddings.py` | 75 | Deterministic embedding doubles |
| `fixtures.py` | 59 | Fixture loaders |
| `__init__.py` | 62 | Re-exports |

### 13.1 `MockLLMRouter`

```python
# backend/tests/harness/mock_llm.py
"""
A test fixture file maps ``(task_type, prompt_hash)`` keys to recorded
``LLMResponse`` payloads. When a test asks the mock for an LLM call
that has no fixture, the mock falls back to a deterministic stub
generator so the run still terminates (with a clear "STUB:" prefix in
the output) rather than throwing.
"""
```

Two modes, both needed:

| Mode | Use |
|---|---|
| Replay | Record a golden with the real router, then replay the fixture |
| Inline | Construct `MockLLMRouter(fixtures={...})` and assert on **prompt shape**, not response text |

The fallback behaviour is the good design choice here: an unmatched call returns
a `STUB:`-prefixed response rather than raising, so a test exercising a new code
path still terminates and you can see in the output which calls were unmocked.

The harness deliberately does not import the production `LLMResponse`:

```python
# backend/tests/harness/mock_llm.py
# Lightweight response wrapper — production code uses
# ``src.ai.llm.types.LLMResponse`` but we don't want to import the heavy
# router module from tests/harness/ (keeps the harness importable even
# when half the kernel is broken mid-refactor).
```

That is why `MockLLMRouter` *"matches the surface of `LLMRouter` only loosely"*.

### 13.2 Fixture loaders

```python
# backend/tests/harness/fixtures.py
FIXTURES_ROOT = Path(__file__).resolve().parent.parent / "fixtures"

def load_entity_fixture(name: str) -> HierarchicalEntityCreate:
    """Read ``fixtures/entities/<name>.json`` and validate against the schema.

    Returns a ``HierarchicalEntityCreate``. Validation is the test that
    the fixture is well-formed for the current schemas package.
    """
```

Note the second sentence — **loading a fixture is itself a schema test**. If you
change `HierarchicalEntityCreate`, every fixture must still validate.

| Function | Returns |
|---|---|
| `fixture_path(*parts)` | Path under `tests/fixtures/` |
| `load_entity_fixture(name)` | Validated `HierarchicalEntityCreate` |
| `load_entity_fixture_raw(name)` | Raw dict, for tests that mutate |
| `load_meta_input(name)` | Meta-Agent input dict |
| `list_entity_fixtures()` | Names of every entity fixture on disk |

`tests/fixtures/llm_fixture.py` (111 lines) additionally exposes
`MockLLMRouter`, `deterministic_embedding` and `cosine_similarity` — the
integration conftest imports from there rather than from `harness/`.

> ⚠️ There are **two** `MockLLMRouter` definitions — one in
> `tests/harness/mock_llm.py` and one re-exported from
> `tests/fixtures/llm_fixture.py`. Check which one your conftest imports before
> assuming behaviour.

---

## 14. Fixtures on disk

```
tests/fixtures/
├── entities/
│   ├── research_agent.json
│   ├── research_process.json
│   └── simple_skill.json
├── cortex/
│   └── canonical_tree.json
├── meta_inputs/
│   ├── hostile.json
│   ├── research_agent.json
│   └── simple_skill.json
└── llm_fixture.py
```

| Fixture | Type | Used by |
|---|---|---|
| `simple_skill` | SKILL entity | Unit, parity, regression — the simplest end-to-end case |
| `research_agent` | AGENT entity | Parity, regression, meta inputs |
| `research_process` | PROCESS entity | Multi-child parity case |
| `canonical_tree` | CORTEX tree seed | Memory tests |
| `meta_inputs/hostile` | Adversarial Meta-Agent input | Board hostile-case testing |

Reuse these rather than building new ones — they are already wired into the
parity goldens and regression cases.

---

## 15. Command cheat-sheet

Everything runs from `backend/`.

```bash
cd backend && .venv/bin/python -m pytest tests/unit/ -q
```

```bash
cd backend && .venv/bin/python -m pytest tests/ -q
```

```bash
cd backend && .venv/bin/python -m pytest tests/unit/test_agent_loop_integration.py -v
```

```bash
cd backend && .venv/bin/python -m pytest tests/unit/test_agent_loop_integration.py::test_agent_loop_runs_one_step_to_completion -v
```

```bash
cd backend && .venv/bin/python -m pytest tests/ -k "cortex and not slow" -q
```

```bash
cd backend && .venv/bin/python -m pytest tests/ -m "not (parity or regression or chaos)" -q
```

```bash
cd backend && .venv/bin/python -m pytest tests/ -m "parity or regression" -q
```

```bash
cd backend && .venv/bin/python -m pytest tests/unit/ -q -x --tb=short
```

```bash
cd backend && .venv/bin/python -m pytest tests/unit/ --log-cli-level=DEBUG -s -k my_test
```

The `-s` is essential when debugging — without it pytest captures stdout and you
will not see log output.

### 15.1 The CI lanes

[scripts/run_ci_matrix.sh](../../backend/scripts/run_ci_matrix.sh) bundles them:

```bash
cd backend && scripts/run_ci_matrix.sh fast
```

```mermaid
flowchart TD
    subgraph Fast["fast - every PR"]
        F1["lint_ai_layout.py"] --> F2["typecheck_ai.py"]
        F2 --> F3["pytest tests/unit/"]
        F3 --> F4["pytest tests/integration/<br/>-m 'not (slow or chaos or parity or regression or kpi)'"]
    end
    subgraph Nightly["nightly"]
        N1["pytest tests/chaos/ -m chaos"]
        N2["pytest tests/parity/"]
        N3["pytest tests/regression/"]
        N4["pytest tests/kpi/ -m kpi"]
    end
    subgraph Migration["migration"]
        M1["alembic upgrade head"] --> M2["alembic downgrade -1"]
        M2 --> M3["alembic upgrade head"]
    end
```

| Lane | Runs |
|---|---|
| `fast` | layout lint → typecheck → unit → fast integration |
| `nightly` | chaos, parity, regression, KPI |
| `migration` | Alembic up → down → up round-trip |
| `all` | Every lane sequentially |

The `kpi` step degrades gracefully:

```bash
# backend/scripts/run_ci_matrix.sh
run_kpi() {
    bold "KPI drift suite"
    if [ -d tests/kpi ]; then
        $PYTEST tests/kpi/ -q -m kpi
    else
        echo "(no tests/kpi/ yet — skipped)"
    fi
}
```

`tests/kpi/` does not exist, so this always prints the skip message.

The `migration` lane is genuinely valuable — `downgrade -1` catches
irreversible migrations before they reach production, which matters for the
rollback runbook in [18 §16.10](18-infrastructure-and-deployment.md#1610-roll-back).

> ⚠️ **None of these lanes are wired to a CI trigger.** The only GitHub Actions
> workflow covers the extracted `cortex_memory` package, and its `paths` filter
> does not even match the directory currently in the tree. Run
> `scripts/run_ci_matrix.sh fast` manually before pushing. See
> [18 §13](18-infrastructure-and-deployment.md#13-continuous-integration).

---

## 16. How to write a new test

### 16.1 A pure service unit test

```python
# backend/tests/unit/test_my_service.py
from src.ai.memory.rule_lifecycle import RuleLifecycle, next_state


def test_candidate_promotes_after_three_net_validations():
    assert next_state("candidate", validations=3, contradictions=0) is RuleLifecycle.CONFIRMED


def test_candidate_stays_candidate_below_threshold():
    assert next_state("candidate", validations=2, contradictions=0) is RuleLifecycle.CANDIDATE
```

No decorator, no fixture, no infrastructure. Put it in `tests/unit/`.

### 16.2 An async test

```python
# backend/tests/unit/test_my_async_service.py
async def test_flag_falls_back_to_default_without_db():
    from src.ai.core.feature_flags import FeatureFlags
    flags = FeatureFlags(db=None)
    assert await flags.is_on("bandit.enabled") is True
```

`asyncio_mode = auto` collects this without `@pytest.mark.asyncio`.

### 16.3 A test that needs the database

```python
# backend/tests/integration/test_my_repo.py
import pytest
from sqlalchemy import text


async def test_entity_is_scoped_to_company(db, test_company_id):
    await db.execute(
        text("INSERT INTO hierarchical_entities (id, company_id, type, status, name, version) "
             "VALUES (gen_random_uuid(), :cid, 'ACTION', 'ACTIVE', 'probe', '1.0.0')"),
        {"cid": str(test_company_id)},
    )
    await db.flush()
    rows = await db.execute(
        text("SELECT count(*) FROM hierarchical_entities WHERE company_id = :cid"),
        {"cid": str(test_company_id)},
    )
    assert rows.scalar() == 1
```

Use the `db` and `test_company_id` fixtures. Everything rolls back automatically
— do **not** call `db.commit()`, or you defeat the isolation.

### 16.4 A test with a mocked LLM

```python
# backend/tests/integration/test_my_llm_path.py
async def test_planner_prompt_includes_the_goal(db, test_company_id, mock_llm):
    from src.ai.planning.plan_generator import PlanGenerator
    gen = PlanGenerator(db, test_company_id, llm=mock_llm)
    await gen.generate(goal="summarise Q3 revenue")
    prompt = mock_llm.calls[-1].prompt
    assert "summarise Q3 revenue" in prompt
```

Assert on **prompt shape**, not response text — the mock's response is either a
fixture or a `STUB:` string, so asserting on it tests nothing.

### 16.5 An API test

```python
# backend/tests/e2e/test_my_endpoint.py
from tests.e2e.conftest import auth_headers, register_and_login, _email


async def test_entities_requires_auth(client):
    resp = await client.get("/api/v1/ai/entities")
    assert resp.status_code == 401


async def test_entities_returns_list_for_authenticated_user(client):
    token, _ = await register_and_login(
        client, _email("tenant"), "Passw0rd!", "Test Tenant"
    )
    resp = await client.get("/api/v1/ai/entities", headers=auth_headers(token))
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
```

### 16.6 A chaos test

```python
# backend/tests/chaos/test_my_fault.py
async def test_service_degrades_when_redis_is_down(monkeypatch):
    # 1. baseline
    # 2. inject: make redis raise
    # 3. assert graceful degradation, not a crash
    ...
```

The `chaos` marker is applied automatically by the conftest.

### 16.7 A regression case

Add a YAML to `tests/regression/cases/`, then validate the loader:

```bash
cd backend && .venv/bin/python -m pytest tests/unit/test_regression_suite.py -q
```

---

## 17. Quality gates

```mermaid
flowchart TD
    DEV["Local change"] --> G1["ruff check src/"]
    G1 --> G2["black src/"]
    G2 --> G3["scripts/lint_ai_layout.py"]
    G3 --> G4["scripts/typecheck_ai.py"]
    G4 --> G5["pytest tests/unit/"]
    G5 --> G6["pytest tests/integration/ (fast)"]
    G6 --> FE["npm run lint && npm run build"]
    FE --> PR["Push"]
```

| Gate | Command | Enforces | Fixing a failure |
|---|---|---|---|
| ruff | `.venv/bin/ruff check src/` | E, F, I, B rule sets; 88 cols | `ruff check --fix src/` for most |
| black | `.venv/bin/black src/` | Formatting | Run it; it rewrites in place |
| layout lint | `.venv/bin/python scripts/lint_ai_layout.py` | Package line caps, top-level allowlist, forbidden imports | Extract code into a new module |
| typecheck | `.venv/bin/python scripts/typecheck_ai.py` | `mypy --strict` on an allowlist | Add annotations, or don't add the package to the allowlist yet |
| unit | `pytest tests/unit/ -q` | Behaviour | — |
| frontend lint | `npm run lint` | ESLint, `--max-warnings 0` | A warning fails it |
| frontend build | `npm run build` | `tsc` then `vite build` | Type errors fail the build |

The layout lint is the one that surprises people. It enforces **per-package
maximum file lengths**, and `core` currently sits at 1480/1500 — see
[18 §14.1](18-infrastructure-and-deployment.md#141-lint_ai_layoutpy--architectural-rules).
Adding twenty lines to `agent_loop.py` breaks the build by design.

### 17.1 Documentation tests

Two gates enforce that docs match code:

| Test | Enforces |
|---|---|
| `test_internal_keys_documented` | `INTERNAL_CONTEXT_KEYS` matches the table in `core/INTERNAL_KEYS.md` |
| `tests/integration/test_cost_attribution.py` | Every cost surface writes an attributed `usage_logs` row |

The second is the CI guard behind the `tools.cost_attribution_required` flag —
see [15 §13.5](15-governance-and-hitl.md#135-tools-and-cost).

---

## 18. Frontend testing

Two test files exist:

| File | Covers |
|---|---|
| [cortex-helpers.test.ts](../../frontend/src/components/agent/cortex-helpers.test.ts) | CORTEX tree rendering helpers |
| [useExecutionEvents.test.ts](../../frontend/src/hooks/useExecutionEvents.test.ts) | The SSE execution-event hook |

> ⚠️ **No test runner is configured.** `frontend/package.json` has four scripts
> — `dev`, `build`, `lint`, `preview` — and **no `test` script**. Neither Vitest
> nor Jest appears in `dependencies` or `devDependencies`. These two `.test.ts`
> files cannot currently be executed by any command in the repository.
>
> They are written in a Vitest-compatible style. Wiring it up would mean adding
> `vitest` as a dev dependency and a `"test": "vitest"` script — a small change
> that would immediately make two existing test files useful.

For a 25,000-line React application including a 1,780-line configuration screen
and a live-trace viewer, two unexecutable test files is the largest coverage gap
in the repository.

The only automated frontend checks that do run are `npm run lint`
(`--max-warnings 0`) and `npm run build` (which runs `tsc` first, so type errors
are caught).

---

## 19. Key files reference

| File | Lines | What it does |
|---|---|---|
| [backend/pytest.ini](../../backend/pytest.ini) | 19 | All pytest config — `asyncio_mode`, markers |
| [tests/harness/run_result.py](../../backend/tests/harness/run_result.py) | 256 | `RunResult`, `compare_run_results`, `ParityTolerance` |
| [tests/e2e/conftest.py](../../backend/tests/e2e/conftest.py) | 225 | httpx client, register/login helpers |
| [tests/harness/mock_llm.py](../../backend/tests/harness/mock_llm.py) | 183 | `MockLLMRouter`, `MockLLMResponse` |
| [tests/integration/conftest.py](../../backend/tests/integration/conftest.py) | 127 | DB engine, SAVEPOINT session, `test_company_id`, `mock_llm` |
| [tests/parity/conftest.py](../../backend/tests/parity/conftest.py) | 124 | Engine adapters, autouse hermetic patches |
| [tests/fixtures/llm_fixture.py](../../backend/tests/fixtures/llm_fixture.py) | 111 | `MockLLMRouter`, `deterministic_embedding`, `cosine_similarity` |
| [tests/harness/embeddings.py](../../backend/tests/harness/embeddings.py) | 75 | Deterministic embedding doubles |
| [tests/harness/__init__.py](../../backend/tests/harness/__init__.py) | 62 | Re-exports |
| [tests/harness/fixtures.py](../../backend/tests/harness/fixtures.py) | 59 | Entity / meta-input loaders |
| [tests/chaos/conftest.py](../../backend/tests/chaos/conftest.py) | 23 | Auto-marks chaos tests |
| [tests/parity/hermetic.py](../../backend/tests/parity/hermetic.py) | — | `DeterministicAdapter`, `seed_parity_run` |
| [tests/parity/harness.py](../../backend/tests/parity/harness.py) | — | `run_parity_case()` |
| [tests/regression/case_schema.py](../../backend/tests/regression/case_schema.py) | — | `RegressionCase` schema |
| [tests/regression/judge.py](../../backend/tests/regression/judge.py) | — | LLM judge |
| [tests/eval/metrics.py](../../backend/tests/eval/metrics.py) | — | Aggregation + significance testing |
| [scripts/run_ci_matrix.sh](../../backend/scripts/run_ci_matrix.sh) | — | fast / nightly / migration lanes |
| [scripts/record_golden_runs.py](../../backend/scripts/record_golden_runs.py) | — | Regenerates parity goldens |

---

## 20. Gotchas

1. **`asyncio_mode = auto`** — new async tests need no decorator, though 503
   existing tests still carry `@pytest.mark.asyncio`.

2. **DB suites skip, they do not fail.** `integration/`, `e2e/` and `parity/`
   call `pytest.skip()` from fixtures when Postgres is unreachable. Always read
   the skip count before believing a green run.

3. **`integration/` rolls back; `e2e/` does not.** The e2e suite leaves users,
   companies and runs in your database on every run.

4. **Never `db.commit()` in an integration test** — it defeats the SAVEPOINT
   isolation.

5. **"attached to a different loop"** means you parametrised or re-scoped a test
   that touches the global `AsyncSessionLocal`. asyncpg connections cannot cross
   event loops; both loop scopes are `session` for this reason.

6. **The engine fixture is function-scoped on purpose** — a deliberate
   performance trade for isolation.

7. **`@pytest.mark.integration` is not registered** in `pytest.ini`;
   `needs_redis`, `needs_llm` and `kpi` are registered but unused.

8. **`tests/kpi/` does not exist.** The `kpi` marker and CI step are
   placeholders.

9. **`tests/phase9/` contains no pytest tests** — two legacy scripts only.

10. **The root `tests/` directory is empty scaffolding.** All real tests are in
    `backend/tests/`.

11. **Parity leaves `parity-*` tenants behind.** Use a disposable Postgres.

12. **Parity ignores wall-clock time** by design — mock timing is noise.

13. **Two `MockLLMRouter` definitions exist** — `tests/harness/mock_llm.py` and
    `tests/fixtures/llm_fixture.py`. Check which your conftest imports.

14. **An unmocked LLM call returns a `STUB:` response, not an error.** If output
    looks wrong, grep it for `STUB:`.

15. **Loading an entity fixture validates it** against
    `HierarchicalEntityCreate` — schema changes break fixture loading.

16. **The eval README says `*.yml`; the cases are `*.yaml`.**

17. **The ONBOARDING.md "~420 passed" figure is stale** — `tests/unit/` now has
    745 test functions.

18. **No CI runs any of this automatically.** Run `scripts/run_ci_matrix.sh fast`
    before pushing.

19. **The frontend has two test files and no test runner.** They cannot be
    executed today.

20. **Use `-s` when debugging**, or pytest swallows your log output.

---

## Where to go next

- [18 — Infrastructure and deployment](18-infrastructure-and-deployment.md) —
  the quality gates in the CI matrix, and how to get Postgres running.
- [05 — Agent kernel](05-agent-kernel.md) — `test_agent_loop_integration.py` is
  the best executable companion to that document.
- [07 — Planning and critics](07-planning-and-critics.md) — what the eval
  harness's `false_pass_rate` calibrates.
- [15 — Governance and flags](15-governance-and-hitl.md) — the flags the eval
  configs toggle.
- [20 — Onboarding and glossary](20-onboarding-and-glossary.md) — the guided
  first-PR exercise.
