import React, { useState, useEffect } from 'react';
import { reportsService, WalletLiabilityData, ExecutionHealthData, LLMPerformanceData } from '@/services/reports.service';
import { DollarSign, Activity, Cpu, CheckCircle } from 'lucide-react';
import { StatCard, SectionTitle, EmptyChart, fmtUSD, fmtPct } from './DashboardShared';
import { ResponsiveContainer, AreaChart, Area, CartesianGrid, XAxis, YAxis, Tooltip, Legend, BarChart, Bar } from 'recharts';
import AccessibleChart from '@/components/ui/AccessibleChart';
import '@/components/ui/AccessibleChart.css';
import './SharedDashboard.css';

export const AppAdminDashboard: React.FC = () => {
    const [walletData, setWalletData] = useState<WalletLiabilityData | null>(null);
    const [execData, setExecData] = useState<ExecutionHealthData | null>(null);
    const [llmData, setLlmData] = useState<LLMPerformanceData | null>(null);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        const fetchData = async () => {
            try {
                const [walletRes, execRes, llmRes] = await Promise.all([
                    reportsService.getWalletLiability(),
                    reportsService.getExecutionHealth(30, true),
                    reportsService.getLLMPerformance(30, true),
                ]);
                setWalletData(walletRes);
                setExecData(execRes);
                setLlmData(llmRes);
            } catch (err) {
                console.error("Failed to load dashboard data", err);
            } finally {
                setLoading(false);
            }
        };
        fetchData();
    }, []);

    if (loading) return <div className="loading-state"><div className="pulse">Loading System Data…</div></div>;

    const execTrend = execData?.daily_trend || [];
    const models = llmData?.model_breakdown || [];

    return (
        <div className="dashboard-wrapper">
            <div className="dashboard-header">
                <h1 className="page-title">Welcome back, Administrator</h1>
                <p className="page-subtitle">Global Platform Overview - HB-Proto-3</p>
            </div>

            <div className="stats-grid-4">
                <StatCard label="Total Liability" value={fmtUSD(walletData?.totals.total_liability || 0)} icon={DollarSign} color="#e8885a" />
                <StatCard label="Total Execution Runs" value={execData?.summary.total_runs || 0} icon={Activity} color="#6b9bd2" />
                <StatCard label="Global Success Rate" value={fmtPct(execData?.summary.success_rate || 0)} icon={CheckCircle} color="#4dbe8d" />
                <StatCard label="Total LLM Cost" value={fmtUSD(llmData?.total_cost_usd || 0)} icon={Cpu} color="#d2b96b" />
            </div>

            <div className="two-col-grid">
                <div>
                    <SectionTitle>Global Execution Trends (30d)</SectionTitle>
                    <div className="dashboard-chart-container">
                        {execTrend.length === 0 ? <EmptyChart /> : (
                            <AccessibleChart
                                title="Global execution trends — last 30 days"
                                summary={`Area chart of run outcomes over 30 days. ${execTrend.length} day buckets covering COMPLETED and FAILED counts.`}
                                sourceNote="Source: execution_runs grouped by date"
                            >
                                <ResponsiveContainer width="100%" height={260}>
                                    <AreaChart data={execTrend} margin={{ top: 5, right: 20, left: 0, bottom: 0 }}>
                                        <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
                                        <XAxis dataKey="date" tick={{ fill: 'rgba(255,255,255,0.45)', fontSize: 10 }} />
                                        <YAxis tick={{ fill: 'rgba(255,255,255,0.45)', fontSize: 10 }} />
                                        <Tooltip contentStyle={{ background: 'rgba(20,15,30,0.95)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 10 }} />
                                        <Area type="monotone" dataKey="COMPLETED" stroke="#4dbe8d" fill="rgba(77,190,141,0.15)" />
                                        <Area type="monotone" dataKey="FAILED" stroke="#e8885a" fill="rgba(232,136,90,0.15)" />
                                        <Legend />
                                    </AreaChart>
                                </ResponsiveContainer>
                            </AccessibleChart>
                        )}
                    </div>
                </div>

                <div>
                    <SectionTitle>LLM Provider Breakdown (Cost $)</SectionTitle>
                    <div className="dashboard-chart-container">
                        {models.length === 0 ? <EmptyChart /> : (
                            <AccessibleChart
                                title="LLM provider cost breakdown"
                                summary={`Bar chart of total cost USD per LLM provider. ${models.length} providers in scope.`}
                                sourceNote="Source: usage_logs aggregated by integration_registry.provider_name"
                            >
                                <ResponsiveContainer width="100%" height={260}>
                                    <BarChart data={models} margin={{ top: 10, right: 20, left: 20, bottom: 40 }}>
                                        <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
                                        <XAxis dataKey="provider" tick={{ fill: 'rgba(255,255,255,0.45)', fontSize: 11 }} angle={-30} textAnchor="end" />
                                        <YAxis tick={{ fill: 'rgba(255,255,255,0.45)', fontSize: 11 }} />
                                        <Tooltip contentStyle={{ background: 'rgba(20,15,30,0.95)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 10 }} />
                                        <Bar dataKey="total_cost_usd" name="Total Cost USD" fill="#c9956c" radius={[4, 4, 0, 0]} />
                                    </BarChart>
                                </ResponsiveContainer>
                            </AccessibleChart>
                        )}
                    </div>
                </div>
            </div>
        </div>
    );
};
