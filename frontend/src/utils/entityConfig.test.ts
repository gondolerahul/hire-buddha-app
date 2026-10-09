/**
 * entityConfig.test.ts — saving from the builder keeps what it does not show (FE-25, FE-03).
 */
import { describe, expect, it } from 'vitest';

import { hasPath, overlayConfig, unknownKeyPaths, withoutPaths } from './entityConfig';

describe('overlayConfig', () => {
    it('keeps stored keys the builder does not know, and lets its own keys win', () => {
        const loaded = { governance: { max_cost_usd: 1, meta_review_interval: 5 }, tags: ['a'] };
        const built = { governance: { max_cost_usd: 2 }, tags: ['b'] };
        expect(overlayConfig(loaded, built)).toEqual({
            governance: { max_cost_usd: 2, meta_review_interval: 5 }, tags: ['b'],
        });
    });

    it('clears a key the form cleared', () => {
        expect(overlayConfig({ goal: 'old' }, { goal: undefined })).toEqual({ goal: undefined });
    });
});

describe('unknownKeyPaths', () => {
    it('reads the paths out of the 422 detail', () => {
        const detail = [{ msg: 'Value error, Unknown configuration key(s), which would be ignored: '
            + 'governance.foo, steps[1].target.bar. Check the field names.' }];
        expect(unknownKeyPaths(detail)).toEqual(['governance.foo', 'steps[1].target.bar']);
        expect(unknownKeyPaths('something else')).toEqual([]);
    });
});

describe('hasPath and withoutPaths', () => {
    const config = { governance: { foo: 1 }, steps: [{}, { target: { bar: 2, tool: 'x' } }] };

    it('finds dotted and indexed paths', () => {
        expect(hasPath(config, 'steps[1].target.bar')).toBe(true);
        expect(hasPath(config, 'steps[0].target.bar')).toBe(false);
    });

    it('drops the paths from a copy and leaves the original alone', () => {
        const trimmed = withoutPaths(config, ['governance.foo', 'steps[1].target.bar']);
        expect(trimmed).toEqual({ governance: {}, steps: [{}, { target: { tool: 'x' } }] });
        expect(config.governance.foo).toBe(1);
    });
});
