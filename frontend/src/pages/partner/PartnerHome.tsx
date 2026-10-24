/**
 * pages/partner/PartnerHome — the Partner Portal's home (Phase 15 T8-14; 07 §5.8).
 *
 * Gold: tenants, their billed amount this month, earnings, next payout, the
 * partnership fee, open charges, leads. Silver: leads, referred customers,
 * earnings. Earnings and statements are the partner admin's only (07 §6).
 * Staff are sent to the tenants view (the old partner dashboard).
 */
import React, { useEffect, useState } from 'react';
import { Link, Navigate } from 'react-router-dom';
import { HeartHandshake } from 'lucide-react';

import { useAuth } from '@/hooks/useAuth';
import { partnerPortal, PartnerOverview, LEDGER_STATUS_LABEL } from '@/services/partners.service';
import { apiErrorMessage } from '@/utils/apiError';
import { formatDate } from '@/utils/datetime';
import { formatMoney } from '@/utils/money';

import '@/pages/admin/MoneyConsole.css';
import './Partner.css';

export const PartnerHome: React.FC = () => {
    const { user } = useAuth();
    const [data, setData] = useState<PartnerOverview | null>(null);
    const [error, setError] = useState<string | null>(null);
    const staff = user?.role === 'app_admin';

    useEffect(() => {
        if (staff) return;
        partnerPortal.overview().then(setData).catch(err => setError(apiErrorMessage(err, 'The overview could not be loaded')));
    }, [staff]);

    if (staff) return <Navigate to="/partner/tenants" replace />;
    const ccy = data?.currency ?? 'INR';
    const gold = data?.partner_type === 'GOLD';

    return (
        <div className="money-console partner-page">
            <div className="page-header">
                <div>
                    <h1 className="page-title"><HeartHandshake size={22} /> Partner home</h1>
                    <p className="page-subtitle">
                        {data ? `${gold ? 'Gold' : 'Silver'} partner · ${data.status.replace('_', ' ')}` : 'Loading…'}
                    </p>
                </div>
            </div>
            {error && <div className="error-banner">{error}</div>}
            {data && data.status !== 'active' && (
                <div className="error-banner">
                    Your partnership is {data.status.replace('_', ' ')}. See <Link to="/partner/partnership">Partnership</Link>.
                </div>
            )}
            {data && (
                <>
                    <div className="partner-tiles">
                        {gold && <Tile label="Tenants" value={String(data.tenants)} to="/partner/tenants" />}
                        <Tile label="Referred customers" value={String(data.referred_customers)} to="/partner/customers" />
                        <Tile label="Customers billed this month" value={formatMoney(data.customers_billed_mtd, ccy)} />
                        {data.earnings_mtd !== null && <Tile label="Earned this month" value={formatMoney(data.earnings_mtd, ccy)} to="/partner/earnings" />}
                        {data.next_statement && (
                            <Tile label="Next payout" value={formatMoney(data.next_statement.net, data.next_statement.currency)}
                                  hint={`${data.next_statement.period.slice(0, 7)} · ${data.next_statement.status}`} to="/partner/earnings?tab=statements" />
                        )}
                        {data.fee.required && (
                            <Tile label="Partnership fee" value={data.fee.paid_until ? `Paid to ${formatDate(data.fee.paid_until)}` : 'Due'}
                                  to="/partner/partnership" />
                        )}
                        {gold && <Tile label="Open charges" value={String(data.open_charges)} to="/partner/charges" />}
                    </div>
                    <div className="partner-two-col">
                        <section className="money-card glass">
                            <h2>Leads</h2>
                            {Object.keys(data.leads).length === 0
                                ? <p className="card-desc">No leads yet. <Link to="/partner/leads">Register one</Link>.</p>
                                : (
                                    <table className="money-table">
                                        <tbody>
                                            {Object.entries(data.leads).map(([status, count]) => (
                                                <tr key={status}><td>{status.replace('_', ' ')}</td><td>{count}</td></tr>
                                            ))}
                                        </tbody>
                                    </table>
                                )}
                        </section>
                        {data.earnings_by_status && (
                            <section className="money-card glass">
                                <h2>Earnings by status</h2>
                                <table className="money-table">
                                    <tbody>
                                        {Object.entries(data.earnings_by_status).map(([status, amount]) => (
                                            <tr key={status}><td>{LEDGER_STATUS_LABEL[status] ?? status}</td><td>{formatMoney(amount, ccy)}</td></tr>
                                        ))}
                                    </tbody>
                                </table>
                            </section>
                        )}
                    </div>
                </>
            )}
        </div>
    );
};

const Tile: React.FC<{ label: string; value: string; hint?: string; to?: string }> = ({ label, value, hint, to }) => {
    const body = (
        <>
            <p className="partner-tile-label">{label}</p>
            <p className="partner-tile-value">{value}</p>
            {hint && <p className="partner-tile-hint">{hint}</p>}
        </>
    );
    return to ? <Link className="partner-tile glass" to={to}>{body}</Link> : <div className="partner-tile glass">{body}</div>;
};

export default PartnerHome;
