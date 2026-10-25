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
    /** What the provider charges (cost side, staff only; Phase 15 NR-6). */
    provider_monthly_cost_usd?: number;
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
    /** USD at today's rate (the health score's figure). */
    wallet_balance: number;
    /** The wallet as the business sees it: `wallet_available` (and `daily_credits`) in `wallet_currency`. */
    wallet_currency?: string;
    wallet_available?: number;
    daily_credits: number;
    integration_count: number;
    entity_count: number;
    recent_executions_7d: number;
    user_count: number;
    created_at?: string;
    /** The one health score's weak spots (Phase 15 T0-6). */
    health_reasons?: string[];
    at_risk?: boolean;
}

/** What a partner's tenants were billed — billed amounts, never cost (Phase 15 T0-6). */
export interface PartnerRevenue {
    currency: string;
    months: number;
    totals: {
        tenants: number;
        active_tenants: number;
        suspended_tenants: number;
        billed_this_month: number;
        billed_period: number;
    };
    monthly: { month: string; billed: number }[];
    tenants: { company_id: string; company_name: string; status: string; billed_this_month: number; billed_period: number }[];
}

export interface PartnerAnalytics {
    total_tenants: number;
    total_entities: number;
    total_executions: number;
    /** Raw cost: staff only (Phase 15 T9-3). */
    total_cost_usd?: number;
    /** What the tenants were billed, in the viewer's currency (`billed_currency`). */
    total_billed_usd?: number;
    billed_currency?: string;
    /** USD at today's rate; `wallet_balance_local` is the same in the viewer's `wallet_currency`. */
    total_wallet_balance: number;
    wallet_balance_local?: number;
    wallet_currency?: string;
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

    getRevenue: async (months = 6): Promise<PartnerRevenue> => {
        const res = await apiClient.get('/partner/analytics/revenue', { params: { months } });
        return res.data;
    },
};

/** A number's rent, charged in advance every 30 days (Phase 15 T7-1). */
export interface NumberRental {
    status: 'active' | 'held' | 'ended';
    started_at: string | null;
    next_charge_at: string | null;
    amount: string | null;
    currency: string | null;
    periods_charged: number;
}

/** What claiming a number costs, and how many the plan allows (T7-2). */
export interface NumberRent {
    currency: string;
    monthly: string | null;
    period_days: number;
    allowed: boolean;
    limit: number | null;
    held: number;
}

export const phonePoolService = {
    getRent: async (): Promise<NumberRent> => {
        const res = await apiClient.get<NumberRent>('/phone-numbers/rent');
        return res.data;
    },

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
        provider_monthly_cost_usd?: number;
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
