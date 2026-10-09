/**
 * events.test.ts — the run stream's resume URL and its last frame (GW-18, GW-19).
 */
import { describe, expect, it } from 'vitest';

import { isTerminalFrame, resumeUrl } from './events';
import { isMilestone } from '@/hooks/useExecutionEvents';

describe('resumeUrl', () => {
    it('leaves a first connection alone', () => {
        expect(resumeUrl('/api/v1/ai/executions/r1/stream', null)).toBe('/api/v1/ai/executions/r1/stream');
    });

    it('asks for what came after the last frame', () => {
        expect(resumeUrl('/api/v1/ai/executions/r1/stream', '1700000000001-0')).toBe(
            '/api/v1/ai/executions/r1/stream?last_event_id=1700000000001-0',
        );
        expect(resumeUrl('/s?x=1', '5-0')).toBe('/s?x=1&last_event_id=5-0');
    });
});

describe('isTerminalFrame', () => {
    it('is the field, not a status word in a payload', () => {
        expect(isTerminalFrame({ type: 'run_end', outcome: 'COMPLETED', terminal: true })).toBe(true);
        expect(isTerminalFrame({ type: 'span_close', payload: { status: 'COMPLETED' } })).toBe(false);
        expect(isTerminalFrame({ status: 'FAILED' })).toBe(false);
        expect(isTerminalFrame(null)).toBe(false);
    });
});

describe('isMilestone', () => {
    it('marks the frames after which the stored run has moved on', () => {
        expect(isMilestone({ type: 'iteration_end', iteration: 1 })).toBe(true);
        expect(isMilestone({ type: 'run_end', outcome: 'PAUSED' })).toBe(true);
        expect(isMilestone({ status: 'HITL_PENDING', approval_id: 'a' })).toBe(true);
        expect(isMilestone({ type: 'step_delta', step: 's', text: 'x' })).toBe(false);
        expect(isMilestone({ type: 'span_open', span_id: 's' })).toBe(false);
    });
});
