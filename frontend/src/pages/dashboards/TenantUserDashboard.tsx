import { parseServerDate } from '@/utils/datetime';
import React, { useState, useEffect } from 'react';
import { reportsService, PersonalTasksData, HitlData } from '@/services/reports.service';
import { Activity, Clock, ShieldAlert, CheckCircle } from 'lucide-react';
import { StatCard, SectionTitle, EmptyChart, fmtPct } from './DashboardShared';
import { ResponsiveContainer, PieChart, Pie, Cell, Tooltip, Legend } from 'recharts';
import './SharedDashboard.css';

export const TenantUserDashboard: React.FC = () => {
    const [tasksData, setTasksData] = useState<PersonalTasksData | null>(null);
    const [hitlData, setHitlData] = useState<HitlData | null>(null);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        const fetchData = async () => {
            try {
                const [tasksRes, hitlRes] = await Promise.all([
                    reportsService.getPersonalTasks(50), // fetch recent personal tasks
                    reportsService.getHitlOverview(30, false), // tenant user view scoped via backend
                ]);
                setTasksData(tasksRes);
                setHitlData(hitlRes);
            } catch (err) {
                console.error("Failed to load dashboard data", err);
            } finally {
                setLoading(false);
            }
        };
        fetchData();
    }, []);

    if (loading) return <div className="loading-state"><div className="pulse">Loading Worklog…</div></div>;

    const tasks = tasksData?.tasks || [];
    const summary = tasksData?.summary;
    const approvals = hitlData?.approvals || [];
    const pendingApprovals = approvals.filter(a => a.status === 'PENDING');

    const statusPie = [
        { name: 'Completed', value: summary?.completed || 0 },
        { name: 'Failed', value: summary?.failed || 0 },
        { name: 'Other', value: (summary?.total || 0) - (summary?.completed || 0) - (summary?.failed || 0) }
    ];

    return (
        <div className="dashboard-wrapper">
            <div className="dashboard-header">
                <h1 className="page-title">My Worklog</h1>
                <p className="page-subtitle">Personal tasks, automations, and pending approvals</p>
            </div>

            <div className="stats-grid-4">
                <StatCard label="Total Tasks Run" value={summary?.total || 0} icon={Activity} color="#6b9bd2" />
                <StatCard label="Success Rate" value={fmtPct(summary?.success_rate || 0)} icon={CheckCircle} color="#4dbe8d" />
                <StatCard label="Time Saved (Est.)" value={`${summary?.estimated_time_saved_hours?.toFixed(1) || 0} hrs`} icon={Clock} color="#d2b96b" />
                <StatCard label="Pending Approvals" value={pendingApprovals.length} icon={ShieldAlert} color={pendingApprovals.length > 0 ? "#e8885a" : "#4dbe8d"} />
            </div>

            <div className="two-col-grid">
                <div>
                    <SectionTitle>Action Items: Pending Approvals</SectionTitle>
                    <div className="alert-list">
                        {pendingApprovals.length === 0 ? (
                            <div className="chart-empty"><p>No pending approvals. Great job!</p></div>
                        ) : (
                            pendingApprovals.slice(0, 5).map(a => (
                                <div key={a.id} className="alert-card alert-danger">
                                    <ShieldAlert size={20} />
                                    <div>
                                        <p className="alert-name">{a.entity_name} ({a.entity_type})</p>
                                        <p className="alert-value">Waiting at: {a.checkpoint_trigger} • {a.age_hours.toFixed(1)} hrs old</p>
                                    </div>
                                    <button className="pill active mt-2">Review</button>
                                </div>
                            ))
                        )}
                    </div>
                </div>

                <div>
                    <SectionTitle>Task Outcomes</SectionTitle>
                    <div className="dashboard-chart-container">
                        {(!summary || summary.total === 0) ? <EmptyChart message="No tasks run recently" /> : (
                            <ResponsiveContainer width="100%" height={260}>
                                <PieChart>
                                    <Pie data={statusPie} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={100} label={({ name, value }) => `${name}: ${value}`}>
                                        <Cell fill="#4dbe8d" />
                                        <Cell fill="#e8885a" />
                                        <Cell fill="#6b9bd2" />
                                    </Pie>
                                    <Tooltip contentStyle={{ background: 'rgba(20,15,30,0.95)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 10 }} />
                                    <Legend />
                                </PieChart>
                            </ResponsiveContainer>
                        )}
                    </div>
                </div>
            </div>

            <SectionTitle>Recent Activity Trail</SectionTitle>
            <div className="dashboard-table-wrapper">
                <table className="dashboard-table">
                    <thead>
                        <tr>
                            <th>Entity Name</th>
                            <th>Status</th>
                            <th>Execution Time</th>
                            <th>Tokens</th>
                            <th>Created At</th>
                        </tr>
                    </thead>
                    <tbody>
                        {tasks.slice(0, 10).map((t) => (
                            <tr key={t.id}>
                                <td>{t.entity_name}</td>
                                <td><span className={`badge badge-${t.status.toLowerCase()}`}>{t.status}</span></td>
                                <td>{t.execution_time_ms ? `${t.execution_time_ms}ms` : '—'}</td>
                                <td>{t.total_tokens}</td>
                                <td>{parseServerDate(t.created_at).toLocaleString()}</td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
        </div>
    );
};
