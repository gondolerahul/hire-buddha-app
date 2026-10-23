/**
 * services/geography.service.ts — countries and the currency each is billed in
 * (Phase 15 T2-3). `GET /countries` needs no sign-in: the sign-up form uses it.
 */
import { apiClient } from './api.client';

export interface CountryOption {
    code: string;
    name: string;
    /** The billing currency a company in this country gets (FX-1). */
    currency: string;
}

let cached: Promise<CountryOption[]> | null = null;

export const geographyService = {
    /** Every country, once per page load. */
    getCountries(): Promise<CountryOption[]> {
        cached ??= apiClient.get<CountryOption[]>('/countries').then(r => r.data).catch((error) => {
            cached = null;
            throw error;
        });
        return cached;
    },
};
