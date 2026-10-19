/**
 * services/tenancy.service.ts — the business's own database (Phase 14 WS2/WS8 8.5, 8.6).
 *
 * `workspace` says whether the caller's workspace is ready or which setup steps
 * are left (the "setting up your workspace" screen). Platform staff see every
 * tenant, its server, schema version and health, and retry a failed setup.
 */
import { apiClient } from './api.client';

export interface WorkspaceStatus {
    company_id: string;
    mode: 'single' | 'split';
    status: string;
    ready: boolean;
    steps: { step: string; outcome: string }[];
}

export interface TenantHealth {
    company_id: string;
    reachable: boolean | null;
    schema: 'current' | 'behind' | 'unknown';
    latency_ms: number | null;
    error: string | null;
}

export interface TenantRow {
    company_id: string;
    tenant_key: string;
    slug: string;
    status: string;
    automation_state: string;
    timezone: string;
    database: string;
    server: string | null;
    platform_schema_version: string | null;
    created_at: string | null;
    health?: TenantHealth | null;
}

export interface TenantDetail {
    company_id: string;
    tenant_key?: string;
    slug?: string;
    status: string;
    ready: boolean;
    platform_schema_version?: string | null;
    steps: { step: string; outcome: string; attempt: number; error: string | null; at: string | null }[];
    health?: TenantHealth | null;
}

export interface TenantServer {
    name: string;
    host: string;
    kind: string;
    region: string;
    capacity: number;
    status: string;
    tenants: number;
}

/** What each provisioning step is, in words (the setting-up screen). */
export const STEP_LABELS: Record<string, string> = {
    requested: 'Reserving your workspace',
    db_created: 'Creating your database',
    migrated: 'Setting up your tables',
    identity_ready: 'Giving your workspace its own identity',
    keys_ready: 'Making your encryption keys',
    namespace_ready: 'Preparing where your apps run',
    storage_ready: 'Preparing your file storage',
    data_api_ready: 'Starting your data API',
    active: 'Ready',
};

export const tenancyService = {
    async workspace(): Promise<WorkspaceStatus> {
        return (await apiClient.get('/workspace')).data;
    },
    async tenants(health = false): Promise<{ mode: string; tenants: TenantRow[]; health?: Record<string, unknown> }> {
        return (await apiClient.get('/admin/tenants', { params: { health } })).data;
    },
    async tenant(companyId: string): Promise<TenantDetail> {
        return (await apiClient.get(`/admin/tenants/${companyId}`)).data;
    },
    async provision(companyId: string, server?: string): Promise<TenantDetail> {
        return (await apiClient.post('/admin/tenants', { company_id: companyId, server })).data;
    },
    async retry(companyId: string): Promise<TenantDetail> {
        return (await apiClient.post(`/admin/tenants/${companyId}/provision`)).data;
    },
    async servers(): Promise<TenantServer[]> {
        return (await apiClient.get('/admin/tenant-servers')).data;
    },
};
