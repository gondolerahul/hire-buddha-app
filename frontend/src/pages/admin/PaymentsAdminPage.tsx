/**
 * pages/admin/PaymentsAdminPage — payments and refunds, for staff (Phase 15 T6-6, T6-7).
 *
 * Every gateway payment with its net, GST and invoice. A refund is of a net
 * amount (all that is left by default): the gateway refunds it with its GST,
 * the credit it bought is taken back from the wallet (into debt when already
 * spent), and a credit note is issued against the invoice. Audited.
 */
import React, { useCallback, useEffect, useState } from 'react';
import { Download, Receipt, Undo2 } from 'lucide-react';

import { AdminPayment, plansService } from '@/services/plans.service';
import { useCompanyList } from '@/queries/hooks';
import { apiErrorMessage } from '@/utils/apiError';
import { formatDateTime } from '@/utils/datetime';
import { formatMoney } from '@/utils/money';

import './MoneyConsole.css';

export const PaymentsAdminPage: React.FC = () => {
    const companies = useCompanyList<{ id: string; name: string }>(true).data ?? [];
    const names = Object.fromEntries(companies.map(c => [c.id, c.name]));
    const [companyId, setCompanyId] = useState('');
    const [status, setStatus] = useState('');
    const [payments, setPayments] = useState<AdminPayment[]>([]);
    const [refunding, setRefunding] = useState<AdminPayment | null>(null);
    const [form, setForm] = useState({ net: '', reason: '' });
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [notice, setNotice] = useState<string | null>(null);

    const load = useCallback(async () => {
        try {
            setPayments(await plansService.adminPayments({ company_id: companyId || undefined, status: status || undefined }));
            setError(null);
        } catch (err) {
            setError(apiErrorMessage(err, 'Payments could not be loaded'));
        }
    }, [companyId, status]);

    useEffect(() => { load(); }, [load]);

    const refundable = (p: AdminPayment) => p.status === 'success' && !!p.gateway_payment_id
        && Number(p.gross) - Number(p.refunded_gross) > 0;

    const refund = async (e: React.FormEvent) => {
        e.preventDefault();
        if (!refunding) return;
        setBusy(true);
        try {
            const done = await plansService.refund(refunding.id, { net: form.net.trim() || undefined, reason: form.reason.trim() });
            setNotice(`Refunded ${formatMoney(done.gross, done.currency)} (net ${formatMoney(done.net, done.currency)}); `
                + `${formatMoney(done.credit_taken, done.currency)} credit taken back`
                + (Number(done.debt_added) > 0 ? `, ${formatMoney(done.debt_added, done.currency)} into debt` : '')
                + (done.credit_note_id ? '; credit note issued.' : '.'));
            setRefunding(null);
            setForm({ net: '', reason: '' });
            load();
        } catch (err) {
            setError(apiErrorMessage(err, 'The refund failed'));
        } finally {
            setBusy(false);
        }
    };

    return (
        <div className="money-console">
            <div className="page-header">
                <div>
                    <h1 className="page-title"><Receipt size={22} /> Payments</h1>
                    <p className="page-subtitle">Gateway payments with their GST invoices; refunds issue a credit note.</p>
                </div>
            </div>
            {error && <div className="error-banner">{error}</div>}
            {notice && <div className="success-banner">{notice}</div>}
            <section className="money-card glass">
                <div className="money-form" style={{ marginTop: 0 }}>
                    <label>Company
                        <select value={companyId} onChange={(e) => setCompanyId(e.target.value)}>
                            <option value="">All</option>
                            {companies.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
                        </select>
                    </label>
                    <label>Status
                        <select value={status} onChange={(e) => setStatus(e.target.value)}>
                            <option value="">All</option>
                            {['pending', 'success', 'failed'].map(s => <option key={s} value={s}>{s}</option>)}
                        </select>
                    </label>
                </div>
                <table className="money-table" style={{ marginTop: '1rem' }}>
                    <thead>
                        <tr><th>When</th><th>Company</th><th>For</th><th>Status</th><th>Net</th><th>GST</th><th>Gross</th>
                            <th>Refunded</th><th>Invoice</th><th /></tr>
                    </thead>
                    <tbody>
                        {payments.map(p => (
                            <tr key={p.id} className={refunding?.id === p.id ? 'selected' : ''}>
                                <td>{p.created_at ? formatDateTime(p.created_at) : ''}</td>
                                <td>{names[p.company_id] ?? p.company_id.slice(0, 8)}</td>
                                <td>{p.purpose}</td>
                                <td>{p.status}</td>
                                <td>{formatMoney(p.net, p.currency)}</td>
                                <td>{formatMoney(p.tax, p.currency)}</td>
                                <td>{formatMoney(p.gross, p.currency)}</td>
                                <td>{Number(p.refunded_gross) > 0 ? formatMoney(p.refunded_gross, p.currency) : '—'}</td>
                                <td>
                                    {p.invoice_id
                                        ? <button className="btn-secondary" onClick={() => plansService.openInvoicePdf(p.invoice_id!)
                                            .catch(err => setError(apiErrorMessage(err, 'The PDF could not be opened')))}>
                                            <Download size={14} /> {p.invoice_number}
                                        </button>
                                        : '—'}
                                </td>
                                <td>
                                    {refundable(p) && (
                                        <button className="btn-secondary" onClick={() => { setRefunding(p); setForm({ net: '', reason: '' }); }}>
                                            <Undo2 size={14} /> Refund
                                        </button>
                                    )}
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
                {refunding && (
                    <form className="money-form" onSubmit={refund}>
                        <label>Net to refund ({refunding.currency}; blank: all that is left)
                            <input type="text" inputMode="decimal" value={form.net}
                                   onChange={(e) => setForm({ ...form, net: e.target.value })} /></label>
                        <label className="grow">Reason (on the credit note, audited)
                            <input type="text" value={form.reason} required minLength={3}
                                   onChange={(e) => setForm({ ...form, reason: e.target.value })} /></label>
                        <button type="submit" className="btn-primary" disabled={busy}>{busy ? 'Refunding…' : 'Refund'}</button>
                        <button type="button" className="btn-secondary" onClick={() => setRefunding(null)}>Cancel</button>
                    </form>
                )}
            </section>
        </div>
    );
};

export default PaymentsAdminPage;
