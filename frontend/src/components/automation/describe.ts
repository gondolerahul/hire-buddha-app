/**
 * components/automation/describe — how the control room says things
 * (functional spec §3.4): when a trigger fires, what a decision means, and
 * times in the business time zone.
 */
import type { EventStatus, Trigger, TriggerCondition, TriggerFilter } from '@/services/automation.service';
import { parseServerDate } from '@/utils/datetime';

/** A time in the business time zone, e.g. "18 Oct, 09:00". */
export const formatTime = (value: string | null | undefined, timeZone: string): string => {
    if (!value) return '—';
    try {
        return new Intl.DateTimeFormat('en-GB', {
            timeZone, day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false,
        }).format(parseServerDate(value));
    } catch {
        return parseServerDate(value).toISOString();
    }
};

/** A full date for a schedule preview, e.g. "Fri, 1 Jan 2027, 09:00". */
export const formatDay = (value: string, timeZone: string): string => {
    try {
        return new Intl.DateTimeFormat('en-GB', {
            timeZone, weekday: 'short', day: 'numeric', month: 'short', year: 'numeric',
            hour: '2-digit', minute: '2-digit', hour12: false,
        }).format(parseServerDate(value));
    } catch {
        return parseServerDate(value).toISOString();
    }
};

/** Where an event came from, in words. */
export const sourceLabel = (source: string): string => {
    if (source === 'automation:scheduler') return 'Schedule';
    if (source.startsWith('automation:')) return 'Automation';
    if (source.startsWith('user:')) return 'Run now (a person)';
    if (source.startsWith('run:')) return 'An agent run';
    return source;
};

/** "just now", "5 min ago", "3 h ago", "2 days ago". */
export const ago = (value: string | null | undefined, now: Date = new Date()): string => {
    if (!value) return '—';
    const seconds = Math.round((now.getTime() - parseServerDate(value).getTime()) / 1000);
    if (seconds < 60) return 'just now';
    if (seconds < 3600) return `${Math.floor(seconds / 60)} min ago`;
    if (seconds < 86400) return `${Math.floor(seconds / 3600)} h ago`;
    const days = Math.floor(seconds / 86400);
    return `${days} day${days === 1 ? '' : 's'} ago`;
};

export type RunOutcome = 'completed' | 'failed' | 'any';

const RUN_EVENT: Record<RunOutcome, string> = { completed: 'run.completed', failed: 'run.failed', any: 'run.*' };

/** "When an agent finishes": an event trigger on run.* for one agent (functional spec §3.1). */
export const runFinishedFields = (agentId: string, outcome: RunOutcome): { event_type: string; filter: TriggerFilter } => ({
    event_type: RUN_EVENT[outcome],
    filter: { all: [{ path: 'data.entity_id', op: 'eq', value: agentId }] },
});

/** The agent a run-finished trigger watches and for which outcome, or null for any other trigger. */
export const watchedAgent = (trigger: Pick<Trigger, 'kind' | 'event_type' | 'filter'>):
    { agentId: string; outcome: RunOutcome } | null => {
    const outcome = (Object.keys(RUN_EVENT) as RunOutcome[]).find(o => RUN_EVENT[o] === trigger.event_type);
    if (trigger.kind !== 'event' || !outcome || !trigger.filter) return null;
    const filter = trigger.filter as { all?: TriggerFilter[] };
    const conditions = 'path' in trigger.filter ? [trigger.filter] : filter.all ?? [];
    if (conditions.length !== 1) return null;
    const only = conditions[0] as { path?: string; op?: string; value?: unknown };
    return only.path === 'data.entity_id' && only.op === 'eq' && typeof only.value === 'string'
        ? { agentId: only.value, outcome } : null;
};

const FINISHES: Record<RunOutcome, string> = { completed: 'completes', failed: 'fails', any: 'finishes' };

const COMPARISONS: Record<string, string> = { gt: '>', gte: '≥', lt: '<', lte: '≤', eq: '=', ne: '≠' };

/** A condition trigger's check, as the backend words it: "count of product where stock lt 10 > 0". */
export const describeCondition = (condition: TriggerCondition | null | undefined): string => {
    if (!condition) return 'a condition';
    const { measure } = condition;
    const what = measure.fn === 'count' ? 'count' : `${measure.fn} of ${measure.field ?? ''}`;
    const where = (condition.filter ?? []).map(([field, op, value]) => `${field} ${op} ${String(value)}`).join(' and ');
    return `${what} of ${condition.object}${where ? ` where ${where}` : ''} ${COMPARISONS[condition.op] ?? condition.op} ${condition.value}`;
};

/** What starts the trigger, in a few words. */
export const describeWhen = (trigger: Pick<Trigger, 'kind' | 'cron' | 'run_at' | 'event_type' | 'timezone'>
    & Partial<Pick<Trigger, 'filter' | 'condition'>>, timeZone: string, names: Record<string, string> = {}): string => {
    const watched = watchedAgent({ kind: trigger.kind, event_type: trigger.event_type, filter: trigger.filter ?? null });
    if (watched) return `when ${names[watched.agentId] ?? 'an agent'} ${FINISHES[watched.outcome]}`;
    switch (trigger.kind) {
        case 'schedule':
            return `schedule ${trigger.cron ?? ''}${trigger.timezone && trigger.timezone !== timeZone ? ` (${trigger.timezone})` : ''}`;
        case 'timer':
            return `once at ${formatTime(trigger.run_at, timeZone)}`;
        case 'event':
            return `on ${trigger.event_type ?? 'event'}`;
        case 'data':
            return `on change ${trigger.event_type ?? ''}`;
        case 'condition':
            return `schedule ${trigger.cron ?? ''}, if ${describeCondition(trigger.condition)}`;
        default:
            return 'run by hand';
    }
};

/** The next run column: a time, "on event", or why there is none. */
export const describeNext = (trigger: Trigger, timeZone: string): string => {
    if (trigger.status === 'off') return '—';
    if (trigger.kind === 'event' || trigger.kind === 'data') return 'on event';
    if (trigger.kind === 'manual') return 'when run';
    return trigger.next_fire_at ? formatTime(trigger.next_fire_at, timeZone) : 'finished';
};

const OUTCOMES: Record<string, string> = {
    started: 'Started',
    queued: 'Queued (waiting its turn)',
    skipped_overlap: 'Skipped: still running',
    skipped_rate: 'Skipped: rate limit',
    skipped_chain_depth: 'Stopped: loop limit',
    skipped_condition_false: 'Skipped: condition false',
    skipped_missed: 'Missed (catch-up rule)',
    blocked_budget: 'Blocked: budget',
    blocked_paused: 'Held: automation paused',
    blocked_policy: 'Blocked: not allowed',
    failed: 'Failed',
};

export const outcomeLabel = (outcome: string): string => OUTCOMES[outcome] ?? outcome;

/** Good, waiting or bad — the colour of an outcome. */
export const outcomeTone = (outcome: string): 'ok' | 'wait' | 'bad' => {
    if (outcome === 'started') return 'ok';
    if (outcome === 'queued' || outcome.startsWith('skipped') || outcome === 'blocked_paused') return 'wait';
    return 'bad';
};

const EVENT_STATUS: Record<EventStatus, string> = {
    received: 'Waiting',
    routed: 'Handled',
    parked: 'Held',
    dead: 'Failed',
};

export const eventStatusLabel = (status: EventStatus): string => EVENT_STATUS[status] ?? status;
