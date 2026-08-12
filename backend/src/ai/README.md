# backend/src/ai/ — Agent Kernel

This package implements the HireBuddha agent kernel. Its shape is
governed by `docs/phase11/07_folder_restructure.md` and enforced by
`backend/scripts/lint_ai_layout.py`.

## Subpackages

| Path | Purpose | See |
|------|---------|-----|
| `core/` | The AgentLoop, executors, ARQ jobs, prompt + context utilities. | `docs/phase11/plan/04_track_2_agent_loop.md` |
| `planning/` | Plan generation, goal alignment, goal guard, critic pipeline. | `docs/phase11/plan/05_track_3_critic_pipeline.md`, `09_track_7_planner_priors.md` |
| `memory/` | CORTEX engine + four memory domains + dreaming. | `docs/phase11/plan/08_track_6_memory_v2.md` |
| `meta/` | Meta-Agent board, anti-sprawl manager, skill library. | `docs/phase11/plan/07_track_5_meta_agent_board.md` |
| `governance/` | Cost gating, HITL, rate limiting, tool cost resolver. | `docs/phase11/plan/10_track_8_tool_and_cost.md` |
| `llm/` | Provider adapters + the LLM router. | (stable) |
| `tools/` | Tool registry and tool implementations. | `docs/phase11/plan/10_track_8_tool_and_cost.md` |
| `shared/` | Cross-package utilities (JSON parsing, text helpers). | — |

`worker.py` is the Arq entry point. It MUST stay minimal — only
`WorkerSettings` and cron registration.

## Transitional top-level modules

Track 1 will move the remaining top-level service modules
(`schemas.py`, `models.py`, `service.py`, `step_executor.py`, the
campaign / artifact / lead-queue / social / email / reports services,
…) into proper subpackages (`schemas/`, `orm/`, `services/`). Until
they move, they live on a transitional allow-list inside
`backend/scripts/lint_ai_layout.py::TRANSITIONAL_TOPLEVEL`.

## Rules (enforced by lint)

* No new top-level files in `src/ai/` other than the allow-list
  (`__init__.py`, `worker.py`, `README.md`) and the transitional
  modules.
* No `from src.ai.worker import …`. Import the canonical location.
* No cross-package import aliasing like `… as CortexService` that
  masks a name collision (Track 0 killed the `CortexRouter` alias).
* Per-package line caps — see `MAX_LINES` in the lint script.

## Where the migrations and seeds went

Track 0 moved:

* `src/ai/migrate_*.py` → `backend/scripts/migrations/`
* `SeedEntities/*` → `backend/scripts/seeds/default_entities/`
* `SeedEntities/DeepResearchSetup` → `backend/scripts/seeds/deep_research/DeepResearchSetup/`
