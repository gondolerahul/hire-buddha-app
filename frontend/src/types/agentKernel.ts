/**
 * types/agentKernel.ts — Typed agent kernel contracts.
 *
 * Mirrors the backend dataclasses in
 *   - backend/src/ai/core/agent_state.py
 *   - backend/src/ai/planning/step_health_record.py
 *   - backend/src/ai/planning/plan_generator.py
 *   - backend/src/ai/planning/plan_style_bandit.py
 *   - backend/src/ai/meta/meta_intelligence_tree.py
 *   - backend/src/ai/schemas/cortex.py (Provenance)
 *   - backend/src/ai/services/cost_attribution.py
 *
 * Source of truth: backend; this file mirrors the wire shape.
 */

// ---------------------------------------------------------------------------
// Enums — mirror Python str enums.
// ---------------------------------------------------------------------------

export type ExecutorName =
    | 'DAG'
    | 'Recursive'
    | 'SingleStep'
    | 'ChildEntity'
    | 'Dialog'
    | 'ToolBurst'
    | 'Skill';

export type StepType =
    | 'THOUGHT'
    | 'ACTION'
    | 'TOOL_CALL'
    | 'CHILD_ENTITY_INVOCATION'
    | 'NAVIGATE'
    | 'READ'
    | 'WRITE'
    | 'RECURSE'
    | 'AWAIT_CHILDREN';

export type FailureTag =
    | 'OFF_TOPIC'
    | 'HALLUCINATION'
    | 'INCOMPLETE'
    | 'WRONG_FORMAT'
    | 'TOOL_FAILURE'
    | 'CONTRADICTION'
    | 'UNVERIFIABLE'
    | 'POLICY_VIOLATION'
    | 'UNDER_BUDGET'
    | 'OVER_BUDGET'
    | 'BLOCKED_DEPENDENCY'
    | 'NEEDS_CLARIFICATION';

export type RetryStrategy =
    | 'NONE'
    | 'RETRY_AS_IS'
    | 'RETRY_DIFFERENT_MODEL'
    | 'RETRY_DIFFERENT_PROMPT'
    | 'RETRY_DIFFERENT_TOOL'
    | 'ASK_USER'
    | 'ABANDON';

export type PreCriticVerdictKind = 'PASS' | 'BLOCK' | 'REVISE';
export type PostCriticVerdictKind = 'PASS' | 'REVISE' | 'REJECT';
export type SupervisorRecommendation = 'CONTINUE' | 'REPLAN' | 'ABORT' | 'PAUSE';

export type PlanStyleArm =
    | 'DAG_PARALLEL'
    | 'DAG_SEQUENTIAL'
    | 'RECURSIVE'
    | 'SINGLE_TOOL'
    | 'DIALOG'
    | 'CHILD_ENTITY';

export type CostAttribution =
    | 'planner'
    | 'actor_step'
    | 'critic_pre'
    | 'critic_post'
    | 'critic_align'
    | 'critic_super'
    | 'reformat_retry'
    | 'meta_review'
    | 'dreaming'
    | 'tool'
    | 'child_run'
    | 'embedding'
    | 'meta_spec_critic'
    | 'test_driver';

export type ToolStatus = 'ACTIVE' | 'EXPERIMENTAL' | 'DEPRECATED';

export type ProvenanceSourceType =
    | 'tool'
    | 'user_upload'
    | 'reflection'
    | 'dreaming'
    | 'external_link'
    | 'manual'
    | 'context_source';

// ---------------------------------------------------------------------------
// AgentState (subset returned by /executions/{id}/agent_state)
// ---------------------------------------------------------------------------

export interface Subgoal {
    id: string;
    description: string;
    parent_id?: string | null;
    priority?: number;
    blocked_on?: string | null;
    achieved?: boolean;
}

export interface Reflection {
    iteration: number;
    scope: 'run' | 'entity' | 'task_class';
    what_worked: string;
    what_didnt: string;
    cause_hypothesis: string;
    proposed_change: string;
    confidence: number;
}

export interface Blocker {
    kind: 'missing_tool' | 'missing_data' | 'awaiting_hitl' | 'budget' | 'error';
    detail: string;
    related_subgoal_id?: string | null;
}

export interface BudgetSnapshot {
    tokens_max: number;
    tokens_used: number;
    usd_max: string | number;
    usd_used: string | number;
    wall_max_s: number;
    wall_used_s: number;
    iters_max: number;
    iters: number;
    pressure?: number;
}

export interface AgentStateSnapshot {
    run_id: string;
    entity_id: string;
    company_id?: string | null;
    entity_type?: string;
    iteration: number;
    budget: BudgetSnapshot;
    open_subgoals: Subgoal[];
    achieved: Subgoal[];
    blockers: Blocker[];
    reflections: Reflection[];
    last_action?: { iteration: number; executor: ExecutorName; move_id: string } | null;
    last_observation?: {
        iteration: number;
        outcome: 'success' | 'partial' | 'fail' | 'blocked';
        novelty_score: number;
        goal_delta_estimate: number;
        summary: string;
    } | null;
    chosen_executor?: ExecutorName | null;
    task_class?: string;
    chosen_arms_by_iteration?: string[];
    health_records?: StepHealthRecord[];
    done: boolean;
    next_decision: 'CONTINUE' | 'DONE' | 'PAUSE_HITL' | 'ABORT';
}

// ---------------------------------------------------------------------------
// StepHealthRecord
// ---------------------------------------------------------------------------

export interface StepHealthRecord {
    record_id: string;
    step_id: string;
    iteration: number;
    move_id: string;
    pre_critic_verdict?: PreCriticVerdictKind | null;
    pre_critic_concerns?: string[];
    pre_critic_cost_usd?: string | number;
    post_critic_verdict?: PostCriticVerdictKind | null;
    post_critic_tags?: FailureTag[];
    post_critic_suggestion?: string;
    post_critic_cost_usd?: string | number;
    post_critic_model?: string;
    alignment_aligned?: boolean | null;
    alignment_drift?: number | null;
    alignment_cost_usd?: string | number;
    supervisor_recommendation?: SupervisorRecommendation | null;
    supervisor_reasoning?: string;
    supervisor_confidence?: number;
    supervisor_cost_usd?: string | number;
    total_latency_ms?: number;
}

export interface HealthRecordRow {
    node_id: string;
    title: string;
    summary: string | null;
    record: StepHealthRecord;
    source_ref: Record<string, unknown>;
    created_at: string | null;
}

// ---------------------------------------------------------------------------
// Plan candidates
// ---------------------------------------------------------------------------

export interface PlanCandidate {
    style: PlanStyleArm | string;
    estimated_cost_usd: string;
    estimated_latency_s?: number;
    rationale?: string;
    invariant_violations?: string[];
    judge_score?: number | null;
    steps?: Array<Record<string, unknown>>;
}

export interface PlanCandidatesResponse {
    chosen: PlanCandidate | null;
    alternates: PlanCandidate[];
    judge_reasoning: string;
}

// ---------------------------------------------------------------------------
// Bandit
// ---------------------------------------------------------------------------

export interface BanditArmState {
    pulls: number;
    successes: number;
    avg_cost_usd: number;
    last_pull_at: string | null;
}

export interface BanditTable {
    entity_id: string;
    task_class: string;
    arms: Record<string, BanditArmState>;
}

// ---------------------------------------------------------------------------
// Meta-Agent admin
// ---------------------------------------------------------------------------

export interface SkillCandidate {
    node_id: string;
    title: string;
    summary: string | null;
    metadata: {
        kind?: string;
        frequency?: number;
        source_entity_id?: string;
        promoted?: boolean;
        promoted_at?: string;
        promoted_entity_id?: string;
        [key: string]: unknown;
    };
    content: { chain?: string[]; frequency?: number; source_entity_id?: string; suggestion?: string };
    created_at: string | null;
}

export interface AntiPatternRow {
    node_id: string | null;
    title: string;
    suggestion: string;
    evidence_count: number;
    related_tags: string[];
    last_seen: string | null;
}

export interface PromptCandidate {
    node_id: string;
    title: string;
    summary: string | null;
    metadata: { approved?: boolean; approved_at?: string; [k: string]: unknown };
    content: {
        prompt_diff?: string;
        rationale?: string;
        evidence_run_ids?: string[];
    };
    created_at: string | null;
}

// ---------------------------------------------------------------------------
// Cost attribution
// ---------------------------------------------------------------------------

export interface CostAttributionRow {
    attribution: CostAttribution | string;
    cost_usd: number;
    charges: number;
}

// ---------------------------------------------------------------------------
// KPI rollup
// ---------------------------------------------------------------------------

export interface KPIRunRow {
    day: string;
    runs_total: number;
    runs_completed: number;
    runs_failed: number;
    runs_paused: number;
    goal_hit_rate: number;
}

export interface KPICriticResponse {
    verdict_distribution: Array<{ verdict: string; occurrences: number }>;
    cost_share: number;
}

export interface KPIMetaAgentResponse {
    intelligence_growth: Array<{ kind: string; rows: number }>;
}

// ---------------------------------------------------------------------------
// Provenance — for CORTEX nodes
// ---------------------------------------------------------------------------

export interface ProvenanceBlock {
    source_type: ProvenanceSourceType;
    tool_id?: string | null;
    url?: string | null;
    upload_ref?: string | null;
    fetched_at?: string | null;
    trust_score: number;
    run_id?: string | null;
    step_id?: string | null;
    notes?: string | null;
}

// ---------------------------------------------------------------------------
// Feature flags
// ---------------------------------------------------------------------------

export interface FeatureFlagsResponse {
    defaults: Record<string, boolean>;
    numeric_defaults: Record<string, number>;
    overrides: Record<string, { company?: boolean; global?: boolean }>;
}

export interface FeatureFlagRow {
    id: string;
    company_id: string | null;
    entity_id: string | null;
    flag_key: string;
    enabled: boolean;
    value_json: unknown;
    created_at: string | null;
    updated_at: string | null;
    scope: 'global' | 'company' | 'entity';
}

// ---------------------------------------------------------------------------
// Track 15 — risk register, exit checklist, decision log
// ---------------------------------------------------------------------------

export type RiskStatus = 'ok' | 'warn' | 'breach';

export interface RiskIndicator {
    id: string;            // "R-PRG-3", "R-INFRA-1", ...
    title: string;
    metric: number;
    threshold: number;
    status: RiskStatus;
    details: string;
}

export interface RiskIndicatorsResponse {
    since: string;
    as_of: string;
    overall: RiskStatus;
    indicators: RiskIndicator[];
}

export interface ExitChecklistItem {
    id: string;            // "EXIT-1" … "EXIT-10"
    title: string;
    satisfied: boolean;
    detail: string;
}

export interface ExitChecklistResponse {
    as_of: string;
    total: number;
    satisfied: number;
    percent_complete: number;
    items: ExitChecklistItem[];
}

export interface DecisionRow {
    date: string;
    kind: string;          // "decision" | "pivot" | "defer" | "accept-risk"
    summary: string;
    rationale: string;
}

// ---------------------------------------------------------------------------
// SSE typed event union — every agent.* event the backend emits.
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// Execution trace spans (per-iteration transparency)
// ---------------------------------------------------------------------------

export type SpanKind =
    | 'iteration'
    | 'executor'
    | 'step'
    | 'child'
    | 'tool'
    | 'llm'
    | 'critic';

export type SpanStatus = 'running' | 'success' | 'error';

/** One span row as returned by GET /executions/{id}/trace (and SSE). */
export interface TraceSpan {
    span_id: string;
    parent_span_id: string | null;
    iteration: number | null;
    kind: SpanKind;
    name: string | null;
    status: SpanStatus;
    seq: number;
    started_at?: string | null;
    ended_at?: string | null;
    duration_ms?: number | null;
    cost_usd?: number | null;
    tokens_in?: number | null;
    tokens_out?: number | null;
    child_run_id?: string | null;
    payload?: Record<string, unknown> | null;
    error?: string | null;
}

export interface TraceResponse {
    run_id: string;
    count: number;
    spans: TraceSpan[];
}

/** A span with its resolved children — the shape SpanTree renders. */
export interface SpanNode extends TraceSpan {
    children: SpanNode[];
}

export type AgentEvent =
    | {
          type: 'span_open';
          span_id: string;
          parent_span_id: string | null;
          kind: SpanKind;
          name: string | null;
          iteration: number | null;
          seq: number;
          status: SpanStatus;
          payload?: Record<string, unknown>;
      }
    | {
          type: 'span_close';
          span_id: string;
          parent_span_id: string | null;
          kind: SpanKind;
          name: string | null;
          iteration: number | null;
          seq: number;
          status: SpanStatus;
          duration_ms?: number | null;
          cost_usd?: number | null;
          tokens_in?: number | null;
          tokens_out?: number | null;
          child_run_id?: string | null;
          payload?: Record<string, unknown>;
          error?: string | null;
      }
    | { type: 'iteration_start'; iteration: number; executor: ExecutorName; budget_pressure: number; open_subgoals: number }
    | { type: 'iteration_end'; iteration: number; outcome: 'success' | 'partial' | 'fail' | 'blocked'; decision: 'CONTINUE' | 'DONE' | 'PAUSE_HITL' | 'ABORT'; cost_iter_usd: string | number }
    | { type: 'resume'; from_iteration: number }
    | { type: 'budget_pressure'; iteration: number; pressure: number }
    | { type: 'budget_exhausted'; iteration: number; dim: string }
    | { type: 'pre_critic_block'; iteration: number; concerns: string[] }
    | { type: 'critic_pre'; iteration: number; verdict: PreCriticVerdictKind; concerns_count: number; cost_usd: number }
    | { type: 'critic_post'; iteration: number; verdict: PostCriticVerdictKind; tags: FailureTag[]; cost_usd: number }
    | { type: 'critic_align'; iteration: number; aligned: boolean; drift: number }
    | { type: 'critic_super'; iteration: number; recommendation: SupervisorRecommendation; confidence: number }
    | { type: 'retry_picked'; iteration: number; strategy: RetryStrategy; tags: FailureTag[] }
    | { type: 'retry_dequeued'; iteration: number; strategy: RetryStrategy }
    | { type: 'retry_exhausted'; iteration: number; step_id: string }
    | { type: 'bandit_arm_updated'; entity_id: string; task_class: string; arm: string; success: boolean; cost_usd: number; new_score: number }
    | { type: 'replan_triggered'; iteration: number; by: string; proposed_subgoals_count: number; new_plan_size: number }
    | { type: 'task_class_classified'; entity_id?: string | null; task_class: string; classifier_version: string }
    | { type: 'dreaming_triggered'; entity_id: string; reason: 'success' | 'failure' }
    | { type: 'cost_charged'; attribution: CostAttribution | string; sku?: string | null; amount_usd: number; latency_ms?: number; persisted: boolean }
    | { type: 'plan_candidate_generated'; style: string; estimated_cost_usd: string; latency_estimate_s: number }
    | { type: 'plan_chosen'; style: string; expected_cost_usd: string; alternates: string[] }
    | { type: 'plan_invariant_violation'; candidate_idx: number; violations: string[] }
    | { type: 'plan_judge_decision'; winner_idx: number; scores: number[] }
    | { type: 'meta_role_started'; role: string; iteration?: number }
    | { type: 'meta_role_completed'; role: string; verdict?: string; concerns_count?: number };
