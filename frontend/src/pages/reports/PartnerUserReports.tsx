import React, { useState, useEffect } from 'react';
import {
    BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell,
} from 'recharts';
import { Users, AlertTriangle, CheckCircle, Activity, Clock, Shield } from 'lucide-react';
import { reportsService, TenantHealthData } from '@/services/reports.service';
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

const SectionTitle: React.FC<{ children: React.ReactNode }> = ({ children }) => <h3 className="section-title">{children}</h3>;

const TABS = [
    { id: 'scorecard', label: 'Health Scorecard', icon: Activity },
    { id: 'onboarding', label: 'Onboarding Tracker', icon: CheckCircle },
    { id: 'errors', label: 'Config Error Logs', icon: AlertTriangle },
    { id: 'credit-alerts', label: 'Credit Alerts', icon: Shield },
];

const ScorecardTab: React.FC = () => {
    const [data, setData] = useState<TenantHealthData | null>(null);
    const [loading, setLoading] = useState(true);
    const [search, setSearch] = useState('');

    useEffect(() => {
        reportsService.getTenantHealth().then(setData).catch(() => setData(null)).finally(() => setLoading(false));
    }, []);

    if (loading) return <div className="loading-state"><div className="pulse">Loading…</div></div>;

    const tenants = (data?.tenants || []).filter(t => t.company_name.toLowerCase().includes(search.toLowerCase()));

    return (
        <div className="tab-content">
            <div className="filter-row">
                <input className="search-input" placeholder="Search tenant…" value={search} onChange={e => setSearch(e.target.value)} />
            </div>
            <div className="stats-grid-4">
                <StatCard label="Total Tenants" value={tenants.length} icon={Users} />
                <StatCard label="Active" value={tenants.filter(t => t.status === 'active').length} icon={CheckCircle} color="#4dbe8d" />
                <StatCard label="At Risk" value={tenants.filter(t => t.at_risk).length} icon={AlertTriangle} color="#e8885a" />
                <StatCard label="Avg Health" value={`${tenants.length ? (tenants.reduce((s, t) => s + t.health_score, 0) / tenants.length).toFixed(0) : 0}%`} icon={Activity} />
            </div>

            <SectionTitle>Individual Tenant Health</SectionTitle>
            <div className="report-table-wrapper glass">
                <table className="report-table">
                    <thead><tr>
                        <th>Tenant</th><th>Status</th><th className="num">Runs (30d)</th>
                        <th className="num">Success</th><th className="num">Failed</th>
                        <th className="num">Wallet</th><th className="num highlight-col">Health Score</th>
                    </tr></thead>
                    <tbody>
                        {tenants.map(t => (
                            <tr key={t.company_id}>
                                <td>{t.company_name}</td>
                                <td><span className={`badge badge-${t.status}`}>{t.status}</span></td>
                                <td className="num">{t.total_runs_30d}</td>
                                <td className="num deduction">{t.completed_runs}</td>
                                <td className="num" style={{ color: t.failed_runs > 0 ? '#e8885a' : 'inherit' }}>{t.failed_runs}</td>
                                <td className="num">${t.wallet_balance.toFixed(2)}</td>
                                <td className="num highlight-col" style={{ color: t.health_score > 70 ? '#4dbe8d' : t.health_score > 40 ? '#d2b96b' : '#e8885a', fontWeight: 700 }}>
                                    {t.health_score}%
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
        </div>
    );
};

const OnboardingTab: React.FC = () => {
    const [data, setData] = useState<TenantHealthData | null>(null);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        reportsService.getTenantHealth().then(setData).catch(() => setData(null)).finally(() => setLoading(false));
    }, []);

    if (loading) return <div className="loading-state"><div className="pulse">Loading…</div></div>;

    const tenants = data?.tenants || [];
    const onboarded = tenants.filter(t => t.total_runs_30d > 0).length;
    const milestones = [
        { label: 'Company Registered', count: tenants.length },
        { label: 'First Execution Run', count: onboarded },
        { label: 'Wallet Topped Up', count: tenants.filter(t => t.wallet_balance > 0).length },
        { label: 'Active Users', count: tenants.filter(t => t.total_runs_30d > 5).length },
    ];

    return (
        <div className="tab-content">
            <SectionTitle>Onboarding Funnel</SectionTitle>
            <div className="chart-container glass">
                <ResponsiveContainer width="100%" height={260}>
                    <BarChart data={milestones} margin={{ top: 10, right: 30, left: 20, bottom: 5 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
                        <XAxis dataKey="label" tick={{ fill: 'rgba(255,255,255,0.45)', fontSize: 11 }} />
                        <YAxis tick={{ fill: 'rgba(255,255,255,0.45)', fontSize: 11 }} />
                        <Tooltip contentStyle={{ background: 'rgba(20,15,30,0.95)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 10 }} />
                        <Bar dataKey="count" name="Tenants" radius={[4, 4, 0, 0]}>
                            {milestones.map((_, i) => <Cell key={i} fill={CHART_COLORS[i % CHART_COLORS.length]} />)}
                        </Bar>
                    </BarChart>
                </ResponsiveContainer>
            </div>

            <SectionTitle>Tenant Milestone Status</SectionTitle>
            <div className="report-table-wrapper glass">
                <table className="report-table">
                    <thead><tr>
                        <th>Tenant</th>
                        <th>Registered</th><th>Has Runs</th><th>Has Wallet Balance</th><th>Active (5+ runs)</th>
                    </tr></thead>
                    <tbody>
                        {tenants.map(t => (
                            <tr key={t.company_id}>
                                <td>{t.company_name}</td>
                                <td><CheckCircle size={14} color="#4dbe8d" /></td>
                                <td>{t.total_runs_30d > 0 ? <CheckCircle size={14} color="#4dbe8d" /> : <Clock size={14} color="#d2b96b" />}</td>
                                <td>{t.wallet_balance > 0 ? <CheckCircle size={14} color="#4dbe8d" /> : <Clock size={14} color="#d2b96b" />}</td>
                                <td>{t.total_runs_30d > 5 ? <CheckCircle size={14} color="#4dbe8d" /> : <Clock size={14} color="#d2b96b" />}</td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
        </div>
    );
};

const CreditAlertsTab: React.FC = () => {
    const [data, setData] = useState<TenantHealthData | null>(null);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        reportsService.getTenantHealth().then(setData).catch(() => setData(null)).finally(() => setLoading(false));
    }, []);

    if (loading) return <div className="loading-state"><div className="pulse">Loading…</div></div>;

    const atRisk = (data?.tenants || []).filter(t => t.at_risk).sort((a, b) => a.wallet_balance - b.wallet_balance);

    return (
        <div className="tab-content">
            <SectionTitle>Proactive Credit Top-up Alerts</SectionTitle>
            {atRisk.length === 0 ? (
                <div className="empty-state glass"><div className="empty-icon">✅</div><h3>All wallets are adequately funded</h3></div>
            ) : (
                <div className="alert-list">
                    {atRisk.map(t => (
                        <div key={t.company_id} className={`alert-card glass ${t.wallet_balance < 1 ? 'alert-danger' : 'alert-warn'}`}>
                            <AlertTriangle size={16} />
                            <div className="flex-1">
                                <p className="alert-name">{t.company_name}</p>
                                <p className="alert-value">${t.wallet_balance.toFixed(4)} remaining · {t.total_runs_30d} executions in 30d</p>
                            </div>
                            <span className={`badge ${t.wallet_balance < 1 ? 'badge-failed' : 'badge-warn'}`}>
                                {t.wallet_balance < 1 ? 'CRITICAL' : 'LOW'}
                            </span>
                        </div>
                    ))}
                </div>
            )}
        </div>
    );
};

export const PartnerUserReports: React.FC = () => {
    const [activeTab, setActiveTab] = useState('scorecard');

    const renderTab = () => {
        switch (activeTab) {
            case 'scorecard': return <ScorecardTab />;
            case 'onboarding': return <OnboardingTab />;
            case 'errors': return (
                <div className="tab-content">
                    <div className="empty-state glass"><div className="empty-icon">🔧</div><h3>Configuration Error Logs</h3><p>Tenant configuration errors (malformed prompts, invalid API keys) will appear here as they occur during executions.</p></div>
                </div>
            );
            case 'credit-alerts': return <CreditAlertsTab />;
            default: return <ScorecardTab />;
        }
    };

    return (
        <div className="report-page">
            <div className="page-header">
                <div>
                    <h1 className="page-title"><Users size={24} style={{ marginRight: '0.5rem' }} />Partner User — Tenant Support</h1>
                    <p className="page-subtitle">Tenant health scorecards, onboarding progress, and credit alerts</p>
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
