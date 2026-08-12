import React, { useState, useEffect, useCallback } from 'react';
import {
    BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
    AreaChart, Area, PieChart, Pie, Cell,
} from 'recharts';
import {
    DollarSign, Activity, TrendingDown, AlertTriangle, CheckCircle,
    Users, Shield, BarChart3, Zap, Clock,
} from 'lucide-react';
import { reportsService, UsageBreakdownData, CreditForecastData, AgentErrorsData, CampaignAnalyticsData } from '@/services/reports.service';
import './Report.css';

const CHART_COLORS = ['#e8c5a0', '#c9956c', '#9b6fa0', '#6b9bd2', '#4dbe8d', '#e8885a', '#a0c8e8', '#d2b96b'];

const StatCard: React.FC<{ label: string; value: string | number; icon: React.ElementType; color?: string; sub?: string }> = ({ label, value, icon: Icon, color, sub }) => (
    <div className="stat-card glass">
        <div className="stat-card-icon" style={{ color: color || '#e8c5a0' }}><Icon size={20} /></div>
        <div>
            <p className="stat-label">{label}</p>
            <p className="stat-value" style={{ color: color || '#e8c5a0' }}>{value}</p>
            {sub && <p className="stat-sub">{sub}</p>}
        </div>
    </div>
);

const SectionTitle: React.FC<{ children: React.ReactNode }> = ({ children }) => <h3 className="section-title">{children}</h3>;
const EmptyChart: React.FC<{ message?: string }> = ({ message = 'No data available' }) => (
    <div className="chart-empty"><BarChart3 size={32} opacity={0.3} /><p>{message}</p></div>
);

const TABS = [
    { id: 'cost', label: 'Billing Breakdown', icon: DollarSign },
    { id: 'forecast', label: 'Credit Forecast', icon: TrendingDown },
    { id: 'campaign', label: 'Campaign Analytics', icon: BarChart3 },
    { id: 'agents', label: 'Agent Performance', icon: Zap },
    { id: 'hitl-mix', label: 'Automation vs HITL', icon: Shield },
    { id: 'channels', label: 'Channel Efficacy', icon: Activity },
];

// ── Cost Breakdown Tab ────────────────────────────────────────────────────────
const CostTab: React.FC = () => {
    const [data, setData] = useState<UsageBreakdownData | null>(null);
    const [days, setDays] = useState(30);
    const [loading, setLoading] = useState(true);

    const load = useCallback(() => {
        setLoading(true);
        reportsService.getUsageBreakdown(days).then(setData).catch(() => setData(null)).finally(() => setLoading(false));
    }, [days]);

    useEffect(() => { load(); }, [load]);

    if (loading) return <div className="loading-state"><div className="pulse">Loading…</div></div>;

    const channels = data?.channels || [];
    const trend = data?.daily_trend || [];

    return (
        <div className="tab-content">
            <div className="filter-row">
                <label className="filter-label">Range</label>
                <div className="pill-group">
                    {[7, 14, 30, 90].map(d => (
                        <button key={d} className={`pill ${days === d ? 'active' : ''}`} onClick={() => setDays(d)}>{d}d</button>
                    ))}
                </div>
            </div>

            <div className="stats-grid-4">
                <StatCard label="Total Billing" value={`$${(data?.total_cost_usd || 0).toFixed(4)}`} icon={DollarSign} color="#e8885a" />
                <StatCard label="Largest Channel" value={channels[0]?.service || '—'} icon={Activity} />
                <StatCard label="Total API Calls" value={channels.reduce((s, c) => s + c.calls, 0).toLocaleString()} icon={Zap} />
                <StatCard label="Days Tracked" value={days} icon={Clock} />
            </div>

            <div className="two-col-grid">
                <div>
                    <SectionTitle>Billing by Channel</SectionTitle>
                    <div className="chart-container glass">
                        {channels.length === 0 ? <EmptyChart /> : (
                            <ResponsiveContainer width="100%" height={260}>
                                <PieChart>
                                    <Pie data={channels} dataKey="total_cost_usd" nameKey="service" cx="50%" cy="50%" outerRadius={100} label={({ service, total_cost_usd }) => `${service}: $${Number(total_cost_usd).toFixed(3)}`}>
                                        {channels.map((_, i) => <Cell key={i} fill={CHART_COLORS[i % CHART_COLORS.length]} />)}
                                    </Pie>
                                    <Tooltip contentStyle={{ background: 'rgba(20,15,30,0.95)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 10 }} />
                                    <Legend />
                                </PieChart>
                            </ResponsiveContainer>
                        )}
                    </div>
                </div>
                <div>
                    <SectionTitle>Daily Burn Rate</SectionTitle>
                    <div className="chart-container glass">
                        {trend.length === 0 ? <EmptyChart /> : (
                            <ResponsiveContainer width="100%" height={260}>
                                <AreaChart data={trend}>
                                    <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
                                    <XAxis dataKey="date" tick={{ fill: 'rgba(255,255,255,0.45)', fontSize: 10 }} />
                                    <YAxis tick={{ fill: 'rgba(255,255,255,0.45)', fontSize: 10 }} />
                                    <Tooltip contentStyle={{ background: 'rgba(20,15,30,0.95)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 10 }} formatter={(v) => [`$${Number(v).toFixed(6)}`, 'Billing']} />
                                    <Area type="monotone" dataKey="cost" stroke="#e8c5a0" fill="rgba(232,197,160,0.15)" strokeWidth={2} />
                                </AreaChart>
                            </ResponsiveContainer>
                        )}
                    </div>
                </div>
            </div>

            <SectionTitle>Usage by Service</SectionTitle>
            <div className="report-table-wrapper glass">
                <table className="report-table">
                    <thead><tr>
                        <th>Service</th><th>Category</th><th className="num">Calls</th>
                        <th className="num">Total Quantity</th><th className="num highlight-col">Total Billing</th>
                    </tr></thead>
                    <tbody>
                        {channels.map((c, i) => (
                            <tr key={i}>
                                <td>{c.service}</td>
                                <td>{c.category || '—'}</td>
                                <td className="num">{c.calls.toLocaleString()}</td>
                                <td className="num">{c.total_quantity.toFixed(4)}</td>
                                <td className="num total highlight-col">${c.total_cost_usd.toFixed(6)}</td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
        </div>
    );
};

// ── Credit Forecast Tab ───────────────────────────────────────────────────────
const ForecastTab: React.FC = () => {
    const [data, setData] = useState<CreditForecastData | null>(null);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        reportsService.getCreditForecast().then(setData).catch(() => setData(null)).finally(() => setLoading(false));
    }, []);

    if (loading) return <div className="loading-state"><div className="pulse">Loading…</div></div>;

    const wallet = data?.wallet;
    const burn = data?.burn_rate;
    const forecast = data?.forecast;

    const daysLeft = forecast?.days_remaining || 0;
    const isCritical = daysLeft < 7;
    const isWarning = daysLeft < 14;

    return (
        <div className="tab-content">
            <div className="stats-grid-4">
                <StatCard label="Total Available" value={`$${(wallet?.total_available || 0).toFixed(4)}`} icon={DollarSign} />
                <StatCard label="Daily Burn Rate" value={`$${(burn?.avg_daily_usd || 0).toFixed(6)}`} icon={TrendingDown} />
                <StatCard label="Days Remaining" value={daysLeft >= 999 ? '∞' : daysLeft} icon={Clock} color={isCritical ? '#e8885a' : isWarning ? '#d2b96b' : '#4dbe8d'} />
                <StatCard label="Depletion Date" value={forecast?.depletion_date || 'N/A'} icon={AlertTriangle} color={isCritical ? '#e8885a' : '#4dbe8d'} />
            </div>

            {(isCritical || isWarning) && (
                <div className={`alert-card glass ${isCritical ? 'alert-danger' : 'alert-warn'} mb-4`}>
                    <AlertTriangle size={16} />
                    <div>
                        <p className="alert-name">{isCritical ? '🔴 Critical: Funds depleting rapidly' : '🟡 Warning: Low credit balance'}</p>
                        <p className="alert-value">Top up your wallet to avoid campaign failures. Estimated depletion: {forecast?.depletion_date}</p>
                    </div>
                </div>
            )}

            <div className="two-col-grid">
                <div>
                    <SectionTitle>Wallet Composition</SectionTitle>
                    <div className="chart-container glass">
                        {!wallet ? <EmptyChart /> : (
                            <ResponsiveContainer width="100%" height={220}>
                                <PieChart>
                                    <Pie data={[
                                        { name: 'Daily Credits', value: wallet.daily_credits },
                                        { name: 'PAYG Wallet', value: wallet.wallet_balance },
                                        { name: 'Subscription', value: wallet.subscription_credits },
                                    ]} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={85} label>
                                        {[0, 1, 2].map(i => <Cell key={i} fill={CHART_COLORS[i]} />)}
                                    </Pie>
                                    <Tooltip contentStyle={{ background: 'rgba(20,15,30,0.95)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 10 }} />
                                    <Legend />
                                </PieChart>
                            </ResponsiveContainer>
                        )}
                    </div>
                </div>
                <div>
                    <SectionTitle>7-Day Burn History</SectionTitle>
                    <div className="chart-container glass">
                        {(burn?.daily_history || []).length === 0 ? <EmptyChart /> : (
                            <ResponsiveContainer width="100%" height={220}>
                                <BarChart data={burn?.daily_history} margin={{ top: 5, right: 10, left: 10, bottom: 5 }}>
                                    <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
                                    <XAxis dataKey="date" tick={{ fill: 'rgba(255,255,255,0.45)', fontSize: 10 }} />
                                    <YAxis tick={{ fill: 'rgba(255,255,255,0.45)', fontSize: 10 }} />
                                    <Tooltip contentStyle={{ background: 'rgba(20,15,30,0.95)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 10 }} formatter={(v) => [`$${Number(v).toFixed(6)}`, 'Billing']} />
                                    <Bar dataKey="cost" fill="#c9956c" radius={[4, 4, 0, 0]} />
                                </BarChart>
                            </ResponsiveContainer>
                        )}
                    </div>
                </div>
            </div>

            <SectionTitle>30-Day Balance Projection</SectionTitle>
            <div className="chart-container glass">
                {(forecast?.projection || []).length === 0 ? <EmptyChart /> : (
                    <ResponsiveContainer width="100%" height={220}>
                        <AreaChart data={forecast?.projection}>
                            <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
                            <XAxis dataKey="date" tick={{ fill: 'rgba(255,255,255,0.45)', fontSize: 10 }} />
                            <YAxis tick={{ fill: 'rgba(255,255,255,0.45)', fontSize: 10 }} />
                            <Tooltip contentStyle={{ background: 'rgba(20,15,30,0.95)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 10 }} formatter={(v) => [`$${Number(v).toFixed(4)}`, 'Projected Balance']} />
                            <Area type="monotone" dataKey="projected_balance" stroke="#4dbe8d" fill="rgba(77,190,141,0.15)" strokeWidth={2} />
                        </AreaChart>
                    </ResponsiveContainer>
                )}
            </div>
        </div>
    );
};

// ── Campaign Analytics Tab ────────────────────────────────────────────────────
const CampaignTab: React.FC = () => {
    const [data, setData] = useState<CampaignAnalyticsData | null>(null);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        reportsService.getCampaignAnalytics(30).then(setData).catch(() => setData(null)).finally(() => setLoading(false));
    }, []);

    if (loading) return <div className="loading-state"><div className="pulse">Loading…</div></div>;

    const statusData = Object.entries(data?.status_breakdown || {}).map(([status, v]) => ({
        status, count: (v as any).count, avg_ms: (v as any).avg_ms,
    }));

    return (
        <div className="tab-content">
            <div className="stats-grid-4">
                <StatCard label="Inbound Minutes" value={`${(data?.telephony?.total_inbound_minutes || 0).toFixed(1)} min`} icon={Activity} />
                <StatCard label="Outbound Minutes" value={`${(data?.telephony?.total_outbound_minutes || 0).toFixed(1)} min`} icon={Activity} color="#c9956c" />
                <StatCard label="Telephony Spend" value={`$${(data?.telephony?.total_charge_usd || 0).toFixed(4)}`} icon={DollarSign} />
                <StatCard label="LLM Spend" value={`$${(data?.ai_usage?.total_llm_charge_usd || 0).toFixed(4)}`} icon={Zap} />
            </div>

            <SectionTitle>Campaign Execution Status</SectionTitle>
            <div className="chart-container glass">
                {statusData.length === 0 ? <EmptyChart message="No campaign data for this period" /> : (
                    <ResponsiveContainer width="100%" height={260}>
                        <BarChart data={statusData} margin={{ top: 10, right: 30, left: 20, bottom: 5 }}>
                            <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
                            <XAxis dataKey="status" tick={{ fill: 'rgba(255,255,255,0.45)', fontSize: 12 }} />
                            <YAxis tick={{ fill: 'rgba(255,255,255,0.45)', fontSize: 12 }} />
                            <Tooltip contentStyle={{ background: 'rgba(20,15,30,0.95)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 10 }} />
                            <Bar dataKey="count" name="Run Count" radius={[4, 4, 0, 0]}>
                                {statusData.map((s, i) => (
                                    <Cell key={i} fill={s.status === 'COMPLETED' ? '#4dbe8d' : s.status === 'FAILED' ? '#e8885a' : '#d2b96b'} />
                                ))}
                            </Bar>
                        </BarChart>
                    </ResponsiveContainer>
                )}
            </div>
        </div>
    );
};

// ── Agent Performance Tab ─────────────────────────────────────────────────────
const AgentsTab: React.FC = () => {
    const [data, setData] = useState<AgentErrorsData | null>(null);
    const [loading, setLoading] = useState(true);
    const [sortBy, setSortBy] = useState<'error_rate' | 'total'>('error_rate');

    useEffect(() => {
        reportsService.getAgentErrors(30).then(setData).catch(() => setData(null)).finally(() => setLoading(false));
    }, []);

    if (loading) return <div className="loading-state"><div className="pulse">Loading…</div></div>;

    const agents = [...(data?.agents || [])].sort((a, b) => sortBy === 'error_rate' ? b.error_rate - a.error_rate : b.total - a.total);

    return (
        <div className="tab-content">
            <div className="filter-row">
                <label className="filter-label">Sort By</label>
                <div className="pill-group">
                    <button className={`pill ${sortBy === 'error_rate' ? 'active' : ''}`} onClick={() => setSortBy('error_rate')}>Error Rate</button>
                    <button className={`pill ${sortBy === 'total' ? 'active' : ''}`} onClick={() => setSortBy('total')}>Volume</button>
                </div>
            </div>

            <SectionTitle>Agent Error Rates</SectionTitle>
            <div className="chart-container glass">
                {agents.length === 0 ? <EmptyChart /> : (
                    <ResponsiveContainer width="100%" height={280}>
                        <BarChart data={agents.slice(0, 10)} layout="vertical" margin={{ top: 5, right: 60, left: 120, bottom: 5 }}>
                            <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
                            <XAxis type="number" tick={{ fill: 'rgba(255,255,255,0.45)', fontSize: 11 }} unit="%" />
                            <YAxis dataKey="name" type="category" tick={{ fill: 'rgba(255,255,255,0.45)', fontSize: 11 }} width={110} />
                            <Tooltip contentStyle={{ background: 'rgba(20,15,30,0.95)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 10 }} />
                            <Bar dataKey="error_rate" name="Error Rate %" radius={[0, 4, 4, 0]}>
                                {agents.slice(0, 10).map((a, i) => (
                                    <Cell key={i} fill={a.error_rate > 20 ? '#e8885a' : a.error_rate > 5 ? '#d2b96b' : '#4dbe8d'} />
                                ))}
                            </Bar>
                        </BarChart>
                    </ResponsiveContainer>
                )}
            </div>

            <div className="report-table-wrapper glass">
                <table className="report-table">
                    <thead><tr>
                        <th>Agent / Entity</th><th>Type</th><th className="num">Total Runs</th>
                        <th className="num">Completed</th><th className="num">Failed</th>
                        <th className="num">Avg Time</th><th className="num highlight-col">Error Rate</th>
                    </tr></thead>
                    <tbody>
                        {agents.map((a, i) => (
                            <tr key={i}>
                                <td>{a.name}</td>
                                <td><span className="badge badge-type">{a.type}</span></td>
                                <td className="num">{a.total}</td>
                                <td className="num deduction">{a.completed}</td>
                                <td className="num" style={{ color: a.failed > 0 ? '#e8885a' : 'inherit' }}>{a.failed}</td>
                                <td className="num">{(a.avg_ms / 1000).toFixed(1)}s</td>
                                <td className="num highlight-col" style={{ color: a.error_rate > 10 ? '#e8885a' : '#4dbe8d', fontWeight: 700 }}>{a.error_rate.toFixed(1)}%</td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
        </div>
    );
};

// ── Automation vs HITL Tab ────────────────────────────────────────────────────
const HitlMixTab: React.FC = () => {
    const [exec, setExec] = useState<any>(null);
    const [hitl, setHitl] = useState<any>(null);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        Promise.all([
            reportsService.getExecutionHealth(30),
            reportsService.getHitlOverview(30),
        ]).then(([e, h]) => { setExec(e); setHitl(h); }).catch(() => { }).finally(() => setLoading(false));
    }, []);

    if (loading) return <div className="loading-state"><div className="pulse">Loading…</div></div>;

    const total = exec?.summary?.total_runs || 0;
    const paused = exec?.summary?.paused_count || 0;
    const automated = total - paused;
    const pieData = [
        { name: 'Fully Automated', value: automated },
        { name: 'Required HITL', value: paused },
    ];

    return (
        <div className="tab-content">
            <div className="stats-grid-4">
                <StatCard label="Total Runs" value={total} icon={Activity} />
                <StatCard label="Fully Automated" value={automated} icon={CheckCircle} color="#4dbe8d" />
                <StatCard label="Required HITL" value={paused} icon={Users} color="#d2b96b" />
                <StatCard label="Automation Rate" value={total ? `${((automated / total) * 100).toFixed(1)}%` : '—'} icon={Zap} color="#4dbe8d" />
            </div>

            <div className="two-col-grid">
                <div>
                    <SectionTitle>Automation Mix</SectionTitle>
                    <div className="chart-container glass">
                        <ResponsiveContainer width="100%" height={240}>
                            <PieChart>
                                <Pie data={pieData} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={95} label>
                                    <Cell fill="#4dbe8d" />
                                    <Cell fill="#d2b96b" />
                                </Pie>
                                <Tooltip contentStyle={{ background: 'rgba(20,15,30,0.95)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 10 }} />
                                <Legend />
                            </PieChart>
                        </ResponsiveContainer>
                    </div>
                </div>
                <div>
                    <SectionTitle>Pending HITL Approvals</SectionTitle>
                    <div className="chart-container glass" style={{ padding: '1rem' }}>
                        <div className="stats-grid-2">
                            <StatCard label="Pending" value={hitl?.status_counts?.['PENDING'] || 0} icon={Clock} color="#d2b96b" />
                            <StatCard label="Overdue" value={hitl?.overdue_count || 0} icon={AlertTriangle} color="#e8885a" />
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
};

// ── Main ─────────────────────────────────────────────────────────────────────
export const TenantAdminReports: React.FC = () => {
    const [activeTab, setActiveTab] = useState('cost');

    const renderTab = () => {
        switch (activeTab) {
            case 'cost': return <CostTab />;
            case 'forecast': return <ForecastTab />;
            case 'campaign': return <CampaignTab />;
            case 'agents': return <AgentsTab />;
            case 'hitl-mix': return <HitlMixTab />;
            case 'channels': return (
                <div className="tab-content">
                    <div className="empty-state glass"><div className="empty-icon">📡</div><h3>Channel Delivery Efficacy</h3><p>Response rates across Text, Voice, and WhatsApp will populate here as campaigns execute across multiple channels.</p></div>
                </div>
            );
            default: return <CostTab />;
        }
    };

    return (
        <div className="report-page">
            <div className="page-header">
                <div>
                    <h1 className="page-title"><DollarSign size={24} style={{ marginRight: '0.5rem' }} />Tenant Admin — Operations Analytics</h1>
                    <p className="page-subtitle">Billing allocation, campaign performance, and AI agent analytics</p>
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
