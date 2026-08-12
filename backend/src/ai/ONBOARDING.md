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
Should print `~420 passed` (Phase 11 baseline). If anything fails, stop and ask.

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

This codebase implements `docs/phase11/`. Skim:

* `docs/phase11/plan/01_overview_and_principles.md` — the seven design principles.
* `docs/phase11/plan/04_track_2_agent_loop.md` — heart of Phase 11.
* `docs/phase11/RETROSPECTIVE.md` — what landed, what's deferred to Phase 12.

## 5. First PR (15 min) — guided exercise

Enable the EXPERIMENTAL `video_generation` tool for your dev tenant:

1. Find the tenant's company_id in the `companies` table.
2. Insert a row into `feature_flags`:
   ```sql
   INSERT INTO feature_flags (id, company_id, flag_key, enabled)
   VALUES (gen_random_uuid(), '<company-id>', 'tools.experimental.video_generation', true);
   ```
3. Add a unit test under `tests/unit/test_tool_status.py` that asserts
   `ToolRegistry.get_visible_tools_for_company(<company_id>, feature_flags=...)`
   surfaces `video_generation` when the flag is on.
4. Run `.venv/bin/python -m pytest tests/unit/test_tool_status.py`.
5. Submit the PR. The CI will run the lint + the unit suite.

## Where to ask questions

* Architecture / loop semantics → check `docs/phase11/plan/01_overview_and_principles.md` first, then the agent-kernel team.
* Tool registry → `tools/README.md` + the Track 8 plan.
* Cost attribution → `services/cost_attribution.py` + Track 8 plan.
* Memory / Cortex → `memory/README.md` + the Track 6 plan.

## What to read next

* `docs/phase11/plan/12_data_model_and_migrations.md` — every Alembic
  migration the programme touched.
* `docs/phase11/plan/13_observability_feature_flags_rollout.md` — how
  flags / events flow.
* `docs/phase11/plan/14_test_strategy.md` — what each tier of tests
  covers.
