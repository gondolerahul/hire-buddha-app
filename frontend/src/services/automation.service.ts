/**
 * services/automation.service.ts — the automation API (Phase 14 WS3, decision D47).
 *
 * A business's automation limits are its own settings, none by default. In a
 * scope's values a limit that is absent inherits (business ← platform ← no
 * limit); `null` means no limit; a value is the limit.
 *
 * The control room (tech spec §7.12): triggers — saving one runs nothing —
 * their decisions, the event log with replay, and a health summary. Times
 * from the API are UTC without a zone suffix (read them with parseServerDate).
 */
import { apiClient } from './api.client';

export type LimitValue = number | string | null;
export type LimitValues = Record<string, LimitValue>;

export interface LimitInfo {
    key: string;
    label: string;
    help: string;
    kind: 'count' | 'choice';
    choices: string[];
    unit: string;
    default: string | null;
}

export interface AutomationSettings {
    company_id: string;
    automation_state: 'running' | 'paused';
    paused_reason: string | null;
    timezone: string;
    effective: LimitValues;
    business: LimitValues;
    platform: LimitValues;
    catalogue: LimitInfo[];
}

export interface PlatformAutomation {
    platform: LimitValues;
    catalogue: LimitInfo[];
    automation_state: 'running' | 'paused';
    paused_reason: string | null;
}

export type TriggerKind = 'schedule' | 'timer' | 'event' | 'data' | 'manual';
export type TriggerStatus = 'active' | 'off' | 'finished' | 'paused';

export interface FilterCondition {
    path: string;
    op: string;
    value?: unknown;
}
export type TriggerFilter = FilterCondition | { all: TriggerFilter[] } | { any: TriggerFilter[] };

/** What the trigger editor sends (on a change, only what changed). */
export interface TriggerFields {
    name?: string;
    kind?: TriggerKind;
    enabled?: boolean;
    entity_id?: string;
    entity_version_id?: string | null;
    input_template?: Record<string, unknown>;
    event_type?: string | null;
    filter?: TriggerFilter | null;
    cron?: string | null;
    timezone?: string | null;
    run_at?: string | null;
    until_at?: string | null;
    max_firings?: number | null;
    catch_up?: string | null;
    overlap?: string | null;
    max_concurrency?: number | null;
    rate_per_hour?: number | null;
    scope?: string | null;
}

export interface Trigger {
    id: string;
    name: string;
    kind: TriggerKind;
    enabled: boolean;
    status: TriggerStatus;
    entity_id: string;
    entity_version_id: string | null;
    input_template: Record<string, unknown>;
    event_type: string | null;
    filter: TriggerFilter | null;
    cron: string | null;
    timezone: string | null;
    run_at: string | null;
    until_at: string | null;
    max_firings: number | null;
    catch_up: string | null;
    overlap: string | null;
    max_concurrency: number | null;
    rate_per_hour: number | null;
    scope: string | null;
    created_by_kind: 'user' | 'agent' | 'system';
    created_by_id: string | null;
    created_by_run_id: string | null;
    next_fire_at: string | null;
    last_fired_at: string | null;
    firings: number;
    paused_reason: string | null;
    version: number;
    created_at: string | null;
    updated_at: string | null;
}

export interface Firing {
    id: string;
    trigger_id: string;
    event_id: string | null;
    run_id: string | null;
    decided_at: string;
    outcome: string;
    reason: string | null;
}

export type EventStatus = 'received' | 'routed' | 'parked' | 'dead';

export interface AutomationEvent {
    id: string;
    type: string;
    source: string;
    subject: string | null;
    time: string;
    received_at: string;
    trust: string;
    chain_depth: number;
    correlation_id: string | null;
    causation_id: string | null;
    status: EventStatus;
    attempts: number;
    last_error: string | null;
    routed_at: string | null;
}

export interface EventRun {
    id: string;
    status: string;
    entity_id: string;
    trigger_id: string | null;
    created_at: string | null;
}

export interface EventDetail extends AutomationEvent {
    data: Record<string, unknown>;
    data_ref: string | null;
    firings: Firing[];
    runs: EventRun[];
}

export interface AutomationHealth {
    automation_state: 'running' | 'paused';
    started_24h: number;
    triggers_enabled: number;
    triggers_total: number;
    dead_events: number;
    parked_events: number;
    oldest_parked_at: string | null;
    queued_firings: number;
    missed_schedules_24h: number;
    failing_triggers: { trigger_id: string; name: string; problems: number; last_outcome: string; last_reason: string | null }[];
    upcoming: { trigger_id: string; name: string; kind: TriggerKind; next_fire_at: string; created_by_kind: string }[];
}

export interface EventQuery {
    type?: string;
    status?: EventStatus | '';
    before?: string;
    limit?: number;
}

export interface PreviewRequest {
    kind: TriggerKind;
    cron?: string | null;
    timezone?: string | null;
    run_at?: string | null;
    until_at?: string | null;
    count?: number;
}

export const automationService = {
    getSettings: async (): Promise<AutomationSettings> =>
        (await apiClient.get<AutomationSettings>('/automation/settings')).data,

    saveLimits: async (limits: LimitValues): Promise<AutomationSettings> =>
        (await apiClient.put<AutomationSettings>('/automation/settings/limits', { limits })).data,

    pause: async (reason?: string): Promise<AutomationSettings> =>
        (await apiClient.post<AutomationSettings>('/automation/pause', { reason: reason || null })).data,

    resume: async (): Promise<AutomationSettings> =>
        (await apiClient.post<AutomationSettings>('/automation/resume')).data,

    getPlatform: async (): Promise<PlatformAutomation> =>
        (await apiClient.get<PlatformAutomation>('/admin/automation/limits')).data,

    savePlatformLimits: async (limits: LimitValues): Promise<PlatformAutomation> =>
        (await apiClient.put<PlatformAutomation>('/admin/automation/limits', { limits })).data,

    pausePlatform: async (reason?: string): Promise<PlatformAutomation> =>
        (await apiClient.post<PlatformAutomation>('/admin/automation/pause', { reason: reason || null })).data,

    resumePlatform: async (): Promise<PlatformAutomation> =>
        (await apiClient.post<PlatformAutomation>('/admin/automation/resume')).data,

    // ── Control room ──────────────────────────────────────────────────────
    listTriggers: async (): Promise<Trigger[]> =>
        (await apiClient.get<Trigger[]>('/automation/triggers')).data,

    createTrigger: async (fields: TriggerFields): Promise<Trigger> =>
        (await apiClient.post<Trigger>('/automation/triggers', fields)).data,

    updateTrigger: async (id: string, changes: TriggerFields): Promise<Trigger> =>
        (await apiClient.patch<Trigger>(`/automation/triggers/${id}`, changes)).data,

    deleteTrigger: async (id: string): Promise<void> => {
        await apiClient.delete(`/automation/triggers/${id}`);
    },

    runTrigger: async (id: string): Promise<AutomationEvent> =>
        (await apiClient.post<AutomationEvent>(`/automation/triggers/${id}/run`)).data,

    firings: async (id: string, limit = 20): Promise<Firing[]> =>
        (await apiClient.get<Firing[]>(`/automation/triggers/${id}/firings`, { params: { limit } })).data,

    preview: async (request: PreviewRequest): Promise<{ timezone: string; times: string[] }> =>
        (await apiClient.post<{ timezone: string; times: string[] }>('/automation/triggers/preview', request)).data,

    testFilter: async (eventType: string, filter: TriggerFilter | null):
        Promise<{ checked: number; matched: number; matches: AutomationEvent[] }> =>
        (await apiClient.post<{ checked: number; matched: number; matches: AutomationEvent[] }>(
            '/automation/triggers/test-filter', { event_type: eventType, filter })).data,

    listEvents: async (query: EventQuery = {}): Promise<AutomationEvent[]> => {
        const params = Object.fromEntries(Object.entries(query).filter(([, v]) => v !== undefined && v !== ''));
        return (await apiClient.get<AutomationEvent[]>('/automation/events', { params })).data;
    },

    getEvent: async (id: string): Promise<EventDetail> =>
        (await apiClient.get<EventDetail>(`/automation/events/${id}`)).data,

    replayEvent: async (id: string): Promise<AutomationEvent> =>
        (await apiClient.post<AutomationEvent>(`/automation/events/${id}/replay`)).data,

    health: async (): Promise<AutomationHealth> =>
        (await apiClient.get<AutomationHealth>('/automation/health')).data,
};
