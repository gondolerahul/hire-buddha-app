/**
 * services/records.service.ts — the business's records (Phase 14 WS4/WS8 8.2; tech spec §9).
 *
 * The screens talk to the Data API (`/data/v1/…`) with a 15-minute user token
 * from `POST /api/v1/records/token`, kept until a minute before it expires.
 * Updates send `If-Match` with the record's row version; a 412 means someone
 * changed it since ("this record changed — reload"). Keys, the owner's policy
 * and tenant settings go through the platform API.
 */
import axios, { type AxiosInstance } from 'axios';

import { API_ORIGIN } from '@/config/api';
import { apiClient } from './api.client';

export type FieldType = 'text' | 'long_text' | 'integer' | 'decimal' | 'money' | 'boolean' | 'date' | 'datetime'
    | 'enum' | 'email' | 'phone' | 'url' | 'ref' | 'file';

export interface FieldSpec {
    type: FieldType;
    label?: string;
    required?: boolean;
    default?: unknown;
    values?: string[];
    to?: string;
    sensitivity?: string;
    archived?: boolean;
}

export interface ObjectSpec {
    label: string;
    plural: string;
    fields: Record<string, FieldSpec>;
    platform?: boolean;
    description?: string;
    row_policy?: { owner_field: string; match: 'email' | 'id' };
}

export interface Blueprint {
    version: number;
    base_pack?: string;
    objects: Record<string, ObjectSpec>;
}

export type RecordRow = Record<string, unknown> & { id: string; row_version: number; created_at?: string;
    updated_at?: string; created_by?: string; updated_by?: string };

export interface Page<T = RecordRow> {
    object: string;
    items: T[];
    next: string | null;
}

export interface HistoryItem {
    actor: string;
    action: string;
    changed: string[];
    at: string;
}

export interface SchemaChange {
    id: string;
    status: string;
    operations: Record<string, unknown>[];
    reason: string | null;
    actor_kind: string;
    actor_id: string | null;
    plan: { summary?: string[]; additive?: boolean; checks?: { message: string }[] } | null;
    impact: Record<string, unknown> | null;
    error: string | null;
    decided_by: string | null;
    created_at: string | null;
    applied_at: string | null;
}

export interface DataKey {
    id: string;
    name: string;
    prefix: string;
    scopes: { objects?: Record<string, string[]>; reports?: boolean; public?: boolean };
    external: boolean;
    created_at: string | null;
    last_used_at: string | null;
    revoked_at: string | null;
}

export interface RecordsSettings {
    agents_auto_approve_additive: boolean;
    scratch_retention_days: number | null;
    scratch_retention_default: number;
    public_api_access: boolean;
}

/** A Data API problem's message (its `detail`), or the fallback. */
export const problemText = (err: unknown, fallback: string): string => {
    const data = (err as { response?: { data?: { detail?: unknown } } })?.response?.data;
    return typeof data?.detail === 'string' ? data.detail : fallback;
};

export const isStale = (err: unknown): boolean =>
    (err as { response?: { status?: number } })?.response?.status === 412;

let token: { value: string; until: number } | null = null;

async function dataToken(): Promise<string> {
    if (token && token.until > Date.now()) return token.value;
    const { data } = await apiClient.post('/records/token');
    token = { value: data.token, until: Date.now() + (Number(data.expires_in || 900) - 60) * 1000 };
    return token.value;
}

/** Forget the cached token (another company, or after a sign-out). */
export const forgetDataToken = () => { token = null; };

const data: AxiosInstance = axios.create({ baseURL: `${API_ORIGIN}/data/v1` });
data.interceptors.request.use(async (config) => {
    config.headers.Authorization = `Bearer ${await dataToken()}`;
    return config;
});

export const recordsService = {
    async schema(): Promise<Blueprint> {
        return (await data.get('/schema')).data;
    },
    async list(object: string, params: Record<string, string> = {}): Promise<Page> {
        return (await data.get(`/${object}`, { params })).data;
    },
    async get(object: string, id: string): Promise<RecordRow> {
        return (await data.get(`/${object}/${id}`)).data;
    },
    async create(object: string, values: Record<string, unknown>): Promise<RecordRow> {
        return (await data.post(`/${object}`, values)).data;
    },
    async update(object: string, id: string, rowVersion: number, values: Record<string, unknown>): Promise<RecordRow> {
        return (await data.patch(`/${object}/${id}`, values, { headers: { 'If-Match': `"${rowVersion}"` } })).data;
    },
    async archive(object: string, id: string): Promise<RecordRow> {
        return (await data.delete(`/${object}/${id}`)).data;
    },
    async history(object: string, id: string): Promise<HistoryItem[]> {
        return (await data.get(`/${object}/${id}/history`)).data.items;
    },
    async changes(status?: string): Promise<SchemaChange[]> {
        return (await data.get('/schema/changes', { params: status ? { status } : {} })).data.items;
    },
    async propose(operations: Record<string, unknown>[], reason?: string, dryRun = false): Promise<SchemaChange> {
        return (await data.post('/schema/changes', { operations, reason, dry_run: dryRun })).data;
    },
    async decide(changeId: string, approve: boolean): Promise<SchemaChange> {
        return (await data.post(`/schema/changes/${changeId}/${approve ? 'approve' : 'reject'}`)).data;
    },
    docsUrl: `${API_ORIGIN}/data/v1/openapi.json`,
    async openapi(): Promise<Record<string, unknown>> {
        return (await data.get('/openapi.json')).data;
    },

    // Keys and settings: the platform API.
    async keys(): Promise<DataKey[]> {
        return (await apiClient.get('/data-keys')).data;
    },
    async createKey(name: string, objects: Record<string, string[]>, external: boolean): Promise<DataKey & { key: string }> {
        return (await apiClient.post('/data-keys', { name, scopes: { objects }, external })).data;
    },
    async revokeKey(id: string): Promise<void> {
        await apiClient.delete(`/data-keys/${id}`);
    },
    async settings(): Promise<RecordsSettings> {
        return (await apiClient.get('/records/settings')).data;
    },
    async saveSettings(changes: Partial<Omit<RecordsSettings, 'scratch_retention_default'>>): Promise<RecordsSettings> {
        return (await apiClient.put('/records/settings', changes)).data;
    },
};

/** The fields a person edits on a form (not system columns), in blueprint order. */
export const editableFields = (object: ObjectSpec): [string, FieldSpec][] =>
    Object.entries(object.fields).filter(([, f]) => !f.archived);

/** Who made a change, in words: a person, an agent's run, an app key, an app user. */
export const actorLabel = (actor: string | null | undefined): string => {
    if (!actor) return 'unknown';
    const [kind] = actor.split(':');
    return { user: 'a person', run: 'an agent', key: 'an app key', app_user: 'an app user',
             platform: 'HireBuddha' }[kind] ?? actor;
};
