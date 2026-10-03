# `meta/` — Meta-Agent Architecture Board + Platform Intelligence

The Meta-Agent is just another agent that runs through the same
`AgentLoop`. It happens to have a multi-role internal **Board** that
turns user requests into validated, tested, promoted
HierarchicalEntities.

## What's in here

| File | Purpose |
|------|---------|
| `meta_agent_template.py` | Seeds the Meta-Agent runtime template. |
| `seed_meta_agent.py` | One-shot seeder. |
| `platform_schema_compiler.py` | Materialises a HierarchicalEntity from its declarative parts. Hosts the Track 5 `resolve_meta_cognition` opt-in defaults flip. |
| `meta_cognition_migration.py` | Pre-deploy backfill: preserves explicit `registry_search` / `self_modification` for AGENT/PROCESS entities that relied on the old auto-on default. |
| `registry_search_service.py` | Phase-aware structural + semantic search over existing entities. |
| `anti_sprawl.py` | Per-company AntiSprawlGuard: blocks CREATE on near-duplicates / over-cap counts. |
| `meta_intelligence_tree.py` | Platform-scoped IntelligenceTree (per company). 7 sections (`SECTIONS`): anti-patterns, spec patterns, test failures, curator decisions, tool reliability, prompt candidates, composition graph. LRU-pruned at 200 rows / section (MI-15). |
| `skill_library.py` | Detects repeated successful tool chains across recent runs and writes `skill_candidate` nodes for HITL promotion. |
| `board/` | What is left of the Architecture Board (MI-20, D27): `ValidatorRole`, the publication gate, and `ToolSmith`, used by tool synthesis. |

### `meta/board/`

| Role | Purpose |
|------|---------|
| `validator.py::ValidatorRole` | 9 deterministic checks; `governance/publication.py` runs them before a draft version is published or a `DRAFT` entity promoted (D27). |
| `tool_smith.py::ToolSmith` | Drafts a tool's source for the tool-synthesis pipeline. |

RequirementChat, Curator, Architect, BoardCritic, TestDriver and Promoter had no caller and were deleted on 2026-10-03 (MI-20).

## Key types

- `ValidatorReport`, `CheckResult`.
- `MetaIntelligenceTree` (per company); `AntiPatternRow`.
- `SkillLibrary`, `ChainCandidate`.

## Entry points

- Anyone building an entity via the Meta-Agent loop runs through `meta/board/*` in order.
- `meta_intelligence_tree.add_anti_pattern(...)` is invoked by the `meta_spec_critic` tool when a concern crosses `severity ≥ med`.
- Weekly crons: `skill_promotion_scan` and `meta_agent_prompt_evolution` (both in `core/arq_jobs.py`).

## See also

- `docs/phase11/plan/07_track_5_meta_agent_board.md`
- `docs/phase11/review/04_meta_agent_blueprint.md`
