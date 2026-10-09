/**
 * queries/client.ts — the app's one query cache (FE-21, FE-I3).
 *
 * Pages fetched on every mount: the phone pool made five requests each time,
 * the hierarchy canvas pulled every entity and tool on each tab switch, the
 * report tabs fetched again whenever they were reopened, and every mutation
 * refetched everything. Reads now go through `@tanstack/react-query`: a
 * result is shared by every component that asks for the same key, kept for
 * five minutes, and fresh for thirty seconds; a mutation invalidates the keys
 * it changed (`queries/keys.ts`). The cache is cleared at sign-out.
 */
import { QueryClient } from '@tanstack/react-query';

import { onApiWrite } from '@/services/api.client';

import { queryKeys } from './keys';

export const queryClient = new QueryClient({
    defaultOptions: {
        queries: {
            staleTime: 30_000,
            gcTime: 5 * 60_000,
            retry: 1,
            refetchOnWindowFocus: false,
        },
    },
});

/**
 * The cached resource each write path changes. Whatever page made the write —
 * the builder saving an entity, the library deleting one — the lists that
 * hold it are refetched by whoever shows them next.
 */
export const WRITE_INVALIDATES: Array<[RegExp, readonly unknown[]]> = [
    [/^\/?ai\/(entities|templates)(\/|\?|$)/, queryKeys.entities.all],
    [/^\/?ai\/tool-registry(\/|\?|$)/, queryKeys.tools.all],
    [/^\/?phone-numbers(\/|\?|$)/, queryKeys.phoneNumbers.all],
    [/^\/?companies(\/|\?|$)/, queryKeys.companies.all],
    [/^\/?users(\/|\?|$)/, queryKeys.users.all],
];

export function invalidateAfterWrite(url: string): void {
    for (const [pattern, key] of WRITE_INVALIDATES) {
        if (pattern.test(url)) void queryClient.invalidateQueries({ queryKey: key });
    }
}

onApiWrite((_method, url) => invalidateAfterWrite(url));
