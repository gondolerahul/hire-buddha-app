/**
 * utils/money.ts — showing money (Phase 15 T2-5, tech design §3.3).
 *
 * The API keeps amounts exact (no rounding in costing or billing, K-1); the
 * screen is one of the three places an amount is rounded: here, for display
 * only. A company's money is shown in its billing currency (`/auth/me`
 * `billing_currency`); staff views in the platform's display currency, with
 * USD alongside (REQ-BL-4).
 */

/** Indian grouping (1,00,000) for rupees; international grouping otherwise. */
const LOCALE: Record<string, string> = { INR: 'en-IN' };

export interface MoneyOptions {
    /** Decimal places shown: 2 by default; small amounts (< 1) show up to `smallDigits`. */
    digits?: number;
    /** Places for amounts under 1 (a per-token price, a cent of usage); default 4. */
    smallDigits?: number;
    /** Compact notation (₹1.2L, $3.4K) for tiles. */
    compact?: boolean;
}

export function formatMoney(amount: number | string | null | undefined, currency = 'INR',
                            options: MoneyOptions = {}): string {
    const value = Number(amount ?? 0);
    if (!Number.isFinite(value)) return '—';
    const code = (currency || 'INR').toUpperCase();
    const { digits = 2, smallDigits = 4, compact = false } = options;
    const max = Math.abs(value) > 0 && Math.abs(value) < 1 ? Math.max(digits, smallDigits) : digits;
    try {
        return new Intl.NumberFormat(LOCALE[code] ?? 'en-US', {
            style: 'currency',
            currency: code,
            minimumFractionDigits: Math.min(digits, max),
            maximumFractionDigits: max,
            notation: compact ? 'compact' : 'standard',
        }).format(value);
    } catch {
        return `${code} ${value.toFixed(max)}`;
    }
}

/** An amount in USD converted at `unitsPerUsd` (FX-5); for display, never to store. */
export function fromUsd(usd: number, unitsPerUsd: number): number {
    return usd * unitsPerUsd;
}

/**
 * A billed amount as the API sends it (Phase 15 T9-3): staff get USD; a tenant's
 * or partner's people get their company's currency, named in `billed_currency`
 * on the same object.
 */
export function formatBilled(row: object | null | undefined,
                             amount: number | string | null | undefined, options: MoneyOptions = {}): string {
    const currency = (row as { billed_currency?: string | null } | null | undefined)?.billed_currency;
    return formatMoney(amount ?? 0, currency ?? 'USD', options);
}
