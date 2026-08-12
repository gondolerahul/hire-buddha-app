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
| `meta_intelligence_tree.py` | Platform-scoped IntelligenceTree (per company). 6 sections: anti-patterns, spec patterns, test failures, curator decisions, tool reliability, prompt candidates. LRU-pruned at 200 rows / section. |
| `skill_library.py` | Detects repeated successful tool chains across recent runs and writes `skill_candidate` nodes for HITL promotion. |
| `board/` | The 7 roles. See below. |

### `meta/board/` — Architecture Board roles

| Role | Purpose |
|------|---------|
| `requirement_chat.py::RequirementChat` | Normalises raw user request → typed `Spec`. |
| `curator.py::Curator` | REUSE / ADAPT / COMPOSE / CREATE decision. Wraps RegistrySearch + AntiSprawl + MetaIntelligenceTree audit. |
| `architect.py::Architect` | Builds / revises the draft entity payload. |
| `critic.py::BoardCritic` | Drives `meta_spec_critic` tool with a max-2 revise loop. |
| `validator.py::ValidatorRole` | 8 deterministic spec checks. |
| `test_driver.py::TestDriver` | Suite under shared budget — smoke / regression / boundary / hostile / comparative. |
| `promoter.py::Promoter` | 6 gates → DRAFT → ACTIVE; optional HITL. |

## Key types

- `Spec`, `CuratorDecision`, `ArchitectDraft`.
- `CriticReport` (verdict / concerns / rules_referenced / rounds).
- `ValidatorReport`, `CheckResult`.
- `TestCaseResult`, `SuiteResult`.
- `PromoterGateResult`, `PromotionDecision`.
- `MetaIntelligenceTree` (per company); `AntiPatternRow`.
- `SkillLibrary`, `ChainCandidate`.

## Entry points

- Anyone building an entity via the Meta-Agent loop runs through `meta/board/*` in order.
- `meta_intelligence_tree.add_anti_pattern(...)` is invoked by the `meta_spec_critic` tool when a concern crosses `severity ≥ med`.
- Weekly crons: `skill_promotion_scan` and `meta_agent_prompt_evolution` (both in `core/arq_jobs.py`).

## See also

- `docs/phase11/plan/07_track_5_meta_agent_board.md`
- `docs/phase11/review/04_meta_agent_blueprint.md`
