/**
 * pages/partner/PartnerGuidePage — how the partner programme works, with this partner's own rates (Phase 15 T9-6; 07 §4.3).
 */
import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';

import { Card, Notice, PageHeader } from '@/components/ui/brand';
import { AgreementTerms, partnerPortal } from '@/services/partners.service';
import { apiErrorMessage } from '@/utils/apiError';
import { formatMoney } from '@/utils/money';

const EARNED_ON: Record<string, string> = {
    subscription: 'Subscriptions', usage: 'Usage', wallet_recharge: 'Wallet recharges', setup_fee: 'Setup fees',
    customisation_fee: 'Customisation fees', partnership_fee: 'Partnership fees', hosting: 'Hosting', number_rent: 'Number rent',
};

const STEPS: Array<[string, string]> = [
    ['Bring a customer', 'Register a lead on Leads, or invite the customer to sign up. A Gold partner can also create the workspace for them.'],
    ['The customer pays', 'Subscriptions, recharges and fees are paid to HireBuddha; GST invoices are issued in the customer\'s currency.'],
    ['You earn', 'Commission is a share of what the customer paid, at the rates below. It is held for the holdback period, then becomes payable.'],
    ['You are paid', 'A monthly statement lists every earning. Approve it, upload your GST invoice if you are registered, and it is paid to your verified bank account.'],
];

export const PartnerGuidePage: React.FC = () => {
    const [guide, setGuide] = useState<AgreementTerms | null>(null);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        partnerPortal.guide().then(setGuide).catch(err => setError(apiErrorMessage(err, 'The guide could not be loaded')));
    }, []);

    const policy = guide?.policy ?? {};
    return (
        <div className="b-page">
            <PageHeader eyebrow="Partner Portal" title="Programme guide"
                        subtitle="How you earn with HireBuddha, and the rates in your agreement." />
            {error && <Notice tone="negative">{error}</Notice>}
            <div className="b-tiles">
                {STEPS.map(([title, text], i) => (
                    <Card key={title} eyebrow={`Step ${i + 1}`} title={title}><p className="b-muted">{text}</p></Card>
                ))}
            </div>
            {guide && (
                <>
                    <Card title="Your commission">
                        <table className="b-table">
                            <thead><tr><th>Earned on</th><th>From</th><th className="num">Rate</th><th className="num">Cap</th></tr></thead>
                            <tbody>
                                {guide.commission_rules.filter(r => r.partner_type === guide.partner_type).map(r => (
                                    <tr key={r.id}>
                                        <td>{EARNED_ON[r.revenue_kind] ?? r.revenue_kind}</td>
                                        <td>{r.level === 0 ? 'Your own customers' : `Partners you recruited (level ${r.level})`}</td>
                                        <td className="num">{Number(r.rate_pct)} %</td>
                                        <td className="num">{r.cap_pct ? `${Number(r.cap_pct)} %` : '—'}</td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </Card>
                    <Card title="Setup and customisation fees">
                        <table className="b-table">
                            <thead><tr><th>Fee</th><th>Range</th><th>Split</th></tr></thead>
                            <tbody>
                                {guide.fee_rules.map(f => (
                                    <tr key={f.id}>
                                        <td>{EARNED_ON[f.fee_kind] ?? f.fee_kind}</td>
                                        <td>{formatMoney(f.min_usd, 'USD')} – {formatMoney(f.max_usd, 'USD')}</td>
                                        <td>{Object.entries(f.split).map(([k, v]) => `${k} ${v} %`).join(' · ')}</td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </Card>
                    <Card title="Payouts">
                        <ul className="b-muted">
                            <li>Earnings are held {policy['partners.holdback_days']} days ({policy['partners.probation_holdback_days']} while on probation), so a refund can reverse them.</li>
                            <li>The minimum payout is USD {policy['partners.payout_min_usd']}; a smaller balance carries to the next month.</li>
                            <li>TDS of {policy['partners.tds_pct']} % is deducted where the law needs it.</li>
                            <li>Overrides on partners you recruited need USD {policy['partners.override_min_monthly_revenue_usd']} of your own paid revenue in the month,
                                and last {policy['partners.override_months']} months from when that partner joined.</li>
                        </ul>
                        <p className="b-muted">Your agreement, KYC and fee are on <Link to="/partner/partnership">Partnership</Link>.</p>
                    </Card>
                </>
            )}
        </div>
    );
};

export default PartnerGuidePage;
