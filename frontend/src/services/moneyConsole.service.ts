/**
 * services/moneyConsole.service.ts — the money consoles, for staff (Phase 15 T5-6, M15.2):
 * money settings, daily-credit policies and overrides, price items, wallets.
 * Every write is app_admin only and audited server-side. Amounts are exact strings.
 */
import { apiClient } from './api.client';
import type { LedgerEntry, WalletLot, WalletState } from './credits.service';

// ── Money settings (T5-1) ────────────────────────────────────────────────────

export interface MoneySetting {
    key: string;
    type: 'usd' | 'int' | 'bool' | 'choice' | 'usd_list' | 'decimal';
    group: string;
    unit: string | null;
    help: string;
    scopes: string[];
    choices: string[];
    minimum: string | null;
    maximum: string | null;
    nullable: boolean;
    default: unknown;
    value: unknown;
    source: 'company' | 'partner' | 'plan' | 'platform' | 'default';
}

export interface SettingChange {
    at: string | null;
    action: string;
    actor_user_id: string | null;
    scope: { scope?: string; scope_id?: string | null } | null;
    old_value: unknown;
    new_value: unknown;
    reason: string | null;
}

// ── Daily credits (T5-5) ─────────────────────────────────────────────────────

export interface DailyBand { from_day: number; to_day: number; amount_usd: string }

export interface DailyPolicy {
    id: string;
    name: string;
    audience: 'direct' | 'partner' | 'all_partners';
    partner_id: string | null;
    partner_name?: string | null;
    duration_days: number | null;
    active: boolean;
    effective_from: string | null;
    updated_at: string | null;
    bands: DailyBand[];
}

export type DailyPolicyBody = Omit<DailyPolicy, 'id' | 'effective_from' | 'updated_at' | 'partner_name'> & {
    reason?: string;
};

export interface DailyPreviewRow { from_day: number; to_day: number; amount_usd: string; amount: string; currency: string }

export interface DailyOverride {
    company_id: string;
    company_name: string | null;
    mode: 'policy' | 'custom' | 'none';
    amount_usd: string | null;
    duration_days: number | null;
    until: string | null;
    reason: string | null;
    updated_at: string | null;
}

export interface CompanyDailyCredits {
    company_id: string;
    company_name: string;
    currency: string;
    timezone: string;
    source: string;
    policy_name: string | null;
    day: number;
    duration_days: number | null;
    amount_usd: string;
    amount: string;
    local_date: string | null;
    next_midnight_utc: string | null;
}

// ── Price items (T5-3) ───────────────────────────────────────────────────────

export interface PriceItem {
    code: string;
    name: string;
    kind: 'recurring' | 'one_time';
    interval: 'month' | 'year' | null;
    amount_usd: string;
    currency_overrides: Record<string, string>;
    taxable: boolean;
    active: boolean;
    version: number;
    updated_at: string | null;
    prices: Record<string, { amount: string; overridden: boolean }>;
}

export interface PriceItemVersion {
    version: number;
    amount_usd: string;
    currency_overrides: Record<string, string>;
    active: boolean;
    reason: string | null;
    created_by: string | null;
    created_at: string | null;
}

// ── Wallets (T4-1, T2-7) ─────────────────────────────────────────────────────

export interface WalletRow {
    company_id: string;
    company_name: string;
    company_type: string;
    currency: string;
    state: WalletState;
    available: string;
    debt: string;
    in_debt_since: string | null;
}

export interface WalletDetail {
    company_id: string;
    company_name: string;
    wallet: {
        currency: string;
        state: WalletState;
        available: string;
        held: string;
        free: string;
        debt: string;
        tolerance: string;
        in_debt_since: string | null;
        over_tolerance_since: string | null;
        suspended_at: string | null;
        by_kind: Record<string, string>;
        lots: WalletLot[];
    };
    entries: (LedgerEntry & { lot_id: string | null; source_id: string | null; actor_id: string | null })[];
    problems: string[];
}

export const moneyConsole = {
    // settings
    listSettings: (companyId?: string) =>
        apiClient.get<{ settings: MoneySetting[] }>('/admin/billing-settings',
                                                    { params: companyId ? { company_id: companyId } : {} })
            .then(r => r.data.settings),
    settingHistory: (key: string) =>
        apiClient.get<SettingChange[]>(`/admin/billing-settings/${encodeURIComponent(key)}/history`).then(r => r.data),
    putSetting: (key: string, body: { value: unknown; scope: string; scope_id?: string | null; reason?: string }) =>
        apiClient.put(`/admin/billing-settings/${encodeURIComponent(key)}`, body).then(r => r.data),
    deleteSetting: (key: string, scope: string, scopeId?: string | null, reason?: string) =>
        apiClient.delete(`/admin/billing-settings/${encodeURIComponent(key)}`,
                         { params: { scope, scope_id: scopeId ?? undefined, reason } }).then(r => r.data),

    // daily credits
    listPolicies: () => apiClient.get<DailyPolicy[]>('/admin/daily-credits/policies').then(r => r.data),
    createPolicy: (body: DailyPolicyBody) =>
        apiClient.post<DailyPolicy>('/admin/daily-credits/policies', body).then(r => r.data),
    updatePolicy: (id: string, body: DailyPolicyBody) =>
        apiClient.put<DailyPolicy>(`/admin/daily-credits/policies/${id}`, body).then(r => r.data),
    deactivatePolicy: (id: string) => apiClient.delete(`/admin/daily-credits/policies/${id}`).then(r => r.data),
    previewPolicy: (body: { duration_days: number | null; bands: DailyBand[]; currency: string }) =>
        apiClient.post<{ currency: string; days: DailyPreviewRow[] }>('/admin/daily-credits/preview', body)
            .then(r => r.data.days),
    listOverrides: () => apiClient.get<DailyOverride[]>('/admin/daily-credits/overrides').then(r => r.data),
    putOverride: (companyId: string, body: { mode: string; amount_usd?: string | null; duration_days?: number | null;
                                             until?: string | null; reason: string }) =>
        apiClient.put<DailyOverride>(`/admin/daily-credits/overrides/${companyId}`, body).then(r => r.data),
    deleteOverride: (companyId: string) =>
        apiClient.delete(`/admin/daily-credits/overrides/${companyId}`).then(r => r.data),
    companyDailyCredits: (companyId: string) =>
        apiClient.get<CompanyDailyCredits>(`/admin/daily-credits/companies/${companyId}`).then(r => r.data),

    // price items
    listPriceItems: () => apiClient.get<PriceItem[]>('/admin/price-items').then(r => r.data),
    priceItemVersions: (code: string) =>
        apiClient.get<PriceItemVersion[]>(`/admin/price-items/${code}/versions`).then(r => r.data),
    putPriceItem: (code: string, body: { amount_usd: string; currency_overrides: Record<string, string | null>;
                                         active: boolean; reason?: string }) =>
        apiClient.put<PriceItem>(`/admin/price-items/${code}`, body).then(r => r.data),

    // wallets
    listWallets: (params: { state?: string; q?: string }) =>
        apiClient.get<{ counts: Record<WalletState, number>; wallets: WalletRow[] }>('/admin/wallets', { params })
            .then(r => r.data),
    getWallet: (companyId: string) => apiClient.get<WalletDetail>(`/admin/wallets/${companyId}`).then(r => r.data),
    adjustWallet: (companyId: string, body: { amount: string; reason: string; expires_in_days?: number }) =>
        apiClient.post(`/admin/wallets/${companyId}/adjust`, body).then(r => r.data),
    changeCurrency: (companyId: string, body: { currency: string; reason: string }) =>
        apiClient.post(`/admin/wallets/${companyId}/currency`, body).then(r => r.data),
};
