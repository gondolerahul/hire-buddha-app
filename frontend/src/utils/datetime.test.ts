/**
 * datetime.test.ts — the API's naive-UTC timestamps read as UTC (FE-09, FE-03).
 */
import { describe, expect, it } from 'vitest';

import { formatDateTime, parseServerDate } from './datetime';

describe('parseServerDate', () => {
    it('reads a timestamp with no zone as UTC, not browser-local time', () => {
        expect(parseServerDate('2026-06-11T05:20:00').toISOString()).toBe('2026-06-11T05:20:00.000Z');
        expect(parseServerDate('2026-06-11 05:20:00').toISOString()).toBe('2026-06-11T05:20:00.000Z');
    });

    it('keeps a zone the string already has', () => {
        expect(parseServerDate('2026-06-11T05:20:00+05:30').toISOString()).toBe('2026-06-10T23:50:00.000Z');
        expect(parseServerDate('2026-06-11T05:20:00Z').toISOString()).toBe('2026-06-11T05:20:00.000Z');
    });

    it('passes dates and epoch numbers through, and reads nothing as an invalid date', () => {
        const d = parseServerDate(0);
        expect(d.getTime()).toBe(0);
        expect(parseServerDate(d)).toBe(d);
        for (const empty of [null, undefined, '']) expect(isNaN(parseServerDate(empty).getTime())).toBe(true);
    });
});

describe('formatDateTime', () => {
    it('shows a dash for a missing timestamp', () => {
        expect(formatDateTime(null)).toBe('—');
        expect(formatDateTime('not a date')).toBe('—');
    });
});
