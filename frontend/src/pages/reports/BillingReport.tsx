import React, { useState, useEffect, useCallback } from 'react';
import { DollarSign, Download, RefreshCw, ChevronDown } from 'lucide-react'; import { billingService, BillingEvent, ReportTotals } from '@/services/billing.service';
import './Report.css';

const GROUPING_OPTIONS = [
    { value: '', label: 'No Grouping' },
    { value: 'partner', label: 'By Partner' },
    { value: 'tenant', label: 'By Tenant' },
    { value: 'user', label: 'By User' },
    { value: 'process', label: 'By Process' },
    { value: 'agent', label: 'By Agent' },
];

function getCurrentMonthStr(): string {
    const now = new Date();
    return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-01`;
}

function formatUSD(val: number): string {
    return `$${val.toFixed(4)}`;
}

function exportToCSV(events: BillingEvent[], filename: string) {
    const headers = ['Period', 'Grouping', 'Telephony Charge', 'Images Charge', 'Video Charge', 'API Charge', 'Total Billing', 'Tel In', 'Tel Out', 'Images', 'Videos'];
    const rows = events.map((e) => [
        e.period_month, e.grouping_value || '', e.telephony_charge, e.image_charge, e.video_charge, e.api_charge, e.total_billing,
        e.telephony_in_minutes, e.telephony_out_minutes, e.image_gen_count, e.video_gen_count,
    ]);
    const csv = [headers, ...rows].map((r) => r.join(',')).join('\n');
    const blob = new Blob([csv], { type: 'text/csv' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = filename;
    a.click();
}

const SummaryCard: React.FC<{ label: string; value: string; accent?: boolean }> = ({ label, value, accent }) => (
    <div className={`summary-card glass ${accent ? 'accent' : ''}`}>
        <p className="summary-label">{label}</p>
        <p className="summary-value">{value}</p>
    </div>
);

export const BillingReport: React.FC = () => {
    const [events, setEvents] = useState<BillingEvent[]>([]);
    const [totals, setTotals] = useState<ReportTotals>({});
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [periodMonth, setPeriodMonth] = useState(getCurrentMonthStr());
    const [groupingType, setGroupingType] = useState('');

    const fetchReport = useCallback(async () => {
        setLoading(true);
        setError(null);
        try {
            const res = await billingService.getBillingReport({
                period_month: periodMonth,
                grouping_type: groupingType || undefined,
            });
            setEvents(res.events);
            setTotals(res.totals);
        } catch (e: any) {
            setError(e?.response?.data?.detail || 'Failed to load billing report');
        } finally {
            setLoading(false);
        }
    }, [periodMonth, groupingType]);

    useEffect(() => { fetchReport(); }, [fetchReport]);

    return (
        <div className="report-page">
            <div className="page-header">
                <div>
                    <h1 className="page-title">
                        <DollarSign size={24} style={{ marginRight: '0.5rem' }} />
                        Billing Report
                    </h1>
                    <p className="page-subtitle">Client-facing revenue and billing totals</p>
                </div>
                <div className="report-header-actions">
                    <button className="btn-secondary" onClick={fetchReport}>
                        <RefreshCw size={14} /> Refresh
                    </button>
                    <button
                        className="btn-secondary"
                        onClick={() => exportToCSV(events, `billing-${periodMonth}.csv`)}
                    >
                        <Download size={14} /> Export CSV
                    </button>
                </div>
            </div>

            {/* Controls */}
            <div className="report-controls glass">
                <div className="control-group">
                    <label>Period (Month)</label>
                    <input
                        type="month"
                        value={periodMonth.slice(0, 7)}
                        onChange={(e) => setPeriodMonth(`${e.target.value}-01`)}
                    />
                </div>
                <div className="control-group">
                    <label>Group By</label>
                    <div className="select-wrapper">
                        <select value={groupingType} onChange={(e) => setGroupingType(e.target.value)}>
                            {GROUPING_OPTIONS.map((o) => (
                                <option key={o.value} value={o.value}>{o.label}</option>
                            ))}
                        </select>
                        <ChevronDown size={14} />
                    </div>
                </div>
            </div>

            {/* Summary Cards */}
            <div className="summary-grid">
                <SummaryCard accent label="Total Billed" value={formatUSD(totals.total_revenue || 0)} />
                <SummaryCard label="Telephony Charge" value={formatUSD(totals.total_telephony_charge || 0)} />
                <SummaryCard label="Intelligence Charge (LLM & API)" value={formatUSD((totals.total_llm_charge || 0) + (totals.total_api_charge || 0))} />
                <SummaryCard label="Media Content Charge" value={formatUSD((totals.total_image_charge || 0) + (totals.total_video_charge || 0))} />
            </div>

            {error && <div className="error-banner">{error}</div>}

            {loading ? (
                <div className="loading-state"><div className="pulse">Loading report…</div></div>
            ) : events.length === 0 ? (
                <div className="empty-state glass">
                    <div className="empty-icon">💰</div>
                    <h3>No billing data for this period</h3>
                    <p>Complete billable tasks to see revenue entries appear here.</p>
                </div>
            ) : (
                <div className="report-table-wrapper glass">
                    <table className="report-table">
                        <thead>
                            <tr>
                                <th>Period</th>
                                {groupingType && <th>Grouping</th>}
                                <th>Telephony Use</th>
                                <th>Telephony Charge</th>
                                <th>Media Gen Use</th>
                                <th>Media Gen Charge</th>
                                <th>Intelligence Charge</th>
                                <th className="highlight-col">Total Billing</th>
                            </tr>
                        </thead>
                        <tbody>
                            {events.map((e) => (
                                <tr key={e.id}>
                                    <td>{e.period_month}</td>
                                    {groupingType && <td>{e.grouping_value || '—'}</td>}
                                    <td className="num">
                                        {e.telephony_in_minutes.toFixed(1)}↓ / {e.telephony_out_minutes.toFixed(1)}↑
                                    </td>
                                    <td className="num">{formatUSD(e.telephony_charge)}</td>
                                    <td className="num">{e.image_gen_count} imgs / {e.video_gen_count} vids</td>
                                    <td className="num">{formatUSD(e.image_charge + e.video_charge)}</td>
                                    <td className="num">{formatUSD(e.llm_charge + e.api_charge)}</td>
                                    <td className="num total highlight-col">{formatUSD(e.total_billing)}</td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            )}
        </div>
    );
};
