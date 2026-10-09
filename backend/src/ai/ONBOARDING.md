# `backend/src/ai/` — Onboarding (clone → first PR in ≤90 minutes)

Welcome. This walks you from a fresh clone to a merged trivial PR.
Skip anything you've already done.

## 0. Setup (10 min)

```bash
git clone <repo>
cd hb-proto-3/backend
poetry install                       # or `python -m venv .venv && pip install -r requirements`
cp .env.example .env                 # ask the team for dev secrets
docker compose up -d                 # postgres + redis
alembic upgrade head
```

Smoke-test the worker boots:
```bash
.venv/bin/python -c "from src.ai.worker import WorkerSettings; print(len(WorkerSettings.functions), 'jobs;', len(WorkerSettings.cron_jobs), 'crons')"
```

## 1. Run the unit suite (5 min)

```bash
.venv/bin/python -m pytest tests/unit/ -q
```
Should end with no failures. The pass count grows with the suite, so do not compare it with a
fixed figure; a failure, or an error in collection, is the signal. If anything fails, stop and ask.

## 2. Read the loop (15 min)

Read these in order — they are the agent kernel:

1. `core/agent_loop.py` — the orchestrator. Trace `AgentLoop.run` → `_loop` → `_iteration`.
2. `core/agent_state.py` — the typed envelope every layer sees.
3. `planning/critic_pipeline.py::RealCriticPipeline` — the four-stage critic.
4. `meta/board/__init__.py` — the seven Meta-Agent Board roles in execution order.

Then skim:

* `core/README.md`, `planning/README.md`, `memory/README.md`,
  `meta/README.md`, `governance/README.md`, `tools/README.md`.
* `core/INTERNAL_KEYS.md` — the legacy `context_state` keys you'll
  meet when reading older code.

## 3. Run one fixture entity end-to-end (15 min)

```bash
.venv/bin/python -m pytest tests/unit/test_agent_loop_integration.py -v
```

These tests drive the AgentLoop against stub executors. Read
`test_agent_loop_runs_one_step_to_completion` to see what a single
iteration looks like in code.

## 4. The plan documents (30 min, skim)

This codebase implements `docs/history/phase11/`. Skim:

* `docs/history/phase11/plan/01_overview_and_principles.md` — the seven design principles.
* `docs/history/phase11/plan/04_track_2_agent_loop.md` — heart of Phase 11.
* `docs/history/phase11/RETROSPECTIVE.md` — what landed, what's deferred to Phase 12.

## 5. First PR (15 min) — guided exercise

Learn the control that decides whether a tool may run — a **tool grant** — by
limiting one. An entity runs only the tools in its `capabilities.tools`, and
`governance/tool_access.py`'s `ToolAccess` is the one place every execution
path asks (TL-50).

1. Read `ToolAccess._check` in `governance/tool_access.py`: the order of its
   refusals is the order a call is checked in.
2. Add a test to `tests/unit/test_tool_access.py`: an entity granted
   `web_search` with `rate_limit_per_run: 1` may call it once and is refused
   the second time.
   ```python
   from src.ai.governance.tool_access import ToolAccess, ToolDenied
   from src.ai.schemas.capabilities import ToolGrant


   def test_a_grant_with_a_rate_limit_allows_one_call_per_run() -> None:
       access = ToolAccess(company_id=None,
                           grants={"web_search": ToolGrant(tool_id="web_search", rate_limit_per_run=1)})
       assert not isinstance(access.resolve("web_search"), ToolDenied)
       access.record("web_search")
       refused = access.resolve("web_search")
       assert isinstance(refused, ToolDenied) and refused.reason == "rate_limited"
       assert access.resolve("send_email").reason == "not_granted"
   ```
3. Run `.venv/bin/python -m pytest tests/unit/test_tool_access.py`.
4. Run the gates yourself — `scripts/run_ci_matrix.sh fast` — then submit the
   PR. Nothing runs them on push yet (no CI for the app, IN-05).

(The exercise used to enable `video_generate` through a feature flag and assert
on `get_visible_tools_for_company`, a gate nothing called and that has since
been deleted — ON-06.)

## Where to ask questions

* Architecture / loop semantics → check `docs/history/phase11/plan/01_overview_and_principles.md` first, then the agent-kernel team.
* Tool registry → `tools/README.md` + the Track 8 plan.
* Cost attribution → `services/cost_attribution.py` + Track 8 plan.
* Memory / Cortex → `memory/README.md` + the Track 6 plan.

## What to read next

* `docs/history/phase11/plan/12_data_model_and_migrations.md` — every Alembic
  migration the programme touched.
* `docs/history/phase11/plan/13_observability_feature_flags_rollout.md` — how
  flags / events flow.
* `docs/history/phase11/plan/14_test_strategy.md` — what each tier of tests
  covers.
