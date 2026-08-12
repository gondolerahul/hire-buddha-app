/**
 * pages/dashboards/KPIDashboard — Six-tab KPI dashboard.
 *
 * Sourced from the Track 8/9 `kpi_daily_rollup` view + `usage_logs.attribution`
 * + the StepHealthRecord / MetaIntelligenceTree CORTEX nodes via
 * the /ai/admin/admin/kpi/* endpoints.
 */
import React, { useEffect, useMemo, useState } from 'react';

import { kpiService } from '@/services/kpi.service';
import type {
    CostAttributionRow,
    KPICriticResponse,
    KPIMetaAgentResponse,
    KPIRunRow,
} from '@/types/agentKernel';

import './KPIDashboard.css';

type Tab = 'runs' | 'cost' | 'critic' | 'meta' | 'memory' | 'loop';

export const KPIDashboard: React.FC = () => {
    const [tab, setTab] = useState<Tab>('runs');
    const [since, setSince] = useState<string>('7d');

    return (
        <div className="page-container agentk-kpi-page">
            <header className="page-header">
                <h1>Phase 11 KPI</h1>
                <p>Run health, cost, critic, meta-agent, memory, loop telemetry.</p>
            </header>

            <nav className="agentk-kpi-page__tabs">
                {([
                    ['runs', 'Run health'],
                    ['cost', 'Cost'],
                    ['critic', 'Critic'],
                    ['meta', 'Meta-Agent'],
                    ['memory', 'Memory'],
                    ['loop', 'Loop'],
                ] as Array<[Tab, string]>).map(([key, label]) => (
                    <button
                        key={key}
                        className={tab === key ? 'active' : ''}
                        onClick={() => setTab(key)}
                    >
                        {label}
                    </button>
                ))}

                <span className="agentk-kpi-page__window">
                    window:
                    <select value={since} onChange={(e) => setSince(e.target.value)}>
                        <option value="24h">24h</option>
                        <option value="7d">7 days</option>
                        <option value="30d">30 days</option>
                    </select>
                </span>
            </nav>

            <section className="agentk-kpi-page__body">
                {tab === 'runs' && <RunsTab since={since} />}
                {tab === 'cost' && <CostTab since={since} />}
                {tab === 'critic' && <CriticTab since={since} />}
                {tab === 'meta' && <MetaTab since="30d" />}
                {tab === 'memory' && (
                    <p className="agentk-kpi-page__placeholder">
                        Memory KPIs (viewport overhead, dreaming runs,
                        candidate→confirmed promotions, trust scores) — backed
                        by the memory KPI SQL queries under <code>infra/dashboards/</code>;
                        Grafana / Metabase panels wire-up deferred to follow-up.
                    </p>
                )}
                {tab === 'loop' && (
                    <p className="agentk-kpi-page__placeholder">
                        Loop telemetry (iterations per run, resume events, bandit
                        arm distribution, retry strategies) — backed by SQL queries
                        under <code>infra/dashboards/</code>.
                    </p>
                )}
            </section>
        </div>
    );
};

// ---------------------------------------------------------------------------

const RunsTab: React.FC<{ since: string }> = ({ since }) => {
    const [rows, setRows] = useState<KPIRunRow[]>([]);
    const [loading, setLoading] = useState(true);
    useEffect(() => {
        setLoading(true);
        kpiService.getRunHealth({ since }).then(setRows).finally(() => setLoading(false));
    }, [since]);

    const totals = useMemo(() => {
        const r = rows.reduce(
            (acc, row) => {
                acc.total += row.runs_total;
                acc.completed += row.runs_completed;
                acc.failed += row.runs_failed;
                acc.paused += row.runs_paused;
                return acc;
            },
            { total: 0, completed: 0, failed: 0, paused: 0 },
        );
        const hitRate = r.total ? r.completed / r.total : 0;
        return { ...r, hitRate };
    }, [rows]);

    if (loading) return <p>loading…</p>;
    return (
        <>
            <div className="agentk-kpi-page__cards">
                <Card label="goal_hit_rate" value={`${(totals.hitRate * 100).toFixed(1)}%`} />
                <Card label="runs total" value={totals.total} />
                <Card label="failed" value={totals.failed} highlight={totals.failed > 0} />
                <Card label="paused" value={totals.paused} />
            </div>

            <table className="agentk-kpi-page__table">
                <thead>
                    <tr>
                        <th>day</th>
                        <th>total</th>
                        <th>completed</th>
                        <th>failed</th>
                        <th>paused</th>
                        <th>hit rate</th>
                    </tr>
                </thead>
                <tbody>
                    {rows.map((r) => (
                        <tr key={r.day}>
                            <td>{r.day.slice(0, 10)}</td>
                            <td>{r.runs_total}</td>
                            <td>{r.runs_completed}</td>
                            <td>{r.runs_failed}</td>
                            <td>{r.runs_paused}</td>
                            <td>{(r.goal_hit_rate * 100).toFixed(0)}%</td>
                        </tr>
                    ))}
                </tbody>
            </table>
        </>
    );
};

const CostTab: React.FC<{ since: string }> = ({ since }) => {
    const [rows, setRows] = useState<CostAttributionRow[]>([]);
    const [loading, setLoading] = useState(true);
    useEffect(() => {
        setLoading(true);
        kpiService.getCostBreakdown({ since }).then(setRows).finally(() => setLoading(false));
    }, [since]);
    const total = rows.reduce((s, r) => s + r.cost_usd, 0);
    if (loading) return <p>loading…</p>;
    return (
        <>
            <Card label="total cost (USD)" value={`$${total.toFixed(4)}`} />
            <table className="agentk-kpi-page__table">
                <thead>
                    <tr>
                        <th>attribution</th>
                        <th>cost USD</th>
                        <th>charges</th>
                        <th>share</th>
                    </tr>
                </thead>
                <tbody>
                    {rows.map((r) => (
                        <tr key={r.attribution}>
                            <td>{r.attribution}</td>
                            <td>${r.cost_usd.toFixed(4)}</td>
                            <td>{r.charges}</td>
                            <td>{total ? ((r.cost_usd / total) * 100).toFixed(1) : '0'}%</td>
                        </tr>
                    ))}
                </tbody>
            </table>
        </>
    );
};

const CriticTab: React.FC<{ since: string }> = ({ since }) => {
    const [data, setData] = useState<KPICriticResponse | null>(null);
    const [loading, setLoading] = useState(true);
    useEffect(() => {
        setLoading(true);
        kpiService.getCriticHealth({ since }).then(setData).finally(() => setLoading(false));
    }, [since]);
    if (loading) return <p>loading…</p>;
    if (!data) return <p>no data</p>;
    return (
        <>
            <Card
                label="critic cost share"
                value={`${(data.cost_share * 100).toFixed(1)}%`}
                highlight={data.cost_share > 0.25}
            />
            <h3 className="agentk-kpi-page__subhead">Post-critic verdict distribution</h3>
            <table className="agentk-kpi-page__table">
                <thead>
                    <tr>
                        <th>verdict</th>
                        <th>occurrences</th>
                    </tr>
                </thead>
                <tbody>
                    {data.verdict_distribution.map((v) => (
                        <tr key={v.verdict}>
                            <td>{v.verdict}</td>
                            <td>{v.occurrences}</td>
                        </tr>
                    ))}
                </tbody>
            </table>
        </>
    );
};

const MetaTab: React.FC<{ since: string }> = ({ since }) => {
    const [data, setData] = useState<KPIMetaAgentResponse | null>(null);
    const [loading, setLoading] = useState(true);
    useEffect(() => {
        setLoading(true);
        kpiService.getMetaAgentHealth({ since }).then(setData).finally(() => setLoading(false));
    }, [since]);
    if (loading) return <p>loading…</p>;
    if (!data) return <p>no data</p>;
    return (
        <>
            <h3 className="agentk-kpi-page__subhead">MetaIntelligenceTree growth (last 30d)</h3>
            <table className="agentk-kpi-page__table">
                <thead>
                    <tr>
                        <th>kind</th>
                        <th>rows</th>
                    </tr>
                </thead>
                <tbody>
                    {data.intelligence_growth.map((row) => (
                        <tr key={row.kind}>
                            <td>{row.kind}</td>
                            <td>{row.rows}</td>
                        </tr>
                    ))}
                </tbody>
            </table>
        </>
    );
};

const Card: React.FC<{ label: string; value: React.ReactNode; highlight?: boolean }> = ({
    label,
    value,
    highlight,
}) => (
    <div className={`agentk-kpi-page__card ${highlight ? 'agentk-kpi-page__card--highlight' : ''}`}>
        <div className="agentk-kpi-page__card-label">{label}</div>
        <div className="agentk-kpi-page__card-value">{value}</div>
    </div>
);

export default KPIDashboard;
