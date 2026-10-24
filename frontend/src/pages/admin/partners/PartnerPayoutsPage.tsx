/**
 * pages/admin/partners/PartnerPayoutsPage — partner statements and payouts (Phase 15 T8-10, T8-14; 07 §4.1).
 *
 * Statements by month and status; make a month's now (the job makes them on
 * the statement day); approve (KYC and bank verified), export the bank file,
 * mark paid with the transfer reference; reopen a disputed one.
 */
import React, { useCallback, useEffect, useState } from 'react';
import { Download, Wallet } from 'lucide-react';

import { partnerAdmin, Statement } from '@/services/partners.service';
import { apiErrorMessage } from '@/utils/apiError';
import { formatMoney } from '@/utils/money';

import '@/pages/admin/MoneyConsole.css';
import '@/pages/partner/Partner.css';

export const PartnerPayoutsPage: React.FC = () => {
    const [rows, setRows] = useState<Statement[]>([]);
    const [status, setStatus] = useState('');
    const [period, setPeriod] = useState(() => {
        const d = new Date();
        d.setDate(1);
        d.setMonth(d.getMonth() - 1);
        return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-01`;
    });
    const [error, setError] = useState<string | null>(null);
    const [notice, setNotice] = useState<string | null>(null);

    const load = useCallback(async () => {
        try {
            setRows(await partnerAdmin.statements(status || undefined));
        } catch (err) {
            setError(apiErrorMessage(err, 'Statements could not be loaded'));
        }
    }, [status]);

    useEffect(() => { load(); }, [load]);

    const act = async (fn: () => Promise<unknown>, done: string) => {
        setError(null);
        try {
            await fn();
            setNotice(done);
            load();
        } catch (err) {
            setError(apiErrorMessage(err, 'Not done'));
        }
    };

    const paid = (s: Statement) => {
        const ref = prompt(`Mark ${formatMoney(s.net, s.currency)} to ${s.partner} paid. Transfer reference:`);
        if (ref) act(() => partnerAdmin.paid(s.id, ref), 'Marked paid; the partner is told.');
    };

    return (
        <div className="money-console">
            <div className="page-header">
                <div>
                    <h1 className="page-title"><Wallet size={22} /> Partner payouts</h1>
                    <p className="page-subtitle">Monthly statements of payable earnings, less TDS. Approve, pay by bank transfer, mark paid.</p>
                </div>
            </div>
            {error && <div className="error-banner">{error}</div>}
            {notice && <div className="success-banner">{notice}</div>}
            <section className="money-card glass">
                <div className="money-form" style={{ marginTop: 0 }}>
                    <label>Status
                        <select value={status} onChange={e => setStatus(e.target.value)}>
                            <option value="">All</option>
                            {['draft', 'approved', 'paid', 'disputed'].map(s => <option key={s} value={s}>{s}</option>)}
                        </select>
                    </label>
                    <label>Month<input type="date" value={period} onChange={e => setPeriod(e.target.value)} /></label>
                    <button className="btn-secondary" onClick={() => act(() => partnerAdmin.build(period), 'The month\'s statements are made.')}>Make statements</button>
                    <button className="btn-secondary" onClick={() => partnerAdmin.exportCsv().catch(err => setError(apiErrorMessage(err, 'Export failed')))}>
                        <Download size={14} /> Bank file (approved)
                    </button>
                </div>
                <table className="money-table" style={{ marginTop: '1rem' }}>
                    <thead><tr><th>Partner</th><th>Month</th><th>Gross</th><th>TDS</th><th>Net</th><th>Status</th><th>GST invoice</th><th /></tr></thead>
                    <tbody>
                        {rows.map(s => (
                            <tr key={s.id}>
                                <td>{s.partner}</td><td>{s.period.slice(0, 7)}</td>
                                <td>{formatMoney(s.gross, s.currency)}</td><td>{formatMoney(s.tds, s.currency)}</td>
                                <td><strong>{formatMoney(s.net, s.currency)}</strong></td>
                                <td>{s.status}{s.dispute_reason ? ` — ${s.dispute_reason}` : ''}{s.payout_ref ? ` · ${s.payout_ref}` : ''}</td>
                                <td>{s.gst_invoice_ref ? 'yes' : '—'}</td>
                                <td style={{ whiteSpace: 'nowrap' }}>
                                    <button className="btn-secondary" onClick={() => partnerAdmin.statementPdf(s.id)}>PDF</button>{' '}
                                    {s.status === 'draft' && <button className="btn-primary" onClick={() => act(() => partnerAdmin.approveStatement(s.id), 'Approved.')}>Approve</button>}
                                    {s.status === 'approved' && <button className="btn-primary" onClick={() => paid(s)}>Mark paid</button>}
                                    {s.status === 'disputed' && <button className="btn-secondary" onClick={() => act(() => partnerAdmin.reopen(s.id), 'Reopened as a draft.')}>Reopen</button>}
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </section>
        </div>
    );
};

export default PartnerPayoutsPage;
