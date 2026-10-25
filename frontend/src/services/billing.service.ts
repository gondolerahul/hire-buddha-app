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

    // The costing and billing reports are the report library's R-A02 / R-A03 (Phase 15 T9-5, T3-8).
    // Plans replace subscription tiers: plansService and /admin/plans (Phase 15 T6-1).
};
