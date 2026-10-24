/**
 * services/plans.service — plans, entitlements, invoices and payments (Phase 15 M15.3).
 *
 * Amounts are exact strings, in the currency named beside them; GST is added
 * on top of a net price (tech design §11: net + GST = what is charged).
 */
import { apiClient } from './api.client';

/** One feature or limit a plan includes; `limit` is null for no limit. */
export interface EntitlementValue {
    enabled: boolean;
    limit: number | null;
    /** Where it comes from: `override` (set for the company), `plan`, `default` or `platform`. */
    source?: string;
}

export interface FeatureSpec {
    key: string;
    group: string;
    label: string;
    kind: 'feature' | 'limit';
    default_limit?: number | null;
    limit_label?: string | null;
}

/** A plan as the company sees it: priced net in its currency, GST on top. */
export interface PlanOffer {
    id: string;
    code: string;
    name: string;
    tier_level: number;
    bonus_pct: string;
    active: boolean;
    sort: number;
    version: number;
    currency: string;
    monthly_fee: string;
    tax_rate: string;
    current: boolean;
    entitlements: Record<string, EntitlementValue>;
}

export interface PlansOnOffer {
    currency: string;
    current_plan_id: string | null;
    plans: PlanOffer[];
    features: FeatureSpec[];
}

export interface MyEntitlements {
    plan: { id: string; code: string; name: string; tier_level: number } | null;
    entitlements: Record<string, EntitlementValue>;
}

/** A plan as staff manage it. */
export interface AdminPlan {
    id: string;
    code: string;
    name: string;
    tier_level: number;
    monthly_fee_usd: string;
    bonus_pct: string;
    currency_overrides: Record<string, string | null>;
    active: boolean;
    sort: number;
    version: number;
    updated_at: string | null;
    companies: number;
    negative_tolerance_usd: string | null;
    prices: Record<string, string>;
}

export interface PlanVersionRow {
    version: number;
    name: string;
    monthly_fee_usd: string;
    bonus_pct: string;
    currency_overrides: Record<string, string>;
    active: boolean;
    reason: string | null;
    created_at: string | null;
}

export interface EntitlementChange {
    feature_key: string;
    enabled: boolean;
    limit_value: number | null;
}

export interface ImpactLine {
    feature_key: string;
    change: 'loses' | 'lower_limit';
    companies: number;
    text: string;
}

export interface PlanSubscription {
    id: string;
    plan_id: string | null;
    plan_tier: number;
    monthly_fee: number;
    bonus_pct: number;
    currency: string;
    amount: string;
    status: string;
    cancel_at_cycle_end: boolean;
    pending_plan_id: string | null;
    razorpay_subscription_id: string | null;
    next_billing_date: string | null;
}

export interface PlanCheckout {
    subscription_id: string;
    razorpay_subscription_id: string;
    key_id: string;
    plan_id: string;
    plan_tier: number;
    currency: string;
    net: string;
    tax: string;
    amount: string;
    bonus_credits_pct: number;
}

export interface Invoice {
    id: string;
    number: string;
    currency: string;
    net: string;
    cgst: string;
    sgst: string;
    igst: string;
    tax: string;
    total: string;
    tax_rate: string;
    regime: 'intra_state' | 'inter_state' | 'export';
    place_of_supply: string | null;
    issued_at: string | null;
    payment_id: string;
}

export interface CreditNote {
    id: string;
    number: string;
    invoice_id: string;
    invoice_number: string | null;
    currency: string;
    net: string;
    tax: string;
    total: string;
    reason: string | null;
    issued_at: string | null;
}

export interface BillingProfile {
    name: string;
    legal_name: string | null;
    gstin: string | null;
    billing_state: string | null;
    billing_address: Record<string, string>;
    country_code: string | null;
    billing_currency: string;
}

export interface AdminPayment {
    id: string;
    company_id: string;
    purpose: string;
    status: string;
    currency: string;
    gross: string;
    net: string;
    tax: string;
    refunded_gross: string;
    credits_awarded: string;
    invoice_id: string | null;
    invoice_number: string | null;
    gateway_payment_id: string | null;
    created_at: string | null;
}

export interface RefundResult {
    refund_id: string;
    gross: string;
    net: string;
    currency: string;
    credit_taken: string;
    debt_added: string;
    credit_note_id: string | null;
}

async function openPdf(path: string): Promise<void> {
    const { data } = await apiClient.get(path, { responseType: 'blob' });
    const url = URL.createObjectURL(data as Blob);
    window.open(url, '_blank', 'noopener');
    setTimeout(() => URL.revokeObjectURL(url), 60_000);
}

export const plansService = {
    // ── the company ──
    listPlans: async (): Promise<PlansOnOffer> => (await apiClient.get<PlansOnOffer>('/plans')).data,
    myEntitlements: async (): Promise<MyEntitlements> => (await apiClient.get<MyEntitlements>('/me/entitlements')).data,
    getSubscription: async (): Promise<{ subscription: PlanSubscription | null; account_model: string }> =>
        (await apiClient.get('/credits/subscriptions')).data,
    subscribe: async (planId: string): Promise<PlanCheckout> =>
        (await apiClient.post<PlanCheckout>('/credits/subscriptions', { plan_id: planId })).data,
    verifySubscription: async (payload: {
        razorpay_payment_id: string; razorpay_subscription_id: string; razorpay_signature: string;
    }): Promise<{ message: string; credits_granted: boolean }> =>
        (await apiClient.post('/credits/subscriptions/verify', payload)).data,
    changePlan: async (planId: string): Promise<{ change: 'upgrade' | 'downgrade'; effective: string; plan_id: string }> =>
        (await apiClient.post('/credits/subscriptions/change', { plan_id: planId })).data,
    cancel: async (subscriptionId: string, immediately = false): Promise<{ message: string; ends?: string | null }> =>
        (await apiClient.delete(`/credits/subscriptions/${subscriptionId}`, { params: { immediately } })).data,

    listInvoices: async (companyId?: string): Promise<{ invoices: Invoice[]; credit_notes: CreditNote[] }> =>
        (await apiClient.get('/billing/invoices', { params: companyId ? { company_id: companyId } : {} })).data,
    openInvoicePdf: (id: string) => openPdf(`/billing/invoices/${id}/pdf`),
    openCreditNotePdf: (id: string) => openPdf(`/billing/credit-notes/${id}/pdf`),
    getProfile: async (): Promise<BillingProfile> => (await apiClient.get<BillingProfile>('/billing/profile')).data,
    putProfile: async (body: Partial<Pick<BillingProfile, 'legal_name' | 'gstin' | 'billing_state' | 'billing_address'>>):
        Promise<BillingProfile> => (await apiClient.put<BillingProfile>('/billing/profile', body)).data,

    // ── staff ──
    adminPlans: async (): Promise<AdminPlan[]> => (await apiClient.get<AdminPlan[]>('/admin/plans')).data,
    createPlan: async (body: Record<string, unknown>): Promise<AdminPlan> => (await apiClient.post('/admin/plans', body)).data,
    updatePlan: async (id: string, body: Record<string, unknown>): Promise<AdminPlan> =>
        (await apiClient.put(`/admin/plans/${id}`, body)).data,
    archivePlan: async (id: string, reason?: string): Promise<AdminPlan> =>
        (await apiClient.post(`/admin/plans/${id}/archive`, null, { params: reason ? { reason } : {} })).data,
    planVersions: async (id: string): Promise<PlanVersionRow[]> => (await apiClient.get(`/admin/plans/${id}/versions`)).data,
    features: async (): Promise<FeatureSpec[]> => (await apiClient.get<FeatureSpec[]>('/admin/features')).data,
    matrix: async (): Promise<Record<string, Record<string, EntitlementValue>>> =>
        (await apiClient.get('/admin/plans/entitlements')).data,
    impact: async (planId: string, entitlements: EntitlementChange[]): Promise<ImpactLine[]> =>
        (await apiClient.post(`/admin/plans/${planId}/entitlements/impact`, { entitlements })).data.impact,
    putEntitlements: async (planId: string, entitlements: EntitlementChange[], reason?: string):
        Promise<{ entitlements: Record<string, EntitlementValue>; impact: ImpactLine[] }> =>
        (await apiClient.put(`/admin/plans/${planId}/entitlements`, { entitlements, reason })).data,
    companyEntitlements: async (companyId: string): Promise<{
        entitlements: Record<string, EntitlementValue>;
        overrides: Array<{ feature_key: string; enabled: boolean; limit_value: number | null; until: string | null; reason: string | null }>;
    }> => (await apiClient.get(`/admin/companies/${companyId}/entitlements`)).data,
    putCompanyEntitlement: async (companyId: string, key: string,
                                  body: { enabled: boolean; limit_value: number | null; until?: string | null; reason: string }) =>
        (await apiClient.put(`/admin/companies/${companyId}/entitlements/${key}`, body)).data,
    deleteCompanyEntitlement: async (companyId: string, key: string, reason?: string) =>
        (await apiClient.delete(`/admin/companies/${companyId}/entitlements/${key}`, { params: reason ? { reason } : {} })).data,

    adminPayments: async (params: { company_id?: string; status?: string; limit?: number } = {}): Promise<AdminPayment[]> =>
        (await apiClient.get<AdminPayment[]>('/admin/payments', { params })).data,
    refund: async (paymentId: string, body: { net?: string; reason: string }): Promise<RefundResult> =>
        (await apiClient.post<RefundResult>(`/admin/payments/${paymentId}/refund`, body)).data,
};

/** Net + GST, for display (the API computes what is charged; this mirrors its rounding to the paisa). */
export function withGst(net: string | number, ratePct: string | number): { net: number; tax: number; gross: number } {
    const n = Number(net) || 0;
    const tax = Math.round(n * (Number(ratePct) || 0)) / 100;
    return { net: n, tax, gross: Math.round((n + tax) * 100) / 100 };
}
