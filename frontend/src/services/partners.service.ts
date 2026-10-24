/**
 * services/partners.service — the partner programme (Phase 15 WS15-8, tech design §11; 07 §4.3, §5.8–5.10).
 *
 * Partner amounts are in the partner's currency (its ledger); customers'
 * amounts are billed amounts in the currency named beside them.
 */
import { apiClient } from './api.client';

export type PartnerType = 'SILVER' | 'GOLD';
export type PartnerStatus = 'approved' | 'active' | 'renewal_due' | 'lapsed' | 'suspended' | 'terminated';
export type LedgerStatus = 'accrued' | 'held' | 'payable' | 'paid' | 'reversed';

export interface PartnerMe {
    company_id: string;
    partner_type: PartnerType;
    type_name: string;
    can_create_tenants: boolean;
    tenant_data_access: 'none' | 'grants';
    status: PartnerStatus;
    status_reason: string | null;
    legal_name: string | null;
    country_code: string | null;
    currency: string;
    pan: string | null;
    gstin: string | null;
    kyc_status: 'pending' | 'verified' | 'rejected';
    bank_last4: string | null;
    bank_verified: boolean;
    recruiter: string | null;
    depth: number;
    activated_at: string | null;
    probation_until: string | null;
    fee: { required: boolean; amount: string | null; currency: string; paid_until: string | null };
    agreement: { id: string; version: number; terms: AgreementTerms; signed_at: string | null; effective_from: string | null } | null;
}

export interface CommissionRuleRow {
    id: string;
    partner_type: PartnerType;
    revenue_kind: string;
    level: number;
    rate_pct: string;
    cap_pct: string | null;
    months: number | null;
    active: boolean;
    version: number;
    reason: string | null;
    created_at: string | null;
}

export interface FeeRuleRow {
    id: string;
    partner_type: PartnerType;
    fee_kind: 'setup' | 'customisation';
    min_usd: string;
    max_usd: string;
    split: Record<string, number>;
    active: boolean;
    version: number;
    reason: string | null;
}

export interface AgreementTerms {
    partner_type: PartnerType;
    commission_rules: CommissionRuleRow[];
    fee_rules: FeeRuleRow[];
    policy: Record<string, string>;
}

export interface PartnerOverview {
    partner_type: PartnerType;
    status: PartnerStatus;
    currency: string;
    tenants: number;
    referred_customers: number;
    customers_billed_mtd: string;
    earnings_mtd: string | null;
    earnings_by_status: Record<string, string> | null;
    next_statement: Statement | null;
    fee: PartnerMe['fee'];
    leads: Record<string, number>;
    open_charges: number;
}

export interface Customer {
    tenant_id: string;
    name: string | null;
    relationship: 'referred' | 'resold';
    status: string | null;
    since: string | null;
    plan: string | null;
    billed_mtd: string;
    lifetime_commission: string | null;
}

export interface Lead {
    id: string;
    partner_id: string;
    partner: string | null;
    company_name: string;
    contact_name: string | null;
    email: string | null;
    phone: string | null;
    country_code: string | null;
    notes: string | null;
    status: 'registered' | 'accepted' | 'in_progress' | 'converted' | 'lost' | 'expired';
    exclusive_until: string | null;
    converted_company_id: string | null;
    lost_reason: string | null;
    created_at: string | null;
}

export interface Charge {
    id: string;
    tenant_id: string;
    tenant: string | null;
    partner_id: string | null;
    partner: string | null;
    fee_kind: 'setup' | 'customisation';
    description: string | null;
    amount: string;
    currency: string;
    status: 'draft' | 'sent' | 'paid' | 'cancelled' | 'refunded';
    invoice_id: string | null;
    created_at: string | null;
    paid_at: string | null;
}

export interface ChargePreview {
    currency: string;
    min: string | null;
    max: string | null;
    split: Record<string, number> | null;
    rule_version: number | null;
}

export interface NetworkPartner {
    partner_id: string;
    name: string | null;
    type: PartnerType;
    status: PartnerStatus;
    level: number;
    joined: string | null;
    override_earnings: string | null;
}

export interface LedgerEntry {
    id: string;
    kind: 'commission' | 'override' | 'fee_share' | 'clawback' | 'adjustment' | 'payout' | 'tds';
    amount: string;
    currency: string;
    revenue_kind: string | null;
    base_amount: string | null;
    base_currency: string | null;
    rate_pct: string | null;
    tenant_id: string | null;
    tenant: string | null;
    level: number;
    status: LedgerStatus;
    hold_reason: string | null;
    reason: string | null;
    payable_after: string | null;
    statement_id: string | null;
    created_at: string | null;
}

export interface Statement {
    id: string;
    partner_id: string;
    partner?: string | null;
    period: string;
    currency: string;
    gross: string;
    tds: string;
    tds_pct: string;
    net: string;
    status: 'draft' | 'approved' | 'paid' | 'disputed';
    gst_invoice_ref: string | null;
    dispute_reason: string | null;
    payout_ref: string | null;
    approved_at: string | null;
    paid_at: string | null;
    created_at: string | null;
    entries?: LedgerEntry[];
}

export interface Grant {
    id: string;
    partner_id: string;
    partner: string | null;
    tenant_id: string;
    tenant: string | null;
    scopes: string[];
    status: 'requested' | 'active' | 'revoked' | 'expired';
    reason: string | null;
    expires_at: string | null;
    created_at: string | null;
    revoked_at: string | null;
}

export interface Order {
    order_id: string;
    amount: string;
    net: string;
    tax: string;
    tax_rate: string;
    currency: string;
    key_id: string;
    description: string;
}

export interface AdminPartner {
    partner_id: string;
    name: string | null;
    partner_type: PartnerType;
    status: PartnerStatus;
    status_reason: string | null;
    legal_name: string | null;
    currency: string;
    pan: string | null;
    gstin: string | null;
    kyc_status: string;
    bank_last4: string | null;
    bank_verified: boolean;
    depth: number;
    recruiter_partner_id: string | null;
    recruiter: string | null;
    activated_at: string | null;
    fee_paid_until: string | null;
    probation_until: string | null;
    tenants?: number;
    sourced_billed_mtd_usd?: string;
}

export interface Application {
    id: string;
    status: 'invited' | 'applied' | 'under_review' | 'approved' | 'rejected';
    recruiter: string | null;
    requested_type: PartnerType | null;
    approved_type: PartnerType | null;
    company_name: string | null;
    contact_name: string | null;
    email: string | null;
    phone: string | null;
    country_code: string | null;
    details: Record<string, unknown>;
    checklist: Record<string, boolean>;
    review_notes: string | null;
    company_id: string | null;
    created_at: string | null;
}

export interface Assignment {
    id: string;
    tenant_id: string;
    tenant: string | null;
    partner_id: string;
    partner: string | null;
    relationship: 'referred' | 'resold';
    since: string | null;
    until: string | null;
    commission_until: string | null;
    source: string;
    reason: string | null;
}

export interface Partner360 {
    profile: AdminPartner;
    fee: PartnerMe['fee'];
    agreements: Array<{ id: string; version: number; terms: AgreementTerms; signed_at: string | null; effective_from: string | null; effective_to: string | null }>;
    assignments: Assignment[];
    network: AdminPartner[];
    grants: Grant[];
    statements: Statement[];
    ledger_totals: Record<string, string>;
}

export interface SimulationShare { level: number; partner: string | null; rate_pct: string; amount: string; status: string; why: string | null }
export interface Simulation {
    base: string;
    platform: string;
    pool_cap: string | null;
    capped: boolean;
    shares: SimulationShare[];
    margin_guard?: { margin: string; allowed: string; commissions: string; held: string };
}

const get = async <T,>(path: string, params?: Record<string, unknown>): Promise<T> =>
    (await apiClient.get<T>(path, params ? { params } : undefined)).data;
const post = async <T,>(path: string, body?: unknown): Promise<T> => (await apiClient.post<T>(path, body)).data;
const put = async <T,>(path: string, body?: unknown): Promise<T> => (await apiClient.put<T>(path, body)).data;

async function openPdf(path: string): Promise<void> {
    const { data } = await apiClient.get(path, { responseType: 'blob' });
    const url = URL.createObjectURL(data as Blob);
    window.open(url, '_blank', 'noopener');
    setTimeout(() => URL.revokeObjectURL(url), 60_000);
}

export interface PaymentProof { razorpay_order_id: string; razorpay_payment_id: string; razorpay_signature: string }

export const partnerPortal = {
    me: () => get<PartnerMe>('/partner/me'),
    putKyc: (body: { legal_name?: string; pan?: string; gstin?: string; bank?: { account_name: string; account_number: string; ifsc: string } }) =>
        put<{ kyc_status: string; bank_last4: string | null }>('/partner/me/kyc', body),
    sign: () => post<{ version: number; signed_at: string; status: PartnerStatus }>('/partner/me/agreement/sign'),
    feeOrder: () => post<Order>('/partner/me/fee/order'),
    feeVerify: (proof: PaymentProof) => post<{ recorded: boolean; status: PartnerStatus; fee_paid_until: string | null }>('/partner/me/fee/verify', proof),
    overview: () => get<PartnerOverview>('/partner/overview'),
    customers: () => get<{ currency: string; customers: Customer[] }>('/partner/customers'),
    leads: () => get<Lead[]>('/partner/leads'),
    registerLead: (body: Partial<Lead>) => post<Lead>('/partner/leads', body),
    convertLead: (id: string, body: { admin_email?: string }) => post<{ tenant_id: string }>(`/partner/leads/${id}/convert`, body),
    charges: () => get<Charge[]>('/partner/charges'),
    chargePreview: (tenantId: string, feeKind: string) =>
        get<ChargePreview>('/partner/charges/preview', { tenant_id: tenantId, fee_kind: feeKind }),
    raiseCharge: (body: { tenant_id: string; fee_kind: string; amount: string; description?: string }) =>
        post<Charge>('/partner/charges', body),
    cancelCharge: (id: string) => post<Charge>(`/partner/charges/${id}/cancel`),
    network: () => get<{ partners: NetworkPartner[] }>('/partner/network'),
    invites: () => get<Array<{ id: string; email: string | null; status: string; company_name: string | null; token: string | null; created_at: string | null }>>('/partner/network/invites'),
    invite: (email?: string) => post<{ id: string; token: string; link: string }>('/partner/network/invites', { email }),
    earnings: (params: Record<string, unknown> = {}) =>
        get<{ currency: string; entries: LedgerEntry[]; totals: Record<string, string> }>('/partner/earnings', params),
    statements: () => get<Statement[]>('/partner/statements'),
    statement: (id: string) => get<Statement>(`/partner/statements/${id}`),
    statementPdf: (id: string) => openPdf(`/partner/statements/${id}/pdf`),
    dispute: (id: string, reason: string) => post<Statement>(`/partner/statements/${id}/dispute`, { reason }),
    uploadGstInvoice: async (id: string, file: File): Promise<Statement> => {
        const form = new FormData();
        form.append('file', file);
        return (await apiClient.post<Statement>(`/partner/statements/${id}/gst-invoice`, form)).data;
    },
    grants: () => get<Grant[]>('/partner/access'),
    askAccess: (body: { tenant_id: string; scopes: string[]; reason: string; days?: number }) => post<Grant>('/partner/access', body),
    guide: () => get<AgreementTerms>('/partner/guide'),
};

export const partnerBusiness = {
    charges: () => get<Charge[]>('/charges'),
    chargeOrder: (id: string) => post<Order>(`/charges/${id}/order`),
    chargeVerify: (id: string, proof: PaymentProof) =>
        post<{ recorded: boolean; charge: Charge; invoice_id: string | null }>(`/charges/${id}/verify`, proof),
    access: () => get<{ partner: { id: string; name: string | null; type: PartnerType; relationship: string; since: string | null } | null;
        grants: Grant[]; events: Array<{ at: string | null; user: string | null; partner: string | null; method: string; path: string }> }>('/settings/partner-access'),
    approve: (grantId: string, days?: number) => post<Grant>(`/settings/partner-access/${grantId}/approve`, { days }),
    revoke: (grantId: string) => post<Grant>(`/settings/partner-access/${grantId}/revoke`),
    invite: (token: string) => get<{ recruiter: string | null; email: string | null }>(`/partners/invites/${token}`),
    apply: (body: Record<string, unknown>) => post<{ id: string; status: string; message: string }>('/partners/apply', body),
};

export const partnerAdmin = {
    list: () => get<AdminPartner[]>('/admin/partners'),
    treeCheck: () => get<{ violations: Array<Record<string, string>>; count: number }>('/admin/partners/tree-check'),
    get: (id: string) => get<Partner360>(`/admin/partners/${id}`),
    setKyc: (id: string, body: { status: string; bank_verified?: boolean; reason?: string }) => put<AdminPartner>(`/admin/partners/${id}/kyc`, body),
    setStatus: (id: string, body: { status: string; reason: string }) => post<Record<string, unknown>>(`/admin/partners/${id}/status`, body),
    newAgreement: (id: string) => post<{ version: number }>(`/admin/partners/${id}/agreement`),
    adjust: (id: string, body: { amount: string; reason: string }) => post<LedgerEntry>(`/admin/partners/${id}/adjustment`, body),
    applications: (status?: string) => get<{ checklist: string[]; applications: Application[] }>('/admin/partners/applications', status ? { status } : undefined),
    review: (id: string, body: { checklist?: Record<string, boolean>; notes?: string }) => post<Application>(`/admin/partners/applications/${id}/review`, body),
    approve: (id: string, body: { partner_type: PartnerType; notes?: string }) => post<{ company_id: string }>(`/admin/partners/applications/${id}/approve`, body),
    reject: (id: string, notes: string) => post<Application>(`/admin/partners/applications/${id}/reject`, { notes }),
    rules: () => get<{ commission_rules: CommissionRuleRow[]; fee_rules: FeeRuleRow[]; policy: Record<string, string>;
        types: Array<{ code: PartnerType; name: string; can_create_tenants: boolean; tenant_data_access: string; annual_fee_item: string | null }> }>('/admin/partners/rules'),
    putCommission: (body: Record<string, unknown>) => put<CommissionRuleRow>('/admin/partners/rules/commission', body),
    putFee: (body: Record<string, unknown>) => put<FeeRuleRow>('/admin/partners/rules/fee', body),
    simulate: (body: Record<string, unknown>) => post<Simulation>('/admin/partners/simulate', body),
    leads: (status?: string) => get<Lead[]>('/admin/partners/leads', status ? { status } : undefined),
    moveLead: (id: string, body: { status?: string; owner_id?: string; reason?: string }) =>
        (apiClient.patch<Lead>(`/admin/partners/leads/${id}`, body)).then(r => r.data),
    convertLead: (id: string, body: { admin_email?: string }) => post<{ tenant_id: string }>(`/admin/partners/leads/${id}/convert`, body),
    assignments: (params: { tenant_id?: string; partner_id?: string }) => get<Assignment[]>('/admin/partners/assignments', params),
    reassign: (body: Record<string, unknown>) => post<{ history: Assignment[] }>('/admin/partners/assignments/reassign', body),
    charges: () => get<Charge[]>('/admin/partners/charges'),
    raiseCharge: (body: { tenant_id: string; fee_kind: string; amount: string; description?: string }) => post<Charge>('/admin/partners/charges', body),
    statements: (status?: string) => get<Statement[]>('/admin/partners/statements', status ? { status } : undefined),
    statement: (id: string) => get<Statement>(`/admin/partners/statements/${id}`),
    build: (period: string) => post<Record<string, unknown>>('/admin/partners/statements/build', { period }),
    approveStatement: (id: string) => post<Statement>(`/admin/partners/statements/${id}/approve`),
    paid: (id: string, payoutRef: string) => post<Statement>(`/admin/partners/statements/${id}/paid`, { payout_ref: payoutRef }),
    reopen: (id: string) => post<Statement>(`/admin/partners/statements/${id}/reopen`),
    exportCsv: async (): Promise<void> => {
        const { data } = await apiClient.get('/admin/partners/statements/export.csv', { responseType: 'blob' });
        const url = URL.createObjectURL(data as Blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'partner-payouts.csv';
        a.click();
        setTimeout(() => URL.revokeObjectURL(url), 60_000);
    },
    statementPdf: (id: string) => openPdf(`/admin/partners/statements/${id}/pdf`),
};

/** Razorpay Checkout for an order (a partnership fee, a setup fee); resolves with the payment proof. */
export async function payOrder(order: Order): Promise<PaymentProof> {
    const { loadRazorpay } = await import('@/utils/razorpay');
    const Razorpay = await loadRazorpay();
    return new Promise((resolve, reject) => {
        const rzp = new Razorpay({
            key: order.key_id,
            currency: order.currency,
            name: 'HireBuddha',
            description: order.description,
            order_id: order.order_id,
            handler: (response: any) => resolve({
                razorpay_order_id: order.order_id,
                razorpay_payment_id: response.razorpay_payment_id,
                razorpay_signature: response.razorpay_signature,
            }),
            modal: { ondismiss: () => reject(new Error('Payment cancelled')) },
            theme: { color: '#c9956c' },
        });
        rzp.open();
    });
}

export const LEDGER_STATUS_LABEL: Record<string, string> = {
    accrued: 'Accrued (in holdback)', held: 'Held', payable: 'Payable', paid: 'Paid', reversed: 'Reversed',
};

export const REVENUE_LABEL: Record<string, string> = {
    usage_topup: 'Top-up', subscription: 'Subscription', setup_fee: 'Setup fee', customisation_fee: 'Customisation fee',
};
