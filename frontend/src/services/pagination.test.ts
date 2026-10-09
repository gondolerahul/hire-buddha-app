/**
 * pagination.test.ts — following a list's cursor to its end (API-16).
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';

const get = vi.fn();
vi.mock('./api.client', () => ({ apiClient: { get: (...args: unknown[]) => get(...args) } }));

import { fetchAllPages, fetchPage, MAX_PAGE_SIZE } from './pagination';

describe('fetchAllPages', () => {
    beforeEach(() => get.mockReset());

    it('follows next_cursor until it is null, at the largest page size', async () => {
        get.mockResolvedValueOnce({ data: { items: [1, 2], next_cursor: 'c1', limit: MAX_PAGE_SIZE } })
            .mockResolvedValueOnce({ data: { items: [3], next_cursor: null, limit: MAX_PAGE_SIZE } });
        expect(await fetchAllPages<number>('/ai/entities', { type: 'AGENT' })).toEqual([1, 2, 3]);
        expect(get.mock.calls[0]).toEqual(['/ai/entities', { params: { type: 'AGENT', limit: MAX_PAGE_SIZE } }]);
        expect(get.mock.calls[1]).toEqual(['/ai/entities', { params: { type: 'AGENT', limit: MAX_PAGE_SIZE, cursor: 'c1' } }]);
    });

    it('stops at maxPages on a list that never ends', async () => {
        get.mockResolvedValue({ data: { items: [0], next_cursor: 'again', limit: MAX_PAGE_SIZE } });
        expect(await fetchAllPages<number>('/x', {}, 3)).toEqual([0, 0, 0]);
        expect(get).toHaveBeenCalledTimes(3);
    });
});

describe('fetchPage', () => {
    it('sends the cursor only when there is one', async () => {
        get.mockReset().mockResolvedValue({ data: { items: [], next_cursor: null, limit: 50 } });
        await fetchPage('/ai/executions');
        await fetchPage('/ai/executions', {}, 'abc');
        expect(get.mock.calls[0][1]).toEqual({ params: { limit: 50 } });
        expect(get.mock.calls[1][1]).toEqual({ params: { limit: 50, cursor: 'abc' } });
    });
});
