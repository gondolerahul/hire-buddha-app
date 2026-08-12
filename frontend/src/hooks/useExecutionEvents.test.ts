/**
 * useExecutionEvents.test.ts — Phase 11 reducer tests.
 *
 * To run: install vitest (`npm install --save-dev vitest @testing-library/react
 * @testing-library/jest-dom jsdom`) then `npx vitest run`.
 *
 * The reducer is a pure function over the event union so these tests
 * don't need a DOM or a real EventSource; they just describe the
 * derived state for a sequence of events.
 */
import { describe, expect, it } from 'vitest';

import {
    type ExecutionEventState,
    executionEventReducer,
} from './useExecutionEvents';
import type { AgentEvent } from '@/types/agentKernel';

const _INITIAL: ExecutionEventState = {
    iterations: {},
    iterationOrder: [],
    banditUpdates: [],
    replans: [],
    taskClass: undefined,
    costByAttribution: {},
    unknownEvents: [],
};

function apply(state: ExecutionEventState, events: AgentEvent[]): ExecutionEventState {
    return events.reduce(
        (s, e) => executionEventReducer(s, { kind: 'event', event: e }),
        state,
    );
}

describe('executionEventReducer', () => {
    it('records iteration start + end into one slice', () => {
        const next = apply(_INITIAL, [
            { type: 'iteration_start', iteration: 1, executor: 'DAG',
              budget_pressure: 0.1, open_subgoals: 2 },
            { type: 'iteration_end', iteration: 1, outcome: 'success',
              decision: 'CONTINUE', cost_iter_usd: '0.01' },
        ]);
        expect(next.iterationOrder).toEqual([1]);
        expect(next.iterations[1].executor).toBe('DAG');
        expect(next.iterations[1].outcome).toBe('success');
        expect(next.iterations[1].decision).toBe('CONTINUE');
    });

    it('captures all four critic verdicts for one iteration', () => {
        const next = apply(_INITIAL, [
            { type: 'iteration_start', iteration: 3, executor: 'SingleStep',
              budget_pressure: 0.2, open_subgoals: 1 },
            { type: 'critic_pre',  iteration: 3, verdict: 'PASS',
              concerns_count: 0, cost_usd: 0.001 },
            { type: 'critic_post', iteration: 3, verdict: 'REVISE',
              tags: ['WRONG_FORMAT'], cost_usd: 0.005 },
            { type: 'critic_align', iteration: 3, aligned: false, drift: 0.3 },
            { type: 'critic_super', iteration: 3, recommendation: 'REPLAN',
              confidence: 0.7 },
        ]);
        const slice = next.iterations[3];
        expect(slice.pre_critic?.verdict).toBe('PASS');
        expect(slice.post_critic?.verdict).toBe('REVISE');
        expect(slice.post_critic?.tags).toContain('WRONG_FORMAT');
        expect(slice.alignment?.aligned).toBe(false);
        expect(slice.supervisor?.recommendation).toBe('REPLAN');
    });

    it('records resume from a snapshot', () => {
        const next = apply(_INITIAL, [
            { type: 'resume', from_iteration: 5 },
        ]);
        expect(next.iterations[5].resumed_from).toBe(5);
    });

    it('accumulates bandit updates + replans separately', () => {
        const next = apply(_INITIAL, [
            { type: 'bandit_arm_updated', entity_id: 'e1', task_class: 'general',
              arm: 'DAG_PARALLEL', success: true, cost_usd: 0.02, new_score: 0.8 },
            { type: 'replan_triggered', iteration: 4, by: 'supervisor',
              proposed_subgoals_count: 2, new_plan_size: 3 },
        ]);
        expect(next.banditUpdates).toHaveLength(1);
        expect(next.banditUpdates[0].arm).toBe('DAG_PARALLEL');
        expect(next.replans).toHaveLength(1);
        expect(next.replans[0].by).toBe('supervisor');
    });

    it('sums cost-by-attribution across multiple charges', () => {
        const next = apply(_INITIAL, [
            { type: 'cost_charged', attribution: 'critic_post',
              amount_usd: 0.005, persisted: true },
            { type: 'cost_charged', attribution: 'critic_post',
              amount_usd: 0.003, persisted: true },
            { type: 'cost_charged', attribution: 'tool',
              amount_usd: 0.02, persisted: true },
        ]);
        expect(next.costByAttribution.critic_post).toBeCloseTo(0.008);
        expect(next.costByAttribution.tool).toBeCloseTo(0.02);
    });

    it('records task class for the run', () => {
        const next = apply(_INITIAL, [
            { type: 'task_class_classified', task_class: 'research_topic',
              classifier_version: 'v1' },
        ]);
        expect(next.taskClass).toBe('research_topic');
    });

    it('stores unknown events for debug without crashing', () => {
        const next = executionEventReducer(_INITIAL, {
            kind: 'unknown', raw: { hello: 'world' },
        });
        expect(next.unknownEvents).toHaveLength(1);
    });

    it('reset wipes the state', () => {
        const seeded = apply(_INITIAL, [
            { type: 'iteration_start', iteration: 1, executor: 'DAG',
              budget_pressure: 0.5, open_subgoals: 1 },
        ]);
        const reset = executionEventReducer(seeded, { kind: 'reset' });
        expect(reset.iterations).toEqual({});
        expect(reset.iterationOrder).toEqual([]);
    });
});
