import React, { useState, useEffect } from 'react';
import { reportsService, CreditForecastData, AgentErrorsData, CampaignAnalyticsData } from '@/services/reports.service';
import { DollarSign, Clock, Briefcase, Zap } from 'lucide-react';
import { StatCard, SectionTitle, EmptyChart, fmtUSD, fmtPct } from './DashboardShared';
import { ResponsiveContainer, AreaChart, Area, CartesianGrid, XAxis, YAxis, Tooltip, Legend, BarChart, Bar } from 'recharts';
import './SharedDashboard.css';

export const TenantAdminDashboard: React.FC = () => {
    const [forecastData, setForecastData] = useState<CreditForecastData | null>(null);
    const [agentData, setAgentData] = useState<AgentErrorsData | null>(null);
    const [campaignData, setCampaignData] = useState<CampaignAnalyticsData | null>(null);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        const fetchData = async () => {
            try {
                const [forecastRes, agentRes, campRes] = await Promise.all([
                    reportsService.getCreditForecast(),
                    reportsService.getAgentErrors(30),
                    reportsService.getCampaignAnalytics(30),
                ]);
                setForecastData(forecastRes);
                setAgentData(agentRes);
                setCampaignData(campRes);
            } catch (err) {
                console.error("Failed to load dashboard data", err);
            } finally {
                setLoading(false);
            }
        };
        fetchData();
    }, []);

    if (loading) return <div className="loading-state"><div className="pulse">Loading Admin Dashboard…</div></div>;

    const agents = [...(agentData?.agents || [])].sort((a, b) => b.total - a.total).slice(0, 10);
    const forecastTrend = forecastData?.forecast.projection || [];

    return (
        <div className="dashboard-wrapper">
            <div className="dashboard-header">
                <h1 className="page-title">Operations & Budgets</h1>
                <p className="page-subtitle">Billing Control, Campaign Analytics, and Agent Performance</p>
            </div>

            <div className="stats-grid-4">
                <StatCard label="Total Available Credits" value={fmtUSD(forecastData?.wallet.total_available || 0)} icon={DollarSign} color="#4dbe8d" />
                <StatCard label="Burn Rate (Avg/Day)" value={fmtUSD(forecastData?.burn_rate.avg_daily_usd || 0)} icon={Zap} color="#e8885a" />
                <StatCard label="Days Remaining" value={forecastData?.forecast.days_remaining || 0} icon={Clock} color={forecastData && forecastData.forecast.days_remaining < 7 ? "#e8885a" : "#6b9bd2"} />
                <StatCard label="Total Audio Outbound" value={`${campaignData?.telephony.total_outbound_minutes || 0} min`} icon={Briefcase} color="#d2b96b" sub={`Billed: ${fmtUSD(campaignData?.telephony.total_charge_usd || 0)}`} />
            </div>

            <div className="two-col-grid">
                <div>
                    <SectionTitle>Credit Depletion Forecast</SectionTitle>
                    <div className="dashboard-chart-container">
                        {forecastTrend.length === 0 ? <EmptyChart message="No forecast data" /> : (
                            <ResponsiveContainer width="100%" height={260}>
                                <AreaChart data={forecastTrend} margin={{ top: 10, right: 20, left: 0, bottom: 0 }}>
                                    <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
                                    <XAxis dataKey="date" tick={{ fill: 'rgba(255,255,255,0.45)', fontSize: 10 }} />
                                    <YAxis tick={{ fill: 'rgba(255,255,255,0.45)', fontSize: 10 }} />
                                    <Tooltip contentStyle={{ background: 'rgba(20,15,30,0.95)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 10 }} />
                                    <Area type="monotone" dataKey="projected_balance" name="Projected Balance" stroke="#6b9bd2" fill="rgba(107, 155, 210, 0.15)" />
                                    <Legend />
                                </AreaChart>
                            </ResponsiveContainer>
                        )}
                    </div>
                </div>

                <div>
                    <SectionTitle>Top Agent Activity</SectionTitle>
                    <div className="dashboard-chart-container">
                        {agents.length === 0 ? <EmptyChart message="No active agents" /> : (
                            <ResponsiveContainer width="100%" height={260}>
                                <BarChart data={agents} margin={{ top: 10, right: 20, left: 20, bottom: 40 }}>
                                    <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
                                    <XAxis dataKey="name" tick={{ fill: 'rgba(255,255,255,0.45)', fontSize: 11 }} angle={-30} textAnchor="end" />
                                    <YAxis tick={{ fill: 'rgba(255,255,255,0.45)', fontSize: 11 }} />
                                    <Tooltip contentStyle={{ background: 'rgba(20,15,30,0.95)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 10 }} />
                                    <Bar dataKey="total" name="Total Runs" fill="#d2b96b" radius={[4, 4, 0, 0]} />
                                    <Bar dataKey="failed" name="Failed Runs" fill="#e8885a" radius={[4, 4, 0, 0]} />
                                    <Legend />
                                </BarChart>
                            </ResponsiveContainer>
                        )}
                    </div>
                </div>
            </div>

            <SectionTitle>Agent Efficacy Table</SectionTitle>
            <div className="dashboard-table-wrapper">
                <table className="dashboard-table">
                    <thead>
                        <tr>
                            <th>Agent Name</th>
                            <th>Total Runs</th>
                            <th>Failed</th>
                            <th>Error Rate</th>
                            <th>Billing</th>
                        </tr>
                    </thead>
                    <tbody>
                        {agents.map((a) => (
                            <tr key={a.entity_id}>
                                <td>{a.name}</td>
                                <td>{a.total}</td>
                                <td style={{ color: a.failed > 0 ? '#e8885a' : 'inherit' }}>{a.failed}</td>
                                <td style={{ color: a.error_rate > 10 ? '#e8885a' : '#4dbe8d', fontWeight: 700 }}>{fmtPct(a.error_rate)}</td>
                                <td>{fmtUSD(a.total_cost)}</td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
        </div>
    );
};
