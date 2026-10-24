/**
 * pages/admin/MoneySettingsPage — the money settings, for staff (Phase 15 T5-1, T5-6; 06 §8.4, 07 §5.5).
 *
 * Wallet & admission policy and the platform's money settings: every key of the
 * catalogue with its value, where the value comes from (company → partner →
 * plan → platform → default) and its history. Staff set the platform value, or
 * a company's own where the key allows it. Amounts are USD (K-16). Lives under
 * /admin/money-settings until the Platform Console shell (T9-1).
 */
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { History, RotateCcw, Save, SlidersHorizontal } from 'lucide-react';

import { apiErrorMessage } from '@/utils/apiError';
import { formatDateTime } from '@/utils/datetime';
import { MoneySetting, SettingChange, moneyConsole } from '@/services/moneyConsole.service';

import './MoneyConsole.css';

const GROUP_LABEL: Record<string, string> = {
    admission: 'Admission (free credit needed to start)',
    wallet: 'Wallet and top-ups',
    billing: 'Billing and enforcement',
    voice: 'Calls',
    alerts: 'Alerts',
    daily_credits: 'Daily credits',
    currency: 'Currency',
    tax: 'Tax and invoices',
    payments: 'Payments',
    partners: 'Partner programme',
    rollout: 'Rollout (switches for the Phase 15 cutover)',
};

function shown(value: unknown): string {
    if (value === null || value === undefined) return '—';
    if (Array.isArray(value)) return value.join(', ');
    return String(value);
}

function parse(setting: MoneySetting, raw: string): unknown {
    if (setting.type === 'bool') return raw === 'true';
    if (setting.type === 'int') return raw.trim() === '' ? null : Number(raw);
    if (setting.type === 'usd_list') return raw.split(',').map(s => s.trim()).filter(Boolean);
    if (raw.trim() === '' && setting.nullable) return null;
    return raw.trim();
}

/** `groups`: show only these setting groups (the console splits wallet policy and tax onto their own pages). */
export const MoneySettingsPage: React.FC<{ groups?: string[] }> = ({ groups: only }) => {
    const [companyId, setCompanyId] = useState('');
    const [scopeCompany, setScopeCompany] = useState<string | null>(null);
    const [settings, setSettings] = useState<MoneySetting[]>([]);
    const [error, setError] = useState<string | null>(null);
    const [notice, setNotice] = useState<string | null>(null);

    const load = useCallback(async () => {
        try {
            setSettings(await moneyConsole.listSettings(scopeCompany ?? undefined));
            setError(null);
        } catch (err) {
            setError(apiErrorMessage(err, 'Failed to load settings'));
        }
    }, [scopeCompany]);

    useEffect(() => { load(); }, [load]);

    const groups = useMemo(() => {
        const out: Record<string, MoneySetting[]> = {};
        for (const s of settings) if (!only || only.includes(s.group)) (out[s.group] ??= []).push(s);
        return out;
    }, [settings, only]);

    return (
        <div className="money-console">
            <div className="page-header">
                <div>
                    <h1 className="page-title"><SlidersHorizontal size={22} /> Money settings</h1>
                    <p className="page-subtitle">
                        Wallet and admission policy and the platform's money settings. Amounts are USD and convert at
                        today's rate. Every change is audited.
                    </p>
                </div>
            </div>
            {error && <div className="error-banner">{error}</div>}
            {notice && <div className="success-banner">{notice}</div>}

            <section className="money-card glass">
                <form className="money-form" onSubmit={(e) => { e.preventDefault(); setScopeCompany(companyId.trim() || null); }}>
                    <label className="grow">Show the values one company gets (company id; blank: the platform's)
                        <input type="text" value={companyId} onChange={(e) => setCompanyId(e.target.value)} />
                    </label>
                    <button className="btn-secondary" type="submit">Show</button>
                </form>
                {scopeCompany && <p className="card-desc">Editing sets this company's own value where the setting allows it.</p>}
            </section>

            {Object.entries(groups).map(([group, rows]) => (
                <section className="money-card glass" key={group}>
                    <h2>{GROUP_LABEL[group] ?? group}</h2>
                    <table className="money-table">
                        <thead><tr><th>Setting</th><th>Value</th><th>From</th><th>Default</th><th>Change</th></tr></thead>
                        <tbody>
                            {rows.map(s => (
                                <SettingRow key={s.key} setting={s} company={scopeCompany}
                                            onSaved={async (m) => { setNotice(m); await load(); }} onError={setError} />
                            ))}
                        </tbody>
                    </table>
                </section>
            ))}
        </div>
    );
};

const SettingRow: React.FC<{
    setting: MoneySetting;
    company: string | null;
    onSaved: (message: string) => Promise<void>;
    onError: (message: string) => void;
}> = ({ setting, company, onSaved, onError }) => {
    const [value, setValue] = useState(shown(setting.value) === '—' ? '' : shown(setting.value));
    const [history, setHistory] = useState<SettingChange[] | null>(null);
    const scope = company && setting.scopes.includes('company') ? 'company' : 'platform';
    const editable = !company || scope === 'company';

    useEffect(() => { setValue(shown(setting.value) === '—' ? '' : shown(setting.value)); }, [setting.value]);

    const save = async () => {
        try {
            await moneyConsole.putSetting(setting.key, {
                value: parse(setting, value), scope, scope_id: scope === 'company' ? company : null,
            });
            await onSaved(`${setting.key} saved${scope === 'company' ? ' for the company' : ''}.`);
        } catch (err) {
            onError(apiErrorMessage(err, `${setting.key} was not saved`));
        }
    };

    const clear = async () => {
        try {
            await moneyConsole.deleteSetting(setting.key, scope, scope === 'company' ? company : null);
            await onSaved(`${setting.key}: the next scope's value applies again.`);
        } catch (err) {
            onError(apiErrorMessage(err, `${setting.key} was not cleared`));
        }
    };

    const setHere = setting.source === scope;
    return (
        <>
            <tr>
                <td>
                    <strong>{setting.key}</strong>{setting.unit ? <span className="muted"> ({setting.unit})</span> : null}
                    <div className="muted">{setting.help}</div>
                </td>
                <td>{shown(setting.value)}</td>
                <td><span className={`source-tag ${setting.source !== 'default' ? 'set' : ''}`}>{setting.source}</span></td>
                <td className="muted">{shown(setting.default)}</td>
                <td>
                    {editable ? (
                        <div className="band-row">
                            {setting.type === 'bool' || setting.type === 'choice' ? (
                                <select value={value} onChange={(e) => setValue(e.target.value)}>
                                    {(setting.type === 'bool' ? ['true', 'false'] : setting.choices).map(c => <option key={c} value={c}>{c}</option>)}
                                </select>
                            ) : (
                                <input type="text" value={value} onChange={(e) => setValue(e.target.value)}
                                       placeholder={setting.nullable ? 'none' : ''} />
                            )}
                            <button className="btn-secondary" onClick={save} aria-label="Save"><Save size={14} /></button>
                            {setHere && <button className="btn-secondary" onClick={clear} aria-label="Clear"><RotateCcw size={14} /></button>}
                            <button className="btn-secondary" aria-label="History"
                                    onClick={async () => setHistory(history ? null : await moneyConsole.settingHistory(setting.key))}>
                                <History size={14} />
                            </button>
                        </div>
                    ) : <span className="muted">platform only</span>}
                </td>
            </tr>
            {history && (
                <tr>
                    <td colSpan={5}>
                        {history.length === 0 ? <span className="muted">Never changed.</span> : history.map((h, i) => (
                            <div key={i} className="muted">
                                {h.at ? formatDateTime(h.at) : ''} — {h.action} at {h.scope?.scope ?? 'platform'}:
                                {' '}{shown(h.old_value)} → {shown(h.new_value)}{h.reason ? ` (${h.reason})` : ''}
                            </div>
                        ))}
                    </td>
                </tr>
            )}
        </>
    );
};

export default MoneySettingsPage;
