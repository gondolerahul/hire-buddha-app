/**
 * queries/hooks.ts — the reads pages share, as cached queries (FE-21).
 *
 * Two components asking for the same key make one request between them, and
 * a page that remounts within the fresh window reads the cache.
 */
import { useQuery } from '@tanstack/react-query';

import { apiClient } from '@/services/api.client';
import { authService } from '@/services/auth.service';
import { companyService } from '@/services/company.service';
import { fetchAllPages } from '@/services/pagination';
import { phonePoolService } from '@/services/platform.service';
import { plansService } from '@/services/plans.service';
import { toolService } from '@/services/tool.service';
import { userService } from '@/services/user.service';
import type { HierarchicalEntity } from '@/types';

import { queryKeys } from './keys';

/** Every entity matching `params`, all pages (API-16). */
export function useEntityList<T = HierarchicalEntity>(params: Record<string, unknown> = {}, enabled = true) {
    return useQuery({
        queryKey: queryKeys.entities.list(params),
        queryFn: () => fetchAllPages<T>('/ai/entities', params),
        enabled,
    });
}

/** The one tool list (API-19), shared by the builder and the registry page. */
export function useToolRegistry() {
    return useQuery({ queryKey: queryKeys.tools.registry, queryFn: toolService.listTools });
}

/** The company's plan and what it includes (Phase 15 T6-2); cached for five minutes. */
export function useEntitlements(enabled = true) {
    return useQuery({
        queryKey: queryKeys.entitlements,
        queryFn: () => plansService.myEntitlements(),
        staleTime: 5 * 60_000,
        enabled,
    });
}

export function usePhoneNumbers<T = unknown>(status: string, provider: string) {
    return useQuery({
        queryKey: queryKeys.phoneNumbers.list(status, provider),
        queryFn: async (): Promise<T[]> => {
            const data = await phonePoolService.listNumbers(status || undefined, provider || undefined);
            return data.phone_numbers || data || [];
        },
    });
}

export interface CustomerCompany {
    id: string;
    name: string;
    type: string;
}

/** Tenants, and partners for app_admin: the companies a number can be assigned for. */
export function useCustomerCompanies(isAdmin: boolean) {
    return useQuery({
        queryKey: queryKeys.companies.customers(isAdmin),
        queryFn: async (): Promise<CustomerCompany[]> => {
            const results: CustomerCompany[] = [];
            // Either list may be refused on its own.
            const [tenantRes, partnerRes] = await Promise.allSettled([
                apiClient.get('/companies/tenants'),
                isAdmin ? apiClient.get('/companies/partners') : Promise.reject(new Error('not admin')),
            ]);
            const rows = (res: PromiseSettledResult<{ data: any }>): any[] => {
                if (res.status !== 'fulfilled') return [];
                const data = res.value.data;
                return Array.isArray(data) ? data : data.data || [];
            };
            results.push(...rows(tenantRes).map((c: any) => ({ id: c.id, name: c.name, type: 'TENANT' })));
            results.push(...rows(partnerRes).map((c: any) => ({ id: c.id, name: c.name, type: 'PARTNER' })));
            return results;
        },
    });
}

export function useCompanyList<T = unknown>(enabled = true) {
    return useQuery({
        queryKey: queryKeys.companies.list,
        queryFn: async (): Promise<T[]> => {
            const { data } = await apiClient.get('/companies');
            return Array.isArray(data) ? data : [];
        },
        enabled,
    });
}

export function usePartners(enabled = true) {
    return useQuery({ queryKey: queryKeys.companies.partners, queryFn: companyService.getPartners, enabled });
}

export function useTenants(enabled = true) {
    return useQuery({ queryKey: queryKeys.companies.tenants, queryFn: companyService.getTenants, enabled });
}

export function useUserList(enabled = true) {
    return useQuery({ queryKey: queryKeys.users.list, queryFn: userService.getUsers, enabled });
}

export function useCurrentUser() {
    return useQuery({ queryKey: queryKeys.users.me, queryFn: () => authService.getCurrentUser() });
}

/**
 * One report, keyed by its name and parameters. A failed report reads as
 * `null`, as the pages expected.
 */
export function useReport<T>(name: string, fetcher: () => Promise<T>, ...params: unknown[]) {
    return useQuery({
        queryKey: queryKeys.reports.one(name, ...params),
        queryFn: async (): Promise<T | null> => {
            try {
                return await fetcher();
            } catch {
                return null;
            }
        },
    });
}
