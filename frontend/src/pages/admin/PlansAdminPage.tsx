/**
 * pages/admin/PlansAdminPage — plans and entitlements, for staff (Phase 15 T6-1, T6-2, T6-7; 07 §5.4).
 *
 * * Plans: name, monthly fee (USD, with an optional fixed price per currency),
 *   bonus and the plan's negative tolerance. A price, bonus or name change is
 *   a new version: a subscriber moves to it at their next renewal. Pay-as-you-go
 *   (level 0) has no fee and cannot be archived; an archived plan takes no new
 *   subscribers and keeps its existing ones.
 * * Entitlements: the plan × feature matrix. Before a save, the impact — how
 *   many companies would lose a feature or get a lower limit — is shown.
 * * One company: its entitlements with their source, and overrides (a feature
 *   or limit for that company only, optionally until a date).
 */
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Archive, History, Layers, Plus, Save, ShieldCheck } from 'lucide-react';

import {
    AdminPlan, EntitlementChange, EntitlementValue, FeatureSpec, ImpactLine, plansService, PlanVersionRow,
} from '@/services/plans.service';
import { useCompanyList } from '@/queries/hooks';
import { apiErrorMessage } from '@/utils/apiError';
import { formatDateTime } from '@/utils/datetime';
import { formatMoney } from '@/utils/money';

import './MoneyConsole.css';

type Matrix = Record<string, Record<string, EntitlementValue>>;

export const PlansAdminPage: React.FC = () => {
    const [plans, setPlans] = useState<AdminPlan[]>([]);
    const [features, setFeatures] = useState<FeatureSpec[]>([]);
    const [matrix, setMatrix] = useState<Matrix>({});
    const [error, setError] = useState<string | null>(null);
    const [notice, setNotice] = useState<string | null>(null);

    const load = useCallback(async () => {
        try {
            const [p, f, m] = await Promise.all([plansService.adminPlans(), plansService.features(), plansService.matrix()]);
            setPlans(p);
            setFeatures(f);
            setMatrix(m);
            setError(null);
        } catch (err) {
            setError(apiErrorMessage(err, 'Plans could not be loaded'));
        }
    }, []);

    useEffect(() => { load(); }, [load]);

    return (
        <div className="money-console">
            <div className="page-header">
                <div>
                    <h1 className="page-title"><Layers size={22} /> Plans &amp; entitlements</h1>
                    <p className="page-subtitle">
                        What each plan costs and includes. A price change is a new version, charged from each
                        subscriber's next renewal; entitlements apply at once.
                    </p>
                </div>
            </div>
            {error && <div className="error-banner">{error}</div>}
            {notice && <div className="success-banner">{notice}</div>}
            <PlansCard plans={plans} onSaved={(text) => { setNotice(text); load(); }} onError={setError} />
            <MatrixCard plans={plans} features={features} matrix={matrix}
                        onSaved={(text) => { setNotice(text); load(); }} onError={setError} />
            <CompanyCard features={features} onError={setError} onNotice={setNotice} />
        </div>
    );
};

// ── plans ──────────────────────────────────────────────────────────────────

const EMPTY = { code: '', name: '', tier_level: '', monthly_fee_usd: '', inr: '', bonus_pct: '0', tolerance: '', reason: '' };

const PlansCard: React.FC<{ plans: AdminPlan[]; onSaved: (text: string) => void; onError: (text: string) => void }> = (
    { plans, onSaved, onError }) => {
    const [editing, setEditing] = useState<AdminPlan | 'new' | null>(null);
    const [form, setForm] = useState(EMPTY);
    const [versions, setVersions] = useState<{ plan: string; rows: PlanVersionRow[] } | null>(null);
    const [busy, setBusy] = useState(false);

    const edit = (plan: AdminPlan | 'new') => {
        setEditing(plan);
        setForm(plan === 'new' ? EMPTY : {
            code: plan.code, name: plan.name, tier_level: String(plan.tier_level), monthly_fee_usd: plan.monthly_fee_usd,
            inr: plan.currency_overrides?.INR ?? '', bonus_pct: plan.bonus_pct,
            tolerance: plan.negative_tolerance_usd ?? '', reason: '',
        });
    };

    const save = async (e: React.FormEvent) => {
        e.preventDefault();
        if (!editing) return;
        setBusy(true);
        try {
            const body: Record<string, unknown> = {
                name: form.name.trim(), monthly_fee_usd: form.monthly_fee_usd.trim() || '0', bonus_pct: form.bonus_pct.trim() || '0',
                currency_overrides: { INR: form.inr.trim() || null }, reason: form.reason.trim() || undefined,
            };
            if (form.tolerance.trim()) body.negative_tolerance_usd = form.tolerance.trim();
            if (editing === 'new') {
                await plansService.createPlan({ ...body, code: form.code.trim(), tier_level: Number(form.tier_level) });
                onSaved(`${form.name} created.`);
            } else {
                const saved = await plansService.updatePlan(editing.id, body);
                onSaved(`${saved.name}: version ${saved.version} saved.`);
            }
            setEditing(null);
        } catch (err) {
            onError(apiErrorMessage(err, 'The plan was not saved'));
        } finally {
            setBusy(false);
        }
    };

    const archive = async (plan: AdminPlan) => {
        const reason = prompt(`Archive ${plan.name}? No new subscribers; its ${plan.companies} keep it. Reason:`);
        if (reason === null) return;
        try {
            await plansService.archivePlan(plan.id, reason || undefined);
            onSaved(`${plan.name} archived.`);
        } catch (err) {
            onError(apiErrorMessage(err, 'The plan was not archived'));
        }
    };

    return (
        <section className="money-card glass">
            <h2>Plans <button className="btn-secondary" onClick={() => edit('new')}><Plus size={14} /> New plan</button></h2>
            <table className="money-table">
                <thead>
                    <tr><th>Level</th><th>Plan</th><th>Fee (USD)</th><th>INR</th><th>Bonus</th><th>Tolerance</th>
                        <th>Companies</th><th>Version</th><th /></tr>
                </thead>
                <tbody>
                    {plans.map(plan => (
                        <tr key={plan.id} className={editing !== 'new' && editing?.id === plan.id ? 'selected' : ''}>
                            <td>{plan.tier_level}</td>
                            <td>{plan.name} <span className="muted">{plan.code}{plan.active ? '' : ' · archived'}</span></td>
                            <td>{formatMoney(plan.monthly_fee_usd, 'USD')}</td>
                            <td>{formatMoney(plan.prices?.INR ?? 0, 'INR')}{plan.currency_overrides?.INR ? ' (set)' : ' (at FX)'}</td>
                            <td>{Number(plan.bonus_pct)}%</td>
                            <td>{plan.negative_tolerance_usd ? formatMoney(plan.negative_tolerance_usd, 'USD') : <span className="muted">default</span>}</td>
                            <td>{plan.companies}</td>
                            <td>v{plan.version}</td>
                            <td style={{ whiteSpace: 'nowrap' }}>
                                <button className="btn-secondary" onClick={() => edit(plan)}>Edit</button>{' '}
                                <button className="btn-secondary" title="Versions"
                                        onClick={async () => setVersions(versions?.plan === plan.id ? null
                                            : { plan: plan.id, rows: await plansService.planVersions(plan.id) })}>
                                    <History size={14} />
                                </button>{' '}
                                {plan.active && plan.tier_level > 0 && (
                                    <button className="btn-secondary" title="Archive" onClick={() => archive(plan)}><Archive size={14} /></button>
                                )}
                            </td>
                        </tr>
                    ))}
                </tbody>
            </table>
            {versions && (
                <table className="money-table" style={{ marginTop: '1rem' }}>
                    <thead><tr><th>Version</th><th>Name</th><th>USD</th><th>Overrides</th><th>Bonus</th><th>Reason</th><th>When</th></tr></thead>
                    <tbody>
                        {versions.rows.map(v => (
                            <tr key={v.version}>
                                <td>v{v.version}</td><td>{v.name}</td><td>{formatMoney(v.monthly_fee_usd, 'USD')}</td>
                                <td>{Object.entries(v.currency_overrides).map(([c, a]) => formatMoney(a, c)).join(', ') || '—'}</td>
                                <td>{Number(v.bonus_pct)}%</td><td className="muted">{v.reason ?? '—'}</td>
                                <td>{v.created_at ? formatDateTime(v.created_at) : ''}</td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            )}
            {editing && (
                <form className="money-form" onSubmit={save}>
                    {editing === 'new' && (
                        <>
                            <label>Code<input type="text" value={form.code} required pattern="[a-z][a-z0-9_]{1,39}"
                                              onChange={(e) => setForm({ ...form, code: e.target.value })} /></label>
                            <label>Level<input type="number" min={1} value={form.tier_level} required
                                               onChange={(e) => setForm({ ...form, tier_level: e.target.value })} /></label>
                        </>
                    )}
                    <label>Name<input type="text" value={form.name} required onChange={(e) => setForm({ ...form, name: e.target.value })} /></label>
                    <label>Fee (USD / month, before GST)
                        <input type="text" inputMode="decimal" value={form.monthly_fee_usd}
                               disabled={editing !== 'new' && editing.tier_level === 0}
                               onChange={(e) => setForm({ ...form, monthly_fee_usd: e.target.value })} /></label>
                    <label>INR (blank: follow FX)
                        <input type="text" inputMode="decimal" value={form.inr}
                               disabled={editing !== 'new' && editing.tier_level === 0}
                               onChange={(e) => setForm({ ...form, inr: e.target.value })} /></label>
                    <label>Bonus %<input type="text" inputMode="decimal" value={form.bonus_pct}
                                         onChange={(e) => setForm({ ...form, bonus_pct: e.target.value })} /></label>
                    <label>Negative tolerance (USD)<input type="text" inputMode="decimal" value={form.tolerance} placeholder="default"
                                                          onChange={(e) => setForm({ ...form, tolerance: e.target.value })} /></label>
                    <label className="grow">Reason (kept with the version)
                        <input type="text" value={form.reason} onChange={(e) => setForm({ ...form, reason: e.target.value })} /></label>
                    <button type="submit" className="btn-primary" disabled={busy}><Save size={14} /> Save</button>
                    <button type="button" className="btn-secondary" onClick={() => setEditing(null)}>Cancel</button>
                </form>
            )}
        </section>
    );
};

// ── the matrix ─────────────────────────────────────────────────────────────

const MatrixCard: React.FC<{
    plans: AdminPlan[]; features: FeatureSpec[]; matrix: Matrix;
    onSaved: (text: string) => void; onError: (text: string) => void;
}> = ({ plans, features, matrix, onSaved, onError }) => {
    const [planId, setPlanId] = useState<string>('');
    const [draft, setDraft] = useState<Record<string, EntitlementValue>>({});
    const [impact, setImpact] = useState<ImpactLine[] | null>(null);
    const [reason, setReason] = useState('');
    const [busy, setBusy] = useState(false);

    useEffect(() => {
        if (!planId && plans.length) setPlanId(plans[0].id);
    }, [plans, planId]);
    useEffect(() => {
        setDraft(matrix[planId] ?? {});
        setImpact(null);
    }, [matrix, planId]);

    const changes: EntitlementChange[] = useMemo(() => {
        const saved = matrix[planId] ?? {};
        return Object.entries(draft)
            .filter(([key, v]) => saved[key]?.enabled !== v.enabled || (saved[key]?.limit ?? null) !== (v.limit ?? null))
            .map(([key, v]) => ({ feature_key: key, enabled: v.enabled, limit_value: v.limit ?? null }));
    }, [draft, matrix, planId]);

    const set = (key: string, value: Partial<EntitlementValue>) => {
        setDraft(d => ({ ...d, [key]: { ...(d[key] ?? { enabled: true, limit: null }), ...value } }));
        setImpact(null);
    };

    const check = async () => {
        try {
            setImpact(await plansService.impact(planId, changes));
        } catch (err) {
            onError(apiErrorMessage(err, 'The impact could not be worked out'));
        }
    };

    const save = async () => {
        setBusy(true);
        try {
            await plansService.putEntitlements(planId, changes, reason.trim() || undefined);
            setReason('');
            onSaved(`${changes.length} entitlement${changes.length === 1 ? '' : 's'} saved.`);
        } catch (err) {
            onError(apiErrorMessage(err, 'The entitlements were not saved'));
        } finally {
            setBusy(false);
        }
    };

    const groups = useMemo(() => {
        const out: Record<string, FeatureSpec[]> = {};
        for (const f of features) (out[f.group] ??= []).push(f);
        return out;
    }, [features]);

    return (
        <section className="money-card glass">
            <h2><ShieldCheck size={18} /> Entitlements</h2>
            <div className="money-form" style={{ marginTop: 0 }}>
                <label>Plan
                    <select value={planId} onChange={(e) => setPlanId(e.target.value)}>
                        {plans.map(p => <option key={p.id} value={p.id}>{p.name} (level {p.tier_level})</option>)}
                    </select>
                </label>
                <p className="card-desc">Blank limit = no limit. Every plan includes every feature unless it is turned off here.</p>
            </div>
            <table className="money-table" style={{ marginTop: '1rem' }}>
                <thead>
                    <tr><th>Feature</th><th>Included</th><th>Limit</th>
                        {plans.filter(p => p.id !== planId).map(p => <th key={p.id} className="muted">{p.name}</th>)}</tr>
                </thead>
                <tbody>
                    {Object.entries(groups).map(([group, specs]) => (
                        <React.Fragment key={group}>
                            <tr><td colSpan={3 + plans.length} className="muted"><strong>{group}</strong></td></tr>
                            {specs.map(f => {
                                const value = draft[f.key] ?? { enabled: true, limit: f.default_limit ?? null };
                                const hasLimit = f.kind === 'limit' || !!f.limit_label;
                                return (
                                    <tr key={f.key}>
                                        <td>{f.label} <span className="muted">{f.key}</span></td>
                                        <td>
                                            {f.kind === 'feature'
                                                ? <input type="checkbox" checked={value.enabled} onChange={(e) => set(f.key, { enabled: e.target.checked })} />
                                                : <span className="muted">—</span>}
                                        </td>
                                        <td>
                                            {hasLimit
                                                ? <input type="number" min={0} style={{ width: '6rem' }} value={value.limit ?? ''}
                                                         placeholder="none"
                                                         onChange={(e) => set(f.key, { limit: e.target.value === '' ? null : Number(e.target.value) })} />
                                                : null}
                                        </td>
                                        {plans.filter(p => p.id !== planId).map(p => {
                                            const other = matrix[p.id]?.[f.key];
                                            return (
                                                <td key={p.id} className="muted">
                                                    {f.kind === 'limit' ? (other?.limit ?? '∞') : other?.enabled === false ? 'off' : 'on'}
                                                    {f.kind === 'feature' && other?.limit != null ? ` · ${other.limit}` : ''}
                                                </td>
                                            );
                                        })}
                                    </tr>
                                );
                            })}
                        </React.Fragment>
                    ))}
                </tbody>
            </table>
            <div className="money-form">
                <label className="grow">Reason (audited)
                    <input type="text" value={reason} onChange={(e) => setReason(e.target.value)} /></label>
                <button type="button" className="btn-secondary" disabled={!changes.length} onClick={check}>
                    Check impact ({changes.length})
                </button>
                <button type="button" className="btn-primary" disabled={!changes.length || impact === null || busy} onClick={save}>
                    <Save size={14} /> Save
                </button>
            </div>
            {impact && (
                <div className={impact.length ? 'error-banner' : 'success-banner'} style={{ marginTop: '0.75rem' }}>
                    {impact.length ? impact.map(i => <div key={i.feature_key}>{i.text}</div>) : 'No company loses anything with this change.'}
                </div>
            )}
        </section>
    );
};

// ── one company ────────────────────────────────────────────────────────────

const CompanyCard: React.FC<{ features: FeatureSpec[]; onError: (t: string) => void; onNotice: (t: string) => void }> = (
    { features, onError, onNotice }) => {
    const companies = (useCompanyList<{ id: string; name: string; type: string }>(true).data ?? [])
        .filter(c => c.type === 'TENANT');
    const [companyId, setCompanyId] = useState('');
    const [data, setData] = useState<Awaited<ReturnType<typeof plansService.companyEntitlements>> | null>(null);
    const [form, setForm] = useState({ key: '', enabled: true, limit: '', until: '', reason: '' });

    const load = useCallback(async (id: string) => {
        if (!id) { setData(null); return; }
        try {
            setData(await plansService.companyEntitlements(id));
        } catch (err) {
            onError(apiErrorMessage(err, 'The company could not be loaded'));
        }
    }, [onError]);

    useEffect(() => { load(companyId); }, [companyId, load]);

    const save = async (e: React.FormEvent) => {
        e.preventDefault();
        try {
            await plansService.putCompanyEntitlement(companyId, form.key, {
                enabled: form.enabled, limit_value: form.limit === '' ? null : Number(form.limit),
                until: form.until ? `${form.until}T23:59:59` : null, reason: form.reason.trim(),
            });
            onNotice('Override saved.');
            setForm({ key: '', enabled: true, limit: '', until: '', reason: '' });
            load(companyId);
        } catch (err) {
            onError(apiErrorMessage(err, 'The override was not saved'));
        }
    };

    const remove = async (key: string) => {
        try {
            await plansService.deleteCompanyEntitlement(companyId, key, 'removed in the console');
            onNotice('Override removed.');
            load(companyId);
        } catch (err) {
            onError(apiErrorMessage(err, 'The override was not removed'));
        }
    };

    const label = (key: string) => features.find(f => f.key === key)?.label ?? key;

    return (
        <section className="money-card glass">
            <h2>One company</h2>
            <div className="money-form" style={{ marginTop: 0 }}>
                <label>Company
                    <select value={companyId} onChange={(e) => setCompanyId(e.target.value)}>
                        <option value="">— choose —</option>
                        {companies.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
                    </select>
                </label>
            </div>
            {data && (
                <>
                    {data.overrides.length > 0 && (
                        <>
                            <h3>Overrides</h3>
                            <table className="money-table">
                                <thead><tr><th>Feature</th><th>Included</th><th>Limit</th><th>Until</th><th>Reason</th><th /></tr></thead>
                                <tbody>
                                    {data.overrides.map(o => (
                                        <tr key={o.feature_key}>
                                            <td>{label(o.feature_key)}</td><td>{o.enabled ? 'yes' : 'no'}</td>
                                            <td>{o.limit_value ?? '—'}</td><td>{o.until ? formatDateTime(o.until) : '—'}</td>
                                            <td className="muted">{o.reason}</td>
                                            <td><button className="btn-secondary" onClick={() => remove(o.feature_key)}>Remove</button></td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </>
                    )}
                    <form className="money-form" onSubmit={save}>
                        <label>Feature
                            <select value={form.key} required onChange={(e) => setForm({ ...form, key: e.target.value })}>
                                <option value="">— choose —</option>
                                {features.map(f => <option key={f.key} value={f.key}>{f.group}: {f.label}</option>)}
                            </select>
                        </label>
                        <label>Included
                            <select value={form.enabled ? 'yes' : 'no'} onChange={(e) => setForm({ ...form, enabled: e.target.value === 'yes' })}>
                                <option value="yes">yes</option><option value="no">no</option>
                            </select>
                        </label>
                        <label>Limit<input type="number" min={0} value={form.limit} placeholder="none"
                                           onChange={(e) => setForm({ ...form, limit: e.target.value })} /></label>
                        <label>Until<input type="date" value={form.until} onChange={(e) => setForm({ ...form, until: e.target.value })} /></label>
                        <label className="grow">Reason<input type="text" value={form.reason} required minLength={3}
                                                             onChange={(e) => setForm({ ...form, reason: e.target.value })} /></label>
                        <button type="submit" className="btn-primary"><Save size={14} /> Set override</button>
                    </form>
                    <h3>What it has now</h3>
                    <table className="money-table">
                        <thead><tr><th>Feature</th><th>Included</th><th>Limit</th><th>From</th></tr></thead>
                        <tbody>
                            {Object.entries(data.entitlements).map(([key, e]) => (
                                <tr key={key}>
                                    <td>{label(key)}</td><td>{e.enabled ? 'yes' : 'no'}</td>
                                    <td>{e.limit ?? '—'}</td><td className="muted">{e.source}</td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </>
            )}
        </section>
    );
};

export default PlansAdminPage;
