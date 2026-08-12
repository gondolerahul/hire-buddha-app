import { apiClient } from './api.client';

export interface OnboardingStatus {
    status: string;
    completed_steps: string[];
    total_steps: number;
    current_step: string | null;
    completion_pct: number;
    metadata?: Record<string, any>;
}

export interface OnboardingStepData {
    step_name: string;
    step_data?: Record<string, any>;
}

export interface PhonePoolNumber {
    id: string;
    phone_number: string;
    provider: string;
    country_code: string;
    status: string;
    label?: string;
    monthly_cost_usd?: number;
    provider_sid?: string;
    capabilities?: Record<string, boolean>;
    claimed_by_company_id?: string;
    claimed_at?: string;
    notes?: string;
    created_at?: string;
}

export interface TenantSummary {
    id: string;
    name: string;
    status: string;
    onboarding_status: string;
    health_score: number;
    health_level: 'green' | 'amber' | 'red';
    wallet_balance: number;
    daily_credits: number;
    integration_count: number;
    entity_count: number;
    recent_executions_7d: number;
    user_count: number;
    created_at?: string;
}

export interface PartnerAnalytics {
    total_tenants: number;
    total_entities: number;
    total_executions: number;
    total_cost_usd: number;
    total_wallet_balance: number;
    active_tenants: number;
    suspended_tenants: number;
}

export const onboardingService = {
    getStatus: async (): Promise<OnboardingStatus> => {
        const res = await apiClient.get<OnboardingStatus>('/onboarding/status');
        return res.data;
    },

    completeStep: async (stepName: string, stepData?: Record<string, any>): Promise<OnboardingStatus> => {
        const res = await apiClient.post<OnboardingStatus>(`/onboarding/step/${stepName}`, {
            step_name: stepName,
            step_data: stepData,
        });
        return res.data;
    },

    finalizeOnboarding: async (): Promise<OnboardingStatus> => {
        const res = await apiClient.post<OnboardingStatus>('/onboarding/complete');
        return res.data;
    },

    skipOnboarding: async (): Promise<void> => {
        await apiClient.post('/onboarding/skip');
    },
};

export const partnerService = {
    getTenants: async (): Promise<{ total_tenants: number; tenants: TenantSummary[] }> => {
        const res = await apiClient.get('/partner/tenants');
        return res.data;
    },

    getTenantDetails: async (tenantId: string): Promise<any> => {
        const res = await apiClient.get(`/partner/tenants/${tenantId}/details`);
        return res.data;
    },

    getAnalytics: async (): Promise<PartnerAnalytics> => {
        const res = await apiClient.get('/partner/analytics/summary');
        return res.data;
    },
};

export const phonePoolService = {
    listNumbers: async (status?: string, provider?: string): Promise<any> => {
        const params = new URLSearchParams();
        if (status) params.set('status', status);
        if (provider) params.set('provider', provider);
        const res = await apiClient.get(`/phone-numbers?${params}`);
        return res.data;
    },

    addNumber: async (data: {
        phone_number: string;
        provider: string;
        country_code?: string;
        label?: string;
        monthly_cost_usd?: number;
        notes?: string;
        agent_id?: string;
        customer_id?: string;
        customer_name?: string;
    }): Promise<PhonePoolNumber> => {
        const res = await apiClient.post<PhonePoolNumber>('/phone-numbers', data);
        return res.data;
    },

    bulkAddNumbers: async (numbers: any[]): Promise<any> => {
        const res = await apiClient.post('/phone-numbers/bulk', { numbers });
        return res.data;
    },

    syncNumbers: async (provider?: string): Promise<any> => {
        const res = await apiClient.post('/phone-numbers/sync', { provider: provider || null });
        return res.data;
    },

    claimNumber: async (numberId: string, targetCompanyId?: string): Promise<any> => {
        const body = targetCompanyId ? { target_company_id: targetCompanyId } : undefined;
        const res = await apiClient.post(`/phone-numbers/${numberId}/claim`, body);
        return res.data;
    },

    releaseNumber: async (numberId: string): Promise<any> => {
        const res = await apiClient.post(`/phone-numbers/${numberId}/release`);
        return res.data;
    },

    assignAgent: async (numberId: string, data: {
        agent_id: string;
        customer_id?: string;
        customer_name?: string;
    }): Promise<any> => {
        const res = await apiClient.post(`/phone-numbers/${numberId}/assign`, data);
        return res.data;
    },

    updateNumber: async (numberId: string, data: any): Promise<any> => {
        const res = await apiClient.patch(`/phone-numbers/${numberId}`, data);
        return res.data;
    },

    deleteNumber: async (numberId: string): Promise<any> => {
        const res = await apiClient.delete(`/phone-numbers/${numberId}`);
        return res.data;
    },
};
