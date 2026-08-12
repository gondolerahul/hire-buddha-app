import React, { useState, useEffect } from 'react';
import { reportsService, TenantHealthData } from '@/services/reports.service';
import { Users, Activity, AlertTriangle, ShieldCheck } from 'lucide-react';
import { StatCard, SectionTitle, EmptyChart, fmtUSD } from './DashboardShared';
import { ResponsiveContainer, PieChart, Pie, Cell, Tooltip, Legend } from 'recharts';
import './SharedDashboard.css';

export const PartnerUserDashboard: React.FC = () => {
    const [healthData, setHealthData] = useState<TenantHealthData | null>(null);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        const fetchData = async () => {
            try {
                const res = await reportsService.getTenantHealth();
                setHealthData(res);
            } catch (err) {
                console.error("Failed to load dashboard data", err);
            } finally {
                setLoading(false);
            }
        };
        fetchData();
    }, []);

    if (loading) return <div className="loading-state"><div className="pulse">Loading Tenant Data…</div></div>;

    const tenants = healthData?.tenants || [];
    const atRiskCount = tenants.filter(t => t.at_risk).length;
    const avgHealthScore = tenants.length > 0
        ? tenants.reduce((acc, t) => acc + t.health_score, 0) / tenants.length
        : 0;

    const activeTenants = tenants.filter(t => t.status === 'ACTIVE').length;
    const suspendedTenants = tenants.filter(t => t.status !== 'ACTIVE').length;

    const statusPie = [
        { name: 'Active', value: activeTenants },
        { name: 'Suspended/Inactive', value: suspendedTenants }
    ];

    return (
        <div className="dashboard-wrapper">
            <div className="dashboard-header">
                <h1 className="page-title">Tenant Success Management</h1>
                <p className="page-subtitle">Account Health and Onboarding Progression</p>
            </div>

            <div className="stats-grid-4">
                <StatCard label="Total Tenants Managed" value={tenants.length} icon={Users} color="#6b9bd2" />
                <StatCard label="Average Health Score" value={avgHealthScore.toFixed(0)} icon={Activity} color={avgHealthScore > 80 ? "#4dbe8d" : "#e8885a"} sub="Out of 100" />
                <StatCard label="At Risk Tenants" value={atRiskCount} icon={AlertTriangle} color="#e8885a" />
                <StatCard label="Active Workflows" value={tenants.reduce((acc, t) => acc + t.total_runs_30d, 0)} icon={ShieldCheck} color="#4dbe8d" sub="Last 30 days" />
            </div>

            <div className="two-col-grid">
                <div>
                    <SectionTitle>Tenant Status Distribution</SectionTitle>
                    <div className="dashboard-chart-container">
                        {tenants.length === 0 ? <EmptyChart /> : (
                            <ResponsiveContainer width="100%" height={260}>
                                <PieChart>
                                    <Pie data={statusPie} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={100} label={({ name, value }) => `${name}: ${value}`}>
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

                <div>
                    <SectionTitle>At Risk Tenants (Action Required)</SectionTitle>
                    <div className="alert-list">
                        {tenants.filter(t => t.at_risk).length === 0 ? (
                            <div className="chart-empty"><p>All tenants are healthy</p></div>
                        ) : (
                            tenants.filter(t => t.at_risk).slice(0, 5).map(t => (
                                <div key={t.company_id} className="alert-card alert-danger">
                                    <AlertTriangle size={20} />
                                    <div>
                                        <p className="alert-name">{t.company_name}</p>
                                        <p className="alert-value">
                                            Health Score: {t.health_score} • Wallet: {fmtUSD(t.wallet_balance)}
                                        </p>
                                    </div>
                                </div>
                            ))
                        )}
                    </div>
                </div>
            </div>

            <SectionTitle>Tenant Health Scorecard</SectionTitle>
            <div className="dashboard-table-wrapper">
                <table className="dashboard-table">
                    <thead>
                        <tr>
                            <th>Tenant Name</th>
                            <th>Status</th>
                            <th>Health Score</th>
                            <th>30d Runs</th>
                            <th>Wallet Balance</th>
                        </tr>
                    </thead>
                    <tbody>
                        {tenants.sort((a, b) => a.health_score - b.health_score).slice(0, 10).map((t) => (
                            <tr key={t.company_id}>
                                <td>{t.company_name}</td>
                                <td><span className={`badge badge-${t.status.toLowerCase()}`}>{t.status}</span></td>
                                <td style={{ color: t.health_score < 70 ? '#e8885a' : '#4dbe8d', fontWeight: 'bold' }}>{t.health_score}</td>
                                <td>{t.total_runs_30d}</td>
                                <td>{fmtUSD(t.wallet_balance)}</td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
        </div>
    );
};
