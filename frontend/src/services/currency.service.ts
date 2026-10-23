/**
 * services/currency.service.ts — currencies, FX rates, country profiles and the
 * currency settings, for staff (Phase 15 T2-4, T2-6). Every write is app_admin
 * only and audited.
 */
import { apiClient } from './api.client';

export interface CurrencyRow {
    code: string;
    name: string;
    symbol: string;
    minor_units: number;
    active: boolean;
    gateway: string | null;
    current_rate: { units_per_usd: number; effective_from: string | null } | null;
}

export interface FxRateRow {
    id: string;
    currency: string;
    units_per_usd: number;
    effective_from: string | null;
    created_by: string | null;
    reason: string | null;
    created_at: string | null;
}

export interface FxPreview {
    currency: string;
    current_units_per_usd: number;
    proposed_units_per_usd: number;
    change_pct: number;
    examples: { usd: number; current: number; proposed: number }[];
}

export interface CurrencySettings {
    display_currency: string;
    default_currency: string;
}

export interface CountryProfileRow {
    country_code: string;
    name: string;
    billing_currency: string;
    default_timezone: string;
    phone_country_code: string | null;
    tax_regime: 'IN_GST' | 'EXPORT' | 'NONE';
    calling_rules: Record<string, unknown>;
}

export const currencyService = {
    listCurrencies: () => apiClient.get<CurrencyRow[]>('/admin/currencies').then(r => r.data),
    listRates: (currency?: string) =>
        apiClient.get<FxRateRow[]>('/admin/fx-rates', { params: currency ? { currency } : {} }).then(r => r.data),
    addRate: (body: { currency: string; units_per_usd: number; effective_from?: string; reason: string }) =>
        apiClient.post<FxRateRow>('/admin/fx-rates', body).then(r => r.data),
    previewRate: (currency: string, unitsPerUsd: number) =>
        apiClient.get<FxPreview>('/admin/fx-rates/preview', { params: { currency, units_per_usd: unitsPerUsd } })
            .then(r => r.data),
    getSettings: () => apiClient.get<CurrencySettings>('/admin/currency-settings').then(r => r.data),
    putSettings: (body: Partial<CurrencySettings> & { reason?: string }) =>
        apiClient.put<CurrencySettings>('/admin/currency-settings', body).then(r => r.data),
    listCountryProfiles: () => apiClient.get<CountryProfileRow[]>('/admin/country-profiles').then(r => r.data),
    putCountryProfile: (code: string, body: Partial<Omit<CountryProfileRow, 'country_code' | 'name'>> & { reason?: string }) =>
        apiClient.put<CountryProfileRow>(`/admin/country-profiles/${code}`, body).then(r => r.data),
};
