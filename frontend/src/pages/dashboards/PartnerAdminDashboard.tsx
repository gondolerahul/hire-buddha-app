import React, { useState, useEffect } from 'react';
import { partnerService, PartnerRevenue, TenantSummary } from '@/services/platform.service';
import { Users, DollarSign, TrendingUp, AlertTriangle } from 'lucide-react';
import { StatCard, SectionTitle, EmptyChart, fmtUSD } from './DashboardShared';
import { ResponsiveContainer, BarChart, Bar, CartesianGrid, XAxis, YAxis, Tooltip } from 'recharts';
import './SharedDashboard.css';

const MONTHS = 6;

/**
 * The partner's own portfolio (Phase 15 T0-6): what its tenants were billed and
 * how healthy they are. It used to call the app-admin-only partner-performance
 * report, get 403 and show nothing at all. Amounts are billed, never cost.
 */
export const PartnerAdminDashboard: React.FC = () => {
    const [revenue, setRevenue] = useState<PartnerRevenue | null>(null);
    const [tenants, setTenants] = useState<TenantSummary[]>([]);
    const [failed, setFailed] = useState<string[]>([]);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        const fetchData = async () => {
            // Each part loads on its own: one failing must not blank the page.
            const [revenueRes, tenantsRes] = await Promise.allSettled([
                partnerService.getRevenue(MONTHS),
                partnerService.getTenants(),
            ]);
            const missing: string[] = [];
            if (revenueRes.status === 'fulfilled') setRevenue(revenueRes.value);
            else missing.push('billing');
            if (tenantsRes.status === 'fulfilled') setTenants(tenantsRes.value.tenants);
            else missing.push('tenant health');
            setFailed(missing);
            setLoading(false);
        };
        fetchData();
    }, []);

    if (loading) return <div className="loading-state"><div className="pulse">Loading Portfolio Data…</div></div>;

    const totals = revenue?.totals;
    const monthly = revenue?.monthly ?? [];
    const health = new Map(tenants.map((t) => [t.id, t]));
    const atRisk = tenants.filter((t) => t.at_risk).length;
    const rows = revenue?.tenants ?? tenants.map((t) => ({
        company_id: t.id, company_name: t.name, status: t.status, billed_this_month: 0, billed_period: 0,
    }));

    return (
        <div className="dashboard-wrapper">
            <div className="dashboard-header">
                <h1 className="page-title">Portfolio</h1>
                <p className="page-subtitle">What your tenants were billed, and how they are doing</p>
            </div>

            {failed.length > 0 && (
                <div className="error-banner"><AlertTriangle size={14} /> Could not load {failed.join(' and ')}.</div>
            )}

            <div className="stats-grid-4">
                <StatCard label="Billed This Month" value={fmtUSD(totals?.billed_this_month ?? 0)} icon={DollarSign} color="#4dbe8d" />
                <StatCard label={`Billed (${MONTHS} months)`} value={fmtUSD(totals?.billed_period ?? 0)} icon={TrendingUp} color="#e8885a" />
                <StatCard label="Tenants" value={totals?.tenants ?? tenants.length} icon={Users} color="#6b9bd2"
                    sub={totals ? `${totals.active_tenants} active · ${totals.suspended_tenants} suspended` : ''} />
                <StatCard label="Tenants at Risk" value={atRisk} icon={AlertTriangle} color="#d2b96b" />
            </div>

            <SectionTitle>Billed per Month</SectionTitle>
            <div className="dashboard-chart-container">
                {monthly.every((m) => m.billed === 0) ? <EmptyChart message="Nothing billed in this period" /> : (
                    <ResponsiveContainer width="100%" height={260}>
                        <BarChart data={monthly} margin={{ top: 10, right: 20, left: 0, bottom: 0 }}>
                            <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
                            <XAxis dataKey="month" tick={{ fill: 'rgba(255,255,255,0.45)', fontSize: 11 }} />
                            <YAxis tick={{ fill: 'rgba(255,255,255,0.45)', fontSize: 11 }} />
                            <Tooltip formatter={(v: number) => fmtUSD(v)} contentStyle={{ background: 'rgba(20,15,30,0.95)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 10 }} />
                            <Bar dataKey="billed" name="Billed" fill="#4dbe8d" radius={[4, 4, 0, 0]} />
                        </BarChart>
                    </ResponsiveContainer>
                )}
            </div>

            <SectionTitle>Tenants</SectionTitle>
            <div className="dashboard-table-wrapper">
                {rows.length === 0 ? <EmptyChart message="No tenants yet" /> : (
                    <table className="dashboard-table">
                        <thead>
                            <tr>
                                <th>Tenant</th>
                                <th>Status</th>
                                <th>Health</th>
                                <th>Billed This Month</th>
                                <th>Billed ({MONTHS} months)</th>
                            </tr>
                        </thead>
                        <tbody>
                            {rows.map((r) => {
                                const h = health.get(r.company_id);
                                return (
                                    <tr key={r.company_id}>
                                        <td>{r.company_name}</td>
                                        <td><span className={`badge badge-${r.status}`}>{r.status}</span></td>
                                        <td title={h?.health_reasons?.join('; ') || ''}>
                                            {h ? `${h.health_score} (${h.health_level})` : '—'}
                                        </td>
                                        <td>{fmtUSD(r.billed_this_month)}</td>
                                        <td>{fmtUSD(r.billed_period)}</td>
                                    </tr>
                                );
                            })}
                        </tbody>
                    </table>
                )}
            </div>
        </div>
    );
};
