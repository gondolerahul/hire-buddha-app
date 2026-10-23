import { describe, expect, it } from 'vitest';

import { formatMoney, fromUsd } from './money';

describe('formatMoney (Phase 15 T2-5)', () => {
    it('shows rupees with Indian grouping', () => {
        expect(formatMoney(123456.5, 'INR')).toBe('₹1,23,456.50');
    });

    it('shows dollars with international grouping', () => {
        expect(formatMoney(123456.5, 'USD')).toBe('$123,456.50');
    });

    it('keeps more places for small amounts, so a tiny charge is not shown as zero', () => {
        expect(formatMoney(0.0045, 'USD')).toBe('$0.0045');
        expect(formatMoney(0.5, 'INR')).toBe('₹0.50');
    });

    it('rounds only for display', () => {
        expect(formatMoney(1.235, 'USD')).toBe('$1.24');
        expect(formatMoney('2000', 'INR')).toBe('₹2,000.00');
    });

    it('handles nothing and unknown codes', () => {
        expect(formatMoney(null, 'INR')).toBe('₹0.00');
        expect(formatMoney(Number.NaN, 'INR')).toBe('—');
        expect(formatMoney(5, 'XXZ').replace(/\s/g, ' ')).toBe('XXZ 5.00');  // Intl uses a no-break space
    });

    it('converts USD at a rate for display', () => {
        expect(fromUsd(20, 100)).toBe(2000);
    });
});
