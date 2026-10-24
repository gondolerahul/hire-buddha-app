/**
 * queries/keys.ts — every query key, in one place (FE-21).
 *
 * A key's first element names the resource; a mutation invalidates that prefix
 * (`queryClient.invalidateQueries({ queryKey: queryKeys.phoneNumbers.all })`)
 * and every query under it refetches — whatever its filters.
 */
export const queryKeys = {
    entities: {
        all: ['entities'] as const,
        list: (params: Record<string, unknown> = {}) => ['entities', 'list', params] as const,
    },
    tools: {
        all: ['tools'] as const,
        registry: ['tools', 'registry'] as const,
    },
    /** The company's plan and entitlements (Phase 15 T6-2): menu locks. */
    entitlements: ['me', 'entitlements'] as const,
    phoneNumbers: {
        all: ['phone-numbers'] as const,
        list: (status: string, provider: string) => ['phone-numbers', 'list', status, provider] as const,
    },
    companies: {
        all: ['companies'] as const,
        list: ['companies', 'list'] as const,
        partners: ['companies', 'partners'] as const,
        tenants: ['companies', 'tenants'] as const,
        customers: (isAdmin: boolean) => ['companies', 'customers', isAdmin] as const,
    },
    users: {
        all: ['users'] as const,
        list: ['users', 'list'] as const,
        me: ['users', 'me'] as const,
    },
    automation: {
        all: ['automation'] as const,
        settings: ['automation', 'settings'] as const,
        platform: ['automation', 'platform'] as const,
        triggers: ['automation', 'triggers'] as const,
        firings: (id: string) => ['automation', 'firings', id] as const,
        events: (query: object) => ['automation', 'events', query] as const,
        event: (id: string) => ['automation', 'event', id] as const,
        health: ['automation', 'health'] as const,
        waits: ['automation', 'waits'] as const,
    },
    notifications: {
        mine: ['notifications', 'mine'] as const,
    },
    reports: {
        all: ['reports'] as const,
        one: (name: string, ...params: unknown[]) => ['reports', name, ...params] as const,
    },
};
