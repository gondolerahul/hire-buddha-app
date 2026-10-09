// @vitest-environment jsdom
/**
 * hooks.test.tsx — the query cache shares reads and drops what a write changed (FE-21).
 */
import React from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const fetchAllPages = vi.fn();
vi.mock('@/services/pagination', () => ({ fetchAllPages: (...args: unknown[]) => fetchAllPages(...args) }));

import { useEntityList, useReport } from './hooks';
import { queryClient, invalidateAfterWrite } from './client';
import { queryKeys } from './keys';

function wrapperFor(client: QueryClient) {
    return ({ children }: { children: React.ReactNode }) => (
        <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );
}

describe('the query cache', () => {
    beforeEach(() => fetchAllPages.mockReset());

    it('makes one request for two components asking for the same entities', async () => {
        fetchAllPages.mockResolvedValue([{ id: 'e1' }]);
        const client = new QueryClient();
        const { result } = renderHook(
            () => [useEntityList({ type: 'AGENT' }), useEntityList({ type: 'AGENT' })],
            { wrapper: wrapperFor(client) },
        );
        await waitFor(() => expect(result.current[0].isSuccess && result.current[1].isSuccess).toBe(true));
        expect(fetchAllPages).toHaveBeenCalledTimes(1);
        expect(result.current[1].data).toEqual([{ id: 'e1' }]);
    });

    it('reads a failed report as null, as the report pages expect', async () => {
        const client = new QueryClient();
        const { result } = renderHook(
            () => useReport('getWalletLiability', () => Promise.reject(new Error('500'))),
            { wrapper: wrapperFor(client) },
        );
        await waitFor(() => expect(result.current.isSuccess).toBe(true));
        expect(result.current.data).toBeNull();
    });
});

describe('invalidateAfterWrite', () => {
    it('drops the lists a write path changes, and nothing else', () => {
        const spy = vi.spyOn(queryClient, 'invalidateQueries').mockResolvedValue();
        invalidateAfterWrite('/ai/entities/123');
        invalidateAfterWrite('/phone-numbers/9/claim');
        invalidateAfterWrite('/ai/tool-registry/sync-built-in');
        invalidateAfterWrite('/ai/execute');
        expect(spy.mock.calls.map(([filters]) => (filters as { queryKey: unknown }).queryKey)).toEqual([
            queryKeys.entities.all, queryKeys.phoneNumbers.all, queryKeys.tools.all,
        ]);
        spy.mockRestore();
    });
});
