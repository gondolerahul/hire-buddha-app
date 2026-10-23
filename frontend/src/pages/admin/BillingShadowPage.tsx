/**
 * pages/admin/BillingShadowPage — the shadow comparison (Phase 15 T3-7). Staff only.
 *
 * Each settled run and call priced two ways: the old path's charge (the
 * formula on its total) and the sum of its usage rows rated at write. They
 * should agree; every difference is explained before the new path is switched
 * on (plan §1, T10-3).
 */
import React, { useCallback, useEffect, useState } from 'react';
import { Scale } from 'lucide-react';

import { apiClient } from '@/services/api.client';
import { apiErrorMessage } from '@/utils/apiError';
import { formatMoney } from '@/utils/money';
import { parseServerDate } from '@/utils/datetime';

import './CurrencyPage.css';

interface ShadowDiff {
    id: string;
    company_id: string;
    subject_type: 'run' | 'call';
    subject_id: string | null;
    rows: number;
    v1_billed_usd: number;
    v2_billed_usd: number;
    diff_usd: number;
    created_at: string | null;
}

interface ShadowReport {
    mode: 'off' | 'shadow' | 'on';
    days: number;
    summary: { settlements: number; differing: number; v1_billed_usd: number; v2_billed_usd: number; max_abs_diff_usd: number };
    recent: ShadowDiff[];
}

export const BillingShadowPage: React.FC = () => {
    const [days, setDays] = useState(14);
    const [report, setReport] = useState<ShadowReport | null>(null);
    const [error, setError] = useState<string | null>(null);

    const load = useCallback(() => {
        apiClient.get<ShadowReport>('/admin/billing-shadow', { params: { days } })
            .then(r => { setReport(r.data); setError(null); })
            .catch(err => setError(apiErrorMessage(err, 'Failed to load the shadow comparison')));
    }, [days]);

    useEffect(() => { load(); }, [load]);

    const setMode = async (mode: 'off' | 'shadow') => {
        try {
            await apiClient.put('/admin/billing-shadow/mode', { mode });
            load();
        } catch (err) {
            setError(apiErrorMessage(err, 'Failed to change the mode'));
        }
    };

    const s = report?.summary;
    return (
        <div className="currency-page">
            <div className="page-header">
                <div>
                    <h1 className="page-title"><Scale size={22} /> Billing shadow</h1>
                    <p className="page-subtitle">
                        Every settled run and call, billed the current way and as the sum of its rated usage rows.
                        They should agree; each difference is explained before the new settlement is switched on.
                    </p>
                </div>
            </div>
            {error && <div className="error-banner">{error}</div>}

            <section className="currency-card glass">
                <div className="currency-settings">
                    <label>Mode
                        <select value={report?.mode ?? 'shadow'} onChange={(e) => setMode(e.target.value as 'off' | 'shadow')}>
                            <option value="off">off — record nothing</option>
                            <option value="shadow">shadow — record the comparison</option>
                        </select>
                    </label>
                    <label>Period
                        <select value={days} onChange={(e) => setDays(Number(e.target.value))}>
                            {[1, 7, 14, 30, 90].map(d => <option key={d} value={d}>last {d} day{d > 1 ? 's' : ''}</option>)}
                        </select>
                    </label>
                </div>
                {s && (
                    <table className="currency-table" style={{ marginTop: '1rem' }}>
                        <tbody>
                            <tr><th>Settlements compared</th><td>{s.settlements}</td></tr>
                            <tr><th>That differ</th><td>{s.differing}</td></tr>
                            <tr><th>Billed (current path)</th><td>{formatMoney(s.v1_billed_usd, 'USD')}</td></tr>
                            <tr><th>Billed (rated rows)</th><td>{formatMoney(s.v2_billed_usd, 'USD')}</td></tr>
                            <tr><th>Largest difference</th><td>{formatMoney(s.max_abs_diff_usd, 'USD', { smallDigits: 8 })}</td></tr>
                        </tbody>
                    </table>
                )}
            </section>

            <section className="currency-card glass">
                <h2>Settlements (differences first)</h2>
                {report && report.recent.length === 0 ? <p className="card-desc">Nothing settled in this period.</p> : (
                    <table className="currency-table">
                        <thead><tr><th>When</th><th>Kind</th><th>Run</th><th>Rows</th><th>Current path</th><th>Rated rows</th><th>Difference</th></tr></thead>
                        <tbody>
                            {report?.recent.map(d => (
                                <tr key={d.id}>
                                    <td>{d.created_at ? parseServerDate(d.created_at).toLocaleString() : '—'}</td>
                                    <td>{d.subject_type}</td>
                                    <td className="muted">{d.subject_id?.slice(0, 8) ?? '—'}</td>
                                    <td>{d.rows}</td>
                                    <td>{formatMoney(d.v1_billed_usd, 'USD', { smallDigits: 6 })}</td>
                                    <td>{formatMoney(d.v2_billed_usd, 'USD', { smallDigits: 6 })}</td>
                                    <td>{d.diff_usd === 0 ? '—' : formatMoney(d.diff_usd, 'USD', { smallDigits: 8 })}</td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                )}
            </section>
        </div>
    );
};

export default BillingShadowPage;
