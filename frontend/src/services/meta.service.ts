/**
 * services/meta.service.ts — Meta-Agent admin surface (Track 5 + Track 9).
 */
import { apiClient } from './api.client';
import type {
    AntiPatternRow,
    PromptCandidate,
    SkillCandidate,
} from '@/types/agentKernel';

export const metaService = {
    async listSkillCandidates(limit = 25): Promise<SkillCandidate[]> {
        const { data } = await apiClient.get('/ai/admin/meta/skill_candidates', {
            params: { limit },
        });
        return Array.isArray(data) ? data : [];
    },

    async listAntiPatterns(
        opts: { entityType?: string; tags?: string[]; topK?: number } = {},
    ): Promise<AntiPatternRow[]> {
        const { data } = await apiClient.get(
            '/ai/admin/meta/intelligence/anti_patterns',
            {
                params: {
                    entity_type: opts.entityType,
                    tags: opts.tags?.join(','),
                    top_k: opts.topK ?? 25,
                },
            },
        );
        return Array.isArray(data) ? data : [];
    },

    async listPromptCandidates(opts: { onlyPending?: boolean; limit?: number } = {}): Promise<PromptCandidate[]> {
        const { data } = await apiClient.get(
            '/ai/admin/meta/intelligence/prompt_candidates',
            {
                params: {
                    only_pending: opts.onlyPending ?? true,
                    limit: opts.limit ?? 25,
                },
            },
        );
        return Array.isArray(data) ? data : [];
    },

    async approvePromptCandidate(nodeId: string): Promise<{ approved: boolean }> {
        const { data } = await apiClient.post(
            `/ai/admin/meta/intelligence/prompt_candidates/${nodeId}/approve`,
        );
        return data ?? { approved: false };
    },

    async toggleExperimentalTool(
        toolId: string,
        enabled: boolean,
    ): Promise<{ flag_key: string; enabled: boolean }> {
        const { data } = await apiClient.post(
            `/ai/admin/admin/tools/${toolId}/experimental`,
            null,
            { params: { enabled } },
        );
        return data;
    },

    async promoteSkillCandidate(
        nodeId: string,
        opts: { name?: string } = {},
    ): Promise<{
        promoted: boolean;
        node_id: string;
        entity_id: string;
        name: string;
        status: string;
    }> {
        const { data } = await apiClient.post(
            `/ai/admin/meta/skill_candidates/${nodeId}/promote`,
            null,
            opts.name ? { params: { name: opts.name } } : undefined,
        );
        return data;
    },

    async promoteDraftEntity(
        entityId: string,
    ): Promise<{ promoted: boolean; entity_id: string; status: string }> {
        const { data } = await apiClient.post(
            `/ai/admin/meta/entities/${entityId}/promote`,
        );
        return data;
    },

    async runSpecCritic(payload: {
        spec: Record<string, unknown>;
        search_top_k?: unknown[];
        actor_model?: string;
        spec_critic_model_override?: string;
        platform_manifest_hash?: string;
    }): Promise<{
        verdict: 'PASS' | 'REVISE' | 'BLOCK';
        concerns: unknown[];
        rules_referenced?: string[];
        raw?: string;
    }> {
        const { data } = await apiClient.post(
            `/ai/admin/meta/spec_critic`,
            payload,
        );
        return data;
    },
};
