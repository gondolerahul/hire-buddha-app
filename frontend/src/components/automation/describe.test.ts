import { describe, expect, it } from 'vitest';

import type { Trigger } from '@/services/automation.service';
import { parseServerDate } from '@/utils/datetime';

import {
    ago, describeNext, describeWhen, formatDay, formatTime, outcomeLabel, outcomeTone, runFinishedFields, sourceLabel,
    watchedAgent,
} from './describe';

const base = { cron: null, run_at: null, event_type: null, timezone: null };

describe('automation describe', () => {
    it('shows API times (UTC without a suffix) in the business time zone', () => {
        expect(formatTime('2026-10-18T03:30:00', 'Asia/Kolkata')).toBe('18 Oct, 09:00');
        expect(formatTime(null, 'Asia/Kolkata')).toBe('—');
        expect(formatDay('2027-01-01T03:30:00', 'Asia/Kolkata')).toBe('Fri, 1 Jan 2027, 09:00');
    });

    it('reads and writes a "when an agent finishes" trigger', () => {
        const fields = runFinishedFields('a1', 'failed');
        expect(fields).toEqual({ event_type: 'run.failed', filter: { all: [{ path: 'data.entity_id', op: 'eq', value: 'a1' }] } });
        expect(watchedAgent({ kind: 'event', ...fields })).toEqual({ agentId: 'a1', outcome: 'failed' });
        expect(watchedAgent({ kind: 'event', event_type: 'custom.x.y', filter: fields.filter })).toBeNull();
        expect(describeWhen({ ...base, kind: 'event', ...runFinishedFields('a1', 'completed') }, 'UTC', { a1: 'Research' }))
            .toBe('when Research completes');
    });

    it('names where an event came from', () => {
        expect(sourceLabel('automation:scheduler')).toBe('Schedule');
        expect(sourceLabel('user:8c1a')).toBe('Run now (a person)');
        expect(sourceLabel('instagram')).toBe('instagram');
    });

    it('says how long ago', () => {
        const now = parseServerDate('2026-10-18T10:00:00');
        expect(ago('2026-10-18T09:59:30', now)).toBe('just now');
        expect(ago('2026-10-18T09:55:00', now)).toBe('5 min ago');
        expect(ago('2026-10-16T09:00:00', now)).toBe('2 days ago');
    });

    it('describes when each kind fires', () => {
        expect(describeWhen({ ...base, kind: 'schedule', cron: '0 9 * * 1-5' }, 'Asia/Kolkata')).toBe('schedule 0 9 * * 1-5');
        expect(describeWhen({ ...base, kind: 'schedule', cron: '0 9 * * *', timezone: 'UTC' }, 'Asia/Kolkata'))
            .toBe('schedule 0 9 * * * (UTC)');
        expect(describeWhen({ ...base, kind: 'event', event_type: 'social.comment.*' }, 'UTC')).toBe('on social.comment.*');
        expect(describeWhen({ ...base, kind: 'manual' }, 'UTC')).toBe('run by hand');
        expect(describeWhen({
            ...base, kind: 'condition', cron: '0 * * * *',
            condition: { object: 'product', filter: [['stock', 'lt', 10]], measure: { fn: 'count' }, op: 'gt', value: 0 },
        }, 'UTC')).toBe('schedule 0 * * * *, if count of product where stock lt 10 > 0');
    });

    it('says what is next, or that a timer is finished', () => {
        const timer = { kind: 'timer', status: 'finished', next_fire_at: null } as unknown as Trigger;
        expect(describeNext(timer, 'UTC')).toBe('finished');
        expect(describeNext({ ...timer, status: 'off' } as Trigger, 'UTC')).toBe('—');
        expect(describeNext({ kind: 'event', status: 'active' } as unknown as Trigger, 'UTC')).toBe('on event');
    });

    it('explains each decision in words and colours it', () => {
        expect(outcomeLabel('skipped_chain_depth')).toBe('Stopped: loop limit');
        expect(outcomeTone('started')).toBe('ok');
        expect(outcomeTone('queued')).toBe('wait');
        expect(outcomeTone('blocked_budget')).toBe('bad');
    });
});
