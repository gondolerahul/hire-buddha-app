import { apiClient } from './api.client';
import { fetchAllPages } from './pagination';

export interface Integration {
    id: string;
    company_id: string;
    provider_name: string;
    model_name: string | null;
    service_sku: string;
    service_category: string;
    component_type: string;
    internal_cost: number;
    /** A cost unit code (GET /config/cost-units), e.g. PER_1M_TOKENS — Phase 15 T1-2. */
    cost_unit_code: string;
    service_metadata: Record<string, any> | null;
    status: string;
    created_at: string;
    updated_at: string;
}

export interface IntegrationCreate {
    company_id: string;
    provider_name: string;
    model_name?: string;
    service_sku: string;
    service_category?: string;
    component_type: string;
    internal_cost: number;
    /** A cost unit code (GET /config/cost-units), e.g. PER_1M_TOKENS — Phase 15 T1-2. */
    cost_unit_code: string;
    api_key: string;
    service_metadata?: Record<string, any>;
    status?: string;
}

export interface IntegrationUpdate {
    provider_name?: string;
    model_name?: string;
    service_sku?: string;
    service_category?: string;
    component_type?: string;
    internal_cost?: number;
    cost_unit_code?: string;
    api_key?: string;
    service_metadata?: Record<string, any>;
    status?: string;
}

/** A unit a registry price may be quoted in (Phase 15 T1-7). */
export interface CostUnitOption {
    code: string;
    dimension: string;
    per_quantity: number;
    label: string;
}

export interface Model {
    model_key: string;
    model_name: string;
    provider: string;
    model_type: string;
    is_active: boolean;
}

export const integrationService = {
    /** Every integration of the caller's company, page by page (API-16). */
    getIntegrations: async (): Promise<Integration[]> => fetchAllPages<Integration>('/config/integrations'),

    getCostUnits: async (): Promise<CostUnitOption[]> => {
        const response = await apiClient.get<CostUnitOption[]>('/config/cost-units');
        return response.data;
    },

    getModels: async (): Promise<Model[]> => {
        const response = await apiClient.get<Model[]>('/config/models');
        return response.data;
    },

    createIntegration: async (data: IntegrationCreate): Promise<Integration> => {
        const response = await apiClient.post<Integration>('/config/integrations', data);
        return response.data;
    },

    updateIntegration: async (id: string, data: IntegrationUpdate): Promise<Integration> => {
        const response = await apiClient.patch<Integration>(`/config/integrations/${id}`, data);
        return response.data;
    },

    deleteIntegration: async (id: string): Promise<void> => {
        await apiClient.delete(`/config/integrations/${id}`);
    }
};
