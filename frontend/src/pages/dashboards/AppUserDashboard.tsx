import React, { useState, useEffect } from 'react';
import { reportsService, ExecutionHealthData, ToolEfficacyData, HitlData } from '@/services/reports.service';
import { Zap, Shield, AlertTriangle, CheckCircle, XCircle } from 'lucide-react';
import { StatCard, SectionTitle, EmptyChart, fmtPct } from './DashboardShared';
import { ResponsiveContainer, PieChart, Pie, Cell, Tooltip, Legend, BarChart, Bar, CartesianGrid, XAxis, YAxis } from 'recharts';
import './SharedDashboard.css';

export const AppUserDashboard: React.FC = () => {
    const [execData, setExecData] = useState<ExecutionHealthData | null>(null);
    const [toolData, setToolData] = useState<ToolEfficacyData | null>(null);
    const [hitlData, setHitlData] = useState<HitlData | null>(null);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        const fetchData = async () => {
            try {
                const [execRes, toolRes, hitlRes] = await Promise.all([
                    reportsService.getExecutionHealth(7, true),
                    reportsService.getToolEfficacy(7, true),
                    reportsService.getHitlOverview(7, true),
                ]);
                setExecData(execRes);
                setToolData(toolRes);
                setHitlData(hitlRes);
            } catch (err) {
                console.error("Failed to load dashboard data", err);
            } finally {
                setLoading(false);
            }
        };
        fetchData();
    }, []);

    if (loading) return <div className="loading-state"><div className="pulse">Loading Tech Ops Data…</div></div>;

    const statusData = execData?.status_breakdown || [];
    const tools = [...(toolData?.tools || [])].sort((a, b) => b.error_rate - a.error_rate).slice(0, 5);
    const overdueApprovals = (hitlData?.approvals || []).filter(a => a.is_overdue);

    return (
        <div className="dashboard-wrapper">
            <div className="dashboard-header">
                <h1 className="page-title">Technical Operations</h1>
                <p className="page-subtitle">Global System Health, Tool Reliability, and Interpolation</p>
            </div>

            <div className="stats-grid-4">
                <StatCard label="Global Success (7d)" value={fmtPct(execData?.summary.success_rate || 0)} icon={CheckCircle} color="#4dbe8d" />
                <StatCard label="Failed Executions" value={execData?.status_breakdown.find(s => s.status === 'FAILED')?.count || 0} icon={XCircle} color="#e8885a" />
                <StatCard label="Top Error Tool" value={tools.length > 0 ? tools[0].tool_name : 'No Data'} icon={Zap} color="#d2b96b" sub={tools.length > 0 ? `${fmtPct(tools[0].error_rate)} Error Rate` : ''} />
                <StatCard label="Overdue HITL" value={hitlData?.overdue_count || 0} icon={Shield} color="#e8885a" />
            </div>

            <div className="two-col-grid">
                <div>
                    <SectionTitle>System State Distribution</SectionTitle>
                    <div className="dashboard-chart-container">
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
                    <SectionTitle>Tool Error Rates (Top 5)</SectionTitle>
                    <div className="dashboard-chart-container">
                        {tools.length === 0 ? <EmptyChart /> : (
                            <ResponsiveContainer width="100%" height={260}>
                                <BarChart data={tools} layout="vertical" margin={{ top: 5, right: 30, left: 60, bottom: 5 }}>
                                    <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
                                    <XAxis type="number" tick={{ fill: 'rgba(255,255,255,0.45)', fontSize: 11 }} />
                                    <YAxis dataKey="tool_name" type="category" tick={{ fill: 'rgba(255,255,255,0.45)', fontSize: 11 }} width={80} />
                                    <Tooltip contentStyle={{ background: 'rgba(20,15,30,0.95)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 10 }} />
                                    <Bar dataKey="error_rate" name="Error Rate %" fill="#e8885a" radius={[0, 4, 4, 0]} />
                                </BarChart>
                            </ResponsiveContainer>
                        )}
                    </div>
                </div>
            </div>

            {overdueApprovals.length > 0 && (
                <div>
                    <SectionTitle>Urgent Action Needed: Overdue Approvals</SectionTitle>
                    <div className="alert-list">
                        {overdueApprovals.slice(0, 5).map(a => (
                            <div key={a.id} className="alert-card alert-danger">
                                <AlertTriangle size={20} />
                                <div>
                                    <p className="alert-name">{a.entity_name} ({a.entity_type})</p>
                                    <p className="alert-value">Waiting for {a.age_hours.toFixed(1)} hours at checkpoint: {a.checkpoint_trigger}</p>
                                </div>
                            </div>
                        ))}
                    </div>
                </div>
            )}
        </div>
    );
};
