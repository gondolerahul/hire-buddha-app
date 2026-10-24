/**
 * pages/admin/PricingPage — fixed prices, for staff (Phase 15 T5-3, T5-6; O-2, 07 §5.5).
 *
 * Each price item has a USD amount and, per currency, an optional override
 * (blank = follow FX): the phone-number rent is USD 20 and ₹2,000 for Indian
 * tenants. An edit is a new version; it applies from each item's next charge
 * (a rental already charged for its period is not re-priced). The usage price
 * formula is on Billing Settings. Lives under /admin/pricing until the Platform
 * Console shell (T9-1).
 */
import React, { useCallback, useEffect, useState } from 'react';
import { History, Save, Tag } from 'lucide-react';

import { apiErrorMessage } from '@/utils/apiError';
import { formatDateTime } from '@/utils/datetime';
import { formatMoney } from '@/utils/money';
import { moneyConsole, PriceItem, PriceItemVersion } from '@/services/moneyConsole.service';

import './MoneyConsole.css';

const CURRENCIES = ['INR', 'USD'];

export const PricingPage: React.FC = () => {
    const [items, setItems] = useState<PriceItem[]>([]);
    const [error, setError] = useState<string | null>(null);
    const [notice, setNotice] = useState<string | null>(null);

    const load = useCallback(async () => {
        try {
            setItems(await moneyConsole.listPriceItems());
            setError(null);
        } catch (err) {
            setError(apiErrorMessage(err, 'Failed to load prices'));
        }
    }, []);

    useEffect(() => { load(); }, [load]);

    return (
        <div className="money-console">
            <div className="page-header">
                <div>
                    <h1 className="page-title"><Tag size={22} /> Pricing</h1>
                    <p className="page-subtitle">
                        Fixed prices — not rated by the usage formula. An edit is a new version, charged from each
                        item's next charge. The usage formula (mf, pf, d) is on <a href="/settings/billing">Billing Settings</a>.
                    </p>
                </div>
            </div>
            {error && <div className="error-banner">{error}</div>}
            {notice && <div className="success-banner">{notice}</div>}
            {items.map(item => (
                <PriceItemCard key={item.code} item={item}
                               onSaved={(saved) => { setItems(xs => xs.map(x => (x.code === saved.code ? saved : x)));
                                                     setNotice(`${saved.name}: version ${saved.version} saved.`); }}
                               onError={setError} />
            ))}
        </div>
    );
};

const PriceItemCard: React.FC<{
    item: PriceItem;
    onSaved: (item: PriceItem) => void;
    onError: (message: string) => void;
}> = ({ item, onSaved, onError }) => {
    const [usd, setUsd] = useState(item.amount_usd);
    const [overrides, setOverrides] = useState<Record<string, string>>(item.currency_overrides ?? {});
    const [active, setActive] = useState(item.active);
    const [reason, setReason] = useState('');
    const [versions, setVersions] = useState<PriceItemVersion[] | null>(null);
    const [busy, setBusy] = useState(false);

    const save = async (e: React.FormEvent) => {
        e.preventDefault();
        setBusy(true);
        try {
            const body = Object.fromEntries(CURRENCIES.filter(c => c !== 'USD')
                .map(c => [c, overrides[c]?.trim() ? overrides[c].trim() : null]));
            const saved = await moneyConsole.putPriceItem(item.code, {
                amount_usd: usd.trim(), currency_overrides: body, active, reason: reason.trim() || undefined,
            });
            setReason('');
            setVersions(null);
            onSaved(saved);
        } catch (err) {
            onError(apiErrorMessage(err, `${item.name} was not saved`));
        } finally {
            setBusy(false);
        }
    };

    return (
        <section className="money-card glass">
            <h2>{item.name} <span className="muted">{item.code} · v{item.version}
                {item.interval ? ` · per ${item.interval}` : ''}{item.active ? '' : ' · inactive'}</span></h2>
            <p className="card-desc">
                Today: {Object.entries(item.prices).map(([code, p]) =>
                    `${formatMoney(p.amount, code)}${code === 'USD' ? '' : p.overridden ? ' (set)' : ' (at FX)'}`).join(' · ') || 'not priced'}
            </p>
            <form className="money-form" onSubmit={save}>
                <label>USD
                    <input type="text" inputMode="decimal" value={usd} onChange={(e) => setUsd(e.target.value)} required />
                </label>
                {CURRENCIES.filter(c => c !== 'USD').map(code => (
                    <label key={code}>{code} (blank: follow FX)
                        <input type="text" inputMode="decimal" value={overrides[code] ?? ''}
                               onChange={(e) => setOverrides({ ...overrides, [code]: e.target.value })} />
                    </label>
                ))}
                <label>Active
                    <select value={active ? 'yes' : 'no'} onChange={(e) => setActive(e.target.value === 'yes')}>
                        <option value="yes">yes</option><option value="no">no</option>
                    </select>
                </label>
                <label className="grow">Reason (kept with the version)
                    <input type="text" value={reason} onChange={(e) => setReason(e.target.value)} />
                </label>
                <button type="submit" className="btn-primary" disabled={busy}><Save size={14} /> Save</button>
                <button type="button" className="btn-secondary"
                        onClick={async () => setVersions(versions ? null : await moneyConsole.priceItemVersions(item.code))}>
                    <History size={14} /> Versions
                </button>
            </form>
            {versions && (
                <table className="money-table" style={{ marginTop: '1rem' }}>
                    <thead><tr><th>Version</th><th>USD</th><th>Overrides</th><th>Active</th><th>Reason</th><th>When</th></tr></thead>
                    <tbody>
                        {versions.map(v => (
                            <tr key={v.version}>
                                <td>v{v.version}</td>
                                <td>{formatMoney(v.amount_usd, 'USD')}</td>
                                <td>{Object.entries(v.currency_overrides).map(([c, a]) => formatMoney(a, c)).join(', ') || '—'}</td>
                                <td>{v.active ? 'yes' : 'no'}</td>
                                <td className="muted">{v.reason ?? '—'}</td>
                                <td>{v.created_at ? formatDateTime(v.created_at) : ''}</td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            )}
        </section>
    );
};

export default PricingPage;
