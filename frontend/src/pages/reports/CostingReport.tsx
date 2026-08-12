import React, { useState, useEffect, useCallback } from 'react';
import { BarChart2, Download, RefreshCw, ChevronDown } from 'lucide-react';
import { billingService, BillingEvent, ReportTotals } from '@/services/billing.service';
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
    const headers = [
        'Period', 'Grouping Type', 'Grouping Value', 'Base Cost', 'Multiplied',
        'Platform Fee', 'Partner Fee', 'Discount', 'Total', 'Tel In (min)',
        'Tel Out (min)', 'Images', 'Videos', 'Other AI Cost',
    ];
    const rows = events.map((e) => [
        e.period_month, e.grouping_type, e.grouping_value, e.base_cost,
        e.multiplied_cost, e.platform_fee_amount, e.partner_fee_amount,
        e.discount_amount, e.total_billing, e.telephony_in_minutes,
        e.telephony_out_minutes, e.image_gen_count, e.video_gen_count, e.other_ai_cost,
    ]);
    const csv = [headers, ...rows].map((r) => r.join(',')).join('\n');
    const blob = new Blob([csv], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
}

const SummaryCard: React.FC<{ label: string; value: string; sub?: string }> = ({ label, value, sub }) => (
    <div className="summary-card glass">
        <p className="summary-label">{label}</p>
        <p className="summary-value">{value}</p>
        {sub && <p className="summary-sub">{sub}</p>}
    </div>
);

export const CostingReport: React.FC = () => {
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
            const res = await billingService.getCostingReport({
                period_month: periodMonth,
                grouping_type: groupingType || undefined,
            });
            setEvents(res.events);
            setTotals(res.totals);
        } catch (e: any) {
            setError(e?.response?.data?.detail || 'Failed to load report');
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
                        <BarChart2 size={24} style={{ marginRight: '0.5rem' }} />
                        Costing Report
                    </h1>
                    <p className="page-subtitle">Internal operational expense tracking</p>
                </div>
                <div className="report-header-actions">
                    <button className="btn-secondary" onClick={fetchReport}>
                        <RefreshCw size={14} /> Refresh
                    </button>
                    <button
                        className="btn-secondary"
                        onClick={() => exportToCSV(events, `costing-${periodMonth}.csv`)}
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
                <SummaryCard label="Total Base Cost" value={formatUSD(totals.total_base_cost || 0)} />
                <SummaryCard label="Total Billing (TB)" value={formatUSD(totals.total_billing || 0)} />
                <SummaryCard
                    label="Telephony"
                    value={`${(totals.total_telephony_in_minutes || 0).toFixed(1)} in / ${(totals.total_telephony_out_minutes || 0).toFixed(1)} out`}
                    sub="minutes"
                />
                <SummaryCard
                    label="Media Generation"
                    value={`${totals.total_image_gen || 0} images / ${totals.total_video_gen || 0} videos`}
                />
                <SummaryCard label="Other AI Cost" value={formatUSD(totals.total_other_ai_cost || 0)} />
            </div>

            {error && <div className="error-banner">{error}</div>}

            {/* Table */}
            {loading ? (
                <div className="loading-state"><div className="pulse">Loading report…</div></div>
            ) : events.length === 0 ? (
                <div className="empty-state glass">
                    <div className="empty-icon">📊</div>
                    <h3>No data for this period</h3>
                    <p>Complete some agent tasks to generate billing events.</p>
                </div>
            ) : (
                <div className="report-table-wrapper glass">
                    <table className="report-table">
                        <thead>
                            <tr>
                                <th>Period</th>
                                {groupingType && <th>Grouping</th>}
                                <th>Base Cost</th>
                                <th>Multiplied</th>
                                <th>Platform Fee</th>
                                <th>Partner Fee</th>
                                <th>Discount</th>
                                <th>Total (TB)</th>
                                <th>Tel In</th>
                                <th>Tel Out</th>
                                <th>Images</th>
                                <th>Videos</th>
                                <th>Other AI</th>
                            </tr>
                        </thead>
                        <tbody>
                            {events.map((e) => (
                                <tr key={e.id}>
                                    <td>{e.period_month}</td>
                                    {groupingType && <td>{e.grouping_value || '—'}</td>}
                                    <td className="num">{formatUSD(e.base_cost)}</td>
                                    <td className="num">{formatUSD(e.multiplied_cost)}</td>
                                    <td className="num">{formatUSD(e.platform_fee_amount)}</td>
                                    <td className="num">{formatUSD(e.partner_fee_amount)}</td>
                                    <td className="num deduction">-{formatUSD(e.discount_amount)}</td>
                                    <td className="num total">{formatUSD(e.total_billing)}</td>
                                    <td className="num">{e.telephony_in_minutes.toFixed(1)}'</td>
                                    <td className="num">{e.telephony_out_minutes.toFixed(1)}'</td>
                                    <td className="num">{e.image_gen_count}</td>
                                    <td className="num">{e.video_gen_count}</td>
                                    <td className="num">{formatUSD(e.other_ai_cost)}</td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            )}
        </div>
    );
};
