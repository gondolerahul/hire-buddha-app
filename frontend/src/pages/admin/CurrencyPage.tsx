/**
 * pages/admin/CurrencyPage — Currency & FX (Phase 15 T2-6; 07 §5.6). Staff only.
 *
 * - Display and default currency (REQ-BL-4, REQ-BL-2).
 * - Currencies and the current rate per USD; "Add rate" with a reason and an
 *   impact preview. Rates are append-only: a new rate applies to events from
 *   its start; money already charged keeps the rate it used (FX-4, FX-6).
 * - Rate history (who, when, why).
 * - Country profiles: the currency, time zone, phone code and tax regime a new
 *   company in each country gets.
 *
 * Lives under /admin/currency until the Platform Console shell (T9-1) moves it
 * to /console/currency.
 */
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Coins, History, Globe2, Save } from 'lucide-react';

import { apiErrorMessage } from '@/utils/apiError';
import { formatMoney } from '@/utils/money';
import { parseServerDate } from '@/utils/datetime';
import {
    CountryProfileRow, CurrencyRow, CurrencySettings, FxPreview, FxRateRow, currencyService,
} from '@/services/currency.service';

import './CurrencyPage.css';

const TAX_REGIMES: CountryProfileRow['tax_regime'][] = ['IN_GST', 'EXPORT', 'NONE'];

/** A datetime-local value ("2026-10-24T09:30", the admin's own clock) as an ISO instant. */
function localInputToIso(value: string): string {
    const [day, time = '00:00'] = value.split('T');
    const [y, m, d] = day.split('-').map(Number);
    const [hh, mm] = time.split(':').map(Number);
    const local = new Date();  // the browser's own time: what the admin typed (as TriggerEditor does)
    local.setFullYear(y, m - 1, d);
    local.setHours(hh, mm, 0, 0);
    return local.toISOString();
}

export const CurrencyPage: React.FC = () => {
    const [currencies, setCurrencies] = useState<CurrencyRow[]>([]);
    const [rates, setRates] = useState<FxRateRow[]>([]);
    const [settings, setSettings] = useState<CurrencySettings | null>(null);
    const [profiles, setProfiles] = useState<CountryProfileRow[]>([]);
    const [error, setError] = useState<string | null>(null);
    const [notice, setNotice] = useState<string | null>(null);
    const [loading, setLoading] = useState(true);

    const load = useCallback(async () => {
        setLoading(true);
        try {
            const [c, r, s, p] = await Promise.all([
                currencyService.listCurrencies(), currencyService.listRates(),
                currencyService.getSettings(), currencyService.listCountryProfiles(),
            ]);
            setCurrencies(c);
            setRates(r);
            setSettings(s);
            setProfiles(p);
            setError(null);
        } catch (err) {
            setError(apiErrorMessage(err, 'Failed to load currencies'));
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => { load(); }, [load]);

    const saveSettings = async (patch: Partial<CurrencySettings>) => {
        try {
            setSettings(await currencyService.putSettings(patch));
            setNotice('Currency settings saved.');
        } catch (err) {
            setError(apiErrorMessage(err, 'Failed to save currency settings'));
        }
    };

    if (loading && !settings) return <div className="currency-page"><div className="pulse">Loading currencies…</div></div>;

    const activeCodes = currencies.filter(c => c.active).map(c => c.code);

    return (
        <div className="currency-page">
            <div className="page-header">
                <div>
                    <h1 className="page-title"><Coins size={22} /> Currency &amp; FX</h1>
                    <p className="page-subtitle">
                        Costs are computed in USD. A company is billed in its country's currency, converted at the
                        rate in effect when money is held, charged or paid.
                    </p>
                </div>
            </div>

            {error && <div className="error-banner">{error}</div>}
            {notice && <div className="success-banner">{notice}</div>}

            <section className="currency-card glass">
                <h2>Display and default currency</h2>
                <div className="currency-settings">
                    <label>
                        Staff views show amounts in
                        <select value={settings?.display_currency ?? ''}
                                onChange={(e) => saveSettings({ display_currency: e.target.value })}>
                            {activeCodes.map(code => <option key={code} value={code}>{code}</option>)}
                        </select>
                    </label>
                    <label>
                        A country with no profile is billed in
                        <select value={settings?.default_currency ?? ''}
                                onChange={(e) => saveSettings({ default_currency: e.target.value })}>
                            {activeCodes.map(code => <option key={code} value={code}>{code}</option>)}
                        </select>
                    </label>
                </div>
            </section>

            <section className="currency-card glass">
                <h2>Currencies and rates</h2>
                <table className="currency-table">
                    <thead>
                        <tr><th>Currency</th><th>Symbol</th><th>Minor units</th><th>Gateway</th><th>Per USD</th><th>Since</th></tr>
                    </thead>
                    <tbody>
                        {currencies.map(c => (
                            <tr key={c.code}>
                                <td><strong>{c.code}</strong> {c.name}{!c.active && ' (inactive)'}</td>
                                <td>{c.symbol}</td>
                                <td>{c.minor_units}</td>
                                <td>{c.gateway ?? '—'}</td>
                                <td>{c.current_rate ? c.current_rate.units_per_usd.toLocaleString('en-IN', { maximumFractionDigits: 6 }) : '—'}</td>
                                <td>{c.current_rate?.effective_from ? parseServerDate(c.current_rate.effective_from).toLocaleString() : '—'}</td>
                            </tr>
                        ))}
                    </tbody>
                </table>
                <AddRateForm currencies={currencies.filter(c => c.code !== 'USD')}
                             onAdded={() => { setNotice('Rate added.'); load(); }}
                             onError={(m) => setError(m)} />
            </section>

            <section className="currency-card glass">
                <h2><History size={18} /> Rate history</h2>
                <table className="currency-table">
                    <thead><tr><th>Currency</th><th>Per USD</th><th>From</th><th>Reason</th><th>Added</th></tr></thead>
                    <tbody>
                        {rates.map(r => (
                            <tr key={r.id}>
                                <td>{r.currency}</td>
                                <td>{r.units_per_usd.toLocaleString('en-IN', { maximumFractionDigits: 6 })}</td>
                                <td>{r.effective_from ? parseServerDate(r.effective_from).toLocaleString() : '—'}</td>
                                <td>{r.reason ?? '—'}</td>
                                <td>{r.created_at ? parseServerDate(r.created_at).toLocaleString() : '—'}</td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </section>

            <CountryProfiles profiles={profiles} currencies={activeCodes}
                             onSaved={(p) => { setProfiles(ps => ps.map(x => x.country_code === p.country_code ? p : x)); setNotice(`${p.name} saved.`); }}
                             onError={(m) => setError(m)} />
        </div>
    );
};

const AddRateForm: React.FC<{
    currencies: CurrencyRow[];
    onAdded: () => void;
    onError: (message: string) => void;
}> = ({ currencies, onAdded, onError }) => {
    const [currency, setCurrency] = useState(currencies[0]?.code ?? 'INR');
    const [value, setValue] = useState('');
    const [effective, setEffective] = useState('');
    const [reason, setReason] = useState('');
    const [preview, setPreview] = useState<FxPreview | null>(null);
    const [busy, setBusy] = useState(false);

    const rate = Number(value);
    useEffect(() => {
        if (!(rate > 0)) { setPreview(null); return; }
        const timer = setTimeout(() => {
            currencyService.previewRate(currency, rate).then(setPreview).catch(() => setPreview(null));
        }, 300);
        return () => clearTimeout(timer);
    }, [currency, rate]);

    const submit = async (e: React.FormEvent) => {
        e.preventDefault();
        setBusy(true);
        try {
            await currencyService.addRate({
                currency, units_per_usd: rate, reason: reason.trim(),
                ...(effective ? { effective_from: localInputToIso(effective) } : {}),
            });
            setValue('');
            setReason('');
            setEffective('');
            onAdded();
        } catch (err) {
            onError(apiErrorMessage(err, 'Failed to add the rate'));
        } finally {
            setBusy(false);
        }
    };

    return (
        <form className="add-rate" onSubmit={submit}>
            <h3>Add a rate</h3>
            <div className="add-rate__fields">
                <label>Currency
                    <select value={currency} onChange={(e) => setCurrency(e.target.value)}>
                        {currencies.map(c => <option key={c.code} value={c.code}>{c.code}</option>)}
                    </select>
                </label>
                <label>Units per USD
                    <input type="number" min="0" step="any" value={value} onChange={(e) => setValue(e.target.value)} required />
                </label>
                <label>Effective from (blank: now)
                    <input type="datetime-local" value={effective} onChange={(e) => setEffective(e.target.value)} />
                </label>
                <label className="add-rate__reason">Reason (kept in the history)
                    <input type="text" value={reason} onChange={(e) => setReason(e.target.value)} minLength={3} required />
                </label>
            </div>
            {preview && (
                <div className="add-rate__preview">
                    <p>
                        {preview.change_pct >= 0 ? '+' : ''}{preview.change_pct.toFixed(2)}% against today's
                        {' '}{preview.current_units_per_usd.toLocaleString('en-IN')} per USD. New charges, holds and
                        payments use the new rate from its start; money already charged keeps its rate.
                    </p>
                    <ul>
                        {preview.examples.map(x => (
                            <li key={x.usd}>
                                {formatMoney(x.usd, 'USD')}: {formatMoney(x.current, preview.currency)} → <strong>{formatMoney(x.proposed, preview.currency)}</strong>
                            </li>
                        ))}
                    </ul>
                </div>
            )}
            <button type="submit" className="btn-primary" disabled={busy || !(rate > 0) || reason.trim().length < 3}>
                <Save size={14} /> {busy ? 'Adding…' : 'Add rate'}
            </button>
        </form>
    );
};

const CountryProfiles: React.FC<{
    profiles: CountryProfileRow[];
    currencies: string[];
    onSaved: (profile: CountryProfileRow) => void;
    onError: (message: string) => void;
}> = ({ profiles, currencies, onSaved, onError }) => {
    const [filter, setFilter] = useState('');
    const shown = useMemo(() => {
        const q = filter.trim().toLowerCase();
        return q ? profiles.filter(p => p.name.toLowerCase().includes(q) || p.country_code.toLowerCase() === q) : profiles;
    }, [profiles, filter]);

    const save = async (profile: CountryProfileRow, patch: Partial<CountryProfileRow>) => {
        try {
            onSaved(await currencyService.putCountryProfile(profile.country_code, patch));
        } catch (err) {
            onError(apiErrorMessage(err, `Failed to save ${profile.name}`));
        }
    };

    return (
        <section className="currency-card glass">
            <h2><Globe2 size={18} /> Country profiles</h2>
            <p className="card-desc">What a company made in each country gets. Existing companies keep theirs.</p>
            <input className="country-filter" placeholder="Find a country" value={filter} onChange={(e) => setFilter(e.target.value)} />
            <div className="country-table-wrap">
                <table className="currency-table">
                    <thead><tr><th>Country</th><th>Currency</th><th>Time zone</th><th>Phone code</th><th>Tax regime</th></tr></thead>
                    <tbody>
                        {shown.map(p => (
                            <tr key={p.country_code}>
                                <td>{p.name} <span className="muted">{p.country_code}</span></td>
                                <td>
                                    <select value={p.billing_currency} onChange={(e) => save(p, { billing_currency: e.target.value })}>
                                        {currencies.map(c => <option key={c} value={c}>{c}</option>)}
                                    </select>
                                </td>
                                <td>{p.default_timezone}</td>
                                <td>{p.phone_country_code ?? '—'}</td>
                                <td>
                                    <select value={p.tax_regime} onChange={(e) => save(p, { tax_regime: e.target.value as CountryProfileRow['tax_regime'] })}>
                                        {TAX_REGIMES.map(t => <option key={t} value={t}>{t}</option>)}
                                    </select>
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
        </section>
    );
};

export default CurrencyPage;
