/**
 * services/connections.service.ts — the business's own accounts (Phase 14 WS5/WS8 8.3; functional spec §6).
 *
 * Connect: `start` answers with a provider window to open (`redirect`), the
 * WhatsApp sign-up parameters (`embedded_signup`) or a short `form`. The
 * provider sends the browser back to `/connections?pending=<id>`; the owner
 * picks the accounts and who may use them (`finalize`). Platform staff see the
 * connector approvals and the unrouted deliveries.
 */
import { apiClient } from './api.client';

export type ConnectorStatus = 'available' | 'preview' | 'unavailable' | 'planned';

export interface FormField {
    name: string;
    label: string;
    kind: 'text' | 'secret' | 'email' | 'url' | 'number';
    required: boolean;
    default?: unknown;
}

export interface Connector {
    id: string;
    provider: string;
    display_name: string;
    category: string;
    auth_type: string;
    icon: string | null;
    status: ConnectorStatus;
    connectable: boolean;
    scopes: string[];
    actions: string[];
    events: string[];
    form: FormField[];
}

export interface Grant {
    principal_kind: 'all_agents' | 'entity' | 'app';
    principal_id: string | null;
    actions: string[];
}

export interface Connection {
    id: string;
    connector_id: string;
    display_name: string;
    external_account_id: string | null;
    external_account_name: string | null;
    status: 'active' | 'expiring' | 'needs_reconnect' | 'revoked' | 'error';
    scopes: string[];
    token_expires_at: string | null;
    health: { last_check_at?: string; last_ok_at?: string; last_error?: string | null };
    settings: Record<string, unknown>;
    connected_at: string | null;
    last_used_at: string | null;
    grants?: Grant[];
}

export interface Impact {
    all_agents: boolean;
    agents: { id: string; name: string | null }[];
    apps: string[];
    triggers: { id: string; name: string; enabled: boolean }[];
}

export interface ConnectionDetail extends Connection {
    activity: { action: string; actor_kind: string | null; actor_id: string | null; run_id: string | null; at: string;
                detail: Record<string, unknown> | null }[];
    impact: Impact;
}

export type StartResult =
    | { kind: 'redirect'; connector_id: string; url: string }
    | { kind: 'form'; connector_id: string; form: FormField[] }
    | { kind: 'embedded_signup'; connector_id: string; params: Record<string, unknown> };

export interface Pending {
    pending_id: string;
    connector_id: string;
    display_name: string;
    reconnect_id: string | null;
    accounts: { external_id: string; name: string; settings: Record<string, unknown>; available: boolean }[];
}

export interface ConnectorAdmin extends Connector {
    yaml_status?: ConnectorStatus;
    status_override?: ConnectorStatus | null;
    approval?: Record<string, unknown>;
}

export interface UnroutedEvent {
    id: string;
    provider: string;
    external_account_id: string | null;
    event_type: string | null;
    payload_sha256: string;
    payload_bytes: number;
    received_at: string;
}

export const CATEGORY_LABELS: Record<string, string> = {
    social: 'Social', messaging: 'Messaging', dev: 'Dev', docs: 'Docs', mail: 'Mail', crm: 'CRM', ai: 'AI', other: 'Other',
};

export const STATUS_BADGE: Record<ConnectorStatus, string> = {
    available: 'Connect', preview: 'Preview', unavailable: 'Unavailable', planned: 'Coming soon',
};

export const connectionsService = {
    async connectors(): Promise<Connector[]> {
        return (await apiClient.get('/connectors')).data;
    },
    async list(): Promise<Connection[]> {
        return (await apiClient.get('/connections')).data;
    },
    async detail(id: string): Promise<ConnectionDetail> {
        return (await apiClient.get(`/connections/${id}`)).data;
    },
    async start(connectorId: string, returnPath = '/connections'): Promise<StartResult> {
        return (await apiClient.post('/connections/start', { connector_id: connectorId, return_path: returnPath })).data;
    },
    async pending(pendingId: string): Promise<Pending> {
        return (await apiClient.get(`/connections/pending/${pendingId}`)).data;
    },
    async finalize(pendingId: string, accounts: string[], grants?: Grant[]): Promise<Connection[]> {
        return (await apiClient.post(`/connections/pending/${pendingId}/finalize`, { accounts, grants })).data;
    },
    async form(connectorId: string, fields: Record<string, unknown>, displayName?: string, grants?: Grant[]):
        Promise<Connection> {
        return (await apiClient.post('/connections/form', { connector_id: connectorId, fields,
                                                            display_name: displayName, grants })).data;
    },
    async test(id: string): Promise<{ ok: boolean; detail?: string }> {
        return (await apiClient.post(`/connections/${id}/test`)).data;
    },
    async reconnect(id: string): Promise<StartResult> {
        return (await apiClient.post(`/connections/${id}/reconnect`)).data;
    },
    async setGrants(id: string, grants: Grant[]): Promise<Connection> {
        return (await apiClient.put(`/connections/${id}/grants`, { grants })).data;
    },
    async impact(id: string): Promise<Impact> {
        return (await apiClient.get(`/connections/${id}/impact`)).data;
    },
    async revoke(id: string): Promise<Record<string, unknown>> {
        return (await apiClient.delete(`/connections/${id}`)).data;
    },

    // Platform staff.
    async adminConnectors(): Promise<ConnectorAdmin[]> {
        return (await apiClient.get('/admin/connectors')).data;
    },
    async setConnector(id: string, change: { status_override?: ConnectorStatus | null; approval?: Record<string, unknown>;
                                              clear_override?: boolean }): Promise<ConnectorAdmin> {
        return (await apiClient.patch(`/admin/connectors/${id}`, change)).data;
    },
    async unrouted(): Promise<UnroutedEvent[]> {
        return (await apiClient.get('/admin/unrouted-events')).data;
    },
    /** HireBuddha's own app with each provider (M1-12): settings, and secrets by vault name only. */
    async oauthApps(): Promise<ProviderAppView[]> {
        return (await apiClient.get('/admin/oauth-apps')).data;
    },
    async saveOauthApp(provider: string, body: ProviderAppInput): Promise<ProviderAppView> {
        return (await apiClient.put(`/admin/oauth-apps/${provider}`, body)).data;
    },
};

export interface ProviderAppView {
    provider: string;
    registered: boolean;
    status: string | null;
    settings: Record<string, string>;
    secret: string | null;
    secret_in_vault: boolean | null;
    refs: Record<string, string>;
    refs_in_vault: Record<string, boolean | null>;
    required: string[];
    required_refs: string[];
}

export interface ProviderAppInput {
    settings: Record<string, string>;
    refs: Record<string, string>;
    secret: string | null;
}
