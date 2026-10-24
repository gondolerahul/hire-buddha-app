/**
 * pages/partner/PartnerEarnings — the ledger and statements (Phase 15 T8-7, T8-10, T8-14; 07 §5.9).
 *
 * Earnings: every entry with its source, base, rate, amount and status
 * (accrued → payable after the holdback → paid), clawbacks in red, totals by
 * status; each entry says what it is ("20 % of a INR 1,00,000.00 top-up by your
 * customer"). Statements: monthly, TDS deducted; download, dispute, upload
 * your GST invoice.
 */
import React, { useCallback, useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Download, PiggyBank, Upload } from 'lucide-react';

import { LEDGER_STATUS_LABEL, LedgerEntry, partnerPortal, REVENUE_LABEL, Statement } from '@/services/partners.service';
import { apiErrorMessage } from '@/utils/apiError';
import { formatDate } from '@/utils/datetime';
import { formatMoney } from '@/utils/money';

import '@/pages/admin/MoneyConsole.css';
import './Partner.css';

export const PartnerEarnings: React.FC = () => {
    const [params, setParams] = useSearchParams();
    const tab = params.get('tab') === 'statements' ? 'statements' : 'earnings';
    const [entries, setEntries] = useState<LedgerEntry[]>([]);
    const [totals, setTotals] = useState<Record<string, string>>({});
    const [currency, setCurrency] = useState('INR');
    const [filter, setFilter] = useState({ status: '', revenue_kind: '' });
    const [stmts, setStmts] = useState<Statement[]>([]);
    const [error, setError] = useState<string | null>(null);
    const [notice, setNotice] = useState<string | null>(null);

    const load = useCallback(async () => {
        try {
            if (tab === 'earnings') {
                const res = await partnerPortal.earnings(Object.fromEntries(Object.entries(filter).filter(([, v]) => v)));
                setEntries(res.entries);
                setTotals(res.totals);
                setCurrency(res.currency);
            } else {
                setStmts(await partnerPortal.statements());
            }
        } catch (err) {
            setError(apiErrorMessage(err, 'Earnings could not be loaded'));
        }
    }, [tab, filter]);

    useEffect(() => { load(); }, [load]);

    const dispute = async (s: Statement) => {
        const reason = prompt('What is wrong with this statement?');
        if (!reason) return;
        try {
            await partnerPortal.dispute(s.id, reason);
            setNotice('Disputed: HireBuddha will look at it.');
            load();
        } catch (err) {
            setError(apiErrorMessage(err, 'The dispute was not sent'));
        }
    };

    const upload = async (s: Statement, file: File | undefined) => {
        if (!file) return;
        try {
            await partnerPortal.uploadGstInvoice(s.id, file);
            setNotice('Your GST invoice is attached to the statement.');
            load();
        } catch (err) {
            setError(apiErrorMessage(err, 'The invoice was not uploaded'));
        }
    };

    return (
        <div className="money-console partner-page">
            <div className="page-header">
                <div>
                    <h1 className="page-title"><PiggyBank size={22} /> Earnings</h1>
                    <p className="page-subtitle">
                        Commission on what your customers pay, overrides on your partners' customers, your share of setup
                        fees. Payable after the holdback; paid monthly, less TDS.
                    </p>
                </div>
            </div>
            <div className="partner-tabs">
                <button className={tab === 'earnings' ? 'active' : ''} onClick={() => setParams({})}>Ledger</button>
                <button className={tab === 'statements' ? 'active' : ''} onClick={() => setParams({ tab: 'statements' })}>Statements &amp; payouts</button>
            </div>
            {error && <div className="error-banner">{error}</div>}
            {notice && <div className="success-banner">{notice}</div>}
            {tab === 'earnings' ? (
                <>
                    <div className="partner-tiles">
                        {Object.entries(totals).map(([status, amount]) => (
                            <div key={status} className="partner-tile glass">
                                <p className="partner-tile-label">{LEDGER_STATUS_LABEL[status] ?? status}</p>
                                <p className="partner-tile-value">{formatMoney(amount, currency)}</p>
                            </div>
                        ))}
                    </div>
                    <section className="money-card glass">
                        <div className="money-form" style={{ marginTop: 0 }}>
                            <label>Status
                                <select value={filter.status} onChange={e => setFilter({ ...filter, status: e.target.value })}>
                                    <option value="">All</option>
                                    {Object.keys(LEDGER_STATUS_LABEL).map(s => <option key={s} value={s}>{LEDGER_STATUS_LABEL[s]}</option>)}
                                </select>
                            </label>
                            <label>Source
                                <select value={filter.revenue_kind} onChange={e => setFilter({ ...filter, revenue_kind: e.target.value })}>
                                    <option value="">All</option>
                                    {Object.keys(REVENUE_LABEL).map(k => <option key={k} value={k}>{REVENUE_LABEL[k]}</option>)}
                                </select>
                            </label>
                        </div>
                        {entries.length === 0 ? <p className="card-desc">Nothing yet.</p> : (
                            <table className="money-table" style={{ marginTop: '1rem' }}>
                                <thead><tr><th>Date</th><th>Customer</th><th>Source</th><th>Base</th><th>Rate</th><th>Amount</th><th>Status</th></tr></thead>
                                <tbody>
                                    {entries.map(e => (
                                        <tr key={e.id} title={e.reason ?? ''}>
                                            <td>{e.created_at ? formatDate(e.created_at) : ''}</td>
                                            <td>{e.tenant ?? '—'}</td>
                                            <td>{e.kind === 'override' ? `Override (level ${e.level})` : REVENUE_LABEL[e.revenue_kind ?? ''] ?? e.kind}</td>
                                            <td>{e.base_amount ? formatMoney(e.base_amount, e.base_currency ?? currency) : '—'}</td>
                                            <td>{e.rate_pct ? `${Number(e.rate_pct)} %` : '—'}</td>
                                            <td className={Number(e.amount) < 0 ? 'amount-neg' : ''}>{formatMoney(e.amount, e.currency)}</td>
                                            <td>
                                                {LEDGER_STATUS_LABEL[e.status] ?? e.status}
                                                {e.hold_reason ? ` (${e.hold_reason.replace('_', ' ')})` : ''}
                                                {e.status === 'accrued' && e.payable_after ? <div className="partner-explain">payable from {formatDate(e.payable_after)}</div> : null}
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        )}
                    </section>
                </>
            ) : (
                <section className="money-card glass">
                    {stmts.length === 0 ? <p className="card-desc">No statements yet: they are made on the 5th for the month before.</p> : (
                        <table className="money-table">
                            <thead><tr><th>Month</th><th>Gross</th><th>TDS</th><th>Net</th><th>Status</th><th>GST invoice</th><th /></tr></thead>
                            <tbody>
                                {stmts.map(s => (
                                    <tr key={s.id}>
                                        <td>{s.period.slice(0, 7)}</td>
                                        <td>{formatMoney(s.gross, s.currency)}</td>
                                        <td>{formatMoney(s.tds, s.currency)}</td>
                                        <td><strong>{formatMoney(s.net, s.currency)}</strong></td>
                                        <td>{s.status}{s.payout_ref ? ` · ${s.payout_ref}` : ''}</td>
                                        <td>
                                            {s.gst_invoice_ref ? 'attached' : (
                                                <label className="btn-secondary" style={{ cursor: 'pointer' }}>
                                                    <Upload size={14} /> Upload
                                                    <input type="file" accept="application/pdf,image/*" hidden
                                                           onChange={e => upload(s, e.target.files?.[0])} />
                                                </label>
                                            )}
                                        </td>
                                        <td style={{ whiteSpace: 'nowrap' }}>
                                            <button className="btn-secondary" onClick={() => partnerPortal.statementPdf(s.id)
                                                .catch(err => setError(apiErrorMessage(err, 'The PDF could not be opened')))}>
                                                <Download size={14} /> PDF
                                            </button>{' '}
                                            {['draft', 'approved'].includes(s.status) && (
                                                <button className="btn-secondary" onClick={() => dispute(s)}>Dispute</button>
                                            )}
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    )}
                </section>
            )}
        </div>
    );
};

export default PartnerEarnings;
