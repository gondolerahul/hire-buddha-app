/**
 * pages/admin/DailyCreditsPage — daily-credit policies and overrides, for staff (Phase 15 T5-5, T5-6; 07 §5.5).
 *
 * A policy gives a company USD amounts by day of its life (bands), for a
 * duration; direct tenants get the `direct` policy, a partner's tenants their
 * partner's (or `all_partners`). The preview shows the amounts per day in a
 * currency. A company override gives one company its own amount, or none.
 * Changes apply from the next local midnight. Lives under /admin/daily-credits
 * until the Platform Console shell (T9-1).
 */
import React, { useCallback, useEffect, useState } from 'react';
import { CalendarClock, Plus, Save, Trash2 } from 'lucide-react';

import { apiErrorMessage } from '@/utils/apiError';
import { formatMoney } from '@/utils/money';
import {
    CompanyDailyCredits, DailyBand, DailyOverride, DailyPolicy, DailyPolicyBody, DailyPreviewRow, moneyConsole,
} from '@/services/moneyConsole.service';

import './MoneyConsole.css';

const DURATIONS = [0, 10, 15, 30, 60, 90, 180, 365];
const AUDIENCE_LABEL: Record<DailyPolicy['audience'], string> = {
    direct: 'Direct tenants', partner: "One partner's tenants", all_partners: "Partners' tenants (default)",
};

const EMPTY: DailyPolicyBody = {
    name: '', audience: 'direct', partner_id: null, duration_days: 30, active: true,
    bands: [{ from_day: 1, to_day: 30, amount_usd: '1.00' }],
};

export const DailyCreditsPage: React.FC = () => {
    const [policies, setPolicies] = useState<DailyPolicy[]>([]);
    const [overrides, setOverrides] = useState<DailyOverride[]>([]);
    const [editing, setEditing] = useState<{ id: string | null; body: DailyPolicyBody } | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [notice, setNotice] = useState<string | null>(null);

    const load = useCallback(async () => {
        try {
            const [p, o] = await Promise.all([moneyConsole.listPolicies(), moneyConsole.listOverrides()]);
            setPolicies(p);
            setOverrides(o);
            setError(null);
        } catch (err) {
            setError(apiErrorMessage(err, 'Failed to load daily credits'));
        }
    }, []);

    useEffect(() => { load(); }, [load]);

    const save = async () => {
        if (!editing) return;
        try {
            if (editing.id) await moneyConsole.updatePolicy(editing.id, editing.body);
            else await moneyConsole.createPolicy(editing.body);
            setNotice(`${editing.body.name} saved. It applies from each company's next local midnight.`);
            setEditing(null);
            await load();
        } catch (err) {
            setError(apiErrorMessage(err, 'The policy was not saved'));
        }
    };

    const deactivate = async (policy: DailyPolicy) => {
        if (!confirm(`Deactivate ${policy.name}? Its companies get the next policy that applies, or none.`)) return;
        try {
            await moneyConsole.deactivatePolicy(policy.id);
            await load();
        } catch (err) {
            setError(apiErrorMessage(err, 'The policy was not deactivated'));
        }
    };

    return (
        <div className="money-console">
            <div className="page-header">
                <div>
                    <h1 className="page-title"><CalendarClock size={22} /> Daily credits</h1>
                    <p className="page-subtitle">
                        Free credit granted at 00:00 in each company's time zone, replacing the day before's.
                        It never repays debt and is not commissionable.
                    </p>
                </div>
                <button className="btn-primary" onClick={() => setEditing({ id: null, body: { ...EMPTY } })}>
                    <Plus size={14} /> New policy
                </button>
            </div>

            {error && <div className="error-banner">{error}</div>}
            {notice && <div className="success-banner">{notice}</div>}

            <section className="money-card glass">
                <h2>Policies</h2>
                <table className="money-table">
                    <thead><tr><th>Name</th><th>Who</th><th>Days</th><th>Bands (USD a day)</th><th>Active</th><th /></tr></thead>
                    <tbody>
                        {policies.map(p => (
                            <tr key={p.id}>
                                <td>{p.name}</td>
                                <td>{AUDIENCE_LABEL[p.audience]}{p.partner_name ? `: ${p.partner_name}` : ''}</td>
                                <td>{p.duration_days ?? 'no end'}</td>
                                <td>
                                    {p.bands.length === 0 ? <span className="muted">none</span> : p.bands.map(b => (
                                        <div key={b.from_day}>days {b.from_day}–{b.to_day >= 100000 ? '…' : b.to_day}: {formatMoney(b.amount_usd, 'USD')}</div>
                                    ))}
                                </td>
                                <td>{p.active ? 'yes' : 'no'}</td>
                                <td>
                                    <button className="btn-secondary" onClick={() => setEditing({ id: p.id, body: {
                                        name: p.name, audience: p.audience, partner_id: p.partner_id,
                                        duration_days: p.duration_days ?? 365, active: p.active, bands: p.bands,
                                    } })}>Edit</button>
                                    {p.active && (
                                        <button className="btn-secondary" onClick={() => deactivate(p)} aria-label="Deactivate">
                                            <Trash2 size={14} />
                                        </button>
                                    )}
                                </td>
                            </tr>
                        ))}
                        {policies.length === 0 && <tr><td colSpan={6} className="muted">No policies: nobody gets daily credits.</td></tr>}
                    </tbody>
                </table>
            </section>

            {editing && (
                <PolicyEditor value={editing.body} onChange={(body) => setEditing({ ...editing, body })}
                              onSave={save} onCancel={() => setEditing(null)} />
            )}

            <Overrides overrides={overrides} onChanged={async (m) => { setNotice(m); await load(); }} onError={setError} />
        </div>
    );
};

const PolicyEditor: React.FC<{
    value: DailyPolicyBody;
    onChange: (value: DailyPolicyBody) => void;
    onSave: () => void;
    onCancel: () => void;
}> = ({ value, onChange, onSave, onCancel }) => {
    const [currency, setCurrency] = useState('INR');
    const [preview, setPreview] = useState<DailyPreviewRow[]>([]);
    const [problem, setProblem] = useState<string | null>(null);

    useEffect(() => {
        const timer = setTimeout(() => {
            moneyConsole.previewPolicy({ duration_days: value.duration_days, bands: value.bands, currency })
                .then((rows) => { setPreview(rows); setProblem(null); })
                .catch((err) => { setPreview([]); setProblem(apiErrorMessage(err, 'The bands are not valid')); });
        }, 300);
        return () => clearTimeout(timer);
    }, [value.duration_days, value.bands, currency]);

    const band = (i: number, patch: Partial<DailyBand>) =>
        onChange({ ...value, bands: value.bands.map((b, j) => (j === i ? { ...b, ...patch } : b)) });

    return (
        <section className="money-card glass">
            <h2>{value.name || 'New policy'}</h2>
            <div className="money-form">
                <label className="grow">Name
                    <input type="text" value={value.name} onChange={(e) => onChange({ ...value, name: e.target.value })} />
                </label>
                <label>Who
                    <select value={value.audience}
                            onChange={(e) => onChange({ ...value, audience: e.target.value as DailyPolicy['audience'],
                                                        partner_id: e.target.value === 'partner' ? value.partner_id : null })}>
                        {Object.entries(AUDIENCE_LABEL).map(([k, label]) => <option key={k} value={k}>{label}</option>)}
                    </select>
                </label>
                {value.audience === 'partner' && (
                    <label>Partner company id
                        <input type="text" value={value.partner_id ?? ''}
                               onChange={(e) => onChange({ ...value, partner_id: e.target.value.trim() || null })} />
                    </label>
                )}
                <label>Days from sign-up
                    <select value={value.duration_days ?? 365}
                            onChange={(e) => onChange({ ...value, duration_days: Number(e.target.value) })}>
                        {DURATIONS.map(d => <option key={d} value={d}>{d === 0 ? '0 (none)' : d}</option>)}
                    </select>
                </label>
                <label>Active
                    <select value={value.active ? 'yes' : 'no'} onChange={(e) => onChange({ ...value, active: e.target.value === 'yes' })}>
                        <option value="yes">yes</option><option value="no">no</option>
                    </select>
                </label>
            </div>

            <h3>Bands</h3>
            {value.bands.map((b, i) => (
                <div className="band-row" key={i}>
                    <span className="muted">days</span>
                    <input type="number" min="1" value={b.from_day} onChange={(e) => band(i, { from_day: Number(e.target.value) })} />
                    <span className="muted">to</span>
                    <input type="number" min="1" value={b.to_day} onChange={(e) => band(i, { to_day: Number(e.target.value) })} />
                    <span className="muted">USD a day</span>
                    <input type="text" inputMode="decimal" value={b.amount_usd} onChange={(e) => band(i, { amount_usd: e.target.value })} />
                    <button className="btn-secondary" aria-label="Remove band"
                            onClick={() => onChange({ ...value, bands: value.bands.filter((_, j) => j !== i) })}>
                        <Trash2 size={14} />
                    </button>
                </div>
            ))}
            <button className="btn-secondary" onClick={() => {
                const last = value.bands[value.bands.length - 1];
                const from = last ? last.to_day + 1 : 1;
                onChange({ ...value, bands: [...value.bands, { from_day: from, to_day: Math.max(from, value.duration_days ?? from), amount_usd: '0.50' }] });
            }}><Plus size={14} /> Add band</button>

            <h3>Preview</h3>
            <div className="money-toolbar">
                <span className="muted">in</span>
                <select value={currency} onChange={(e) => setCurrency(e.target.value)}>
                    <option value="INR">INR</option><option value="USD">USD</option>
                </select>
            </div>
            {problem ? <div className="error-banner">{problem}</div> : (
                <table className="money-table">
                    <thead><tr><th>Days</th><th>A day</th></tr></thead>
                    <tbody>
                        {preview.map(r => (
                            <tr key={r.from_day}><td>{r.from_day}–{r.to_day}</td><td>{formatMoney(r.amount, r.currency)} ({formatMoney(r.amount_usd, 'USD')})</td></tr>
                        ))}
                        {preview.length === 0 && <tr><td colSpan={2} className="muted">Nothing is granted.</td></tr>}
                    </tbody>
                </table>
            )}
            <div className="money-form">
                <button className="btn-primary" onClick={onSave} disabled={!value.name.trim() || !!problem}>
                    <Save size={14} /> Save policy
                </button>
                <button className="btn-secondary" onClick={onCancel}>Cancel</button>
            </div>
        </section>
    );
};

const Overrides: React.FC<{
    overrides: DailyOverride[];
    onChanged: (message: string) => Promise<void>;
    onError: (message: string) => void;
}> = ({ overrides, onChanged, onError }) => {
    const [companyId, setCompanyId] = useState('');
    const [mode, setMode] = useState<'custom' | 'none' | 'policy'>('custom');
    const [amount, setAmount] = useState('');
    const [days, setDays] = useState('');
    const [reason, setReason] = useState('');
    const [today, setToday] = useState<CompanyDailyCredits | null>(null);

    const check = async () => {
        try {
            setToday(await moneyConsole.companyDailyCredits(companyId.trim()));
        } catch (err) {
            onError(apiErrorMessage(err, 'No such company'));
        }
    };

    const submit = async (e: React.FormEvent) => {
        e.preventDefault();
        try {
            await moneyConsole.putOverride(companyId.trim(), {
                mode, reason: reason.trim(), amount_usd: mode === 'custom' ? amount.trim() : null,
                duration_days: days ? Number(days) : null,
            });
            setReason('');
            await onChanged('Override saved.');
            await check();
        } catch (err) {
            onError(apiErrorMessage(err, 'The override was not saved'));
        }
    };

    const remove = async (o: DailyOverride) => {
        try {
            await moneyConsole.deleteOverride(o.company_id);
            await onChanged(`${o.company_name ?? 'The company'} follows the policies again.`);
        } catch (err) {
            onError(apiErrorMessage(err, 'The override was not removed'));
        }
    };

    return (
        <section className="money-card glass">
            <h2>Company overrides</h2>
            <p className="card-desc">One company's own daily amount, or none, whatever its policy.</p>
            <table className="money-table">
                <thead><tr><th>Company</th><th>Gets</th><th>For</th><th>Why</th><th /></tr></thead>
                <tbody>
                    {overrides.map(o => (
                        <tr key={o.company_id}>
                            <td>{o.company_name}</td>
                            <td>{o.mode === 'custom' ? `${formatMoney(o.amount_usd, 'USD')} a day` : o.mode === 'none' ? 'nothing' : 'its policy'}</td>
                            <td>{o.duration_days != null ? `${o.duration_days} days` : 'no end'}</td>
                            <td className="muted">{o.reason}</td>
                            <td><button className="btn-secondary" onClick={() => remove(o)} aria-label="Remove override"><Trash2 size={14} /></button></td>
                        </tr>
                    ))}
                    {overrides.length === 0 && <tr><td colSpan={5} className="muted">None.</td></tr>}
                </tbody>
            </table>

            <h3>Check or set one company</h3>
            <form className="money-form" onSubmit={submit}>
                <label className="grow">Company id
                    <input type="text" value={companyId} onChange={(e) => setCompanyId(e.target.value)} required />
                </label>
                <button type="button" className="btn-secondary" onClick={check} disabled={!companyId.trim()}>What it gets today</button>
                <label>Override
                    <select value={mode} onChange={(e) => setMode(e.target.value as typeof mode)}>
                        <option value="custom">its own amount</option>
                        <option value="none">nothing</option>
                        <option value="policy">its policy (recorded)</option>
                    </select>
                </label>
                {mode === 'custom' && (
                    <label>USD a day
                        <input type="text" inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} required />
                    </label>
                )}
                <label>For days (blank: no end)
                    <input type="number" min="0" value={days} onChange={(e) => setDays(e.target.value)} />
                </label>
                <label className="grow">Reason
                    <input type="text" value={reason} onChange={(e) => setReason(e.target.value)} minLength={3} required />
                </label>
                <button type="submit" className="btn-primary" disabled={!companyId.trim()}>Save override</button>
            </form>
            {today && (
                <p className="card-desc" style={{ marginTop: '0.75rem' }}>
                    {today.company_name} (day {today.day}, {today.timezone}): {formatMoney(today.amount, today.currency)} today
                    — {today.source.replace('_', ' ')}{today.policy_name ? `: ${today.policy_name}` : ''}.
                </p>
            )}
        </section>
    );
};

export default DailyCreditsPage;
