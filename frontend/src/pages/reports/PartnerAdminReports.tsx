import React, { useState, useEffect } from 'react';
import {
    BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell,
} from 'recharts';
import {
    Users, TrendingUp, AlertTriangle, CheckCircle,
    DollarSign, Activity, Shield, Star,
} from 'lucide-react';
import { reportsService, TenantHealthData } from '@/services/reports.service';
import './Report.css';

const CHART_COLORS = ['#e8c5a0', '#c9956c', '#9b6fa0', '#6b9bd2', '#4dbe8d', '#e8885a', '#a0c8e8', '#d2b96b'];

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
    { id: 'portfolio', label: 'Portfolio Financials', icon: DollarSign },
    { id: 'health', label: 'Tenant Health', icon: Activity },
    { id: 'at-risk', label: 'At-Risk Alerts', icon: AlertTriangle },
    { id: 'top-tenants', label: 'Top Performers', icon: Star },
    { id: 'subscriptions', label: 'Subscription Matrix', icon: TrendingUp },
    { id: 'upsell', label: 'Upsell Opportunities', icon: Shield },
];

// ── Portfolio Financials ──────────────────────────────────────────────────────
const PortfolioTab: React.FC = () => {
    const [data, setData] = useState<TenantHealthData | null>(null);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        reportsService.getTenantHealth().then(setData).catch(() => setData(null)).finally(() => setLoading(false));
    }, []);

    if (loading) return <div className="loading-state"><div className="pulse">Loading…</div></div>;

    const tenants = data?.tenants || [];
    const totalWallet = tenants.reduce((s, t) => s + t.wallet_balance, 0);
    const totalRuns = tenants.reduce((s, t) => s + t.total_runs_30d, 0);
    const activeTenants = tenants.filter(t => t.status === 'active').length;

    const walletData = tenants.slice(0, 12).map(t => ({
        name: t.company_name.slice(0, 12),
        balance: t.wallet_balance,
    }));

    return (
        <div className="tab-content">
            <div className="stats-grid-4">
                <StatCard label="Total Tenants" value={tenants.length} icon={Users} />
                <StatCard label="Active Tenants" value={activeTenants} icon={CheckCircle} color="#4dbe8d" />
                <StatCard label="Total Wallet Balance" value={`$${totalWallet.toFixed(2)}`} icon={DollarSign} />
                <StatCard label="Total Runs (30d)" value={totalRuns.toLocaleString()} icon={Activity} />
            </div>

            <SectionTitle>Wallet Balance by Tenant</SectionTitle>
            <div className="chart-container glass">
                {walletData.length === 0 ? <EmptyChart message="No tenants found under your portfolio" /> : (
                    <ResponsiveContainer width="100%" height={280}>
                        <BarChart data={walletData} margin={{ top: 10, right: 20, left: 20, bottom: 60 }}>
                            <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
                            <XAxis dataKey="name" tick={{ fill: 'rgba(255,255,255,0.45)', fontSize: 11 }} angle={-30} textAnchor="end" />
                            <YAxis tick={{ fill: 'rgba(255,255,255,0.45)', fontSize: 11 }} />
                            <Tooltip contentStyle={{ background: 'rgba(20,15,30,0.95)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 10 }} formatter={(v) => [`$${Number(v).toFixed(4)}`, 'Balance']} />
                            <Bar dataKey="balance" name="Balance" radius={[4, 4, 0, 0]}>
                                {walletData.map((d, i) => <Cell key={i} fill={d.balance < 2 ? '#e8885a' : CHART_COLORS[i % CHART_COLORS.length]} />)}
                            </Bar>
                        </BarChart>
                    </ResponsiveContainer>
                )}
            </div>
        </div>
    );
};

// ── Tenant Health ─────────────────────────────────────────────────────────────
const TenantHealthTab: React.FC = () => {
    const [data, setData] = useState<TenantHealthData | null>(null);
    const [loading, setLoading] = useState(true);
    const [search, setSearch] = useState('');
    const [sortBy, setSortBy] = useState<'health_score' | 'total_runs_30d' | 'wallet_balance'>('health_score');

    useEffect(() => {
        reportsService.getTenantHealth().then(setData).catch(() => setData(null)).finally(() => setLoading(false));
    }, []);

    if (loading) return <div className="loading-state"><div className="pulse">Loading…</div></div>;

    const tenants = [...(data?.tenants || [])]
        .filter(t => t.company_name.toLowerCase().includes(search.toLowerCase()))
        .sort((a, b) => b[sortBy] - a[sortBy]);

    return (
        <div className="tab-content">
            <div className="filter-row">
                <input className="search-input" placeholder="Search tenant…" value={search} onChange={e => setSearch(e.target.value)} />
                <div className="pill-group">
                    {(['health_score', 'total_runs_30d', 'wallet_balance'] as const).map(s => (
                        <button key={s} className={`pill ${sortBy === s ? 'active' : ''}`} onClick={() => setSortBy(s)}>
                            {s === 'health_score' ? 'Health' : s === 'total_runs_30d' ? 'Activity' : 'Balance'}
                        </button>
                    ))}
                </div>
            </div>

            <div className="tenant-grid">
                {tenants.map(t => (
                    <div key={t.company_id} className={`tenant-card glass ${t.at_risk ? 'at-risk' : ''}`}>
                        <div className="tenant-card-header">
                            <span className="tenant-name">{t.company_name}</span>
                            <span className="health-score-badge" style={{ color: t.health_score > 70 ? '#4dbe8d' : t.health_score > 40 ? '#d2b96b' : '#e8885a' }}>
                                {t.health_score}%
                            </span>
                        </div>
                        <div className="health-bar">
                            <div className="health-bar-fill" style={{ width: `${t.health_score}%`, background: t.health_score > 70 ? '#4dbe8d' : t.health_score > 40 ? '#d2b96b' : '#e8885a' }} />
                        </div>
                        <div className="tenant-meta-grid">
                            <div><span className="meta-label">Runs (30d)</span><span className="meta-val">{t.total_runs_30d}</span></div>
                            <div><span className="meta-label">Success</span><span className="meta-val deduction">{t.completed_runs}</span></div>
                            <div><span className="meta-label">Failed</span><span className="meta-val" style={{ color: t.failed_runs > 0 ? '#e8885a' : 'inherit' }}>{t.failed_runs}</span></div>
                            <div><span className="meta-label">Balance</span><span className="meta-val">${t.wallet_balance.toFixed(2)}</span></div>
                        </div>
                        {t.at_risk && <div className="at-risk-badge"><AlertTriangle size={12} /> At Risk</div>}
                    </div>
                ))}
                {tenants.length === 0 && <div className="empty-state glass"><div className="empty-icon">🏢</div><p>No tenants found</p></div>}
            </div>
        </div>
    );
};

// ── At-Risk Alerts ────────────────────────────────────────────────────────────
const AtRiskTab: React.FC = () => {
    const [data, setData] = useState<TenantHealthData | null>(null);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        reportsService.getTenantHealth().then(setData).catch(() => setData(null)).finally(() => setLoading(false));
    }, []);

    if (loading) return <div className="loading-state"><div className="pulse">Loading…</div></div>;

    const atRisk = (data?.tenants || []).filter(t => t.at_risk);
    const critical = atRisk.filter(t => t.wallet_balance < 1);
    const warning = atRisk.filter(t => t.wallet_balance >= 1);

    return (
        <div className="tab-content">
            <div className="stats-grid-4">
                <StatCard label="At-Risk Tenants" value={atRisk.length} icon={AlertTriangle} color="#e8885a" />
                <StatCard label="Critical (< $1)" value={critical.length} icon={AlertTriangle} color="#e8885a" />
                <StatCard label="Warning" value={warning.length} icon={AlertTriangle} color="#d2b96b" />
                <StatCard label="Safe Tenants" value={(data?.tenants.length || 0) - atRisk.length} icon={CheckCircle} color="#4dbe8d" />
            </div>

            {critical.length > 0 && (
                <>
                    <SectionTitle>🔴 Critical — Near Zero Balance</SectionTitle>
                    <div className="alert-list">
                        {critical.map(t => (
                            <div key={t.company_id} className="alert-card glass alert-danger">
                                <AlertTriangle size={16} />
                                <div className="flex-1">
                                    <p className="alert-name">{t.company_name}</p>
                                    <p className="alert-value">${t.wallet_balance.toFixed(4)} remaining · {t.total_runs_30d} runs in 30d</p>
                                </div>
                                <span className="badge badge-failed">CRITICAL</span>
                            </div>
                        ))}
                    </div>
                </>
            )}

            {warning.length > 0 && (
                <>
                    <SectionTitle>🟡 Warning — Low Balance</SectionTitle>
                    <div className="alert-list">
                        {warning.map(t => (
                            <div key={t.company_id} className="alert-card glass alert-warn">
                                <AlertTriangle size={16} />
                                <div className="flex-1">
                                    <p className="alert-name">{t.company_name}</p>
                                    <p className="alert-value">${t.wallet_balance.toFixed(4)} remaining · {t.failed_runs} failures</p>
                                </div>
                                <span className="badge badge-warn">WARNING</span>
                            </div>
                        ))}
                    </div>
                </>
            )}

            {atRisk.length === 0 && (
                <div className="empty-state glass"><div className="empty-icon">✅</div><h3>All tenants in good standing</h3><p>No at-risk tenants detected.</p></div>
            )}
        </div>
    );
};

// ── Top Performers ────────────────────────────────────────────────────────────
const TopTenantsTab: React.FC = () => {
    const [data, setData] = useState<TenantHealthData | null>(null);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        reportsService.getTenantHealth().then(setData).catch(() => setData(null)).finally(() => setLoading(false));
    }, []);

    if (loading) return <div className="loading-state"><div className="pulse">Loading…</div></div>;

    const top = [...(data?.tenants || [])].sort((a, b) => b.total_runs_30d - a.total_runs_30d).slice(0, 10);

    return (
        <div className="tab-content">
            <SectionTitle>Top Tenants by AI Execution Volume</SectionTitle>
            <div className="chart-container glass">
                {top.length === 0 ? <EmptyChart /> : (
                    <ResponsiveContainer width="100%" height={280}>
                        <BarChart data={top} layout="vertical" margin={{ top: 5, right: 60, left: 120, bottom: 5 }}>
                            <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
                            <XAxis type="number" tick={{ fill: 'rgba(255,255,255,0.45)', fontSize: 11 }} />
                            <YAxis dataKey="company_name" type="category" tick={{ fill: 'rgba(255,255,255,0.45)', fontSize: 11 }} width={110} />
                            <Tooltip contentStyle={{ background: 'rgba(20,15,30,0.95)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 10 }} />
                            <Bar dataKey="total_runs_30d" name="Total Runs (30d)" radius={[0, 4, 4, 0]}>
                                {top.map((_, i) => <Cell key={i} fill={CHART_COLORS[i % CHART_COLORS.length]} />)}
                            </Bar>
                        </BarChart>
                    </ResponsiveContainer>
                )}
            </div>

            <div className="partner-leaderboard">
                {top.map((t, i) => (
                    <div key={t.company_id} className="partner-card glass">
                        <div className="partner-rank">#{i + 1}</div>
                        <div className="partner-info">
                            <p className="partner-name">{t.company_name}</p>
                            <p className="partner-meta">Health: <span style={{ color: t.health_score > 70 ? '#4dbe8d' : '#e8885a' }}>{t.health_score}%</span> · {t.completed_runs} completed</p>
                        </div>
                        <div className="partner-revenue">{t.total_runs_30d} runs</div>
                    </div>
                ))}
                {top.length === 0 && <div className="empty-state glass"><p>No tenant activity found</p></div>}
            </div>
        </div>
    );
};

// ── Main ─────────────────────────────────────────────────────────────────────
export const PartnerAdminReports: React.FC = () => {
    const [activeTab, setActiveTab] = useState('portfolio');

    const renderTab = () => {
        switch (activeTab) {
            case 'portfolio': return <PortfolioTab />;
            case 'health': return <TenantHealthTab />;
            case 'at-risk': return <AtRiskTab />;
            case 'top-tenants': return <TopTenantsTab />;
            case 'subscriptions': return (
                <div className="tab-content">
                    <div className="empty-state glass"><div className="empty-icon">📊</div><h3>Subscription Matrix</h3><p>Subscription tier upgrade/downgrade matrix for your tenants. Data populates as tenants subscribe and change plans.</p></div>
                </div>
            );
            case 'upsell': return (
                <div className="tab-content">
                    <div className="empty-state glass"><div className="empty-icon">🎯</div><h3>Upsell Opportunities</h3><p>Tenants using only basic chat without Voice or WhatsApp will be highlighted here as their activity grows.</p></div>
                </div>
            );
            default: return <PortfolioTab />;
        }
    };

    return (
        <div className="report-page">
            <div className="page-header">
                <div>
                    <h1 className="page-title"><Users size={24} style={{ marginRight: '0.5rem' }} />Partner Admin — Portfolio Analytics</h1>
                    <p className="page-subtitle">Tenant portfolio health, financials, and sales opportunities</p>
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
