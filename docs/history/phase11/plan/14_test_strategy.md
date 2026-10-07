# 14 — Test Strategy (Cross-Cutting)

This document defines the **single test-strategy contract** for the
Phase 11 programme. Each Track lists its own tests; this file defines
the test *categories*, *fixtures*, *harnesses*, and *coverage gates*
that every Track adheres to.

---

## 1. Test categories

| Category | Where it lives | When it runs | Owner |
|----------|----------------|--------------|-------|
| Unit | `backend/tests/<area>/test_*.py` | Every PR | Track owner |
| Integration | `backend/tests/integration/` | Every PR | Track owner |
| Parity | `backend/tests/parity/` | Every PR + nightly | Agent kernel engineer |
| Regression suite | `backend/tests/regression/` | Nightly + pre-deploy | Platform |
| Canary | Live tenant traffic | Always | On-call |
| Load / Chaos | `backend/tests/chaos/` | Weekly | Platform |
| Cost / KPI | `backend/tests/kpi/` | Nightly | Platform |

---

## 2. Unit tests

### 2.1 Coverage targets

| Package | Min coverage |
|---------|-------------:|
| `core/` | 85% line / 75% branch |
| `planning/` | 85% / 75% |
| `memory/` | 80% / 70% |
| `meta/` | 75% / 65% |
| `governance/` | 90% / 80% |
| `schemas/`, `orm/` | 70% / 60% (much of it is dataclasses) |
| `tools/` core+resilience | 80% / 70%; provider integrations not enforced |

### 2.2 Coverage gates

CI fails any PR that lowers coverage in a touched package below the
threshold above. New code in a PR has a per-PR floor of 80%.

### 2.3 What to unit-test

* **Pure functions:** all of them. Examples: `pick_retry`,
  `classify_tool_failure`, `validate_plan` invariants,
  `Budget.pressure`, `FailureTag.from_string`,
  `child_resolver.resolve_child_entity_id`.
* **Adapters / wrappers:** the executor adapters, the reasoning
  strategies (their dispatch + parsing logic), the LLM router's
  retries.
* **Dataclasses with logic:** `AgentState.snapshot_to_cortex /
  restore`, `Budget.consume`, `StepHealthRecord` serialisation.

### 2.4 What NOT to unit-test

* LLM responses verbatim — they change. Mock the LLM, assert the
  *shape* of the prompt and the parse logic against fixed strings.
* External APIs — mock at the adapter boundary.

---

## 3. Integration tests

### 3.1 Definition

An integration test runs **multiple modules together** but stubs the
network: real Postgres (in CI: ephemeral container), real Redis (in
CI: same), mocked LLM router (returns fixture JSON).

### 3.2 Required integration suites

| Suite | Track | What it asserts |
|-------|------:|-----------------|
| `test_agent_loop_end_to_end` | 2 | One full iteration through all sub-components produces consistent events + writes |
| `test_loop_resume_after_crash` | 2 | Worker dies mid-iter → next pickup resumes |
| `test_critic_pipeline_blocks_off_topic` | 3 | Fixture entity + off-topic move → pre-critic BLOCK |
| `test_retry_different_model` | 3 | REVISE verdict with `HALLUCINATION` tag → retry uses different model |
| `test_meta_review_replan` | 4 | Supervisor REPLAN triggers planner.replan |
| `test_meta_agent_v4_create_path` | 5 | RequirementChat → Curator → Architect → Critic → Validator → TestDriver → Promoter |
| `test_meta_agent_v4_blocked_by_critic` | 5 | Hallucinated tool → BLOCK |
| `test_memory_v2_full_assembly` | 6 | Four-domain memory injected correctly |
| `test_dreaming_outcome_trigger` | 6 | Run completes → DreamingEngine enqueued |
| `test_planner_v2_multi_candidate` | 7 | 3 candidates → invariants → judge → choice |
| `test_replan_with_proposed_subgoals` | 7 | Supervisor's subgoals appear in new plan |
| `test_cost_attribution_full_run` | 8 | Every cost path tags itself; sums match |
| `test_tool_resilience_react_path` | 8 | REACT-path tool failure recovered |
| `test_kpi_view_refresh` | 9 | Materialised view refresh succeeds |

### 3.3 Fixtures

Three canonical entity fixtures live in
`backend/tests/fixtures/entities/`:

| Fixture | Purpose |
|---------|---------|
| `simple_skill.json` | Two-step SKILL (web_search → summarise) |
| `research_agent.json` | AGENT with REACT + CORTEX + 5 tools |
| `research_process.json` | PROCESS with two AGENT children (researcher + synthesiser) |

Plus three Meta-Agent input fixtures:

| Fixture | Purpose |
|---------|---------|
| `meta_input_simple_skill.json` | "create a tool that scrapes a URL and returns JSON" |
| `meta_input_research_agent.json` | "make me an agent that researches a topic" |
| `meta_input_hostile.json` | "make me an agent that uses tool `unicorn_search`" (deliberately bad) |

Every Track that adds a new code path adds at least one fixture or
extends an existing one.

---

## 4. Parity tests

### 4.1 Purpose

Detect regressions between the **legacy** code path and the **new**
code path during the Track 2-8 transition. Especially important for
Tracks 2 (AgentLoop) and 3 (CriticPipeline).

### 4.2 Harness

`backend/tests/parity/test_*.py` runs the same fixture entity twice:

```python
async def run_with_flag(entity, input_data, flag_name, flag_on, db) -> RunResult:
    await FeatureFlags(db).set(flag_name, enabled=flag_on,
                               company_id=entity.company_id)
    run = await create_run(entity, input_data, db)
    await ExecutionEngine(db, redis).execute_run(run.id) \
       if not flag_on else AgentLoop(db, redis, ...).run(run.id)
    return RunResult.from_run(run)
```

### 4.3 Acceptance contract

| Metric | Tolerance |
|--------|-----------|
| Final status | Equal |
| Total cost | ±5% (Track 2), ±15% (Track 3), ±10% (Track 7), ±5% (Track 6) |
| Output cosine similarity (via embedding) | ≥ 0.85 |
| Iterations / steps count | ±2 |
| Wall time | ±25% |

Cost tolerances widen on Tracks that genuinely change cost shape
(critic, planner). Beyond tolerance → flag stays OFF.

---

## 5. Regression suite

### 5.1 Composition

A larger fixture set (~25 entities, ~50 inputs) representing the
breadth of production traffic patterns:

* SKILLs (web_search, scrape, summarise, draft).
* AGENTs (research, analysis, content generation).
* PROCESSes (multi-step pipelines).
* Meta-Agent runs (Track 5+).

Stored in `backend/tests/regression/cases/*.yaml`:

```yaml
case_id: research_topic_easy_001
entity_fixture: research_agent
input:
  topic: "post-quantum cryptography 2025 progress"
expected_status: COMPLETED
expected_min_cost_usd: 0.05
expected_max_cost_usd: 0.40
expected_must_mention: ["lattice", "NIST"]
expected_must_not_mention: ["asset management"]
acceptance:
  llm_judge_threshold: 0.7
```

### 5.2 Acceptance

LLM-judge grades each output against `expected_must_mention /
must_not_mention / llm_judge_threshold`. Aggregate pass rate must
not drop below baseline at each Track's exit.

### 5.3 Cadence

* Nightly.
* Pre-deploy gate.
* On any Track's final PR.

---

## 6. Canary tests (live tenant traffic)

### 6.1 Setup

A small set of "canary tenants" (see [13](./13_observability_feature_flags_rollout.md) §4.3)
run with the new flag ON before the rest of production.

### 6.2 Signals to watch

* `goal_hit_rate` over the last 24h.
* `cost_per_success` over the last 24h.
* `critic_false_pass_rate`.
* Number of `agent.loop.budget_exhausted` events.
* User-reported issues in Slack.

### 6.3 Promotion criteria

* `goal_hit_rate` ≥ pre-flag baseline.
* `cost_per_success` ≤ pre-flag baseline × 1.15 (or per Track tolerance).
* Zero ERROR severity events directly attributable to the new path.

---

## 7. Load / Chaos tests

### 7.1 Load

Weekly Locust job: 200 concurrent runs of `research_agent` fixture
against a staging environment. Watch:

* P95 latency.
* DB connection pool saturation.
* Redis pubsub backlog.

### 7.2 Chaos

Weekly chaos suite:

| Chaos | Track validating |
|-------|------------------|
| Kill Arq worker mid-run | 2 (resume from snapshot) |
| Drop DB connection mid-iteration | 2 |
| Mock LLM returns malformed JSON | 3, 5 |
| Mock tool returns 500 | 3, 8 |
| Redis pubsub disconnect during SSE stream | 2 |
| `feature_flags` table briefly unavailable | 13 |
| Cost-attribution column missing (rollback simulation) | 8 |

Every chaos case has an expected recovery time and a test that
asserts the system reaches a clean state.

---

## 8. Cost / KPI tests

### 8.1 Cost ceiling tests

* For each fixture, the run cost must stay below
  `entity.governance.max_cost_usd × 1.10` (the +10% covers critic and
  retry overhead).
* If cost exceeds the cap, the test fails — proves Budget enforcement
  works.

### 8.2 KPI regression tests

Nightly job compares today's `kpi_daily_rollup` row vs 7-day average:

| Metric | Allowable drift |
|--------|-----------------|
| `goal_hit_rate` | -2 pp |
| `cost_per_success` | +10% |
| `critic_false_pass_rate` | +3 pp |
| `budget_overshoot_rate` | +2 pp |

Drift beyond tolerance pages the on-call.

---

## 9. CI matrix

Each PR runs:

```
[setup]   pip install + DB / Redis containers
[lint]    ruff + lint_ai_layout.py + lint_no_phase_narration (warn|error)
[type]    mypy --strict on the Track's paths (full kernel by Track 9)
[unit]    pytest backend/tests/<area>
[integ]   pytest backend/tests/integration -m "fast"
[parity]  pytest backend/tests/parity (only when Track 2-8 paths touched)
[migr]    alembic upgrade head + downgrade -1 + upgrade head on staging clone
```

Nightly:

```
[regress] pytest backend/tests/regression (with LLM-judge against fixtures)
[load]    Locust 200 concurrent
[chaos]   pytest backend/tests/chaos
[kpi]     run KPI rollup diff job, alert on drift
```

---

## 10. Test data + LLM mocking

### 10.1 LLM mocking pattern

```python
# backend/tests/fixtures/llm_fixture.py
class MockLLMRouter:
    def __init__(self, fixtures: dict[str, LLMResponse]):
        self.fixtures = fixtures

    async def call_llm(self, *, task_type, system_prompt, user_prompt, **kw):
        key = (task_type, hashlib.sha256(user_prompt.encode()).hexdigest()[:8])
        if key in self.fixtures:
            return self.fixtures[key]
        # Fallback: a deterministic stub based on the prompt
        return LLMResponse(output=stub_for(user_prompt), ...)
```

Fixtures live in `backend/tests/fixtures/llm/<scenario>.json` and are
selected per test via a context manager.

### 10.2 Embedding mocking

Deterministic: each text hashes to a fixed 768-dim vector. Cosine
similarity between two known fixture texts is computable in advance.

### 10.3 CORTEX seed data

A canonical CORTEX tree fixture (`backend/tests/fixtures/cortex/canonical_tree.json`)
contains a Knowledge subtree with 10 nodes, an Episodic subtree with
5 episodes, and an Intelligence subtree with 3 confirmed rules.
Tests load it into a fresh DB to exercise memory assembly.

---

## 11. Specific test suites per Track

(Each Track file lists its own; this is the **cross-cutting checklist**.)

* T0: layout-lint, import-passes, smoke run.
* T1: schemas back-compat, ORM back-compat, typed enum coercion, mypy strict on schemas/orm.
* T2: unit (Budget, AgentState, executors), integration (loop+resume), parity (3 fixtures).
* T3: unit (retry table, tag parsing), integration (loop+critic), cost regression.
* T4: unit (bandit, supervisor fast-path), integration (replan), parity (catch rate).
* T5: unit (board roles), integration (full create path), canary (Meta-Agent only).
* T6: unit (viewport, scope, embedding), integration (memory assembly), perf (prompt-token reduction).
* T7: unit (invariants, child_resolver), integration (multi-candidate), parity (cost per success).
* T8: unit (resilience, cost resolver, attribution), integration (REACT recovery), tool registry filter.
* T9: deletion sanity, mypy strict full, layout strict, KPI view, no narration.

---

## 12. Definition of "test green" for the programme

The Phase 11 programme is considered "test-green" when:

1. Full nightly `regression` suite pass rate ≥ baseline pass rate
   measured before Track 2 started.
2. Every Track's listed integration tests pass.
3. Parity tolerances respected at each Track's exit.
4. Coverage gates met per §2.1.
5. `mypy --strict` clean on the full agent kernel (post-Track 9).
6. No KPI alert active on the canary tenant for ≥48h.

That's the bar for shipping Phase 11.
