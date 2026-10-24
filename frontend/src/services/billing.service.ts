import { apiClient } from './api.client';

/** The price formula in effect, TB = c·mf·(1 + pf − d) (Phase 15 T3-2). Daily credits are policies (T5-5). */
export interface BillingConfig {
    company_id: string | null;
    formula_id: string | null;
    formula_scope: string;
    multiplier_factor: number;
    platform_fee_pct: number;
    discount_pct: number;
}

/** One version of a formula (append-only). */
export interface FormulaVersion {
    id: string;
    multiplier_factor: number;
    platform_fee_pct: number;
    discount_pct: number;
    active: boolean;
    effective_from: string | null;
    reason: string | null;
    created_by: string | null;
}

export interface BillingEvent {
    id: string;
    company_id: string;
    company_name: string | null;
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
    /** Billed seconds, exact (Phase 15 T1-4). */
    telephony_in_seconds: number;
    telephony_out_seconds: number;
    image_gen_count: number;
    video_gen_count: number;
    other_ai_cost: number;
}

export interface ReportTotals {
    total_base_cost?: number;
    total_billing?: number;
    total_revenue?: number;
    total_telephony_in_seconds?: number;
    total_telephony_out_seconds?: number;
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
    discount_pct?: number;
    company_id?: string;
    /** Kept with the formula version. */
    reason?: string;
}

export const billingService = {
    getConfig: async (): Promise<{ config: BillingConfig | null; history?: FormulaVersion[] }> => {
        const { data } = await apiClient.get('/billing/config');
        return data;
    },

    updateConfig: async (payload: BillingConfigUpdate): Promise<{ config: BillingConfig; history?: FormulaVersion[] }> => {
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
    // Plans replace subscription tiers: plansService and /admin/plans (Phase 15 T6-1).
};
