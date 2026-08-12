# `planning/` — Planner, critics, plan invariants

Everything the agent uses to decide *what plan to run* and *how to
judge it after the fact*.

## What's in here

| File | Purpose |
|------|---------|
| `planner_service.py` | Legacy planner. Generates / reconciles the dynamic plan. `adapt_plan` is now a v2 shim that calls `PlanGenerator.generate` when `planner.v2_enabled` is on. |
| `plan_generator.py` | Phase 11 Track 7 multi-candidate planner. `PlanContext` / `PlanCandidate` / `PlanCandidates` envelopes; varied-temperature parallel candidates; invariant filter + repair fallback; bandit-aware selection via `PlanJudge`. |
| `plan_invariants.py` | Eight pure-function checks: cycle, tool capability, dangling var refs, dangling step deps, cost-vs-budget, orphan outputs, child-invocation entity_id, prompt-templates-are-strings. `validate_plan` runs the suite. |
| `plan_judge.py` | LLM judge for best-of-N plan selection with cost-based tiebreak. |
| `plan_style_bandit.py` | ε-greedy bandit keyed by `(entity_id, task_class)`; arm state lives in IntelligenceTree under `🎯 Strategies`. |
| `cost_estimator.py` | `TOOL_BASELINE_COST` + `MODEL_PRICE_FACTOR` tables and `estimate_step_cost` / `estimate_plan_cost` / `estimate_latency_s` pure functions. |
| `child_resolver.py` | Single source of truth for resolving `CHILD_ENTITY_INVOCATION.entity_id` (UUID passthrough → static-plan name match → hierarchy index → DB name-hint lookup). |
| `critic_pipeline.py` | The four-stage `RealCriticPipeline` (pre / post / alignment / supervisor); `NoOpCriticPipeline` fallback. |
| `critic_prompts.py` | Pre / post critic prompt templates (extracted to keep `critic_pipeline.py` under the layout-lint cap). |
| `critic_calibration.py` | Weekly job: scans recent StepHealthRecords vs ExecutionRun outcomes and writes false-pass / false-fail rates into IntelligenceTree. |
| `step_health_record.py` | One typed record per executed step, populated by every critic stage. |
| `supervisor_critic.py` | Track 4 supervisor with budget-pressure short-circuit + 3-clean-step fast path + proposed-subgoals on REPLAN. |
| `retry_strategies.py` | Deterministic `pick_retry(record, state) -> RetryStrategy`. The Strategist consumes it after every actionable failure. |
| `failure_tags.py` | Closed enum the post-action critic tags outputs with. |
| `goal_alignment.py` | Cheap LLM alignment verifier used by both `CriticPipeline.alignment` and the GoalGuard shim. |
| `goal_guard.py` | **Deprecated shim** of the Phase 10D GoalGuard for legacy `execute_run` callers. |

## Key types

- `StepHealthRecord` — one per executed step; shared by every critic stage.
- `FailureTag` — closed enum the post-action critic emits.
- `RetryStrategy`, `RetryDecision`, `RetryExecutor` — Strategist's retry contract.
- `Invariant` — `(name, passed, detail)` triplet from `validate_plan`.
- `PlanContext`, `PlanCandidate`, `PlanCandidates` — planner-side envelopes.
- `SupervisorCritic`, `SupervisorCriticConfig`.

## Entry points

- `AgentLoop._compose` constructs `RealCriticPipeline` and `Strategist(bandit=PlanStyleBandit(...))`.
- `PlannerService.adapt_plan` is the legacy REPLAN entry point; it now delegates to `PlanGenerator.generate` when `planner.v2_enabled` is on.

## See also

- `docs/phase11/plan/05_track_3_critic_pipeline.md`
- `docs/phase11/plan/06_track_4_meta_review_goalguard.md`
- `docs/phase11/plan/09_track_7_planner_priors.md`
