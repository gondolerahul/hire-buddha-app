import React, { useState, useEffect } from 'react';
import { reportsService, PartnerPerformanceData, UsageBreakdownData } from '@/services/reports.service';
import { Users, DollarSign, TrendingUp, Activity } from 'lucide-react';
import { StatCard, SectionTitle, EmptyChart, fmtUSD } from './DashboardShared';
import { ResponsiveContainer, BarChart, Bar, CartesianGrid, XAxis, YAxis, Tooltip } from 'recharts';
import './SharedDashboard.css';

export const PartnerAdminDashboard: React.FC = () => {
    const [partnerData, setPartnerData] = useState<PartnerPerformanceData | null>(null);
    const [usageData, setUsageData] = useState<UsageBreakdownData | null>(null);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        const fetchData = async () => {
            try {
                const [partnerRes, usageRes] = await Promise.all([
                    reportsService.getPartnerPerformance(),
                    reportsService.getUsageBreakdown(30),
                ]);
                setPartnerData(partnerRes);
                setUsageData(usageRes);
            } catch (err) {
                console.error("Failed to load dashboard data", err);
            } finally {
                setLoading(false);
            }
        };
        fetchData();
    }, []);

    if (loading) return <div className="loading-state"><div className="pulse">Loading Portfolio Data…</div></div>;

    const partners = partnerData?.partners || [];
    const usageDaily = usageData?.daily_trend || [];

    // Aggregate metrics
    const totalRevenue = partners.reduce((acc, p) => acc + p.total_revenue_usd, 0);
    const totalTenants = partners.reduce((acc, p) => acc + p.tenant_count, 0);
    const topPartner = partners.sort((a, b) => b.total_revenue_usd - a.total_revenue_usd)[0];

    return (
        <div className="dashboard-wrapper">
            <div className="dashboard-header">
                <h1 className="page-title">Portfolio Financials</h1>
                <p className="page-subtitle">Aggregate Sub-Tenant Margins and Usage Tracking</p>
            </div>

            <div className="stats-grid-4">
                <StatCard label="Total Portfolio Revenue" value={fmtUSD(totalRevenue)} icon={DollarSign} color="#4dbe8d" />
                <StatCard label="Total Sub-Tenants" value={totalTenants} icon={Users} color="#6b9bd2" />
                <StatCard label="Total Billing (30d)" value={fmtUSD(usageData?.total_cost_usd || 0)} icon={Activity} color="#e8885a" />
                <StatCard label="Top Performer" value={topPartner ? topPartner.partner_name : 'N/A'} icon={TrendingUp} color="#d2b96b" sub={topPartner ? fmtUSD(topPartner.total_revenue_usd) : ''} />
            </div>

            <div className="two-col-grid">
                <div>
                    <SectionTitle>Partner Revenue Leaderboard</SectionTitle>
                    <div className="dashboard-chart-container">
                        {partners.length === 0 ? <EmptyChart message="No partner data available" /> : (
                            <ResponsiveContainer width="100%" height={260}>
                                <BarChart data={partners} margin={{ top: 10, right: 20, left: 20, bottom: 40 }}>
                                    <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
                                    <XAxis dataKey="partner_name" tick={{ fill: 'rgba(255,255,255,0.45)', fontSize: 11 }} angle={-30} textAnchor="end" />
                                    <YAxis tick={{ fill: 'rgba(255,255,255,0.45)', fontSize: 11 }} />
                                    <Tooltip contentStyle={{ background: 'rgba(20,15,30,0.95)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 10 }} />
                                    <Bar dataKey="total_revenue_usd" name="Revenue USD" fill="#4dbe8d" radius={[4, 4, 0, 0]} />
                                </BarChart>
                            </ResponsiveContainer>
                        )}
                    </div>
                </div>

                <div>
                    <SectionTitle>Sub-Tenant Daily Billing Trend (30d)</SectionTitle>
                    <div className="dashboard-chart-container">
                        {usageDaily.length === 0 ? <EmptyChart message="No trend data available" /> : (
                            <ResponsiveContainer width="100%" height={260}>
                                <BarChart data={usageDaily} margin={{ top: 10, right: 20, left: 0, bottom: 0 }}>
                                    <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
                                    <XAxis dataKey="date" tick={{ fill: 'rgba(255,255,255,0.45)', fontSize: 10 }} />
                                    <YAxis tick={{ fill: 'rgba(255,255,255,0.45)', fontSize: 10 }} />
                                    <Tooltip contentStyle={{ background: 'rgba(20,15,30,0.95)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 10 }} />
                                    <Bar dataKey="cost" name="Daily Billing" fill="#e8885a" radius={[2, 2, 0, 0]} />
                                </BarChart>
                            </ResponsiveContainer>
                        )}
                    </div>
                </div>
            </div>

            <SectionTitle>Top Sub-Tenants</SectionTitle>
            <div className="dashboard-table-wrapper">
                <table className="dashboard-table">
                    <thead>
                        <tr>
                            <th>Partner Name</th>
                            <th>Status</th>
                            <th>Tenants</th>
                            <th>Total Revenue</th>
                        </tr>
                    </thead>
                    <tbody>
                        {partners.slice(0, 10).map((p) => (
                            <tr key={p.partner_id}>
                                <td>{p.partner_name}</td>
                                <td><span className={`badge badge-${p.status}`}>{p.status}</span></td>
                                <td>{p.tenant_count}</td>
                                <td>{fmtUSD(p.total_revenue_usd)}</td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
        </div>
    );
};
