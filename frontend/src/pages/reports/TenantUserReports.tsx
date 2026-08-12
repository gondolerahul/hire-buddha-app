import { parseServerDate } from '@/utils/datetime';
import React, { useState, useEffect, useCallback } from 'react';
import {
    BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
    AreaChart, Area,
} from 'recharts';
import {
    User, Activity, CheckCircle, XCircle, AlertTriangle, Clock,
    Zap, BarChart3, Shield,
} from 'lucide-react';
import { reportsService, PersonalTasksData } from '@/services/reports.service';
import './Report.css';

const StatusBadge: React.FC<{ status: string }> = ({ status }) => {
    const color = status === 'COMPLETED' ? '#4dbe8d' : status === 'FAILED' ? '#e8885a' : status === 'RUNNING' ? '#6b9bd2' : '#d2b96b';
    return <span className={`badge badge-${status.toLowerCase()}`} style={{ color, border: `1px solid ${color}30` }}>{status}</span>;
};

const StatCard: React.FC<{ label: string; value: string | number; icon: React.ElementType; color?: string }> = ({ label, value, icon: Icon, color }) => (
    <div className="stat-card glass">
        <div className="stat-card-icon" style={{ color: color || '#e8c5a0' }}><Icon size={20} /></div>
        <div>
            <p className="stat-label">{label}</p>
            <p className="stat-value" style={{ color: color || '#e8c5a0' }}>{value}</p>
        </div>
    </div>
);

const SectionTitle: React.FC<{ children: React.ReactNode }> = ({ children }) => <h3 className="section-title">{children}</h3>;
const EmptyChart: React.FC<{ message?: string }> = ({ message = 'No data available' }) => (
    <div className="chart-empty"><BarChart3 size={32} opacity={0.3} /><p>{message}</p></div>
);

const TABS = [
    { id: 'history', label: 'My Task History', icon: Activity },
    { id: 'trace', label: 'Execution Trace', icon: BarChart3 },
    { id: 'hitl', label: 'Pending Approvals', icon: Shield },
    { id: 'time-saved', label: 'Time Saved', icon: Clock },
    { id: 'usage', label: 'My Usage', icon: Zap },
];

// ── Task History Tab ──────────────────────────────────────────────────────────
const TaskHistoryTab: React.FC = () => {
    const [data, setData] = useState<PersonalTasksData | null>(null);
    const [loading, setLoading] = useState(true);
    const [statusFilter, setStatusFilter] = useState('');
    const [search, setSearch] = useState('');
    const [expanded, setExpanded] = useState<string | null>(null);

    const load = useCallback(() => {
        setLoading(true);
        reportsService.getPersonalTasks(100, statusFilter || undefined)
            .then(setData).catch(() => setData(null)).finally(() => setLoading(false));
    }, [statusFilter]);

    useEffect(() => { load(); }, [load]);

    if (loading) return <div className="loading-state"><div className="pulse">Loading your tasks…</div></div>;

    const summary = data?.summary;
    const tasks = (data?.tasks || []).filter(t => !search || t.entity_name.toLowerCase().includes(search.toLowerCase()));

    return (
        <div className="tab-content">
            <div className="stats-grid-4">
                <StatCard label="Total Tasks" value={summary?.total || 0} icon={Activity} />
                <StatCard label="Completed" value={summary?.completed || 0} icon={CheckCircle} color="#4dbe8d" />
                <StatCard label="Failed" value={summary?.failed || 0} icon={XCircle} color="#e8885a" />
                <StatCard label="Success Rate" value={`${summary?.success_rate || 0}%`} icon={Zap} color={summary?.success_rate && summary.success_rate > 70 ? '#4dbe8d' : '#e8885a'} />
            </div>

            <div className="filter-row">
                <input className="search-input" placeholder="Search by agent name…" value={search} onChange={e => setSearch(e.target.value)} />
                <div className="pill-group">
                    {['', 'COMPLETED', 'FAILED', 'RUNNING'].map(s => (
                        <button key={s} className={`pill ${statusFilter === s ? 'active' : ''}`} onClick={() => setStatusFilter(s)}>
                            {s || 'All'}
                        </button>
                    ))}
                </div>
            </div>

            <SectionTitle>Execution History</SectionTitle>
            <div className="report-table-wrapper glass">
                <table className="report-table">
                    <thead><tr>
                        <th>Agent / Entity</th><th>Status</th><th className="num">Duration</th>
                        <th className="num">Tokens</th><th className="num">Billing</th><th>Date</th><th>Details</th>
                    </tr></thead>
                    <tbody>
                        {tasks.map(t => (
                            <React.Fragment key={t.id}>
                                <tr>
                                    <td>{t.entity_name}</td>
                                    <td><StatusBadge status={t.status} /></td>
                                    <td className="num">{t.execution_time_ms ? `${(t.execution_time_ms / 1000).toFixed(1)}s` : '—'}</td>
                                    <td className="num">{(t.total_tokens || 0).toLocaleString()}</td>
                                    <td className="num">${(t.billed_amount != null ? t.billed_amount : t.total_cost_usd).toFixed(6)}</td>
                                    <td>{parseServerDate(t.created_at).toLocaleDateString()}</td>
                                    <td>
                                        <button className="btn-icon" onClick={() => setExpanded(expanded === t.id ? null : t.id)}>
                                            {expanded === t.id ? '▲' : '▼'}
                                        </button>
                                    </td>
                                </tr>
                                {expanded === t.id && (
                                    <tr className="expanded-row">
                                        <td colSpan={7}>
                                            <div className="expanded-content glass">
                                                {t.error_message && (
                                                    <div className="alert-card alert-danger" style={{ marginBottom: '0.5rem' }}>
                                                        <AlertTriangle size={14} />
                                                        <span>{t.error_message}</span>
                                                    </div>
                                                )}
                                                <div className="expanded-grid">
                                                    <div>
                                                        <p className="expand-label">Run ID</p>
                                                        <p className="expand-val mono">{t.id}</p>
                                                    </div>
                                                    <div>
                                                        <p className="expand-label">Started</p>
                                                        <p className="expand-val">{t.started_at ? parseServerDate(t.started_at).toLocaleString() : '—'}</p>
                                                    </div>
                                                    <div>
                                                        <p className="expand-label">Completed</p>
                                                        <p className="expand-val">{t.completed_at ? parseServerDate(t.completed_at).toLocaleString() : '—'}</p>
                                                    </div>
                                                </div>
                                                {t.input_data && (
                                                    <div style={{ marginTop: '0.5rem' }}>
                                                        <p className="expand-label">Input</p>
                                                        <pre className="code-preview">{JSON.stringify(t.input_data, null, 2).slice(0, 500)}</pre>
                                                    </div>
                                                )}
                                            </div>
                                        </td>
                                    </tr>
                                )}
                            </React.Fragment>
                        ))}
                        {tasks.length === 0 && (
                            <tr><td colSpan={7} style={{ textAlign: 'center', padding: '2rem', opacity: 0.5 }}>No tasks found</td></tr>
                        )}
                    </tbody>
                </table>
            </div>
        </div>
    );
};

// ── Time Saved Tab ────────────────────────────────────────────────────────────
const TimeSavedTab: React.FC = () => {
    const [data, setData] = useState<PersonalTasksData | null>(null);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        reportsService.getPersonalTasks(200).then(setData).catch(() => setData(null)).finally(() => setLoading(false));
    }, []);

    if (loading) return <div className="loading-state"><div className="pulse">Loading…</div></div>;

    const summary = data?.summary;
    const tasks = data?.tasks || [];

    // Group tasks by week for chart
    const byDate: Record<string, number> = {};
    tasks.forEach(t => {
        const d = parseServerDate(t.created_at);
        const week = `${d.getFullYear()}-W${Math.ceil((d.getDate()) / 7)}`;
        byDate[week] = (byDate[week] || 0) + 1;
    });
    const chartData = Object.entries(byDate).map(([week, count]) => ({ week, count }));

    const totalMs = summary?.total_execution_ms || 0;
    const totalTasks = summary?.total || 0;
    const estimatedManualHours = totalTasks * (10 / 60); // 10 min per task
    const actualHours = totalMs / 3600000;
    const savedHours = Math.max(0, estimatedManualHours - actualHours);

    return (
        <div className="tab-content">
            <div className="stats-grid-4">
                <StatCard label="Tasks Automated" value={totalTasks} icon={Activity} />
                <StatCard label="Est. Manual Hours" value={summarizeHours(estimatedManualHours)} icon={User} color="#d2b96b" />
                <StatCard label="Actual AI Hours" value={summarizeHours(actualHours)} icon={Zap} color="#6b9bd2" />
                <StatCard label="⚡ Hours Saved" value={summarizeHours(savedHours)} icon={CheckCircle} color="#4dbe8d" />
            </div>

            <div className="productivity-card glass">
                <div className="productivity-header">Time Savings Breakdown</div>
                <div className="productivity-bars">
                    <div className="prod-bar-row">
                        <span>Estimated Manual</span>
                        <div className="prod-bar-track">
                            <div className="prod-bar-fill" style={{ width: '100%', background: 'rgba(210,185,107,0.4)' }} />
                        </div>
                        <span>{summarizeHours(estimatedManualHours)}</span>
                    </div>
                    <div className="prod-bar-row">
                        <span>AI Execution</span>
                        <div className="prod-bar-track">
                            <div className="prod-bar-fill" style={{ width: `${estimatedManualHours ? (actualHours / estimatedManualHours * 100) : 0}%`, background: 'rgba(107,155,210,0.5)' }} />
                        </div>
                        <span>{summarizeHours(actualHours)}</span>
                    </div>
                    <div className="prod-bar-row">
                        <span>⚡ Saved</span>
                        <div className="prod-bar-track">
                            <div className="prod-bar-fill" style={{ width: `${estimatedManualHours ? (savedHours / estimatedManualHours * 100) : 0}%`, background: '#4dbe8d' }} />
                        </div>
                        <span>{summarizeHours(savedHours)}</span>
                    </div>
                </div>
            </div>

            <SectionTitle>Weekly Task Volume</SectionTitle>
            <div className="chart-container glass">
                {chartData.length === 0 ? <EmptyChart /> : (
                    <ResponsiveContainer width="100%" height={220}>
                        <BarChart data={chartData}>
                            <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
                            <XAxis dataKey="week" tick={{ fill: 'rgba(255,255,255,0.45)', fontSize: 11 }} />
                            <YAxis tick={{ fill: 'rgba(255,255,255,0.45)', fontSize: 11 }} />
                            <Tooltip contentStyle={{ background: 'rgba(20,15,30,0.95)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 10 }} />
                            <Bar dataKey="count" name="Tasks" fill="#e8c5a0" radius={[4, 4, 0, 0]} />
                        </BarChart>
                    </ResponsiveContainer>
                )}
            </div>
        </div>
    );
};

function summarizeHours(h: number): string {
    if (h < 1) return `${Math.round(h * 60)}m`;
    return `${h.toFixed(1)}h`;
}

// ── HITL Pending Approvals Tab ────────────────────────────────────────────────
const HitlTab: React.FC = () => {
    const [data, setData] = useState<any>(null);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        reportsService.getHitlOverview(30).then(setData).catch(() => setData(null)).finally(() => setLoading(false));
    }, []);

    if (loading) return <div className="loading-state"><div className="pulse">Loading…</div></div>;

    const pending = (data?.approvals || []).filter((a: any) => a.status === 'PENDING').sort((a: any, b: any) => b.age_hours - a.age_hours);

    return (
        <div className="tab-content">
            <div className="stats-grid-4">
                <StatCard label="Pending Approvals" value={data?.status_counts?.['PENDING'] || 0} icon={Clock} color="#d2b96b" />
                <StatCard label="Overdue (>24h)" value={data?.overdue_count || 0} icon={AlertTriangle} color="#e8885a" />
                <StatCard label="Total HITL" value={data?.total || 0} icon={Shield} />
                <StatCard label="Resolved" value={data?.status_counts?.['APPROVED'] || 0} icon={CheckCircle} color="#4dbe8d" />
            </div>

            {pending.length === 0 ? (
                <div className="empty-state glass"><div className="empty-icon">✅</div><h3>No pending approvals</h3><p>You have no workflows waiting for your input.</p></div>
            ) : (
                <>
                    <SectionTitle>Workflows Awaiting Your Review</SectionTitle>
                    <div className="alert-list">
                        {pending.map((a: any) => (
                            <div key={a.id} className={`alert-card glass ${a.is_overdue ? 'alert-danger' : 'alert-warn'}`}>
                                <div className="flex-1">
                                    <p className="alert-name">
                                        {a.entity_name} <span className="badge badge-type">{a.entity_type}</span>
                                        {a.is_overdue && <span className="badge badge-failed" style={{ marginLeft: '0.5rem' }}>OVERDUE</span>}
                                    </p>
                                    <p className="alert-value">Trigger: {a.checkpoint_trigger} · Waiting {a.age_hours.toFixed(1)}h</p>
                                    <p className="alert-value" style={{ opacity: 0.6 }}>Run ID: {a.run_id}</p>
                                </div>
                                <Clock size={20} style={{ opacity: 0.5 }} />
                            </div>
                        ))}
                    </div>
                </>
            )}
        </div>
    );
};

// ── Usage Tab ─────────────────────────────────────────────────────────────────
const UsageTab: React.FC = () => {
    const [data, setData] = useState<PersonalTasksData | null>(null);
    const [forecast, setForecast] = useState<any>(null);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        Promise.all([
            reportsService.getPersonalTasks(200),
            reportsService.getCreditForecast(),
        ]).then(([p, f]) => { setData(p); setForecast(f); }).catch(() => { }).finally(() => setLoading(false));
    }, []);

    if (loading) return <div className="loading-state"><div className="pulse">Loading…</div></div>;

    const wallet = forecast?.wallet;
    const totalAvail = wallet?.total_available || 0;
    const summary = data?.summary;
    const totalSpent = summary?.total_cost_usd || 0;

    // Simple usage gauge (spent vs available)
    const usagePct = totalAvail + totalSpent > 0 ? Math.min(100, (totalSpent / (totalAvail + totalSpent)) * 100) : 0;

    return (
        <div className="tab-content">
            <div className="stats-grid-4">
                <StatCard label="Total Tokens Used" value={((summary?.total || 0) * 1000).toLocaleString()} icon={Zap} />
                <StatCard label="My Billing" value={`$${totalSpent.toFixed(6)}`} icon={User} color="#e8885a" />
                <StatCard label="Available Balance" value={`$${totalAvail.toFixed(4)}`} icon={CheckCircle} color="#4dbe8d" />
                <StatCard label="Wallet Model" value={wallet?.account_model || '—'} icon={Shield} />
            </div>

            <SectionTitle>My Resource Usage</SectionTitle>
            <div className="usage-gauge-card glass">
                <div className="usage-gauge-label">
                    <span>Spend vs Available</span>
                    <span style={{ color: usagePct > 80 ? '#e8885a' : '#4dbe8d' }}>{usagePct.toFixed(1)}% consumed</span>
                </div>
                <div className="usage-gauge-track">
                    <div className="usage-gauge-fill" style={{
                        width: `${usagePct}%`,
                        background: usagePct > 80 ? 'linear-gradient(90deg, #c9956c, #e8885a)' : 'linear-gradient(90deg, #e8c5a0, #4dbe8d)',
                    }} />
                </div>
                {usagePct > 80 && (
                    <div className="alert-card alert-warn" style={{ marginTop: '0.75rem' }}>
                        <AlertTriangle size={14} />
                        <span>You are nearing your available balance. Contact your admin for a top-up.</span>
                    </div>
                )}
            </div>

            <SectionTitle>Daily Burn Forecast (Company)</SectionTitle>
            <div className="chart-container glass">
                {(forecast?.burn_rate?.daily_history || []).length === 0 ? <EmptyChart /> : (
                    <ResponsiveContainer width="100%" height={200}>
                        <AreaChart data={forecast.burn_rate.daily_history}>
                            <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
                            <XAxis dataKey="date" tick={{ fill: 'rgba(255,255,255,0.45)', fontSize: 10 }} />
                            <YAxis tick={{ fill: 'rgba(255,255,255,0.45)', fontSize: 10 }} />
                            <Tooltip contentStyle={{ background: 'rgba(20,15,30,0.95)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 10 }} formatter={(v) => [`$${Number(v).toFixed(6)}`, 'Billing']} />
                            <Area type="monotone" dataKey="cost" stroke="#e8c5a0" fill="rgba(232,197,160,0.12)" strokeWidth={2} />
                        </AreaChart>
                    </ResponsiveContainer>
                )}
            </div>
        </div>
    );
};

// ── Main ─────────────────────────────────────────────────────────────────────
export const TenantUserReports: React.FC = () => {
    const [activeTab, setActiveTab] = useState('history');

    const renderTab = () => {
        switch (activeTab) {
            case 'history': return <TaskHistoryTab />;
            case 'trace': return (
                <div className="tab-content">
                    <p style={{ opacity: 0.6, marginBottom: '1rem', fontSize: '0.875rem' }}>Click into a failed run from "My Task History" to see the full execution trace in the Executions view.</p>
                    <TaskHistoryTab />
                </div>
            );
            case 'hitl': return <HitlTab />;
            case 'time-saved': return <TimeSavedTab />;
            case 'usage': return <UsageTab />;
            default: return <TaskHistoryTab />;
        }
    };

    return (
        <div className="report-page">
            <div className="page-header">
                <div>
                    <h1 className="page-title"><User size={24} style={{ marginRight: '0.5rem' }} />My Analytics</h1>
                    <p className="page-subtitle">Personal task history, productivity metrics, and pending approvals</p>
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
