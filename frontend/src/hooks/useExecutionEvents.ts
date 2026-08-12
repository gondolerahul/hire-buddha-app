/**
 * hooks/useExecutionEvents — Reducer-based derived state for one run.
 *
 * Subscribes to the run's SSE stream via `useAgentEvents`, parses
 * every typed event, and maintains a derived state object the
 * ExecutionDetail page can render against.
 */
import { useEffect, useReducer } from 'react';

import { useAgentEvents } from '@/services/events';
import type {
    AgentEvent,
    CostAttribution,
    FailureTag,
    PostCriticVerdictKind,
    PreCriticVerdictKind,
    RetryStrategy,
    SupervisorRecommendation,
    TraceSpan,
} from '@/types/agentKernel';

// ---------------------------------------------------------------------------
// Derived state shape
// ---------------------------------------------------------------------------

export interface IterationSlice {
    iteration: number;
    executor?: string;
    budget_pressure?: number;
    open_subgoals?: number;
    started_at?: number;
    ended_at?: number;
    outcome?: 'success' | 'partial' | 'fail' | 'blocked';
    decision?: 'CONTINUE' | 'DONE' | 'PAUSE_HITL' | 'ABORT';
    cost_iter_usd?: string | number;
    pre_critic?: { verdict: PreCriticVerdictKind; concerns_count: number; cost_usd: number };
    post_critic?: {
        verdict: PostCriticVerdictKind;
        tags: FailureTag[];
        cost_usd: number;
    };
    alignment?: { aligned: boolean; drift: number };
    supervisor?: { recommendation: SupervisorRecommendation; confidence: number };
    retry?: { strategy: RetryStrategy; tags?: FailureTag[] };
    resumed_from?: number;
}

export interface ExecutionEventState {
    iterations: Record<number, IterationSlice>;
    iterationOrder: number[];
    banditUpdates: Array<{
        entity_id: string;
        task_class: string;
        arm: string;
        success: boolean;
        cost_usd: number;
        new_score: number;
        ts: number;
    }>;
    replans: Array<{ iteration: number; by: string; proposed_subgoals_count: number }>;
    taskClass?: string;
    costByAttribution: Partial<Record<CostAttribution, number>>;
    /** Flat span map keyed by span_id; the component assembles the tree. */
    spans: Record<string, TraceSpan>;
    unknownEvents: unknown[];
}

const _INITIAL: ExecutionEventState = {
    iterations: {},
    iterationOrder: [],
    banditUpdates: [],
    replans: [],
    taskClass: undefined,
    costByAttribution: {},
    spans: {},
    unknownEvents: [],
};

// ---------------------------------------------------------------------------
// Reducer
// ---------------------------------------------------------------------------

type ReducerAction =
    | { kind: 'event'; event: AgentEvent }
    | { kind: 'unknown'; raw: unknown }
    | { kind: 'reset' };

export function executionEventReducer(
    state: ExecutionEventState,
    action: ReducerAction,
): ExecutionEventState {
    if (action.kind === 'reset') return _INITIAL;
    if (action.kind === 'unknown') {
        return { ...state, unknownEvents: [...state.unknownEvents, action.raw] };
    }

    const { event } = action;
    switch (event.type) {
        case 'iteration_start': {
            const slice: IterationSlice = {
                ...state.iterations[event.iteration],
                iteration: event.iteration,
                executor: event.executor,
                budget_pressure: event.budget_pressure,
                open_subgoals: event.open_subgoals,
                started_at: Date.now(),
            };
            return _writeSlice(state, slice);
        }
        case 'iteration_end': {
            const prev = state.iterations[event.iteration] ?? {
                iteration: event.iteration,
            };
            const slice: IterationSlice = {
                ...prev,
                outcome: event.outcome,
                decision: event.decision,
                cost_iter_usd: event.cost_iter_usd,
                ended_at: Date.now(),
            };
            return _writeSlice(state, slice);
        }
        case 'resume': {
            const target = event.from_iteration;
            const slice: IterationSlice = {
                ...state.iterations[target],
                iteration: target,
                resumed_from: target,
            };
            return _writeSlice(state, slice);
        }
        case 'critic_pre': {
            const slice = _ensure(state, event.iteration);
            slice.pre_critic = {
                verdict: event.verdict,
                concerns_count: event.concerns_count,
                cost_usd: event.cost_usd,
            };
            return _writeSlice(state, slice);
        }
        case 'critic_post': {
            const slice = _ensure(state, event.iteration);
            slice.post_critic = {
                verdict: event.verdict,
                tags: event.tags,
                cost_usd: event.cost_usd,
            };
            return _writeSlice(state, slice);
        }
        case 'critic_align': {
            const slice = _ensure(state, event.iteration);
            slice.alignment = {
                aligned: event.aligned,
                drift: event.drift,
            };
            return _writeSlice(state, slice);
        }
        case 'critic_super': {
            const slice = _ensure(state, event.iteration);
            slice.supervisor = {
                recommendation: event.recommendation,
                confidence: event.confidence,
            };
            return _writeSlice(state, slice);
        }
        case 'retry_picked':
        case 'retry_dequeued': {
            const slice = _ensure(state, event.iteration);
            slice.retry = {
                strategy: event.strategy,
                tags: 'tags' in event ? event.tags : undefined,
            };
            return _writeSlice(state, slice);
        }
        case 'bandit_arm_updated':
            return {
                ...state,
                banditUpdates: [
                    ...state.banditUpdates,
                    {
                        entity_id: event.entity_id,
                        task_class: event.task_class,
                        arm: event.arm,
                        success: event.success,
                        cost_usd: event.cost_usd,
                        new_score: event.new_score,
                        ts: Date.now(),
                    },
                ],
            };
        case 'replan_triggered':
            return {
                ...state,
                replans: [
                    ...state.replans,
                    {
                        iteration: event.iteration,
                        by: event.by,
                        proposed_subgoals_count: event.proposed_subgoals_count,
                    },
                ],
            };
        case 'span_open':
        case 'span_close': {
            const prev = state.spans[event.span_id];
            const merged: TraceSpan = {
                ...(prev ?? { children: undefined } as unknown as TraceSpan),
                span_id: event.span_id,
                parent_span_id: event.parent_span_id,
                iteration: event.iteration,
                kind: event.kind,
                name: event.name,
                status: event.status,
                seq: event.seq,
                payload: { ...(prev?.payload ?? {}), ...(event.payload ?? {}) },
            };
            if (event.type === 'span_close') {
                merged.duration_ms = event.duration_ms ?? merged.duration_ms;
                merged.cost_usd = event.cost_usd ?? merged.cost_usd;
                merged.tokens_in = event.tokens_in ?? merged.tokens_in;
                merged.tokens_out = event.tokens_out ?? merged.tokens_out;
                merged.child_run_id = event.child_run_id ?? merged.child_run_id;
                merged.error = event.error ?? merged.error;
            }
            return { ...state, spans: { ...state.spans, [event.span_id]: merged } };
        }
        case 'task_class_classified':
            return { ...state, taskClass: event.task_class };
        case 'cost_charged': {
            const att = event.attribution as CostAttribution;
            const next = { ...state.costByAttribution };
            next[att] = (next[att] ?? 0) + event.amount_usd;
            return { ...state, costByAttribution: next };
        }
        default:
            return state;
    }
}

function _ensure(state: ExecutionEventState, iter: number): IterationSlice {
    return { ...(state.iterations[iter] ?? { iteration: iter }) };
}

function _writeSlice(
    state: ExecutionEventState,
    slice: IterationSlice,
): ExecutionEventState {
    const iterations = { ...state.iterations, [slice.iteration]: slice };
    const iterationOrder = state.iterationOrder.includes(slice.iteration)
        ? state.iterationOrder
        : [...state.iterationOrder, slice.iteration].sort((a, b) => a - b);
    return { ...state, iterations, iterationOrder };
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export interface UseExecutionEventsResult {
    state: ExecutionEventState;
    reset: () => void;
}

/**
 * Subscribe to a run's SSE stream and maintain typed derived state.
 *
 * `url` should be the full SSE endpoint
 * (e.g. ``${API_BASE_URL}/ai/executions/{id}/stream``). Pass `null` to
 * pause the connection (the hook will tear down).
 */
export function useExecutionEvents(url: string | null): UseExecutionEventsResult {
    const [state, dispatch] = useReducer(executionEventReducer, _INITIAL);

    useEffect(() => {
        dispatch({ kind: 'reset' });
    }, [url]);

    useAgentEvents({
        url,
        onEvent: (event) => dispatch({ kind: 'event', event }),
        onUnknown: (raw) => dispatch({ kind: 'unknown', raw }),
    });

    return {
        state,
        reset: () => dispatch({ kind: 'reset' }),
    };
}
