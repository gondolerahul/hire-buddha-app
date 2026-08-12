# `tests/eval/` — offline A/B eval harness (Phase 12 `07` §5)

Turns "we think config B is better" into **"+6pp goal-hit at −9% cost,
p<0.05"**. Replays a fixed corpus through two named configs and reports the
deltas *with* significance.

## Pieces

| File | Role | Pure? |
|------|------|:-----:|
| `metrics.py` | aggregate per-case `RunMetrics` → `ConfigAggregate`; `delta_report` (two-proportion z for rates, Welch's t for cost/latency, p via `math.erfc` — no scipy); `render_report` | ✅ |
| `runner.py` | `grade` (pure: status + must/must-not mentions + false-pass) and `run_corpus` (replays a `RegressionCase` through a config via an injected `run_fn`) | grade ✅ |
| `config.py` | `EvalConfig` — a named bundle of feature-flag/numeric overrides applied for the replay | ✅ |

The **corpus** is just `tests/regression/cases/*.yml` (`RegressionCase`); no
separate format. Seeding reuses the parity hermetic fixtures.

## The four headline metrics

* `goal_hit_rate` — fraction reaching the expected outcome (status + mentions)
* `cost_per_success` — total USD / successful cases (the efficiency lever)
* `false_pass_rate` — critic said "good" but the corpus check fails (calibration)
* `mean_latency_ms` — wall-clock per case

## Config pairs the plan names

* deterministic vs **LLM Strategist** (`06` §3.2) —
  `agent_loop.llm_strategist_enabled`
* task classifier **v1-rules vs v2-embedding** (`06` §5) —
  `task_classifier.v2_enabled`
* **critic model A vs B** — the critic model override

## Running

```bash
# Pure metric/grader unit tests (hermetic, fast):
.venv/bin/python -m pytest tests/eval -o addopts="" -q

# The corpus-replay integration path needs Postgres + Redis (like tests/parity)
# and an AgentLoop-backed run_fn; it skips without them.
```

`run_fn(db, redis, case) -> (status, output_text, cost_usd, critic_passed)` is
injected so the grader and delta math test without a live loop; the integration
wiring passes the real AgentLoop-backed runner and the deterministic mock LLM
from `tests/parity`.
