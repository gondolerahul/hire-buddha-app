/**
 * services/kpi.service.ts — Phase 11 KPI dashboard surface.
 */
import { apiClient } from './api.client';
import type {
    CostAttributionRow,
    KPICriticResponse,
    KPIMetaAgentResponse,
    KPIRunRow,
    RiskIndicatorsResponse,
    ExitChecklistResponse,
    DecisionRow,
} from '@/types/agentKernel';

export interface KPISince {
    since?: string;          // e.g. "7d", "30d", "24h"
    companyId?: string;
}

function _params({ since, companyId }: KPISince = {}): Record<string, string> {
    const out: Record<string, string> = {};
    if (since) out.since = since;
    if (companyId) out.company_id = companyId;
    return out;
}

export const kpiService = {
    async getRunHealth(opts: KPISince = {}): Promise<KPIRunRow[]> {
        const { data } = await apiClient.get('/ai/admin/admin/kpi/runs', {
            params: _params(opts),
        });
        return Array.isArray(data) ? data : [];
    },

    async getCostBreakdown(opts: KPISince = {}): Promise<CostAttributionRow[]> {
        const { data } = await apiClient.get('/ai/admin/admin/kpi/cost', {
            params: _params(opts),
        });
        return Array.isArray(data) ? data : [];
    },

    async getCriticHealth(opts: KPISince = {}): Promise<KPICriticResponse> {
        const { data } = await apiClient.get('/ai/admin/admin/kpi/critic', {
            params: _params(opts),
        });
        return data ?? { verdict_distribution: [], cost_share: 0 };
    },

    async getMetaAgentHealth(opts: KPISince = {}): Promise<KPIMetaAgentResponse> {
        const { data } = await apiClient.get('/ai/admin/admin/kpi/meta_agent', {
            params: _params(opts),
        });
        return data ?? { intelligence_growth: [] };
    },

    async getCompanyCostAttribution(
        companyId: string, since = '7d',
    ): Promise<CostAttributionRow[]> {
        const { data } = await apiClient.get(
            `/ai/admin/companies/${companyId}/cost_attribution`,
            { params: { since } },
        );
        return Array.isArray(data) ? data : [];
    },

    // Track 15 — risk register / exit checklist / decision log.
    async getRiskIndicators(opts: KPISince = {}): Promise<RiskIndicatorsResponse> {
        const { data } = await apiClient.get('/ai/admin/admin/risks', {
            params: _params(opts),
        });
        return data ?? { as_of: '', overall: 'ok', indicators: [], since: '7d' };
    },

    async getExitChecklist(): Promise<ExitChecklistResponse> {
        const { data } = await apiClient.get('/ai/admin/admin/exit_checklist');
        return data ?? { as_of: '', total: 0, satisfied: 0, percent_complete: 0, items: [] };
    },

    async listDecisions(limit = 50): Promise<DecisionRow[]> {
        const { data } = await apiClient.get('/ai/admin/admin/decisions', {
            params: { limit },
        });
        return Array.isArray(data) ? data : [];
    },

    async appendDecision(body: {
        summary: string; rationale?: string; kind?: string;
    }): Promise<{ appended: boolean; date: string; summary: string }> {
        const { data } = await apiClient.post('/ai/admin/admin/decisions', body);
        return data;
    },
};
