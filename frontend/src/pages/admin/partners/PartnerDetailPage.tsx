/**
 * pages/admin/partners/PartnerDetailPage — Partner 360 for staff (Phase 15 T8-14; 07 §4.1).
 *
 * Profile, KYC (verify), status (suspend, reactivate, terminate), agreements,
 * the annual fee, tenants with their assignment history (reassign), the
 * network, access grants, ledger totals, statements, and a ledger adjustment.
 */
import React, { useCallback, useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { HeartHandshake } from 'lucide-react';

import { AdminPartner, Partner360, partnerAdmin } from '@/services/partners.service';
import { apiErrorMessage } from '@/utils/apiError';
import { formatDate } from '@/utils/datetime';
import { formatMoney } from '@/utils/money';

import '@/pages/admin/MoneyConsole.css';
import '@/pages/partner/Partner.css';

export const PartnerDetailPage: React.FC = () => {
    const { id = '' } = useParams();
    const [data, setData] = useState<Partner360 | null>(null);
    const [partners, setPartners] = useState<AdminPartner[]>([]);
    const [adjust, setAdjust] = useState({ amount: '', reason: '' });
    const [error, setError] = useState<string | null>(null);
    const [notice, setNotice] = useState<string | null>(null);

    const load = useCallback(async () => {
        try {
            const [one, all] = await Promise.all([partnerAdmin.get(id), partnerAdmin.list()]);
            setData(one);
            setPartners(all);
        } catch (err) {
            setError(apiErrorMessage(err, 'The partner could not be loaded'));
        }
    }, [id]);

    useEffect(() => { load(); }, [load]);

    const act = async (fn: () => Promise<unknown>, done: string) => {
        setError(null);
        try {
            await fn();
            setNotice(done);
            load();
        } catch (err) {
            setError(apiErrorMessage(err, 'Not saved'));
        }
    };

    const status = (next: string) => {
        const reason = prompt(next === 'terminated'
            ? 'Terminate the partnership? Its tenants move to HireBuddha direct and unpaid earnings are forfeited. Reason:'
            : `Set the partnership ${next}. Reason:`);
        if (reason) act(() => partnerAdmin.setStatus(id, { status: next, reason }), `The partnership is ${next}.`);
    };

    const reassign = (tenantId: string, tenantName: string | null) => {
        const choice = prompt(`Move ${tenantName} to which partner? Type its exact name, or leave blank for HireBuddha direct.`);
        if (choice === null) return;
        const target = choice ? partners.find(p => p.name === choice) : null;
        if (choice && !target) {
            setError('No partner has that name');
            return;
        }
        const reason = prompt('Reason (kept with the move):');
        if (!reason) return;
        act(() => partnerAdmin.reassign({ tenant_id: tenantId, partner_id: target?.partner_id ?? null,
                                          relationship: target?.partner_type === 'SILVER' ? 'referred' : 'resold', reason }),
            `${tenantName} moved.`);
    };

    if (!data) return <div className="money-console">{error ? <div className="error-banner">{error}</div> : <p>Loading…</p>}</div>;
    const p = data.profile;
    const ccy = p.currency;

    return (
        <div className="money-console">
            <div className="page-header">
                <div>
                    <h1 className="page-title"><HeartHandshake size={22} /> {p.name}</h1>
                    <p className="page-subtitle">
                        <Link to="/admin/partners">Partner network</Link> · {p.partner_type} · {p.status.replace('_', ' ')}
                        {p.recruiter ? ` · recruited by ${p.recruiter}` : ''} · level {p.depth}
                    </p>
                </div>
            </div>
            {error && <div className="error-banner">{error}</div>}
            {notice && <div className="success-banner">{notice}</div>}
            <div className="partner-two-col">
                <section className="money-card glass">
                    <h2>Profile and KYC</h2>
                    <table className="money-table"><tbody>
                        <tr><td>Legal name</td><td>{p.legal_name}</td></tr>
                        <tr><td>PAN / GSTIN</td><td>{p.pan ?? '—'} / {p.gstin ?? '—'}</td></tr>
                        <tr><td>KYC</td><td>{p.kyc_status}</td></tr>
                        <tr><td>Bank</td><td>{p.bank_last4 ? `…${p.bank_last4} ${p.bank_verified ? '(verified)' : '(not verified)'}` : 'none'}</td></tr>
                        <tr><td>Active since</td><td>{p.activated_at ? formatDate(p.activated_at) : '—'}</td></tr>
                        <tr><td>Probation until</td><td>{p.probation_until ? formatDate(p.probation_until) : '—'}</td></tr>
                        <tr><td>Fee</td><td>{data.fee.required ? `${formatMoney(data.fee.amount ?? 0, data.fee.currency)} / year, paid to ${data.fee.paid_until ? formatDate(data.fee.paid_until) : '—'}` : 'none due'}</td></tr>
                    </tbody></table>
                    <div className="money-form">
                        <button className="btn-primary" onClick={() => act(() => partnerAdmin.setKyc(id, { status: 'verified', bank_verified: true, reason: 'checked' }), 'KYC verified.')}>Verify KYC and bank</button>
                        <button className="btn-secondary" onClick={() => act(() => partnerAdmin.setKyc(id, { status: 'rejected', reason: 'rejected' }), 'KYC rejected.')}>Reject KYC</button>
                    </div>
                    <div className="money-form">
                        {p.status !== 'active' && p.status !== 'terminated' && <button className="btn-secondary" onClick={() => status('active')}>Reactivate</button>}
                        {['active', 'renewal_due', 'lapsed', 'approved'].includes(p.status) && <button className="btn-secondary" onClick={() => status('suspended')}>Suspend</button>}
                        {p.status !== 'terminated' && <button className="btn-secondary" onClick={() => status('terminated')}>Terminate</button>}
                    </div>
                </section>
                <section className="money-card glass">
                    <h2>Earnings</h2>
                    <table className="money-table"><tbody>
                        {Object.entries(data.ledger_totals).map(([s, v]) => <tr key={s}><td>{s}</td><td>{formatMoney(v, ccy)}</td></tr>)}
                    </tbody></table>
                    <form className="money-form" onSubmit={e => { e.preventDefault(); act(() => partnerAdmin.adjust(id, adjust), 'Adjustment recorded.'); setAdjust({ amount: '', reason: '' }); }}>
                        <label>Adjustment ({ccy})<input type="text" inputMode="decimal" required value={adjust.amount} onChange={e => setAdjust({ ...adjust, amount: e.target.value })} /></label>
                        <label className="grow">Reason<input type="text" required minLength={3} value={adjust.reason} onChange={e => setAdjust({ ...adjust, reason: e.target.value })} /></label>
                        <button type="submit" className="btn-secondary">Record</button>
                    </form>
                </section>
            </div>
            <section className="money-card glass">
                <h2>Agreements <button className="btn-secondary" onClick={() => act(() => partnerAdmin.newAgreement(id), 'A new agreement version is ready to sign.')}>New version</button></h2>
                <table className="money-table">
                    <thead><tr><th>Version</th><th>From</th><th>To</th><th>Signed</th><th>Level-0 rates</th></tr></thead>
                    <tbody>
                        {data.agreements.map(a => (
                            <tr key={a.id}>
                                <td>v{a.version}</td><td>{a.effective_from ? formatDate(a.effective_from) : ''}</td>
                                <td>{a.effective_to ? formatDate(a.effective_to) : '—'}</td><td>{a.signed_at ? formatDate(a.signed_at) : 'not signed'}</td>
                                <td>{a.terms.commission_rules.filter(r => r.level === 0).map(r => `${r.revenue_kind} ${Number(r.rate_pct)} %`).join(', ')}</td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </section>
            <section className="money-card glass">
                <h2>Customers</h2>
                <table className="money-table">
                    <thead><tr><th>Customer</th><th>How</th><th>From</th><th>Until</th><th>Commission until</th><th>Source</th><th /></tr></thead>
                    <tbody>
                        {data.assignments.map(a => (
                            <tr key={a.id}>
                                <td>{a.tenant}</td><td>{a.relationship}</td><td>{a.since ? formatDate(a.since) : ''}</td>
                                <td>{a.until ? formatDate(a.until) : 'current'}</td><td>{a.commission_until ? formatDate(a.commission_until) : 'no end'}</td>
                                <td>{a.source}</td>
                                <td>{!a.until && <button className="btn-secondary" onClick={() => reassign(a.tenant_id, a.tenant)}>Move</button>}</td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </section>
            <div className="partner-two-col">
                <section className="money-card glass">
                    <h2>Network</h2>
                    {data.network.length === 0 ? <p className="card-desc">No recruits.</p> : (
                        <table className="money-table"><tbody>
                            {data.network.map(n => (
                                <tr key={n.partner_id}><td><Link to={`/admin/partners/${n.partner_id}`}>{n.name}</Link></td><td>{n.partner_type}</td><td>{n.status}</td></tr>
                            ))}
                        </tbody></table>
                    )}
                </section>
                <section className="money-card glass">
                    <h2>Access grants</h2>
                    {data.grants.length === 0 ? <p className="card-desc">None.</p> : (
                        <table className="money-table"><tbody>
                            {data.grants.map(g => (
                                <tr key={g.id}><td>{g.tenant}</td><td>{g.scopes.join(', ')}</td><td>{g.status}</td>
                                    <td>{g.expires_at ? formatDate(g.expires_at) : 'no expiry'}</td></tr>
                            ))}
                        </tbody></table>
                    )}
                </section>
            </div>
            <section className="money-card glass">
                <h2>Statements</h2>
                {data.statements.length === 0 ? <p className="card-desc">None.</p> : (
                    <table className="money-table">
                        <thead><tr><th>Month</th><th>Net</th><th>Status</th></tr></thead>
                        <tbody>
                            {data.statements.map(s => (
                                <tr key={s.id}><td>{s.period.slice(0, 7)}</td><td>{formatMoney(s.net, s.currency)}</td><td>{s.status}</td></tr>
                            ))}
                        </tbody>
                    </table>
                )}
            </section>
        </div>
    );
};

export default PartnerDetailPage;
