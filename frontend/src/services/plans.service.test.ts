import { describe, expect, it } from 'vitest';

import { withGst } from './plans.service';

describe('withGst (Phase 15 T6-4: net + GST = what is charged)', () => {
    it('adds 18% to a rupee amount', () => {
        expect(withGst('1000', '18')).toEqual({ net: 1000, tax: 180, gross: 1180 });
    });

    it('rounds the tax to the paisa', () => {
        expect(withGst('999.99', '18')).toEqual({ net: 999.99, tax: 180, gross: 1179.99 });
    });

    it('charges no GST on an export (rate 0)', () => {
        expect(withGst(50, 0)).toEqual({ net: 50, tax: 0, gross: 50 });
    });
});
