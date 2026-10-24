/**
 * pages/partner/PartnerCustomers — the partner's customers (Phase 15 T8-14; 07 §4.3, R-P04).
 *
 * Referred and resold customers with their plan, what they were billed this
 * month and the commission earned on them so far — never their data (a Silver
 * partner has none; a Gold partner opens a tenant through an access grant).
 */
import React, { useEffect, useState } from 'react';
import { Users } from 'lucide-react';

import { Customer, partnerPortal } from '@/services/partners.service';
import { apiErrorMessage } from '@/utils/apiError';
import { formatDate } from '@/utils/datetime';
import { formatMoney } from '@/utils/money';

import '@/pages/admin/MoneyConsole.css';
import './Partner.css';

export const PartnerCustomers: React.FC = () => {
    const [rows, setRows] = useState<Customer[]>([]);
    const [currency, setCurrency] = useState('INR');
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        partnerPortal.customers()
            .then(res => { setRows(res.customers); setCurrency(res.currency); })
            .catch(err => setError(apiErrorMessage(err, 'Customers could not be loaded')));
    }, []);

    return (
        <div className="money-console partner-page">
            <div className="page-header">
                <div>
                    <h1 className="page-title"><Users size={22} /> Customers</h1>
                    <p className="page-subtitle">
                        The businesses attributed to you. Commission is earned on what they pay, for as long as they pay
                        and your partnership is active.
                    </p>
                </div>
            </div>
            {error && <div className="error-banner">{error}</div>}
            <section className="money-card glass">
                {rows.length === 0 ? <p className="card-desc">No customers yet.</p> : (
                    <table className="money-table">
                        <thead>
                            <tr><th>Customer</th><th>How</th><th>Since</th><th>Plan</th><th>Status</th>
                                <th>Billed this month</th><th>Your commission</th></tr>
                        </thead>
                        <tbody>
                            {rows.map(c => (
                                <tr key={c.tenant_id}>
                                    <td>{c.name}</td>
                                    <td>{c.relationship === 'resold' ? 'Resold' : 'Referred'}</td>
                                    <td>{c.since ? formatDate(c.since) : ''}</td>
                                    <td>{c.plan ?? '—'}</td>
                                    <td>{c.status}</td>
                                    <td>{formatMoney(c.billed_mtd, currency)}</td>
                                    <td>{c.lifetime_commission !== null ? formatMoney(c.lifetime_commission, currency) : '—'}</td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                )}
            </section>
        </div>
    );
};

export default PartnerCustomers;
