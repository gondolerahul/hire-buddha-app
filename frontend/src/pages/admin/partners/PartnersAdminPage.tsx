/**
 * pages/admin/partners/PartnersAdminPage — the partner network for staff (Phase 15 T8-14; 07 §4.1 Partners).
 *
 * Tabs: Partners (list and tree: type, status, depth, tenants, sourced billed
 * revenue, fee, KYC), Applications (the underwriting queue: checklist, approve
 * with a type, reject), Leads (the sales queue: accept, work, convert, lose),
 * Tree check (what the company tree and roles break, T8-1).
 */
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { HeartHandshake } from 'lucide-react';

import { AdminPartner, Application, Lead, partnerAdmin, PartnerType } from '@/services/partners.service';
import { apiErrorMessage } from '@/utils/apiError';
import { formatDate } from '@/utils/datetime';
import { formatMoney } from '@/utils/money';

import '@/pages/admin/MoneyConsole.css';
import '@/pages/partner/Partner.css';

const TABS = ['partners', 'applications', 'leads', 'tree-check'] as const;
type Tab = typeof TABS[number];
const CHECK_LABEL: Record<string, string> = {
    identity_kyc: 'Identity KYC', business_kyc: 'Business KYC', bank_verified: 'Bank verified',
    sanctions_check: 'Sanctions / adverse media', no_duplicate: 'No duplicate', territory_check: 'Territory',
    capability_assessment: 'Capability (Gold)', agreement_reviewed: 'Agreement',
};

export const PartnersAdminPage: React.FC<{ defaultTab?: Tab }> = ({ defaultTab = 'partners' }) => {
    const [params, setParams] = useSearchParams();
    const tab = (TABS as readonly string[]).includes(params.get('tab') ?? '') ? params.get('tab') as Tab : defaultTab;
    const [error, setError] = useState<string | null>(null);
    const [notice, setNotice] = useState<string | null>(null);

    return (
        <div className="money-console">
            <div className="page-header">
                <div>
                    <h1 className="page-title"><HeartHandshake size={22} /> Partner network</h1>
                    <p className="page-subtitle">
                        Partners, applications, leads. Rules and the simulator are on <Link to="/console/partners/rules">Programme rules</Link>;
                        statements on <Link to="/console/finance/payouts">Partner payouts</Link>.
                    </p>
                </div>
            </div>
            <div className="partner-tabs">
                {TABS.map(t => (
                    <button key={t} className={tab === t ? 'active' : ''} onClick={() => setParams({ tab: t })}>
                        {t === 'tree-check' ? 'Tree check' : t.charAt(0).toUpperCase() + t.slice(1)}
                    </button>
                ))}
            </div>
            {error && <div className="error-banner">{error}</div>}
            {notice && <div className="success-banner">{notice}</div>}
            {tab === 'partners' && <PartnersTab onError={setError} />}
            {tab === 'applications' && <ApplicationsTab onError={setError} onNotice={setNotice} />}
            {tab === 'leads' && <LeadsTab onError={setError} onNotice={setNotice} />}
            {tab === 'tree-check' && <TreeCheckTab onError={setError} />}
        </div>
    );
};

const PartnersTab: React.FC<{ onError: (t: string) => void }> = ({ onError }) => {
    const [rows, setRows] = useState<AdminPartner[]>([]);
    const [view, setView] = useState<'list' | 'tree'>('list');

    useEffect(() => {
        partnerAdmin.list().then(setRows).catch(err => onError(apiErrorMessage(err, 'Partners could not be loaded')));
    }, [onError]);

    const children = useMemo(() => {
        const out: Record<string, AdminPartner[]> = {};
        for (const p of rows) (out[p.recruiter_partner_id ?? 'root'] ??= []).push(p);
        return out;
    }, [rows]);

    const node = (p: AdminPartner): React.ReactNode => (
        <li key={p.partner_id}>
            <Link to={`/console/partners/${p.partner_id}`}>{p.name}</Link>{' '}
            <span className="partner-status">{p.partner_type}</span>{' '}
            <span className={`partner-status ${p.status === 'active' ? 'ok' : 'warn'}`}>{p.status}</span>
            <span className="muted"> · {p.tenants ?? 0} tenants</span>
            {children[p.partner_id] && <ul>{children[p.partner_id].map(node)}</ul>}
        </li>
    );

    return (
        <section className="money-card glass">
            <div className="partner-tabs" style={{ marginTop: 0 }}>
                <button className={view === 'list' ? 'active' : ''} onClick={() => setView('list')}>List</button>
                <button className={view === 'tree' ? 'active' : ''} onClick={() => setView('tree')}>Tree</button>
            </div>
            {view === 'tree' ? (
                <div className="partner-tree"><ul>{(children.root ?? []).map(node)}</ul></div>
            ) : (
                <table className="money-table" style={{ marginTop: '1rem' }}>
                    <thead><tr><th>Partner</th><th>Type</th><th>Status</th><th>Depth</th><th>Recruiter</th><th>Tenants</th>
                        <th>Sourced (MTD)</th><th>KYC</th><th>Fee paid to</th></tr></thead>
                    <tbody>
                        {rows.map(p => (
                            <tr key={p.partner_id}>
                                <td><Link to={`/console/partners/${p.partner_id}`}>{p.name}</Link></td>
                                <td>{p.partner_type}</td><td>{p.status}</td><td>{p.depth}</td><td>{p.recruiter ?? 'HireBuddha'}</td>
                                <td>{p.tenants ?? 0}</td><td>{formatMoney(p.sourced_billed_mtd_usd ?? 0, 'USD')}</td>
                                <td>{p.kyc_status}</td><td>{p.fee_paid_until ? formatDate(p.fee_paid_until) : '—'}</td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            )}
        </section>
    );
};

const ApplicationsTab: React.FC<{ onError: (t: string) => void; onNotice: (t: string) => void }> = ({ onError, onNotice }) => {
    const [rows, setRows] = useState<Application[]>([]);
    const [checklist, setChecklist] = useState<string[]>([]);
    const [open, setOpen] = useState<Application | null>(null);
    const [type, setType] = useState<PartnerType>('SILVER');
    const [notes, setNotes] = useState('');

    const load = useCallback(async () => {
        try {
            const res = await partnerAdmin.applications();
            setRows(res.applications);
            setChecklist(res.checklist);
        } catch (err) {
            onError(apiErrorMessage(err, 'Applications could not be loaded'));
        }
    }, [onError]);

    useEffect(() => { load(); }, [load]);

    const tick = async (key: string, value: boolean) => {
        if (!open) return;
        try {
            setOpen(await partnerAdmin.review(open.id, { checklist: { [key]: value } }));
        } catch (err) {
            onError(apiErrorMessage(err, 'Not saved'));
        }
    };

    const decide = async (approve: boolean) => {
        if (!open) return;
        try {
            if (approve) {
                await partnerAdmin.approve(open.id, { partner_type: type, notes: notes || undefined });
                onNotice(`${open.company_name} is approved as ${type}; its admin is e-mailed a link to set a password.`);
            } else {
                await partnerAdmin.reject(open.id, notes || 'not approved');
                onNotice(`${open.company_name} is rejected.`);
            }
            setOpen(null);
            setNotes('');
            load();
        } catch (err) {
            onError(apiErrorMessage(err, 'Not saved'));
        }
    };

    return (
        <section className="money-card glass">
            <table className="money-table">
                <thead><tr><th>Applicant</th><th>Recruiter</th><th>Wants</th><th>Status</th><th>Applied</th><th /></tr></thead>
                <tbody>
                    {rows.map(a => (
                        <tr key={a.id} className={open?.id === a.id ? 'selected' : ''}>
                            <td>{a.company_name ?? '—'} <span className="muted">{a.contact_name} · {a.email}</span></td>
                            <td>{a.recruiter ?? 'HireBuddha'}</td><td>{a.requested_type ?? '—'}</td><td>{a.status.replace('_', ' ')}</td>
                            <td>{a.created_at ? formatDate(a.created_at) : ''}</td>
                            <td>{['applied', 'under_review'].includes(a.status) && (
                                <button className="btn-secondary" onClick={() => { setOpen(a); setType(a.requested_type ?? 'SILVER'); }}>Review</button>
                            )}</td>
                        </tr>
                    ))}
                </tbody>
            </table>
            {open && (
                <div style={{ marginTop: '1rem' }}>
                    <h3>Underwriting: {open.company_name}</h3>
                    <p className="partner-explain">
                        {Object.entries(open.details).filter(([, v]) => v).map(([k, v]) => `${k}: ${String(v)}`).join(' · ')}
                    </p>
                    <div className="money-form">
                        {checklist.map(key => (
                            <label key={key} style={{ flexDirection: 'row', alignItems: 'center', gap: '0.4rem' }}>
                                <input type="checkbox" checked={!!open.checklist[key]} onChange={e => tick(key, e.target.checked)} />
                                {CHECK_LABEL[key] ?? key}
                            </label>
                        ))}
                    </div>
                    <div className="money-form">
                        <label>Type (staff decide)
                            <select value={type} onChange={e => setType(e.target.value as PartnerType)}>
                                <option value="SILVER">Silver</option><option value="GOLD">Gold</option>
                            </select>
                        </label>
                        <label className="grow">Notes<input type="text" value={notes} onChange={e => setNotes(e.target.value)} /></label>
                        <button className="btn-primary" onClick={() => decide(true)}>Approve</button>
                        <button className="btn-secondary" onClick={() => decide(false)}>Reject</button>
                    </div>
                </div>
            )}
        </section>
    );
};

const LeadsTab: React.FC<{ onError: (t: string) => void; onNotice: (t: string) => void }> = ({ onError, onNotice }) => {
    const [rows, setRows] = useState<Lead[]>([]);
    const [status, setStatus] = useState('');

    const load = useCallback(async () => {
        try {
            setRows(await partnerAdmin.leads(status || undefined));
        } catch (err) {
            onError(apiErrorMessage(err, 'Leads could not be loaded'));
        }
    }, [status, onError]);

    useEffect(() => { load(); }, [load]);

    const move = async (lead: Lead, next: string) => {
        const reason = next === 'lost' ? prompt('Why was it lost?') ?? undefined : undefined;
        try {
            await partnerAdmin.moveLead(lead.id, { status: next, reason });
            load();
        } catch (err) {
            onError(apiErrorMessage(err, 'Not saved'));
        }
    };

    const convert = async (lead: Lead) => {
        const email = prompt(`Make ${lead.company_name} a customer. Its admin's e-mail:`, lead.email ?? '');
        if (email === null) return;
        try {
            await partnerAdmin.convertLead(lead.id, { admin_email: email || undefined });
            onNotice(`${lead.company_name} is a customer, attributed to ${lead.partner}.`);
            load();
        } catch (err) {
            onError(apiErrorMessage(err, 'Not converted'));
        }
    };

    const NEXT: Record<string, string[]> = { registered: ['accepted', 'lost'], accepted: ['in_progress', 'lost'], in_progress: ['lost'] };

    return (
        <section className="money-card glass">
            <div className="money-form" style={{ marginTop: 0 }}>
                <label>Status
                    <select value={status} onChange={e => setStatus(e.target.value)}>
                        <option value="">All</option>
                        {['registered', 'accepted', 'in_progress', 'converted', 'lost', 'expired'].map(s => <option key={s} value={s}>{s}</option>)}
                    </select>
                </label>
            </div>
            <table className="money-table" style={{ marginTop: '1rem' }}>
                <thead><tr><th>Company</th><th>Partner</th><th>Contact</th><th>Status</th><th>Exclusive until</th><th /></tr></thead>
                <tbody>
                    {rows.map(l => (
                        <tr key={l.id}>
                            <td>{l.company_name}</td><td>{l.partner}</td><td>{[l.contact_name, l.email, l.phone].filter(Boolean).join(' · ')}</td>
                            <td>{l.status}</td><td>{l.exclusive_until ? formatDate(l.exclusive_until) : '—'}</td>
                            <td style={{ whiteSpace: 'nowrap' }}>
                                {(NEXT[l.status] ?? []).map(n => (
                                    <button key={n} className="btn-secondary" onClick={() => move(l, n)}>{n.replace('_', ' ')}</button>
                                ))}{' '}
                                {['registered', 'accepted', 'in_progress'].includes(l.status) && (
                                    <button className="btn-primary" onClick={() => convert(l)}>Convert</button>
                                )}
                            </td>
                        </tr>
                    ))}
                </tbody>
            </table>
        </section>
    );
};

const TreeCheckTab: React.FC<{ onError: (t: string) => void }> = ({ onError }) => {
    const [rows, setRows] = useState<Array<Record<string, string>> | null>(null);

    useEffect(() => {
        partnerAdmin.treeCheck().then(res => setRows(res.violations))
            .catch(err => onError(apiErrorMessage(err, 'The check failed')));
    }, [onError]);

    return (
        <section className="money-card glass">
            {rows === null ? <p>Checking…</p> : rows.length === 0 ? <p className="card-desc">The company tree and every role are consistent.</p> : (
                <table className="money-table">
                    <thead><tr><th>Kind</th><th>Company or user</th><th>Problem</th></tr></thead>
                    <tbody>
                        {rows.map((v, i) => (
                            <tr key={i}><td>{v.kind}</td><td>{v.name ?? v.email ?? v.company_id ?? '—'}</td><td>{v.detail}</td></tr>
                        ))}
                    </tbody>
                </table>
            )}
        </section>
    );
};

export default PartnersAdminPage;
