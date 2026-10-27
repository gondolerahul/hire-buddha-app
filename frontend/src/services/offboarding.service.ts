/**
 * services/offboarding — closing a business and erasing its data; deleting a test business
 * at once (docs/phase15/13_offboarding_and_erasure.md).
 */
import { apiClient } from './api.client';

export interface OffboardingStep {
    step: string;
    outcome: 'started' | 'succeeded' | 'skipped' | 'failed';
    attempt: number;
    error: string | null;
    detail: unknown;
    at: string | null;
}

export interface Offboarding {
    id: string;
    company_id: string;
    company_ref: string;
    company_name: string | null;
    mode: 'erasure' | 'immediate';
    state: 'requested' | 'cancelled' | 'exporting' | 'erasing' | 'erased' | 'failed';
    reason: string | null;
    requested_by_role: string | null;
    confirmed: boolean;
    confirmed_at: string | null;
    grace_until: string | null;
    export_requested: boolean;
    export_ready: boolean;
    export_expires_at: string | null;
    started_at: string | null;
    finished_at: string | null;
    last_step: string | null;
    error: string | null;
    certificate: Record<string, unknown> | null;
    created_at: string | null;
    steps?: OffboardingStep[];
}

export interface ImmediateCheck {
    company_id: string;
    name: string;
    allowed: boolean;
    refused: string[];
    workspace: { tenant_key: string | null; database: string | null; storage: string[]; git_owners: string[] };
    rows: Record<string, number>;
    test_tenants: Array<{ id: string; name: string }>;
}

export interface CompanyOffboardingView {
    offboarding: Offboarding | null;
    is_test: boolean | null;
    immediate?: ImmediateCheck;
}

export interface PersonMatch { table: string; id: string; action: 'delete' | 'mask' }

export const offboardingService = {
    // The business itself (its admin).
    mine: async () => (await apiClient.get<{ offboarding: Offboarding | null; remaining_credit: { available: string; currency: string };
        grace_days: number }>('/settings/offboarding')).data,
    request: async (body: { reason: string; export: boolean }) =>
        (await apiClient.post<Offboarding>('/settings/offboarding', body)).data,
    confirm: async () => (await apiClient.post<Offboarding>('/settings/offboarding/confirm')).data,
    cancel: async () => (await apiClient.delete<Offboarding>('/settings/offboarding')).data,
    exportLink: async () => (await apiClient.get<{ url?: string }>('/settings/offboarding/export')).data,
    findPerson: async (query: string) =>
        (await apiClient.post<{ matches: PersonMatch[]; count: number }>('/settings/data-requests/search', { query })).data,
    erasePerson: async (query: string) =>
        (await apiClient.post<{ deleted: Record<string, number>; masked: Record<string, number>; files_deleted: number }>(
            '/settings/data-requests/erase', { query })).data,

    // Staff.
    ofCompany: async (companyId: string, includeTestTenants = false) =>
        (await apiClient.get<CompanyOffboardingView>(`/admin/companies/${companyId}/offboarding`,
            { params: { include_test_tenants: includeTestTenants } })).data,
    requestFor: async (companyId: string, body: { reason: string; export: boolean }) =>
        (await apiClient.post<Offboarding>(`/admin/companies/${companyId}/offboarding`, body)).data,
    cancelFor: async (companyId: string) => (await apiClient.delete<Offboarding>(`/admin/companies/${companyId}/offboarding`)).data,
    bringForward: async (offboardingId: string) =>
        (await apiClient.post<Offboarding>(`/admin/offboarding/${offboardingId}/bring-forward`)).data,
    retry: async (offboardingId: string) => (await apiClient.post<Offboarding>(`/admin/offboarding/${offboardingId}/retry`)).data,
    one: async (offboardingId: string) => (await apiClient.get<Offboarding>(`/admin/offboarding/${offboardingId}`)).data,
    setTest: async (companyId: string, isTest: boolean, reason: string) =>
        (await apiClient.put<{ is_test: boolean }>(`/admin/companies/${companyId}/test`, { is_test: isTest, reason })).data,
    deleteNow: async (companyId: string, body: { confirm_name: string; reason: string; include_test_tenants: boolean }) =>
        (await apiClient.delete<{ offboardings: Offboarding[] }>(`/admin/companies/${companyId}`,
            { params: { mode: 'immediate' }, data: body })).data,
    certificateUrl: (offboardingId: string) => `/admin/offboarding/${offboardingId}/certificate.pdf`,
};
