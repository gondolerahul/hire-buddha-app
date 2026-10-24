/**
 * pages/partner/PartnerPartnership — the partnership (Phase 15 T8-5, T8-6, T8-14; 07 §4.3).
 *
 * Type and status, the agreement (with the rates it was signed at) and signing
 * it, the annual fee (pay and renewal date), KYC and bank details, probation;
 * access grants to tenants (Gold); and the programme guide — today's rates,
 * fee ranges and payout policy.
 */
import React, { useCallback, useEffect, useState } from 'react';
import { BadgeCheck, KeyRound } from 'lucide-react';

import { useAuth } from '@/hooks/useAuth';
import { AgreementTerms, Grant, partnerPortal, PartnerMe, payOrder, REVENUE_LABEL } from '@/services/partners.service';
import { apiErrorMessage } from '@/utils/apiError';
import { formatDate, parseServerDate } from '@/utils/datetime';
import { formatMoney } from '@/utils/money';

import '@/pages/admin/MoneyConsole.css';
import './Partner.css';

export const PartnerPartnership: React.FC = () => {
    const { user } = useAuth();
    const admin = user?.role === 'partner_admin';
    const [me, setMe] = useState<PartnerMe | null>(null);
    const [grants, setGrants] = useState<Grant[]>([]);
    const [guide, setGuide] = useState<AgreementTerms | null>(null);
    const [kyc, setKyc] = useState({ legal_name: '', pan: '', gstin: '', account_name: '', account_number: '', ifsc: '' });
    const [error, setError] = useState<string | null>(null);
    const [notice, setNotice] = useState<string | null>(null);

    const load = useCallback(async () => {
        try {
            const [profile, access, rules] = await Promise.all([partnerPortal.me(), partnerPortal.grants(), partnerPortal.guide()]);
            setMe(profile);
            setGrants(access);
            setGuide(rules);
            setKyc(k => ({ ...k, legal_name: profile.legal_name ?? '', pan: profile.pan ?? '', gstin: profile.gstin ?? '' }));
        } catch (err) {
            setError(apiErrorMessage(err, 'The partnership could not be loaded'));
        }
    }, []);

    useEffect(() => { load(); }, [load]);

    const act = async (fn: () => Promise<unknown>, done: string, failed: string) => {
        setError(null);
        try {
            await fn();
            setNotice(done);
            load();
        } catch (err) {
            setError(apiErrorMessage(err, failed));
        }
    };

    const payFee = () => act(async () => {
        const order = await partnerPortal.feeOrder();
        await partnerPortal.feeVerify(await payOrder(order));
    }, 'Thank you: the partnership fee is paid and invoiced.', 'The fee was not paid');

    const saveKyc = (e: React.FormEvent) => {
        e.preventDefault();
        const bank = kyc.account_number ? { account_name: kyc.account_name, account_number: kyc.account_number,
                                            ifsc: kyc.ifsc.toUpperCase() } : undefined;
        act(() => partnerPortal.putKyc({ legal_name: kyc.legal_name || undefined, pan: kyc.pan.toUpperCase() || undefined,
                                         gstin: kyc.gstin.toUpperCase() || undefined, bank }),
            'Saved: HireBuddha verifies the details before the next payout.', 'The details were not saved');
    };

    if (!me) {
        return <div className="money-console partner-page">{error ? <div className="error-banner">{error}</div> : <p>Loading…</p>}</div>;
    }
    const kindLabel = (k: string) => REVENUE_LABEL[k] ?? k;

    return (
        <div className="money-console partner-page">
            <div className="page-header">
                <div>
                    <h1 className="page-title"><BadgeCheck size={22} /> Partnership</h1>
                    <p className="page-subtitle">
                        {me.type_name} · {me.status.replace('_', ' ')}{me.recruiter ? ` · recruited by ${me.recruiter}` : ''}
                    </p>
                </div>
            </div>
            {error && <div className="error-banner">{error}</div>}
            {notice && <div className="success-banner">{notice}</div>}

            <div className="partner-two-col">
                <section className="money-card glass">
                    <h2>Agreement</h2>
                    {me.agreement ? (
                        <>
                            <p className="card-desc">
                                Version {me.agreement.version}
                                {me.agreement.signed_at ? `, signed ${formatDate(me.agreement.signed_at)}` : ', not signed yet'}.
                                Its rates are the ones below, as they were when it was made.
                            </p>
                            {!me.agreement.signed_at && admin && (
                                <button className="btn-primary" onClick={() => act(() => partnerPortal.sign(), 'The agreement is signed.',
                                                                                  'The agreement was not signed')}>
                                    Sign the agreement
                                </button>
                            )}
                        </>
                    ) : <p className="card-desc">No agreement on file: HireBuddha prepares it.</p>}
                    {me.probation_until && parseServerDate(me.probation_until) > new Date() && (
                        <p className="partner-explain">On probation until {formatDate(me.probation_until)}: commission is held longer.</p>
                    )}
                </section>
                <section className="money-card glass">
                    <h2>Annual fee</h2>
                    {me.fee.required ? (
                        <>
                            <p className="card-desc">
                                {formatMoney(me.fee.amount ?? 0, me.fee.currency)} a year, plus GST.
                                {me.fee.paid_until ? ` Paid until ${formatDate(me.fee.paid_until)}.` : ' Not paid yet.'}
                                {' '}It is never shared with other partners.
                            </p>
                            {admin && <button className="btn-primary" onClick={payFee}>Pay the fee</button>}
                        </>
                    ) : <p className="card-desc">No partnership fee is due.</p>}
                </section>
            </div>

            <section className="money-card glass">
                <h2>KYC and payouts</h2>
                <p className="card-desc">
                    KYC: <span className={`partner-status ${me.kyc_status === 'verified' ? 'ok' : 'warn'}`}>{me.kyc_status}</span>
                    {me.bank_last4 ? ` · bank account ending ${me.bank_last4}${me.bank_verified ? ' (verified)' : ''}` : ' · no bank account yet'}.
                    {me.kyc_status !== 'verified' && ' Earnings are held until KYC is verified.'}
                    {!me.bank_verified && ' Payouts need a verified bank account.'}
                </p>
                {admin && (
                    <form className="money-form" onSubmit={saveKyc}>
                        <label>Legal name<input type="text" value={kyc.legal_name} onChange={e => setKyc({ ...kyc, legal_name: e.target.value })} /></label>
                        <label>PAN<input type="text" maxLength={10} value={kyc.pan} onChange={e => setKyc({ ...kyc, pan: e.target.value })} /></label>
                        <label>GSTIN<input type="text" maxLength={15} value={kyc.gstin} onChange={e => setKyc({ ...kyc, gstin: e.target.value })} /></label>
                        <label>Account name<input type="text" value={kyc.account_name} onChange={e => setKyc({ ...kyc, account_name: e.target.value })} /></label>
                        <label>Account number<input type="text" value={kyc.account_number} onChange={e => setKyc({ ...kyc, account_number: e.target.value })} /></label>
                        <label>IFSC<input type="text" maxLength={11} value={kyc.ifsc} onChange={e => setKyc({ ...kyc, ifsc: e.target.value })} /></label>
                        <button type="submit" className="btn-primary">Save</button>
                    </form>
                )}
            </section>

            {me.tenant_data_access === 'grants' && (
                <section className="money-card glass">
                    <h2><KeyRound size={18} /> Access to your tenants</h2>
                    <p className="card-desc">You work inside a tenant only under its grant; the tenant's admins see and revoke grants.</p>
                    {grants.length === 0 ? <p className="card-desc">No grants.</p> : (
                        <table className="money-table">
                            <thead><tr><th>Tenant</th><th>Scopes</th><th>Status</th><th>Expires</th></tr></thead>
                            <tbody>
                                {grants.map(g => (
                                    <tr key={g.id}>
                                        <td>{g.tenant}</td><td>{g.scopes.join(', ')}</td><td>{g.status}</td>
                                        <td>{g.expires_at ? formatDate(g.expires_at) : 'no expiry'}</td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    )}
                </section>
            )}

            {guide && (
                <section className="money-card glass">
                    <h2>Programme guide</h2>
                    <table className="money-table">
                        <thead><tr><th>Earned on</th><th>Level</th><th>Rate</th><th>Cap</th></tr></thead>
                        <tbody>
                            {guide.commission_rules.filter(r => r.partner_type === me.partner_type)
                                .map(r => (
                                    <tr key={r.id}>
                                        <td>{kindLabel(r.revenue_kind)}</td>
                                        <td>{r.level === 0 ? 'your customers' : `level ${r.level} override`}</td>
                                        <td>{Number(r.rate_pct)} %</td>
                                        <td>{r.cap_pct ? `${Number(r.cap_pct)} % of the payment` : '—'}</td>
                                    </tr>
                                ))}
                        </tbody>
                    </table>
                    <h3>Setup and customisation fees</h3>
                    <table className="money-table">
                        <tbody>
                            {guide.fee_rules.map(f => (
                                <tr key={f.id}>
                                    <td>{f.fee_kind}</td>
                                    <td>{formatMoney(f.min_usd, 'USD')} – {formatMoney(f.max_usd, 'USD')}</td>
                                    <td>{Object.entries(f.split).map(([k, v]) => `${k} ${v} %`).join(' · ')}</td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                    <p className="partner-explain">
                        Holdback {guide.policy['partners.holdback_days']} days (probation {guide.policy['partners.probation_holdback_days']}),
                        minimum payout USD {guide.policy['partners.payout_min_usd']}, TDS {guide.policy['partners.tds_pct']} %.
                        Overrides need your own paid revenue in the month (USD {guide.policy['partners.override_min_monthly_revenue_usd']})
                        and end {guide.policy['partners.override_months']} months after the partner below joined.
                    </p>
                </section>
            )}
        </div>
    );
};

export default PartnerPartnership;
