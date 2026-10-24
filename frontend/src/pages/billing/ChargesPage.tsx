/**
 * pages/billing/ChargesPage — setup and customisation fees a business is asked to pay (Phase 15 T8-8).
 *
 * Raised by its partner (or HireBuddha); paid here, with GST, directly (not
 * from the wallet); the invoice is on the Invoices page.
 */
import React, { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Receipt } from 'lucide-react';

import { useAuth } from '@/hooks/useAuth';
import { Charge, partnerBusiness, payOrder } from '@/services/partners.service';
import { apiErrorMessage } from '@/utils/apiError';
import { formatDate } from '@/utils/datetime';
import { formatMoney } from '@/utils/money';

import '@/pages/admin/MoneyConsole.css';

export const ChargesPage: React.FC = () => {
    const { user } = useAuth();
    const admin = user?.role === 'tenant_admin';
    const [rows, setRows] = useState<Charge[]>([]);
    const [busy, setBusy] = useState<string | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [notice, setNotice] = useState<string | null>(null);

    const load = useCallback(async () => {
        try {
            setRows(await partnerBusiness.charges());
        } catch (err) {
            setError(apiErrorMessage(err, 'Charges could not be loaded'));
        }
    }, []);

    useEffect(() => { load(); }, [load]);

    const pay = async (charge: Charge) => {
        setBusy(charge.id);
        setError(null);
        try {
            const order = await partnerBusiness.chargeOrder(charge.id);
            const proof = await payOrder(order);
            await partnerBusiness.chargeVerify(charge.id, proof);
            setNotice('Paid, thank you. The invoice is on the Invoices page.');
            load();
        } catch (err) {
            setError(apiErrorMessage(err, 'The payment did not go through'));
        } finally {
            setBusy(null);
        }
    };

    return (
        <div className="money-console">
            <div className="page-header">
                <div>
                    <h1 className="page-title"><Receipt size={22} /> Fees to pay</h1>
                    <p className="page-subtitle">
                        One-off setup and customisation fees, paid directly with GST — not from your wallet.
                        Invoices are on the <Link to="/billing/invoices">Invoices</Link> page.
                    </p>
                </div>
            </div>
            {error && <div className="error-banner">{error}</div>}
            {notice && <div className="success-banner">{notice}</div>}
            <section className="money-card glass">
                {rows.length === 0 ? <p className="card-desc">Nothing to pay.</p> : (
                    <table className="money-table">
                        <thead><tr><th>For</th><th>From</th><th>Amount (before GST)</th><th>Status</th><th>Raised</th><th /></tr></thead>
                        <tbody>
                            {rows.map(c => (
                                <tr key={c.id}>
                                    <td>{c.fee_kind}{c.description ? ` · ${c.description}` : ''}</td>
                                    <td>{c.partner ?? 'HireBuddha'}</td>
                                    <td>{formatMoney(c.amount, c.currency)}</td>
                                    <td>{c.status}</td>
                                    <td>{c.created_at ? formatDate(c.created_at) : ''}</td>
                                    <td>
                                        {c.status === 'sent' && admin && (
                                            <button className="btn-primary" disabled={busy === c.id} onClick={() => pay(c)}>
                                                {busy === c.id ? 'Opening checkout…' : 'Pay'}
                                            </button>
                                        )}
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                )}
                {!admin && <p className="card-desc">Only your company's admins can pay.</p>}
            </section>
        </div>
    );
};

export default ChargesPage;
