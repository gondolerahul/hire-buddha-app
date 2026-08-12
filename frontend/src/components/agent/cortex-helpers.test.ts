/**
 * cortex-helpers.test.ts — pure-function provenance extractor tests.
 *
 * Run with vitest (see useExecutionEvents.test.ts for setup notes).
 */
import { describe, expect, it } from 'vitest';

import { extractProvenance, extractRuleStatus } from './cortex-helpers';

describe('extractProvenance', () => {
    it('returns null when source_ref is missing', () => {
        expect(extractProvenance(null)).toBeNull();
        expect(extractProvenance(undefined)).toBeNull();
        expect(extractProvenance({})).toBeNull();
    });

    it('returns null when source_ref has no provenance subkey', () => {
        expect(extractProvenance({ type: 'something' })).toBeNull();
    });

    it('returns null when provenance.source_type is missing', () => {
        expect(extractProvenance({ provenance: { tool_id: 'x' } })).toBeNull();
    });

    it('parses a complete provenance block', () => {
        const ref = {
            provenance: {
                source_type: 'tool',
                tool_id: 'web_search',
                url: 'https://example.com',
                trust_score: 0.72,
                run_id: 'run-1',
                step_id: 's3',
            },
        };
        const p = extractProvenance(ref);
        expect(p).not.toBeNull();
        expect(p?.source_type).toBe('tool');
        expect(p?.tool_id).toBe('web_search');
        expect(p?.trust_score).toBeCloseTo(0.72);
    });

    it('defaults trust_score to 0.5 when missing', () => {
        const p = extractProvenance({ provenance: { source_type: 'reflection' } });
        expect(p?.trust_score).toBe(0.5);
    });
});

describe('extractRuleStatus', () => {
    it('returns confirmed for nodes without a status tag', () => {
        expect(extractRuleStatus(null)).toBe('confirmed');
        expect(extractRuleStatus({})).toBe('confirmed');
    });

    it('returns candidate when source_ref.status === candidate', () => {
        expect(extractRuleStatus({ status: 'candidate' })).toBe('candidate');
    });

    it('returns confirmed for any other status value', () => {
        expect(extractRuleStatus({ status: 'confirmed' })).toBe('confirmed');
        expect(extractRuleStatus({ status: 'unknown' })).toBe('confirmed');
    });
});
