import { parseServerDate } from '@/utils/datetime';
import React, { useState, useEffect, useCallback } from 'react';
import {
    BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
    AreaChart, Area, PieChart, Pie, Cell,
} from 'recharts';
import {
    TrendingUp, Activity, Cpu, Shield, Users, Globe,
    AlertTriangle, CheckCircle, XCircle, Clock, DollarSign, BarChart3,
    Zap, Database,
} from 'lucide-react';
import { reportsService, ExecutionHealthData, LLMPerformanceData, ToolEfficacyData, WalletLiabilityData, SubscriptionMRRData, PartnerPerformanceData } from '@/services/reports.service';
import './Report.css';

const TABS = [
    { id: 'revenue', label: 'Revenue & Margin', icon: DollarSign },
    { id: 'subscription', label: 'Subscription & MRR', icon: TrendingUp },
    { id: 'exec-health', label: 'Execution Health', icon: Activity },
    { id: 'llm', label: 'LLM Performance', icon: Cpu },
    { id: 'tools', label: 'Tool Efficacy', icon: Zap },
    { id: 'wallet', label: 'Wallet Liability', icon: Database },
    { id: 'partners', label: 'Partner Performance', icon: Users },
    { id: 'hitl', label: 'Global HITL', icon: Shield },
];

const CHART_COLORS = ['#e8c5a0', '#c9956c', '#9b6fa0', '#6b9bd2', '#4dbe8d', '#e8885a', '#a0c8e8', '#d2b96b'];

const StatCard: React.FC<{ label: string; value: string | number; icon: React.ElementType; sub?: string; color?: string }> = ({ label, value, icon: Icon, sub, color }) => (
    <div className="stat-card glass">
        <div className="stat-card-icon" style={{ color: color || '#e8c5a0' }}>
            <Icon size={20} />
        </div>
        <div>
            <p className="stat-label">{label}</p>
            <p className="stat-value" style={{ color: color || '#e8c5a0' }}>{value}</p>
            {sub && <p className="stat-sub">{sub}</p>}
        </div>
    </div>
);

const SectionTitle: React.FC<{ children: React.ReactNode }> = ({ children }) => (
    <h3 className="section-title">{children}</h3>
);

const EmptyChart: React.FC<{ message?: string }> = ({ message = 'No data available for this period' }) => (
    <div className="chart-empty">
        <BarChart3 size={32} opacity={0.3} />
        <p>{message}</p>
    </div>
);

function fmtUSD(v: number) { return `$${v.toFixed(4)}`; }
function fmtPct(v: number) { return `${v.toFixed(1)}%`; }

// ── Revenue & Margin Tab ─────────────────────────────────────────────────────
const RevenueTab: React.FC = () => {
    const [data, setData] = useState<WalletLiabilityData | null>(null);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        reportsService.getWalletLiability().then(setData).catch(() => setData(null)).finally(() => setLoading(false));
    }, []);

    if (loading) return <div className="loading-state"><div className="pulse">Loading…</div></div>;

    const wallets = data?.wallets || [];
    const totals = data?.totals;
    const chartData = wallets.slice(0, 12).map(w => ({
        name: w.company_name.slice(0, 14),
        daily: w.daily_credits,
        wallet: w.wallet_balance,
        subscription: w.subscription_credits,
    }));

    return (
        <div className="tab-content">
            <div className="stats-grid-4">
                <StatCard label="Total Credit Liability" value={fmtUSD(totals?.total_liability || 0)} icon={DollarSign} color="#e8885a" />
                <StatCard label="Daily Credits" value={fmtUSD(totals?.total_daily_credits || 0)} icon={Clock} />
                <StatCard label="Wallet Balances" value={fmtUSD(totals?.total_wallet_balance || 0)} icon={Database} />
                <StatCard label="Subscription Credits" value={fmtUSD(totals?.total_subscription_credits || 0)} icon={TrendingUp} color="#4dbe8d" />
            </div>

            <SectionTitle>Credit Liability by Company</SectionTitle>
            <div className="chart-container glass">
                {chartData.length === 0 ? <EmptyChart /> : (
                    <ResponsiveContainer width="100%" height={320}>
                        <BarChart data={chartData} margin={{ top: 10, right: 20, left: 20, bottom: 60 }}>
                            <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
                            <XAxis dataKey="name" tick={{ fill: 'rgba(255,255,255,0.45)', fontSize: 11 }} angle={-35} textAnchor="end" />
                            <YAxis tick={{ fill: 'rgba(255,255,255,0.45)', fontSize: 11 }} />
                            <Tooltip contentStyle={{ background: 'rgba(20,15,30,0.95)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 10 }} />
                            <Legend wrapperStyle={{ paddingTop: 10 }} />
                            <Bar dataKey="daily" name="Daily Credits" fill="#e8c5a0" radius={[4, 4, 0, 0]} />
                            <Bar dataKey="wallet" name="Wallet Balance" fill="#c9956c" radius={[4, 4, 0, 0]} />
                            <Bar dataKey="subscription" name="Subscription" fill="#4dbe8d" radius={[4, 4, 0, 0]} />
                        </BarChart>
                    </ResponsiveContainer>
                )}
            </div>

            <SectionTitle>Company Wallet Details</SectionTitle>
            <div className="report-table-wrapper glass">
                <table className="report-table">
                    <thead><tr>
                        <th>Company</th><th>Type</th><th>Account Model</th>
                        <th className="num">Daily Credits</th><th className="num">Wallet</th>
                        <th className="num">Subscription</th><th className="num highlight-col">Total Available</th>
                    </tr></thead>
                    <tbody>
                        {wallets.map(w => (
                            <tr key={w.company_id}>
                                <td>{w.company_name}</td>
                                <td><span className={`badge badge-${w.company_type.toLowerCase()}`}>{w.company_type}</span></td>
                                <td>{w.account_model}</td>
                                <td className="num">{fmtUSD(w.daily_credits)}</td>
                                <td className="num">{fmtUSD(w.wallet_balance)}</td>
                                <td className="num">{fmtUSD(w.subscription_credits)}</td>
                                <td className="num total highlight-col">{fmtUSD(w.total_available)}</td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
        </div>
    );
};

// ── Subscription & MRR Tab ───────────────────────────────────────────────────
const SubscriptionTab: React.FC = () => {
    const [data, setData] = useState<SubscriptionMRRData | null>(null);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        reportsService.getSubscriptionMRR().then(setData).catch(() => setData(null)).finally(() => setLoading(false));
    }, []);

    if (loading) return <div className="loading-state"><div className="pulse">Loading…</div></div>;

    const summary = data?.summary;
    const tierData = summary?.tier_distribution || [];

    return (
        <div className="tab-content">
            <div className="stats-grid-4">
                <StatCard label="Monthly Recurring Revenue" value={`$${(summary?.mrr_usd || 0).toFixed(2)}`} icon={TrendingUp} color="#4dbe8d" />
                <StatCard label="Active Subscriptions" value={summary?.total_active || 0} icon={CheckCircle} color="#4dbe8d" />
                <StatCard label="Cancelled" value={summary?.total_cancelled || 0} icon={XCircle} color="#e8885a" />
                <StatCard label="Churn Rate" value={fmtPct(summary?.churn_rate || 0)} icon={AlertTriangle} color="#e8885a" />
            </div>

            <div className="two-col-grid">
                <div>
                    <SectionTitle>Tier Distribution</SectionTitle>
                    <div className="chart-container glass">
                        {tierData.length === 0 ? <EmptyChart /> : (
                            <ResponsiveContainer width="100%" height={260}>
                                <PieChart>
                                    <Pie data={tierData} dataKey="count" nameKey="tier" cx="50%" cy="50%" outerRadius={100} label={(props: any) => `Tier ${props.payload.tier}: ${props.count}`} labelLine={true}>
                                        {tierData.map((_, i) => <Cell key={i} fill={CHART_COLORS[i % CHART_COLORS.length]} />)}
                                    </Pie>
                                    <Tooltip contentStyle={{ background: 'rgba(20,15,30,0.95)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 10 }} />
                                </PieChart>
                            </ResponsiveContainer>
                        )}
                    </div>
                </div>
                <div>
                    <SectionTitle>Subscription Status Breakdown</SectionTitle>
                    <div className="chart-container glass">
                        {!summary ? <EmptyChart /> : (
                            <ResponsiveContainer width="100%" height={260}>
                                <PieChart>
                                    <Pie data={[{ name: 'Active', value: summary.total_active }, { name: 'Cancelled', value: summary.total_cancelled }]} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={100} label={({ name, percent }: any) => `${name} ${(percent * 100).toFixed(0)}%`}>
                                        <Cell fill="#4dbe8d" />
                                        <Cell fill="#e8885a" />
                                    </Pie>
                                    <Tooltip contentStyle={{ background: 'rgba(20,15,30,0.95)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 10 }} />
                                    <Legend />
                                </PieChart>
                            </ResponsiveContainer>
                        )}
                    </div>
                </div>
            </div>

            <SectionTitle>Subscription Details</SectionTitle>
            <div className="report-table-wrapper glass">
                <table className="report-table">
                    <thead><tr>
                        <th>Company</th><th>Tier</th><th className="num">Monthly Fee</th>
                        <th>Status</th><th>Next Billing</th><th>Created</th>
                    </tr></thead>
                    <tbody>
                        {(data?.subscriptions || []).map(s => (
                            <tr key={s.company_id}>
                                <td>{s.company_name}</td>
                                <td>Tier {s.plan_tier}</td>
                                <td className="num">${s.monthly_fee.toFixed(2)}</td>
                                <td><span className={`badge badge-${s.status}`}>{s.status}</span></td>
                                <td>{s.next_billing_date ? parseServerDate(s.next_billing_date).toLocaleDateString() : '—'}</td>
                                <td>{parseServerDate(s.created_at).toLocaleDateString()}</td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
        </div>
    );
};

// ── Execution Health Tab ─────────────────────────────────────────────────────
const ExecHealthTab: React.FC = () => {
    const [data, setData] = useState<ExecutionHealthData | null>(null);
    const [days, setDays] = useState(30);
    const [loading, setLoading] = useState(true);

    const load = useCallback(() => {
        setLoading(true);
        reportsService.getExecutionHealth(days, true).then(setData).catch(() => setData(null)).finally(() => setLoading(false));
    }, [days]);

    useEffect(() => { load(); }, [load]);

    if (loading) return <div className="loading-state"><div className="pulse">Loading…</div></div>;

    const summary = data?.summary;
    const statusData = data?.status_breakdown || [];
    const trend = data?.daily_trend || [];

    return (
        <div className="tab-content">
            <div className="filter-row">
                <label className="filter-label">Time Range</label>
                <div className="pill-group">
                    {[7, 14, 30, 90].map(d => (
                        <button key={d} className={`pill ${days === d ? 'active' : ''}`} onClick={() => setDays(d)}>{d}d</button>
                    ))}
                </div>
            </div>

            <div className="stats-grid-4">
                <StatCard label="Total Runs" value={summary?.total_runs || 0} icon={Activity} />
                <StatCard label="Success Rate" value={fmtPct(summary?.success_rate || 0)} icon={CheckCircle} color="#4dbe8d" />
                <StatCard label="Failure Rate" value={fmtPct(summary?.failure_rate || 0)} icon={XCircle} color="#e8885a" />
                <StatCard label="Paused (HITL)" value={summary?.paused_count || 0} icon={Clock} color="#d2b96b" />
            </div>

            <div className="two-col-grid">
                <div>
                    <SectionTitle>Status Distribution</SectionTitle>
                    <div className="chart-container glass">
                        {statusData.length === 0 ? <EmptyChart /> : (
                            <ResponsiveContainer width="100%" height={260}>
                                <PieChart>
                                    <Pie data={statusData} dataKey="count" nameKey="status" cx="50%" cy="50%" outerRadius={100} label={({ status, count }) => `${status}: ${count}`}>
                                        {statusData.map((s, i) => (
                                            <Cell key={i} fill={
                                                s.status === 'COMPLETED' ? '#4dbe8d' :
                                                    s.status === 'FAILED' ? '#e8885a' :
                                                        s.status === 'RUNNING' ? '#6b9bd2' : '#d2b96b'
                                            } />
                                        ))}
                                    </Pie>
                                    <Tooltip contentStyle={{ background: 'rgba(20,15,30,0.95)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 10 }} />
                                    <Legend />
                                </PieChart>
                            </ResponsiveContainer>
                        )}
                    </div>
                </div>
                <div>
                    <SectionTitle>Daily Trends</SectionTitle>
                    <div className="chart-container glass">
                        {trend.length === 0 ? <EmptyChart /> : (
                            <ResponsiveContainer width="100%" height={260}>
                                <AreaChart data={trend} margin={{ top: 5, right: 20, left: 0, bottom: 0 }}>
                                    <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
                                    <XAxis dataKey="date" tick={{ fill: 'rgba(255,255,255,0.45)', fontSize: 10 }} />
                                    <YAxis tick={{ fill: 'rgba(255,255,255,0.45)', fontSize: 10 }} />
                                    <Tooltip contentStyle={{ background: 'rgba(20,15,30,0.95)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 10 }} />
                                    <Area type="monotone" dataKey="COMPLETED" stroke="#4dbe8d" fill="rgba(77,190,141,0.15)" />
                                    <Area type="monotone" dataKey="FAILED" stroke="#e8885a" fill="rgba(232,136,90,0.15)" />
                                    <Legend />
                                </AreaChart>
                            </ResponsiveContainer>
                        )}
                    </div>
                </div>
            </div>
        </div>
    );
};

// ── LLM Performance Tab ──────────────────────────────────────────────────────
const LLMTab: React.FC = () => {
    const [data, setData] = useState<LLMPerformanceData | null>(null);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        reportsService.getLLMPerformance(30, true).then(setData).catch(() => setData(null)).finally(() => setLoading(false));
    }, []);

    if (loading) return <div className="loading-state"><div className="pulse">Loading…</div></div>;

    const models = data?.model_breakdown || [];
    const percentiles = data?.latency_percentiles || {};

    return (
        <div className="tab-content">
            <div className="stats-grid-4">
                <StatCard label="Total LLM Calls" value={(data?.total_calls || 0).toLocaleString()} icon={Cpu} />
                <StatCard label="Total LLM Cost" value={fmtUSD(data?.total_cost_usd || 0)} icon={DollarSign} />
                <StatCard label="P50 Latency" value={`${percentiles.p50 || 0}ms`} icon={Clock} color="#6b9bd2" />
                <StatCard label="P99 Latency" value={`${percentiles.p99 || 0}ms`} icon={AlertTriangle} color="#e8885a" />
            </div>

            <SectionTitle>Model Performance Breakdown</SectionTitle>
            <div className="chart-container glass">
                {models.length === 0 ? <EmptyChart /> : (
                    <ResponsiveContainer width="100%" height={300}>
                        <BarChart data={models} margin={{ top: 10, right: 20, left: 20, bottom: 60 }}>
                            <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
                            <XAxis dataKey="model" tick={{ fill: 'rgba(255,255,255,0.45)', fontSize: 11 }} angle={-30} textAnchor="end" />
                            <YAxis yAxisId="left" tick={{ fill: 'rgba(255,255,255,0.45)', fontSize: 11 }} />
                            <YAxis yAxisId="right" orientation="right" tick={{ fill: 'rgba(255,255,255,0.45)', fontSize: 11 }} />
                            <Tooltip contentStyle={{ background: 'rgba(20,15,30,0.95)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 10 }} />
                            <Legend />
                            <Bar yAxisId="left" dataKey="calls" name="Total Calls" fill="#e8c5a0" radius={[4, 4, 0, 0]} />
                            <Bar yAxisId="right" dataKey="avg_latency_ms" name="Avg Latency (ms)" fill="#6b9bd2" radius={[4, 4, 0, 0]} />
                        </BarChart>
                    </ResponsiveContainer>
                )}
            </div>

            <SectionTitle>Model Details</SectionTitle>
            <div className="report-table-wrapper glass">
                <table className="report-table">
                    <thead><tr>
                        <th>Provider</th><th>Model</th><th className="num">Calls</th>
                        <th className="num">Avg Latency</th><th className="num">Prompt Tokens</th>
                        <th className="num">Completion Tokens</th><th className="num highlight-col">Total Cost</th>
                    </tr></thead>
                    <tbody>
                        {models.map((m, i) => (
                            <tr key={i}>
                                <td>{m.provider}</td>
                                <td>{m.model}</td>
                                <td className="num">{m.calls.toLocaleString()}</td>
                                <td className="num">{m.avg_latency_ms.toFixed(0)}ms</td>
                                <td className="num">{m.total_prompt_tokens.toLocaleString()}</td>
                                <td className="num">{m.total_completion_tokens.toLocaleString()}</td>
                                <td className="num total highlight-col">{fmtUSD(m.total_cost_usd)}</td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
        </div>
    );
};

// ── Tool Efficacy Tab ────────────────────────────────────────────────────────
const ToolsTab: React.FC = () => {
    const [data, setData] = useState<ToolEfficacyData | null>(null);
    const [loading, setLoading] = useState(true);
    const [sortBy, setSortBy] = useState<'error_rate' | 'total_calls' | 'avg_latency_ms'>('error_rate');

    useEffect(() => {
        reportsService.getToolEfficacy(30, true).then(setData).catch(() => setData(null)).finally(() => setLoading(false));
    }, []);

    if (loading) return <div className="loading-state"><div className="pulse">Loading…</div></div>;

    const tools = [...(data?.tools || [])].sort((a, b) => b[sortBy] - a[sortBy]);

    return (
        <div className="tab-content">
            <div className="filter-row">
                <label className="filter-label">Sort By</label>
                <div className="pill-group">
                    {(['error_rate', 'total_calls', 'avg_latency_ms'] as const).map(s => (
                        <button key={s} className={`pill ${sortBy === s ? 'active' : ''}`} onClick={() => setSortBy(s)}>
                            {s === 'error_rate' ? 'Error Rate' : s === 'total_calls' ? 'Call Volume' : 'Latency'}
                        </button>
                    ))}
                </div>
            </div>

            <SectionTitle>Tool Error Rates</SectionTitle>
            <div className="chart-container glass">
                {tools.length === 0 ? <EmptyChart /> : (
                    <ResponsiveContainer width="100%" height={300}>
                        <BarChart data={tools.slice(0, 10)} layout="vertical" margin={{ top: 5, right: 60, left: 100, bottom: 5 }}>
                            <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
                            <XAxis type="number" tick={{ fill: 'rgba(255,255,255,0.45)', fontSize: 11 }} />
                            <YAxis dataKey="tool_name" type="category" tick={{ fill: 'rgba(255,255,255,0.45)', fontSize: 11 }} width={90} />
                            <Tooltip contentStyle={{ background: 'rgba(20,15,30,0.95)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 10 }} />
                            <Bar dataKey="error_rate" name="Error Rate %" radius={[0, 4, 4, 0]}>
                                {tools.slice(0, 10).map((t, i) => (
                                    <Cell key={i} fill={t.error_rate > 20 ? '#e8885a' : t.error_rate > 5 ? '#d2b96b' : '#4dbe8d'} />
                                ))}
                            </Bar>
                        </BarChart>
                    </ResponsiveContainer>
                )}
            </div>

            <SectionTitle>Tool Performance Table</SectionTitle>
            <div className="report-table-wrapper glass">
                <table className="report-table">
                    <thead><tr>
                        <th>Tool</th><th>Provider</th><th className="num">Total Calls</th>
                        <th className="num">Successes</th><th className="num">Failures</th>
                        <th className="num">Avg Latency</th><th className="num highlight-col">Error Rate</th>
                    </tr></thead>
                    <tbody>
                        {tools.map((t, i) => (
                            <tr key={i}>
                                <td>{t.tool_name}</td>
                                <td>{t.provider || '—'}</td>
                                <td className="num">{t.total_calls}</td>
                                <td className="num deduction">{t.success_count}</td>
                                <td className="num" style={{ color: t.failure_count > 0 ? '#e8885a' : 'inherit' }}>{t.failure_count}</td>
                                <td className="num">{t.avg_latency_ms.toFixed(0)}ms</td>
                                <td className="num highlight-col" style={{ color: t.error_rate > 10 ? '#e8885a' : '#4dbe8d', fontWeight: 700 }}>{fmtPct(t.error_rate)}</td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
        </div>
    );
};

// ── Partner Performance Tab ──────────────────────────────────────────────────
const PartnerTab: React.FC = () => {
    const [data, setData] = useState<PartnerPerformanceData | null>(null);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        reportsService.getPartnerPerformance().then(setData).catch(() => setData(null)).finally(() => setLoading(false));
    }, []);

    if (loading) return <div className="loading-state"><div className="pulse">Loading…</div></div>;

    const partners = data?.partners || [];

    return (
        <div className="tab-content">
            <SectionTitle>Revenue by Partner</SectionTitle>
            <div className="chart-container glass">
                {partners.length === 0 ? <EmptyChart message="No partner companies found" /> : (
                    <ResponsiveContainer width="100%" height={300}>
                        <BarChart data={partners} margin={{ top: 10, right: 20, left: 20, bottom: 60 }}>
                            <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
                            <XAxis dataKey="partner_name" tick={{ fill: 'rgba(255,255,255,0.45)', fontSize: 11 }} angle={-30} textAnchor="end" />
                            <YAxis tick={{ fill: 'rgba(255,255,255,0.45)', fontSize: 11 }} />
                            <Tooltip contentStyle={{ background: 'rgba(20,15,30,0.95)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 10 }} formatter={(v) => [`$${Number(v).toFixed(4)}`, 'Revenue']} />
                            <Bar dataKey="total_revenue_usd" name="Revenue (USD)" radius={[4, 4, 0, 0]}>
                                {partners.map((_, i) => <Cell key={i} fill={CHART_COLORS[i % CHART_COLORS.length]} />)}
                            </Bar>
                        </BarChart>
                    </ResponsiveContainer>
                )}
            </div>

            <div className="partner-leaderboard">
                {partners.map((p, i) => (
                    <div key={p.partner_id} className="partner-card glass">
                        <div className="partner-rank">#{i + 1}</div>
                        <div className="partner-info">
                            <p className="partner-name">{p.partner_name}</p>
                            <p className="partner-meta">{p.tenant_count} tenants · <span className={`badge badge-${p.status}`}>{p.status}</span></p>
                        </div>
                        <div className="partner-revenue">{fmtUSD(p.total_revenue_usd)}</div>
                    </div>
                ))}
            </div>
            {partners.length === 0 && <div className="empty-state glass"><div className="empty-icon">🤝</div><p>No partner data available</p></div>}
        </div>
    );
};

// ── Wallet Tab (HITL) ────────────────────────────────────────────────────────
const WalletTab: React.FC = () => {
    const [data, setData] = useState<WalletLiabilityData | null>(null);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        reportsService.getWalletLiability().then(setData).catch(() => setData(null)).finally(() => setLoading(false));
    }, []);

    if (loading) return <div className="loading-state"><div className="pulse">Loading…</div></div>;

    const wallets = data?.wallets || [];
    const pieData = [
        { name: 'Daily Credits', value: data?.totals.total_daily_credits || 0 },
        { name: 'Wallet Balance', value: data?.totals.total_wallet_balance || 0 },
        { name: 'Subscription', value: data?.totals.total_subscription_credits || 0 },
    ];

    return (
        <div className="tab-content">
            <div className="stats-grid-4">
                <StatCard label="Total Liability" value={fmtUSD(data?.totals.total_liability || 0)} icon={Database} color="#e8885a" />
                <StatCard label="Daily Credits Pool" value={fmtUSD(data?.totals.total_daily_credits || 0)} icon={Clock} />
                <StatCard label="PAYG Wallet Pool" value={fmtUSD(data?.totals.total_wallet_balance || 0)} icon={DollarSign} />
                <StatCard label="Subscription Pool" value={fmtUSD(data?.totals.total_subscription_credits || 0)} icon={TrendingUp} color="#4dbe8d" />
            </div>

            <div className="two-col-grid">
                <div>
                    <SectionTitle>Liability Composition</SectionTitle>
                    <div className="chart-container glass">
                        <ResponsiveContainer width="100%" height={260}>
                            <PieChart>
                                <Pie data={pieData} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={100} label={({ name, value }) => `${name}: $${value.toFixed(2)}`}>
                                    {pieData.map((_, i) => <Cell key={i} fill={CHART_COLORS[i]} />)}
                                </Pie>
                                <Tooltip contentStyle={{ background: 'rgba(20,15,30,0.95)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 10 }} />
                                <Legend />
                            </PieChart>
                        </ResponsiveContainer>
                    </div>
                </div>
                <div>
                    <SectionTitle>Low Balance Alert</SectionTitle>
                    <div className="alert-list">
                        {wallets.filter(w => w.total_available < 2).map(w => (
                            <div key={w.company_id} className="alert-card glass alert-danger">
                                <AlertTriangle size={16} />
                                <div>
                                    <p className="alert-name">{w.company_name}</p>
                                    <p className="alert-value">Only {fmtUSD(w.total_available)} remaining</p>
                                </div>
                            </div>
                        ))}
                        {wallets.filter(w => w.total_available < 2).length === 0 && (
                            <div className="alert-card glass alert-ok"><CheckCircle size={16} /><span>All wallets have adequate balance</span></div>
                        )}
                    </div>
                </div>
            </div>
        </div>
    );
};

// ── Global HITL Tab ──────────────────────────────────────────────────────────
const HitlTab: React.FC = () => {
    const [data, setData] = useState<any>(null);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        reportsService.getHitlOverview(30, true).then(setData).catch(() => setData(null)).finally(() => setLoading(false));
    }, []);

    if (loading) return <div className="loading-state"><div className="pulse">Loading…</div></div>;

    const approvals = data?.approvals || [];
    const overdue = approvals.filter((a: any) => a.is_overdue);

    return (
        <div className="tab-content">
            <div className="stats-grid-4">
                <StatCard label="Total Approvals" value={data?.total || 0} icon={Shield} />
                <StatCard label="Pending" value={data?.status_counts?.['PENDING'] || 0} icon={Clock} color="#d2b96b" />
                <StatCard label="Overdue (>24h)" value={data?.overdue_count || 0} icon={AlertTriangle} color="#e8885a" />
                <StatCard label="Approved" value={data?.status_counts?.['APPROVED'] || 0} icon={CheckCircle} color="#4dbe8d" />
            </div>

            {overdue.length > 0 && (
                <>
                    <SectionTitle>🚨 Overdue Approvals</SectionTitle>
                    <div className="alert-list">
                        {overdue.slice(0, 5).map((a: any) => (
                            <div key={a.id} className="alert-card glass alert-danger">
                                <AlertTriangle size={16} />
                                <div className="flex-1">
                                    <p className="alert-name">{a.entity_name} <span className="badge badge-type">{a.entity_type}</span></p>
                                    <p className="alert-value">Waiting {a.age_hours.toFixed(1)}h · {a.checkpoint_trigger}</p>
                                </div>
                            </div>
                        ))}
                    </div>
                </>
            )}

            <SectionTitle>All Approvals</SectionTitle>
            <div className="report-table-wrapper glass">
                <table className="report-table">
                    <thead><tr>
                        <th>Entity</th><th>Type</th><th>Trigger</th><th>Status</th>
                        <th className="num">Age (hrs)</th><th>Requested</th><th>Responded</th>
                    </tr></thead>
                    <tbody>
                        {approvals.slice(0, 50).map((a: any) => (
                            <tr key={a.id}>
                                <td>{a.entity_name}</td>
                                <td><span className="badge badge-type">{a.entity_type}</span></td>
                                <td>{a.checkpoint_trigger}</td>
                                <td><span className={`badge badge-${a.status.toLowerCase()}`}>{a.status}</span></td>
                                <td className="num" style={{ color: a.is_overdue ? '#e8885a' : 'inherit' }}>{a.age_hours.toFixed(1)}</td>
                                <td>{parseServerDate(a.requested_at).toLocaleDateString()}</td>
                                <td>{a.responded_at ? parseServerDate(a.responded_at).toLocaleDateString() : '—'}</td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
        </div>
    );
};

// ── Main Component ───────────────────────────────────────────────────────────
export const AppAdminReports: React.FC = () => {
    const [activeTab, setActiveTab] = useState('revenue');

    const renderTab = () => {
        switch (activeTab) {
            case 'revenue': return <RevenueTab />;
            case 'subscription': return <SubscriptionTab />;
            case 'exec-health': return <ExecHealthTab />;
            case 'llm': return <LLMTab />;
            case 'tools': return <ToolsTab />;
            case 'wallet': return <WalletTab />;
            case 'partners': return <PartnerTab />;
            case 'hitl': return <HitlTab />;
            default: return <RevenueTab />;
        }
    };

    return (
        <div className="report-page">
            <div className="page-header">
                <div>
                    <h1 className="page-title">
                        <Globe size={24} style={{ marginRight: '0.5rem' }} />
                        App Admin Analytics
                    </h1>
                    <p className="page-subtitle">Global platform health, revenue, and infrastructure overview</p>
                </div>
            </div>

            <div className="report-tabs">
                {TABS.map(tab => {
                    const Icon = tab.icon;
                    return (
                        <button
                            key={tab.id}
                            className={`report-tab ${activeTab === tab.id ? 'active' : ''}`}
                            onClick={() => setActiveTab(tab.id)}
                        >
                            <Icon size={15} />
                            <span>{tab.label}</span>
                        </button>
                    );
                })}
            </div>

            {renderTab()}
        </div>
    );
};
