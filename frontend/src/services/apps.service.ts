/**
 * services/apps.service.ts — code lanes, Git and tenant apps (Phase 14 WS6/WS8 8.4; functional spec §7).
 *
 * Code: scratch items an agent kept, promotion to a pull request with checks,
 * approval (owners and admins merge). Apps: created from a template, built
 * from commits, previewed, published, rolled back, operated; their domains,
 * users and roles. Times are UTC ISO strings ending in Z.
 */
import { apiClient } from './api.client';

export interface CodeCheck {
    name: string;
    conclusion: 'success' | 'failure' | 'neutral' | 'skipped';
    summary: string;
    tool: string;
}

export interface CodeReview {
    id: string;
    repo_id: string;
    number: number;
    title: string;
    branch: string;
    base_branch: string;
    url: string | null;
    status: 'open' | 'merged' | 'closed';
    head_sha: string | null;
    merge_sha: string | null;
    checks_status: 'pending' | 'running' | 'passed' | 'failed';
    checks: CodeCheck[];
    code_item_id: string | null;
    app_id: string | null;
    merged_by_login: string | null;
    merged_at: string | null;
    created_at: string | null;
}

export interface CodeItem {
    id: string;
    lane: 'scratch' | 'asset';
    kind: 'script' | 'tool' | 'skill_script' | 'app';
    name: string;
    description: string | null;
    status: 'active' | 'promoting' | 'promoted' | 'rejected' | 'expired';
    files: string[];
    repo_id: string | null;
    path: string | null;
    commit_sha: string | null;
    review_id: string | null;
    created_by_run_id: string | null;
    retention_until: string | null;
    created_at: string | null;
    review?: CodeReview;
    contents?: Record<string, string>;
}

export interface GitRepo {
    id: string;
    provider: 'github' | 'builtin';
    full_name: string;
    default_branch: string;
    url: string | null;
    connection_id: string | null;
    moved_to_repo_id: string | null;
}

export interface AppTemplate {
    id: string;
    name: string;
    version: string;
    stack: string;
    kind: 'web' | 'api' | 'mobile';
    deployable: boolean;
    description: string;
    params: Record<string, string>;
    uses_blueprint: boolean;
    roles: string[];
}

export interface AppBuild {
    id: string;
    commit_sha: string;
    status: 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled';
    builder: string;
    image: string | null;
    image_digest: string | null;
    scan: { tool?: string; critical?: number; high?: number; top?: string[]; skipped?: string; error?: string };
    duration_seconds: number | null;
    cost: number | null;
    error: string | null;
    review_id: string | null;
    created_at: string | null;
    finished_at: string | null;
}

export interface AppDeployment {
    id: string;
    build_id: string;
    kind: 'preview' | 'published';
    pr_number: number | null;
    hostnames: string[];
    url: string | null;
    status: 'pending' | 'active' | 'superseded' | 'stopped' | 'failed' | 'expired';
    runtime_status: { error?: string };
    expires_at: string | null;
    created_at: string | null;
}

export interface AppRole {
    id: string;
    name: string;
    description: string | null;
    permissions: { objects?: Record<string, string[]>; own_rows?: boolean };
}

export interface AppUser {
    id: string;
    email: string;
    name: string | null;
    status: 'active' | 'invited' | 'disabled';
    roles: string[];
    has_password: boolean;
    last_login_at: string | null;
}

export interface AppDomain {
    hostname: string;
    kind: 'custom' | 'platform' | 'preview';
    status: 'pending' | 'verified' | 'failed' | 'removed';
    cert_status: string;
    dns_records: { type: string; name: string; value: string | null; note?: string }[];
    last_error: string | null;
    verified_at: string | null;
}

export interface App {
    id: string;
    name: string;
    display_name: string;
    template: string;
    template_version: string;
    status: 'draft' | 'building' | 'ready' | 'published' | 'stopped' | 'failed' | 'archived';
    mode: 'always_on' | 'sleep';
    resources: { cpu?: string; memory?: string; replicas?: number; maxReplicas?: number };
    env: Record<string, string>;
    outbound_allowlist: string[];
    repo_id: string | null;
    objects: string[];
    hostname: string | null;
    url: string | null;
    kind: 'web' | 'api' | 'mobile' | null;
    published_deployment_id: string | null;
    created_at: string | null;
}

export interface AppDetail extends App {
    builds: AppBuild[];
    deployments: AppDeployment[];
    roles: AppRole[];
    user_count: number;
    domains: AppDomain[];
}

export interface NewApp {
    name: string;
    display_name: string;
    template: string;
    objects?: string[];
    params?: Record<string, string>;
    repo_id?: string;
    provider?: 'builtin' | 'github';
    connection_id?: string;
}

export interface AppSettingsChange {
    display_name?: string;
    mode?: App['mode'];
    resources?: App['resources'];
    env?: Record<string, string>;
    outbound_allowlist?: string[];
}

export const appsService = {
    // Code
    async codeItems(params: { lane?: string; status?: string; kind?: string } = {}): Promise<CodeItem[]> {
        return (await apiClient.get('/code-items', { params })).data;
    },
    async codeItem(id: string): Promise<CodeItem> {
        return (await apiClient.get(`/code-items/${id}`)).data;
    },
    async promote(id: string, repoId: string, path?: string): Promise<CodeReview> {
        return (await apiClient.post(`/code-items/${id}/promote`, { repo_id: repoId, path: path || undefined })).data;
    },
    async reviews(params: { status?: string; app_id?: string } = {}): Promise<CodeReview[]> {
        return (await apiClient.get('/code-reviews', { params })).data;
    },
    async approve(reviewId: string): Promise<CodeReview> {
        return (await apiClient.post(`/code-reviews/${reviewId}/approve`)).data;
    },
    async reject(reviewId: string): Promise<CodeReview> {
        return (await apiClient.post(`/code-reviews/${reviewId}/reject`)).data;
    },
    async rerunChecks(reviewId: string): Promise<void> {
        await apiClient.post(`/code-reviews/${reviewId}/checks`);
    },
    async repos(): Promise<GitRepo[]> {
        return (await apiClient.get('/git/repos')).data;
    },
    async createRepo(name: string, provider: 'builtin' | 'github' = 'builtin', connectionId?: string): Promise<GitRepo> {
        return (await apiClient.post('/git/repos', { name, provider, connection_id: connectionId })).data;
    },
    async importRepo(connectionId: string, fullName: string): Promise<GitRepo> {
        return (await apiClient.post('/git/repos', { connection_id: connectionId, import_full_name: fullName })).data;
    },
    async pushToGithub(repoId: string, connectionId: string, name?: string): Promise<GitRepo> {
        return (await apiClient.post(`/git/repos/${repoId}/push-to-github`, { connection_id: connectionId, name })).data;
    },

    // Apps
    async templates(): Promise<AppTemplate[]> {
        return (await apiClient.get('/app-templates')).data;
    },
    async list(): Promise<App[]> {
        return (await apiClient.get('/apps')).data;
    },
    async create(body: NewApp): Promise<App> {
        return (await apiClient.post('/apps', body)).data;
    },
    async get(id: string): Promise<AppDetail> {
        return (await apiClient.get(`/apps/${id}`)).data;
    },
    async update(id: string, change: AppSettingsChange): Promise<AppDetail> {
        return (await apiClient.patch(`/apps/${id}`, change)).data;
    },
    async archive(id: string): Promise<App> {
        return (await apiClient.delete(`/apps/${id}`)).data;
    },
    async build(id: string, commitSha?: string): Promise<AppBuild> {
        return (await apiClient.post(`/apps/${id}/builds`, { commit_sha: commitSha })).data;
    },
    async buildLog(id: string, buildId: string): Promise<string> {
        return (await apiClient.get(`/apps/${id}/builds/${buildId}/log`, { responseType: 'text' })).data;
    },
    async preview(id: string, buildId?: string): Promise<AppDeployment> {
        return (await apiClient.post(`/apps/${id}/preview`, { build_id: buildId })).data;
    },
    async publish(id: string, buildId?: string): Promise<AppDeployment> {
        return (await apiClient.post(`/apps/${id}/publish`, { build_id: buildId })).data;
    },
    async rollback(id: string): Promise<AppDeployment> {
        return (await apiClient.post(`/apps/${id}/rollback`)).data;
    },
    async operate(id: string, action: 'stop' | 'start' | 'restart' | 'unpublish'): Promise<App> {
        return (await apiClient.post(`/apps/${id}/actions/${action}`)).data;
    },
    async logs(id: string, tail = 200): Promise<string> {
        return (await apiClient.get(`/apps/${id}/logs`, { params: { tail }, responseType: 'text' })).data;
    },
    async metrics(id: string): Promise<{ now: Record<string, unknown>;
        hourly: { window_start: string; vcpu_hours: number; gb_hours: number; egress_gb: number }[] }> {
        return (await apiClient.get(`/apps/${id}/metrics`)).data;
    },
    async addDomain(id: string, hostname: string): Promise<AppDomain> {
        return (await apiClient.post(`/apps/${id}/domains`, { hostname })).data;
    },
    async verifyDomain(id: string, hostname: string): Promise<AppDomain> {
        return (await apiClient.post(`/apps/${id}/domains/${encodeURIComponent(hostname)}/verify`)).data;
    },
    async removeDomain(id: string, hostname: string): Promise<void> {
        await apiClient.delete(`/apps/${id}/domains/${encodeURIComponent(hostname)}`);
    },
    async users(id: string): Promise<AppUser[]> {
        return (await apiClient.get(`/apps/${id}/users`)).data;
    },
    async addUser(id: string, body: { email: string; name?: string; roles: string[]; password?: string }): Promise<AppUser> {
        return (await apiClient.post(`/apps/${id}/users`, body)).data;
    },
    async updateUser(id: string, userId: string, body: { roles?: string[]; status?: 'active' | 'disabled';
                                                         password?: string; name?: string }): Promise<AppUser> {
        return (await apiClient.patch(`/apps/${id}/users/${userId}`, body)).data;
    },
    async removeUser(id: string, userId: string): Promise<void> {
        await apiClient.delete(`/apps/${id}/users/${userId}`);
    },
    async invite(id: string, userId: string, returnUrl: string): Promise<void> {
        await apiClient.post(`/apps/${id}/users/${userId}/invite`, { return_url: returnUrl });
    },
    async saveRole(id: string, name: string, objects: Record<string, string[]>, ownRows: boolean, description?: string):
        Promise<AppRole> {
        return (await apiClient.put(`/apps/${id}/roles/${name}`, { objects, own_rows: ownRows, description })).data;
    },
    async deleteRole(id: string, roleId: string): Promise<void> {
        await apiClient.delete(`/apps/${id}/roles/${roleId}`);
    },
};

/** An app's name from its display name: lower-case words joined by hyphens, 3–30 characters. */
export const suggestAppName = (displayName: string): string =>
    displayName.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').replace(/^[^a-z]+/, '')
        .slice(0, 30).replace(/-+$/, '');

export const APP_STATUS_LABEL: Record<App['status'], string> = {
    draft: 'Draft', building: 'Building', ready: 'Ready to publish', published: 'Live', stopped: 'Stopped',
    failed: 'Build failed', archived: 'Archived',
};
