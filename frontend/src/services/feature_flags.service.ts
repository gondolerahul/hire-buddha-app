/**
 * services/feature_flags.service.ts — Per-company feature flag fetch +
 * admin CRUD.
 *
 * The frontend boots once with `GET /ai/admin/feature_flags/me` and
 * caches the result. The `useFeatureFlag` hook reads from this cache.
 * Admins additionally use the admin endpoints for the Feature Flags page.
 */
import { apiClient } from './api.client';
import type { FeatureFlagsResponse, FeatureFlagRow } from '@/types/agentKernel';

export type FeatureFlagScope = 'all' | 'global' | 'company' | 'entity';

export interface SetFeatureFlagBody {
    scope: 'global' | 'company' | 'entity';
    enabled?: boolean | null;
    value_json?: unknown;
    company_id?: string;
    entity_id?: string;
}

export const featureFlagsService = {
    async fetchMine(): Promise<FeatureFlagsResponse> {
        const { data } = await apiClient.get('/ai/admin/feature_flags/me');
        return data ?? { defaults: {}, numeric_defaults: {}, overrides: {} };
    },

    async listAdmin(scope: FeatureFlagScope = 'all'): Promise<FeatureFlagRow[]> {
        const { data } = await apiClient.get('/ai/admin/feature_flags/admin', {
            params: { scope },
        });
        return Array.isArray(data) ? data : [];
    },

    async set(flagKey: string, body: SetFeatureFlagBody): Promise<FeatureFlagRow> {
        const { data } = await apiClient.put(
            `/ai/admin/feature_flags/${encodeURIComponent(flagKey)}`,
            body,
        );
        return data;
    },

    async remove(
        flagKey: string,
        scope: 'global' | 'company' | 'entity' = 'company',
        opts: { company_id?: string; entity_id?: string } = {},
    ): Promise<{ deleted: boolean }> {
        const { data } = await apiClient.delete(
            `/ai/admin/feature_flags/${encodeURIComponent(flagKey)}`,
            { params: { scope, ...opts } },
        );
        return data;
    },
};
