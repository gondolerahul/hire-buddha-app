import { parseServerDate } from '@/utils/datetime';
import React, { useState, useEffect } from 'react';
import {
    BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
    LineChart, Line, AreaChart, Area, Cell,
} from 'recharts';
import {
    Bug, Activity, Clock, AlertTriangle, Server, Database,
    CheckCircle, XCircle, Shield,
} from 'lucide-react';
import { reportsService } from '@/services/reports.service';
import './Report.css';

const CHART_COLORS = ['#e8c5a0', '#c9956c', '#9b6fa0', '#6b9bd2', '#4dbe8d', '#e8885a'];

const StatCard: React.FC<{ label: string; value: string | number; icon: React.ElementType; color?: string }> = ({ label, value, icon: Icon, color }) => (
    <div className="stat-card glass">
        <div className="stat-card-icon" style={{ color: color || '#e8c5a0' }}><Icon size={20} /></div>
        <div>
            <p className="stat-label">{label}</p>
            <p className="stat-value" style={{ color: color || '#e8c5a0' }}>{value}</p>
        </div>
    </div>
);

const SectionTitle: React.FC<{ children: React.ReactNode }> = ({ children }) => (
    <h3 className="section-title">{children}</h3>
);

const EmptyChart: React.FC<{ message?: string }> = ({ message = 'No data available' }) => (
    <div className="chart-empty"><AlertTriangle size={32} opacity={0.3} /><p>{message}</p></div>
);

const TABS = [
    { id: 'incidents', label: 'Incidents & Traceability', icon: Bug },
    { id: 'providers', label: 'Provider Health', icon: Server },
    { id: 'latency', label: 'Execution Latency', icon: Clock },
    { id: 'rate-limits', label: 'Rate Limits & Quotas', icon: AlertTriangle },
    { id: 'data-growth', label: 'Data Growth', icon: Database },
    { id: 'hitl-sla', label: 'HITL SLA', icon: Shield },
];

// ── Incidents Tab ─────────────────────────────────────────────────────────────
const IncidentsTab: React.FC = () => {
    const [data, setData] = useState<any>(null);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        reportsService.getExecutionHealth(30, true).then(setData).catch(() => setData(null)).finally(() => setLoading(false));
    }, []);

    if (loading) return <div className="loading-state"><div className="pulse">Loading…</div></div>;

    const failures = (data?.status_breakdown || []).filter((s: any) => s.status === 'FAILED');
    const trend = data?.daily_trend || [];

    return (
        <div className="tab-content">
            <div className="stats-grid-4">
                <StatCard label="Total Runs" value={data?.summary?.total_runs || 0} icon={Activity} />
                <StatCard label="Failed Runs" value={failures[0]?.count || 0} icon={XCircle} color="#e8885a" />
                <StatCard label="Failure Rate" value={`${data?.summary?.failure_rate || 0}%`} icon={AlertTriangle} color="#e8885a" />
                <StatCard label="Avg Exec Time" value={`${(failures[0]?.avg_execution_ms || 0).toFixed(0)}ms`} icon={Clock} />
            </div>

            <SectionTitle>Status Distribution (Platform-wide)</SectionTitle>
            <div className="chart-container glass">
                {(data?.status_breakdown || []).length === 0 ? <EmptyChart /> : (
                    <ResponsiveContainer width="100%" height={280}>
                        <BarChart data={data.status_breakdown} margin={{ top: 10, right: 30, left: 20, bottom: 5 }}>
                            <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
                            <XAxis dataKey="status" tick={{ fill: 'rgba(255,255,255,0.45)', fontSize: 12 }} />
                            <YAxis tick={{ fill: 'rgba(255,255,255,0.45)', fontSize: 12 }} />
                            <Tooltip contentStyle={{ background: 'rgba(20,15,30,0.95)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 10 }} />
                            <Bar dataKey="count" name="Count" radius={[4, 4, 0, 0]}>
                                {(data.status_breakdown || []).map((s: any, i: number) => (
                                    <Cell key={i} fill={s.status === 'COMPLETED' ? '#4dbe8d' : s.status === 'FAILED' ? '#e8885a' : '#d2b96b'} />
                                ))}
                            </Bar>
                        </BarChart>
                    </ResponsiveContainer>
                )}
            </div>

            <SectionTitle>Daily Failure Trend</SectionTitle>
            <div className="chart-container glass">
                {trend.length === 0 ? <EmptyChart /> : (
                    <ResponsiveContainer width="100%" height={240}>
                        <AreaChart data={trend}>
                            <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
                            <XAxis dataKey="date" tick={{ fill: 'rgba(255,255,255,0.45)', fontSize: 10 }} />
                            <YAxis tick={{ fill: 'rgba(255,255,255,0.45)', fontSize: 10 }} />
                            <Tooltip contentStyle={{ background: 'rgba(20,15,30,0.95)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 10 }} />
                            <Area type="monotone" dataKey="FAILED" stroke="#e8885a" fill="rgba(232,136,90,0.2)" strokeWidth={2} />
                        </AreaChart>
                    </ResponsiveContainer>
                )}
            </div>
        </div>
    );
};

// ── Provider Health Tab ───────────────────────────────────────────────────────
const ProvidersTab: React.FC = () => {
    const [data, setData] = useState<any>(null);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        reportsService.getToolEfficacy(30, true).then(setData).catch(() => setData(null)).finally(() => setLoading(false));
    }, []);

    if (loading) return <div className="loading-state"><div className="pulse">Loading…</div></div>;

    // Group by provider
    const byProvider: Record<string, any> = {};
    (data?.tools || []).forEach((t: any) => {
        const prov = t.provider || 'unknown';
        if (!byProvider[prov]) byProvider[prov] = { provider: prov, calls: 0, errors: 0, avg_latency: 0 };
        byProvider[prov].calls += t.total_calls;
        byProvider[prov].errors += t.failure_count;
        byProvider[prov].avg_latency = Math.max(byProvider[prov].avg_latency, t.avg_latency_ms);
    });
    const providers = Object.values(byProvider).map((p: any) => ({
        ...p,
        uptime_pct: p.calls > 0 ? ((p.calls - p.errors) / p.calls * 100).toFixed(1) : '100.0',
        error_rate: p.calls > 0 ? (p.errors / p.calls * 100).toFixed(1) : '0.0',
    }));

    return (
        <div className="tab-content">
            <SectionTitle>Provider Uptime & Error Rates</SectionTitle>
            <div className="chart-container glass">
                {providers.length === 0 ? <EmptyChart /> : (
                    <ResponsiveContainer width="100%" height={280}>
                        <BarChart data={providers} layout="vertical" margin={{ top: 5, right: 60, left: 120, bottom: 5 }}>
                            <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
                            <XAxis type="number" domain={[0, 100]} tick={{ fill: 'rgba(255,255,255,0.45)', fontSize: 11 }} unit="%" />
                            <YAxis dataKey="provider" type="category" tick={{ fill: 'rgba(255,255,255,0.45)', fontSize: 11 }} width={110} />
                            <Tooltip contentStyle={{ background: 'rgba(20,15,30,0.95)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 10 }} />
                            <Bar dataKey="uptime_pct" name="Uptime %" radius={[0, 4, 4, 0]}>
                                {providers.map((p: any, i: number) => <Cell key={i} fill={parseFloat(p.uptime_pct) > 95 ? '#4dbe8d' : parseFloat(p.uptime_pct) > 80 ? '#d2b96b' : '#e8885a'} />)}
                            </Bar>
                        </BarChart>
                    </ResponsiveContainer>
                )}
            </div>

            <div className="report-table-wrapper glass">
                <table className="report-table">
                    <thead><tr><th>Provider</th><th className="num">Total Calls</th><th className="num">Errors</th><th className="num">Avg Latency</th><th className="num highlight-col">Uptime</th></tr></thead>
                    <tbody>
                        {providers.map((p: any, i: number) => (
                            <tr key={i}>
                                <td>{p.provider}</td>
                                <td className="num">{p.calls}</td>
                                <td className="num" style={{ color: p.errors > 0 ? '#e8885a' : 'inherit' }}>{p.errors}</td>
                                <td className="num">{p.avg_latency.toFixed(0)}ms</td>
                                <td className="num total highlight-col" style={{ color: parseFloat(p.uptime_pct) > 95 ? '#4dbe8d' : '#e8885a' }}>{p.uptime_pct}%</td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
        </div>
    );
};

// ── Latency Tab ───────────────────────────────────────────────────────────────
const LatencyTab: React.FC = () => {
    const [data, setData] = useState<any>(null);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        reportsService.getLLMPerformance(30, true).then(setData).catch(() => setData(null)).finally(() => setLoading(false));
    }, []);

    if (loading) return <div className="loading-state"><div className="pulse">Loading…</div></div>;

    const percentiles = data?.latency_percentiles || {};
    const models = data?.model_breakdown || [];

    return (
        <div className="tab-content">
            <div className="stats-grid-4">
                <StatCard label="P50 Latency" value={`${percentiles.p50 || 0}ms`} icon={Clock} />
                <StatCard label="P90 Latency" value={`${percentiles.p90 || 0}ms`} icon={Clock} color="#d2b96b" />
                <StatCard label="P99 Latency" value={`${percentiles.p99 || 0}ms`} icon={AlertTriangle} color="#e8885a" />
                <StatCard label="Total Calls" value={(data?.total_calls || 0).toLocaleString()} icon={Activity} />
            </div>

            <SectionTitle>Latency by Model</SectionTitle>
            <div className="chart-container glass">
                {models.length === 0 ? <EmptyChart /> : (
                    <ResponsiveContainer width="100%" height={280}>
                        <BarChart data={models} margin={{ top: 10, right: 30, left: 20, bottom: 60 }}>
                            <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
                            <XAxis dataKey="model" tick={{ fill: 'rgba(255,255,255,0.45)', fontSize: 11 }} angle={-30} textAnchor="end" />
                            <YAxis tick={{ fill: 'rgba(255,255,255,0.45)', fontSize: 11 }} unit="ms" />
                            <Tooltip contentStyle={{ background: 'rgba(20,15,30,0.95)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 10 }} />
                            <Bar dataKey="avg_latency_ms" name="Avg Latency (ms)" radius={[4, 4, 0, 0]}>
                                {models.map((_: any, i: number) => <Cell key={i} fill={CHART_COLORS[i % CHART_COLORS.length]} />)}
                            </Bar>
                        </BarChart>
                    </ResponsiveContainer>
                )}
            </div>
        </div>
    );
};

// ── Data Growth Tab ───────────────────────────────────────────────────────────
const DataGrowthTab: React.FC = () => {
    const [data, setData] = useState<any>(null);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        reportsService.getDataGrowth().then(setData).catch(() => setData(null)).finally(() => setLoading(false));
    }, []);

    if (loading) return <div className="loading-state"><div className="pulse">Loading…</div></div>;

    const counts = data?.row_counts || {};
    const growth = data?.llm_log_growth || [];
    const recs = data?.recommendations || [];
    const barData = Object.entries(counts).map(([k, v]) => ({ table: k.replace(/_/g, ' '), rows: v }));

    return (
        <div className="tab-content">
            <SectionTitle>Table Row Counts</SectionTitle>
            <div className="chart-container glass">
                {barData.length === 0 ? <EmptyChart /> : (
                    <ResponsiveContainer width="100%" height={280}>
                        <BarChart data={barData} layout="vertical" margin={{ top: 5, right: 60, left: 160, bottom: 5 }}>
                            <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
                            <XAxis type="number" tick={{ fill: 'rgba(255,255,255,0.45)', fontSize: 11 }} />
                            <YAxis dataKey="table" type="category" tick={{ fill: 'rgba(255,255,255,0.45)', fontSize: 11 }} width={150} />
                            <Tooltip contentStyle={{ background: 'rgba(20,15,30,0.95)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 10 }} />
                            <Bar dataKey="rows" name="Row Count" radius={[0, 4, 4, 0]}>
                                {barData.map((d: any, i: number) => <Cell key={i} fill={(d.rows as number) > 100000 ? '#e8885a' : '#e8c5a0'} />)}
                            </Bar>
                        </BarChart>
                    </ResponsiveContainer>
                )}
            </div>

            <SectionTitle>LLM Log Growth Over Time</SectionTitle>
            <div className="chart-container glass">
                {growth.length === 0 ? <EmptyChart /> : (
                    <ResponsiveContainer width="100%" height={220}>
                        <LineChart data={growth}>
                            <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
                            <XAxis dataKey="month" tick={{ fill: 'rgba(255,255,255,0.45)', fontSize: 11 }} />
                            <YAxis tick={{ fill: 'rgba(255,255,255,0.45)', fontSize: 11 }} />
                            <Tooltip contentStyle={{ background: 'rgba(20,15,30,0.95)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 10 }} />
                            <Line type="monotone" dataKey="count" stroke="#e8c5a0" strokeWidth={2} dot={false} />
                        </LineChart>
                    </ResponsiveContainer>
                )}
            </div>

            {recs.filter((r: any) => r.needs_archival).length > 0 && (
                <>
                    <SectionTitle>⚠ Archival Recommendations</SectionTitle>
                    <div className="alert-list">
                        {recs.filter((r: any) => r.needs_archival).map((r: any, i: number) => (
                            <div key={i} className="alert-card glass alert-danger">
                                <Database size={16} />
                                <div>
                                    <p className="alert-name">{r.table}</p>
                                    <p className="alert-value">{Number(r.count).toLocaleString()} rows — consider cold storage</p>
                                </div>
                            </div>
                        ))}
                    </div>
                </>
            )}
        </div>
    );
};

// ── HITL SLA Tab ──────────────────────────────────────────────────────────────
const HitlSlaTab: React.FC = () => {
    const [data, setData] = useState<any>(null);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        reportsService.getHitlOverview(30, true).then(setData).catch(() => setData(null)).finally(() => setLoading(false));
    }, []);

    if (loading) return <div className="loading-state"><div className="pulse">Loading…</div></div>;


    return (
        <div className="tab-content">
            <div className="stats-grid-4">
                <StatCard label="Total Approvals" value={data?.total || 0} icon={Shield} />
                <StatCard label="Pending" value={data?.status_counts?.['PENDING'] || 0} icon={Clock} color="#d2b96b" />
                <StatCard label="Overdue >24h" value={data?.overdue_count || 0} icon={AlertTriangle} color="#e8885a" />
                <StatCard label="Resolved" value={data?.status_counts?.['APPROVED'] || 0} icon={CheckCircle} color="#4dbe8d" />
            </div>

            <SectionTitle>HITL Backlog (All Pending)</SectionTitle>
            <div className="report-table-wrapper glass">
                <table className="report-table">
                    <thead><tr>
                        <th>Entity</th><th>Trigger</th><th>Status</th>
                        <th className="num">Age (hrs)</th><th>Overdue?</th><th>Requested At</th>
                    </tr></thead>
                    <tbody>
                        {(data?.approvals || []).filter((a: any) => a.status === 'PENDING').slice(0, 50).map((a: any) => (
                            <tr key={a.id}>
                                <td>{a.entity_name}</td>
                                <td>{a.checkpoint_trigger}</td>
                                <td><span className="badge badge-pending">{a.status}</span></td>
                                <td className="num">{a.age_hours.toFixed(1)}</td>
                                <td>{a.is_overdue ? <span className="badge badge-failed">YES</span> : <span className="badge badge-active">No</span>}</td>
                                <td>{parseServerDate(a.requested_at).toLocaleString()}</td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
        </div>
    );
};

// ── Main ─────────────────────────────────────────────────────────────────────
export const AppUserReports: React.FC = () => {
    const [activeTab, setActiveTab] = useState('incidents');

    const renderTab = () => {
        switch (activeTab) {
            case 'incidents': return <IncidentsTab />;
            case 'providers': return <ProvidersTab />;
            case 'latency': return <LatencyTab />;
            case 'rate-limits': return (
                <div className="tab-content">
                    <div className="empty-state glass">
                        <div className="empty-icon">⚡</div>
                        <h3>Rate Limit Monitoring</h3>
                        <p>Real-time quota monitoring requires integration with live API provider dashboards. Configure alerts via your provider SDK settings.</p>
                    </div>
                </div>
            );
            case 'data-growth': return <DataGrowthTab />;
            case 'hitl-sla': return <HitlSlaTab />;
            default: return <IncidentsTab />;
        }
    };

    return (
        <div className="report-page">
            <div className="page-header">
                <div>
                    <h1 className="page-title"><Bug size={24} style={{ marginRight: '0.5rem' }} />App User — Technical Operations</h1>
                    <p className="page-subtitle">System debugging, provider health, and operational analytics</p>
                </div>
            </div>
            <div className="report-tabs">
                {TABS.map(tab => {
                    const Icon = tab.icon;
                    return (
                        <button key={tab.id} className={`report-tab ${activeTab === tab.id ? 'active' : ''}`} onClick={() => setActiveTab(tab.id)}>
                            <Icon size={15} /><span>{tab.label}</span>
                        </button>
                    );
                })}
            </div>
            {renderTab()}
        </div>
    );
};
