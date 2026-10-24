/**
 * pages/admin/WalletsAdminPage — every company's wallet, for staff (Phase 15 T4-1, T2-7; 07 §5.5).
 *
 * - The wallets by state (ok, in debt, over the limit, suspended), with search.
 * - One wallet: its lots, ledger and consistency check; a staff adjustment
 *   (always with a reason: + a grant that does not repay debt, − a deduction);
 *   the currency tool, which converts lots and debt at one rate.
 *
 * No control moves value between companies (W-1). Lives under /admin/wallets
 * until the Platform Console shell (T9-1).
 */
import React, { useCallback, useEffect, useState } from 'react';
import { AlertTriangle, ArrowLeftRight, RefreshCw, Search, Wallet } from 'lucide-react';

import { apiErrorMessage } from '@/utils/apiError';
import { formatDate, formatDateTime } from '@/utils/datetime';
import { formatMoney } from '@/utils/money';
import { moneyConsole, WalletDetail, WalletRow } from '@/services/moneyConsole.service';
import type { WalletState } from '@/services/credits.service';

import './MoneyConsole.css';

const STATES: WalletState[] = ['ok', 'in_debt', 'over_tolerance', 'suspended'];
const STATE_LABEL: Record<WalletState, string> = {
    ok: 'ok', in_debt: 'in debt', over_tolerance: 'over limit', suspended: 'suspended',
};

export const WalletsAdminPage: React.FC = () => {
    const [rows, setRows] = useState<WalletRow[]>([]);
    const [counts, setCounts] = useState<Partial<Record<WalletState, number>>>({});
    const [state, setState] = useState<string>('');
    const [query, setQuery] = useState('');
    const [selected, setSelected] = useState<string | null>(null);
    const [detail, setDetail] = useState<WalletDetail | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [notice, setNotice] = useState<string | null>(null);

    const load = useCallback(async () => {
        try {
            const data = await moneyConsole.listWallets({ state: state || undefined, q: query.trim() || undefined });
            setRows(data.wallets);
            setCounts(data.counts);
            setError(null);
        } catch (err) {
            setError(apiErrorMessage(err, 'Failed to load wallets'));
        }
    }, [state, query]);

    const open = useCallback(async (companyId: string) => {
        setSelected(companyId);
        try {
            setDetail(await moneyConsole.getWallet(companyId));
        } catch (err) {
            setError(apiErrorMessage(err, 'Failed to load the wallet'));
        }
    }, []);

    useEffect(() => { load(); }, [load]);

    const changed = async (message: string) => {
        setNotice(message);
        await load();
        if (selected) await open(selected);
    };

    return (
        <div className="money-console">
            <div className="page-header">
                <div>
                    <h1 className="page-title"><Wallet size={22} /> Wallets</h1>
                    <p className="page-subtitle">
                        Each company's credit, in its billing currency: lots spent daily → subscription → bonus →
                        top-ups by expiry, then debt. Every change is on the ledger.
                    </p>
                </div>
                <button className="btn-secondary" onClick={load}><RefreshCw size={14} /> Refresh</button>
            </div>

            {error && <div className="error-banner">{error}</div>}
            {notice && <div className="success-banner">{notice}</div>}

            <section className="money-card glass">
                <div className="money-toolbar">
                    <select value={state} onChange={(e) => setState(e.target.value)} aria-label="State">
                        <option value="">All states</option>
                        {STATES.map(s => <option key={s} value={s}>{STATE_LABEL[s]} ({counts[s] ?? 0})</option>)}
                    </select>
                    <label className="muted" style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                        <Search size={14} />
                        <input type="text" placeholder="Company name" value={query}
                               onChange={(e) => setQuery(e.target.value)} />
                    </label>
                </div>
                <table className="money-table">
                    <thead>
                        <tr><th>Company</th><th>Type</th><th>State</th><th>Available</th><th>Owed</th><th>In debt since</th></tr>
                    </thead>
                    <tbody>
                        {rows.map(w => (
                            <tr key={w.company_id} className={`clickable ${selected === w.company_id ? 'selected' : ''}`}
                                onClick={() => open(w.company_id)}>
                                <td>{w.company_name}</td>
                                <td className="muted">{w.company_type}</td>
                                <td><span className={`state-pill ${w.state}`}>{STATE_LABEL[w.state]}</span></td>
                                <td>{formatMoney(w.available, w.currency)}</td>
                                <td>{Number(w.debt) > 0 ? formatMoney(w.debt, w.currency) : '—'}</td>
                                <td>{w.in_debt_since ? formatDate(w.in_debt_since) : '—'}</td>
                            </tr>
                        ))}
                        {rows.length === 0 && <tr><td colSpan={6} className="muted">No wallets match.</td></tr>}
                    </tbody>
                </table>
            </section>

            {detail && (
                <WalletPanel detail={detail} onChanged={changed} onError={setError} />
            )}
        </div>
    );
};

const WalletPanel: React.FC<{
    detail: WalletDetail;
    onChanged: (message: string) => Promise<void>;
    onError: (message: string) => void;
}> = ({ detail, onChanged, onError }) => {
    const w = detail.wallet;
    const [amount, setAmount] = useState('');
    const [reason, setReason] = useState('');
    const [expires, setExpires] = useState('');
    const [currency, setCurrency] = useState(w.currency === 'INR' ? 'USD' : 'INR');
    const [currencyReason, setCurrencyReason] = useState('');
    const [busy, setBusy] = useState(false);

    const adjust = async (e: React.FormEvent) => {
        e.preventDefault();
        setBusy(true);
        try {
            await moneyConsole.adjustWallet(detail.company_id, {
                amount: amount.trim(), reason: reason.trim(),
                ...(expires ? { expires_in_days: Number(expires) } : {}),
            });
            setAmount('');
            setReason('');
            setExpires('');
            await onChanged(`${detail.company_name}: ${formatMoney(amount, w.currency)} adjusted.`);
        } catch (err) {
            onError(apiErrorMessage(err, 'The adjustment was not made'));
        } finally {
            setBusy(false);
        }
    };

    const convert = async (e: React.FormEvent) => {
        e.preventDefault();
        if (!confirm(`Convert ${detail.company_name}'s wallet from ${w.currency} to ${currency} at today's rate?`)) return;
        setBusy(true);
        try {
            await moneyConsole.changeCurrency(detail.company_id, { currency, reason: currencyReason.trim() });
            setCurrencyReason('');
            await onChanged(`${detail.company_name} is billed in ${currency} now.`);
        } catch (err) {
            onError(apiErrorMessage(err, 'The currency was not changed'));
        } finally {
            setBusy(false);
        }
    };

    return (
        <section className="money-card glass">
            <h2>
                {detail.company_name} <span className={`state-pill ${w.state}`}>{STATE_LABEL[w.state]}</span>
            </h2>
            {detail.problems.length > 0 && (
                <div className="error-banner"><AlertTriangle size={14} /> Wallet and ledger disagree: {detail.problems.join('; ')}</div>
            )}
            <p className="card-desc">
                Available {formatMoney(w.available, w.currency)} · held {formatMoney(w.held, w.currency)} ·
                free {formatMoney(w.free, w.currency)} · owed {formatMoney(w.debt, w.currency)} ·
                tolerance {formatMoney(w.tolerance, w.currency)}
                {w.suspended_at && ` · suspended ${formatDate(w.suspended_at)}`}
            </p>
            <div className="two-col">
                <div>
                    <h3>Live lots</h3>
                    <table className="money-table">
                        <thead><tr><th>Kind</th><th>Left</th><th>Of</th><th>Paid</th><th>Expires</th></tr></thead>
                        <tbody>
                            {w.lots.map(lot => (
                                <tr key={lot.id}>
                                    <td>{lot.kind.replace('_', ' ')}</td>
                                    <td>{formatMoney(lot.remaining, w.currency)}</td>
                                    <td>{formatMoney(lot.original, w.currency)}</td>
                                    <td>{lot.paid ? 'yes' : 'no'}</td>
                                    <td>{lot.expires_at ? formatDate(lot.expires_at) : '—'}</td>
                                </tr>
                            ))}
                            {w.lots.length === 0 && <tr><td colSpan={5} className="muted">No live credit.</td></tr>}
                        </tbody>
                    </table>

                    <h3>Adjust</h3>
                    <form className="money-form" onSubmit={adjust}>
                        <label>Amount ({w.currency}; − deducts)
                            <input type="text" inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)}
                                   pattern="-?\d+(\.\d{1,4})?" required />
                        </label>
                        <label>Valid for (days, a grant)
                            <input type="number" min="1" value={expires} onChange={(e) => setExpires(e.target.value)} />
                        </label>
                        <label className="grow">Reason (kept on the ledger and in the audit)
                            <input type="text" value={reason} onChange={(e) => setReason(e.target.value)} minLength={3} required />
                        </label>
                        <button className="btn-primary" type="submit" disabled={busy}>Adjust</button>
                    </form>

                    <h3><ArrowLeftRight size={16} /> Billing currency</h3>
                    <p className="card-desc">
                        Converts every live lot and the debt at today's rate. Refused while a subscription is live.
                    </p>
                    <form className="money-form" onSubmit={convert}>
                        <label>To
                            <select value={currency} onChange={(e) => setCurrency(e.target.value)}>
                                {['INR', 'USD'].filter(c => c !== w.currency).map(c => <option key={c} value={c}>{c}</option>)}
                            </select>
                        </label>
                        <label className="grow">Reason
                            <input type="text" value={currencyReason} onChange={(e) => setCurrencyReason(e.target.value)}
                                   minLength={3} required />
                        </label>
                        <button className="btn-secondary" type="submit" disabled={busy}>Change currency</button>
                    </form>
                </div>
                <div>
                    <h3>Ledger</h3>
                    <table className="money-table">
                        <thead><tr><th>When</th><th>What</th><th>Amount</th><th>After</th></tr></thead>
                        <tbody>
                            {detail.entries.map(e => (
                                <tr key={e.id}>
                                    <td>{e.created_at ? formatDateTime(e.created_at) : ''}</td>
                                    <td>
                                        {e.kind.replace('_', ' ')}{e.category ? ` · ${e.category}` : ''}
                                        {e.reason && <div className="muted">{e.reason}</div>}
                                    </td>
                                    <td className={Number(e.amount) < 0 ? 'amount-out' : 'amount-in'}>
                                        {formatMoney(e.amount, e.currency)}
                                    </td>
                                    <td>
                                        {formatMoney(e.balance_after, e.currency)}
                                        {Number(e.debt_after) > 0 && <div className="muted">owes {formatMoney(e.debt_after, e.currency)}</div>}
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            </div>
        </section>
    );
};

export default WalletsAdminPage;
