import { apiClient } from './api.client';

export interface BillingConfig {
    id: string;
    company_id: string | null;
    config_name: string;
    multiplier_factor: number;
    platform_fee_pct: number;
    sales_partner_fee_pct: number;
    discount_pct: number;
    default_daily_credits: number;
    base_cost_telephony?: number | null;
    base_cost_llm?: number | null;
    base_cost_image_gen?: number | null;
    is_active: boolean;
    updated_at: string;
}

export interface BillingEvent {
    id: string;
    company_id: string;
    period_month: string;
    grouping_type: string | null;
    grouping_value: string | null;
    base_cost: number;
    multiplied_cost: number;
    platform_fee_amount: number;
    partner_fee_amount: number;
    discount_amount: number;
    total_billing: number;
    telephony_charge: number;
    llm_charge: number;
    image_charge: number;
    video_charge: number;
    api_charge: number;
    telephony_in_minutes: number;
    telephony_out_minutes: number;
    image_gen_count: number;
    video_gen_count: number;
    other_ai_cost: number;
}

export interface ReportTotals {
    total_base_cost?: number;
    total_billing?: number;
    total_revenue?: number;
    total_telephony_in_minutes?: number;
    total_telephony_out_minutes?: number;
    total_image_gen?: number;
    total_video_gen?: number;
    total_other_ai_cost?: number;
    total_platform_fees?: number;
    total_partner_fees?: number;
    total_discounts?: number;
    total_telephony_charge?: number;
    total_llm_charge?: number;
    total_image_charge?: number;
    total_video_charge?: number;
    total_api_charge?: number;
}

export interface ReportResponse {
    events: BillingEvent[];
    totals: ReportTotals;
    count: number;
}

export interface BillingConfigUpdate {
    multiplier_factor?: number;
    platform_fee_pct?: number;
    sales_partner_fee_pct?: number;
    discount_pct?: number;
    default_daily_credits?: number;
    base_cost_telephony?: number;
    base_cost_llm?: number;
    base_cost_image_gen?: number;
    company_id?: string;
}

export interface SubscriptionTier {
    id: string;
    name: string;
    tier_level: number;
    monthly_fee: number;
    bonus_pct: number;
    is_active: boolean;
}

export interface SubscriptionTierCreate {
    name: string;
    tier_level: number;
    monthly_fee: number;
    bonus_pct: number;
    is_active?: boolean;
}

export interface SubscriptionTierUpdate {
    name?: string;
    monthly_fee?: number;
    bonus_pct?: number;
    is_active?: boolean;
}

export const billingService = {
    getConfig: async (): Promise<{ config: BillingConfig | null }> => {
        const { data } = await apiClient.get('/billing/config');
        return data;
    },

    updateConfig: async (payload: BillingConfigUpdate): Promise<{ config: BillingConfig }> => {
        const { data } = await apiClient.put('/billing/config', payload);
        return data;
    },

    getCostingReport: async (params?: {
        period_month?: string;
        grouping_type?: string;
    }): Promise<ReportResponse> => {
        const qp = new URLSearchParams();
        if (params?.period_month) qp.append('period_month', params.period_month);
        if (params?.grouping_type) qp.append('grouping_type', params.grouping_type);
        const { data } = await apiClient.get<ReportResponse>(
            `/reports/costing?${qp.toString()}`
        );
        return data;
    },

    getBillingReport: async (params?: {
        period_month?: string;
        grouping_type?: string;
    }): Promise<ReportResponse> => {
        const qp = new URLSearchParams();
        if (params?.period_month) qp.append('period_month', params.period_month);
        if (params?.grouping_type) qp.append('grouping_type', params.grouping_type);
        const { data } = await apiClient.get<ReportResponse>(
            `/reports/billing?${qp.toString()}`
        );
        return data;
    },

    // Subscription Tiers
    getSubscriptionTiers: async (): Promise<SubscriptionTier[]> => {
        const { data } = await apiClient.get<SubscriptionTier[]>('/credits/subscription-tiers');
        return data;
    },

    createSubscriptionTier: async (payload: SubscriptionTierCreate): Promise<{ id: string; message: string }> => {
        const { data } = await apiClient.post('/credits/subscription-tiers', payload);
        return data;
    },

    updateSubscriptionTier: async (tierId: string, payload: SubscriptionTierUpdate): Promise<{ id: string; message: string }> => {
        const { data } = await apiClient.put(`/credits/subscription-tiers/${tierId}`, payload);
        return data;
    },

    deleteSubscriptionTier: async (tierId: string): Promise<{ message: string }> => {
        const { data } = await apiClient.delete(`/credits/subscription-tiers/${tierId}`);
        return data;
    }
};
